from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
import httpx
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.config import Settings
from app.models.incident import User, Incident, Investigation, ProposedFix, Repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

settings = Settings()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


class ChatResponse(BaseModel):
    response: str


def build_context(db: Session, user_id) -> str:
    """Build context about the user's incidents, investigations, and PRs."""
    parts = []

    incidents = db.query(Investigation).all()
    if incidents:
        recent = incidents[-5:] if len(incidents) > 5 else incidents
        for inv in recent:
            inc = db.query(Investigation).filter(Investigation.id == inv.id).first()
            parts.append(
                f"Investigation {str(inv.id)[:8]}: status={inv.status}, "
                f"root_cause={inv.root_cause_analysis[:200] if inv.root_cause_analysis else 'N/A'}, "
                f"confidence={inv.confidence_score}"
            )

    fixes = db.query(ProposedFix).all()
    if fixes:
        recent_fixes = fixes[-5:] if len(fixes) > 5 else fixes
        for fix in recent_fixes:
            parts.append(
                f"Proposed Fix {str(fix.id)[:8]}: title={fix.title}, "
                f"status={fix.status}, "
                f"description={fix.description[:200] if fix.description else 'N/A'}"
            )

    repos = db.query(Repository).filter(Repository.owner_id == user_id).all()
    if repos:
        repo_names = [r.full_name for r in repos[:10]]
        parts.append(f"Connected repositories: {', '.join(repo_names)}")

    if not parts:
        return "No incidents, investigations, or fixes found yet. The system is ready to investigate production issues."

    return "\n".join(parts)


SYSTEM_PROMPT = """You are Sentinel AI Assistant — an expert AI helper for software engineers. You help with TWO main areas:

## 1. Incident Response (Primary)
- Analyze production incidents, errors, crashes
- Investigate root causes using code, logs, and metrics
- Propose code fixes and create draft PRs
- Explain investigation findings and evidence

## 2. General Development Tasks
- Answer questions about code, architecture, best practices
- Suggest code changes (colors, layouts, functionality, refactoring)
- Explain how things work in the codebase
- Help with debugging, testing, documentation
- Provide guidance on technologies, frameworks, patterns

When the user asks you to DO something (like "change the color to blue"), explain:
1. What file(s) need to change
2. What the exact code change would be
3. How to apply it

You have access to the user's incident data, investigations, proposed fixes, and connected repositories.

Always be helpful, concise, and accurate. If you don't have specific data about something, say so clearly.
Do not make up information. Base your answers on the context provided."""


async def call_llm(message: str, context: str, history: List[ChatMessage]) -> str:
    """Call the configured LLM provider."""
    api_key = settings.LLM_API_KEY
    provider = settings.LLM_PROVIDER
    
    logger.info(f"Chat request - provider={provider}, key_present={bool(api_key)}")
    
    if not api_key or provider == "mock":
        logger.warning("Chat falling back to local: no provider or mock mode")
        return generate_local_response(message, context)

    system_msg = f"""{SYSTEM_PROMPT}

Context about the Sentinel system:
{context}"""

    messages = [{"role": "system", "content": system_msg}]
    for msg in history[-10:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": message})

    if provider in ("nvidia", "ollama", "openai", "deepseek"):
        return await call_openai_compatible(messages, api_key, provider)
    elif provider == "gemini":
        return await call_gemini_native(messages, api_key, provider)
    else:
        return generate_local_response(message, context)


async def call_openai_compatible(messages: list, api_key: str, provider: str) -> str:
    """Call any OpenAI-compatible API (NVIDIA NIM, Ollama, DeepSeek, OpenAI)."""
    base_urls = {
        "nvidia": "https://integrate.api.nvidia.com/v1",
        "ollama": "http://localhost:11434/v1",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
    }
    base_url = settings.LLM_BASE_URL or base_urls.get(provider, "https://integrate.api.nvidia.com/v1")

    model_map = {
        "nvidia": settings.LLM_MODEL or "nvidia/nemotron-3-ultra-550b-a55b",
        "ollama": settings.LLM_MODEL or "llama3.2",
        "openai": settings.LLM_MODEL or "gpt-4",
        "deepseek": settings.LLM_MODEL or "deepseek-chat",
    }
    model = model_map.get(provider, "nvidia/nemotron-3-ultra-550b-a55b")

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048,
        "top_p": 0.9,
    }

    logger.info(f"Calling {provider}: model={model}, url={url}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        logger.info(f"{provider} response: status={resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"{provider} API error: {resp.text[:500]}")
            return generate_local_response(messages[-1]["content"], "")

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
            logger.info(f"{provider} response length: {len(text)} chars")
            return text
        except (KeyError, IndexError) as e:
            logger.error(f"{provider} parse error: {e}, data={str(data)[:500]}")
            return generate_local_response(messages[-1]["content"], "")


async def call_gemini_native(messages: list, api_key: str, provider: str) -> str:
    """Call Google Gemini native API."""
    contents = []
    for msg in messages:
        if msg["role"] == "system":
            contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
        else:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    model_name = settings.LLM_MODEL or "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    logger.info(f"Calling Gemini: model={model_name}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json={"contents": contents})
        logger.info(f"Gemini response: status={resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"Gemini API error: {resp.text[:500]}")
            return generate_local_response(messages[-1]["content"], "")

        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            logger.error(f"Gemini parse error: {e}")
            return generate_local_response(messages[-1]["content"], "")


def generate_local_response(message: str, context: str) -> str:
    """Generate a helpful response using context when LLM is unavailable."""
    msg_lower = message.lower()

    if any(w in msg_lower for w in ["incident", "error", "issue", "problem"]):
        if "No incidents" in context:
            return "No incidents have been recorded yet. To report an issue, go to **Incidents → Report Production Error** or use the sidebar button. Sentinel will then investigate automatically."
        lines = [l for l in context.split("\n") if "Investigation" in l]
        if lines:
            return f"Here are the recent investigations:\n\n" + "\n".join(f"- {l}" for l in lines[-3:]) + "\n\nWould you like details on any specific investigation?"
        return "I can see your connected repositories. No investigations have been run yet. Report an incident to get started!"

    if any(w in msg_lower for w in ["fix", "pr", "pull request", "code change", "patch"]):
        if "Proposed Fix" in context:
            lines = [l for l in context.split("\n") if "Proposed Fix" in l]
            return f"Here are the proposed fixes:\n\n" + "\n".join(f"- {l}" for l in lines) + "\n\nThese were generated based on root cause analysis of your incidents."
        return "No fixes have been proposed yet. Fixes are generated after Sentinel identifies a root cause during investigation."

    if any(w in msg_lower for w in ["repo", "repository", "code"]):
        if "Connected repositories" in context:
            return f"Your connected repositories:\n\n{context.split('Connected repositories:')[1].strip()}\n\nThese are synced from your GitHub account. Sentinel analyzes code changes in these repos when investigating incidents."
        return "No repositories are connected yet. Go to **Integrations** to connect your GitHub account."

    if any(w in msg_lower for w in ["root cause", "why", "reason", "cause"]):
        lines = [l for l in context.split("\n") if "root_cause" in l and "N/A" not in l]
        if lines:
            return f"Root causes identified:\n\n" + "\n".join(f"- {l}" for l in lines)
        return "No root causes have been identified yet. Sentinel determines root causes during investigation by analyzing code changes, logs, and metrics."

    if any(w in msg_lower for w in ["color", "colour", "style", "theme", "font", "size", "layout", "design"]):
        return ("I can help with UI changes! To change something in the codebase:\n\n"
                "1. Tell me exactly what you want changed (e.g., 'change the sidebar background to #1a1a1a')\n"
                "2. I'll tell you which file to edit and the exact code change\n"
                "3. You can apply it manually, or ask me to make the change\n\n"
                "**Tip**: For Sentinel, UI files are in `sentinel-ui/src/`. "
                "Colors are defined in `globals.css`, components are in `src/components/`.")

    if any(w in msg_lower for w in ["change", "update", "modify", "edit", "replace"]):
        return ("I can help you make changes! Tell me:\n\n"
                "1. **What** to change (e.g., 'the header color', 'the login button text')\n"
                "2. **Where** (which page or component)\n"
                "3. **What value** (the new color, text, behavior)\n\n"
                "I'll identify the file and give you the exact code change needed.")

    if any(w in msg_lower for w in ["help", "how", "what can"]):
        return """I'm Sentinel AI Assistant. Here's what I can help with:

**Incident Response**: Ask about incidents, root causes, fixes, and investigations
**Code Changes**: Tell me what to change (colors, layout, text, functionality)
**Questions**: Ask about any technology, framework, or coding concept
**Debugging**: Describe the error and I'll help find the cause
**Architecture**: Get advice on how to structure your code

Just ask me anything!"""

    if any(w in msg_lower for w in ["hello", "hi", "hey"]):
        return "Hello! I'm Sentinel AI Assistant. I can help with incidents, code changes, debugging, and more. What would you like to do?"

    return f"I can help you with that! Based on your current data:\n\n{context[:500]}\n\nCould you be more specific about what you'd like to know?"


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context = build_context(db, current_user.id)
    history = [ChatMessage(role=m.role, content=m.content) for m in request.history]

    try:
        response = await call_llm(request.message, context, history)
    except Exception as e:
        logger.error(f"Chat error: {e}")
        response = generate_local_response(request.message, context)

    return ChatResponse(response=response)
