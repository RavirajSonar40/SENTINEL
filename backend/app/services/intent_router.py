"""
Two-Tier Intent Routing Engine for Sentinel Work Items.

Tier 1: High-speed, deterministic regex & entity extractor (0ms latency, $0 cost).
Tier 2: Nemotron LLM structured classifier for complex, ambiguous natural language.
Ambiguity Guard: Returns NEEDS_CLARIFICATION when confidence < 0.70.
"""

import re
import logging
from typing import Optional, List, Dict, Any

from app.models.work_item import WorkType
from app.schemas.work_item import WorkTypeEnvelope
from app.services.llm import generate_json_response, LLMConfig, LLMError

logger = logging.getLogger("sentinel.intent_router")

# Regex for direct file tasks (hardened against false positives)
DIRECT_FILE_REGEX = re.compile(
    r"^(?:add|create|update|make|write|generate|modify)\s+(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-./]+\.(?:md|txt|json|yaml|yml|toml|py|ts|tsx|js|jsx|go|rs|sh|sql|dockerfile|env|html|css))\b",
    re.IGNORECASE,
)

DISQUALIFYING_FEATURE_WORDS = [
    "support for", "feature", "integration", "behavior", "logic",
    "module", "system", "pipeline", "workflow", "algorithm",
]

PRODUCTION_INDICATORS = [
    "production", "prod", "live", "503", "cluster", "traffic",
    "outage", "downtime", "telemetry", "prometheus", "sentry",
    "alert", "customer-facing",
]


def _classify_tier1_deterministic(
    title: str,
    description: Optional[str] = "",
    repository_scope: Optional[List[str]] = None,
    service_scope: Optional[List[str]] = None,
    environment_scope: Optional[List[str]] = None,
    region_scope: Optional[List[str]] = None,
) -> Optional[WorkTypeEnvelope]:
    """
    Tier 1 deterministic rule-based pattern & entity extractor.
    Returns WorkTypeEnvelope if high confidence match, else None.
    """
    full_text = f"{title} {description or ''}".strip()
    full_text_lower = full_text.lower()
    title_lower = title.strip().lower()

    # 1. SECURITY INCIDENT PATTERNS
    security_patterns = [
        r"\bsuspicious\s+login\b",
        r"\bauth(?:entication)?\s+attack\b",
        r"\bcredential\s+leak\b",
        r"\bsql\s+injection\b",
        r"\bcve-\d{4}-\d+\b",
        r"\bunauthorized\s+access\b",
        r"\bbrute\s+force\b",
        r"\bxss\s+vulnerability\b",
    ]
    for pattern in security_patterns:
        if re.search(pattern, full_text_lower):
            return WorkTypeEnvelope(
                work_type=WorkType.SECURITY_INCIDENT,
                confidence=0.95,
                repository_scope=repository_scope or [],
                service_scope=service_scope or [],
                environment_scope=environment_scope or [],
                region_scope=region_scope or [],
                target_files=[],
                requires_runtime_evidence=True,
                runtime_evidence_reason="Security signal detected; strict evidence preservation required",
                requires_code_change=False,
                workflow="security_incident",
                summary=f"Security anomaly: {title}",
                rationale="Matched known security incident telemetry signature",
            )

    # 2. PRODUCTION INCIDENT PATTERNS & TELEMETRY SIGNALS
    prod_patterns = [
        r"\bcpu\s*(?:is\s*)?(?:high|\d+%)",
        r"\bmemory\s*leak\b",
        r"\b503\s*spike\b",
        r"\b(?:production|prod)\s*(?:is\s*)?down\b",
        r"\bproduction\s+checkout\s+is\s+down\b",
        r"\boutage\b",
        r"\bcrash\s*loop\b",
        r"\bservice\s+down\b",
        r"\bhigh\s+error\s+rate\s+in\s+prod",
    ]
    for pattern in prod_patterns:
        if re.search(pattern, full_text_lower):
            return WorkTypeEnvelope(
                work_type=WorkType.PRODUCTION_INCIDENT,
                confidence=0.96,
                repository_scope=repository_scope or [],
                service_scope=service_scope or [],
                environment_scope=environment_scope or ["production"],
                region_scope=region_scope or [],
                target_files=[],
                requires_runtime_evidence=True,
                runtime_evidence_reason="Live production anomaly signals detected",
                requires_code_change=True,
                workflow="production_incident",
                summary=f"Production Incident: {title}",
                rationale="Matched production degradation telemetry signature",
            )

    # 3. DIRECT FILE TASK (Hardened regex & disqualification guard)
    match = DIRECT_FILE_REGEX.match(title.strip())
    if match:
        target_filename = match.group(1).strip()
        # Verify no disqualifying feature words are present in title
        is_disqualified = any(dw in title_lower for dw in DISQUALIFYING_FEATURE_WORDS)
        if not is_disqualified:
            return WorkTypeEnvelope(
                work_type=WorkType.DIRECT_TASK,
                confidence=0.98,
                repository_scope=repository_scope or [],
                service_scope=service_scope or [],
                environment_scope=environment_scope or [],
                region_scope=region_scope or [],
                target_files=[target_filename],
                requires_runtime_evidence=False,
                runtime_evidence_reason="Direct isolated file task; skips operational telemetry",
                requires_code_change=True,
                workflow="repository_task",
                summary=f"Direct file modification: {target_filename}",
                rationale="Matched explicit file creation/modification regex pattern",
            )

    # 4. BUG PATTERNS (With conditional runtime evidence)
    bug_patterns = [
        r"\bfix\b",
        r"\bbug\b",
        r"\berror\s*\d{3}\b",
        r"\bexception\b",
        r"\bcrash\b",
        r"\bfails?\b",
        r"\bbroken\b",
        r"\bpanic\b",
        r"\bnull\s*pointer\b",
        r"\btypeerror\b",
        r"\bundefined\s+is\s+not\b",
    ]
    is_bug = any(re.search(bp, full_text_lower) for bp in bug_patterns)
    if is_bug:
        # Determine if production context exists
        has_prod_context = any(pi in full_text_lower for pi in PRODUCTION_INDICATORS)
        return WorkTypeEnvelope(
            work_type=WorkType.BUG,
            confidence=0.92,
            repository_scope=repository_scope or [],
            service_scope=service_scope or [],
            environment_scope=environment_scope or ([] if not has_prod_context else ["production"]),
            region_scope=region_scope or [],
            target_files=[],
            requires_runtime_evidence=has_prod_context,
            runtime_evidence_reason=(
                "Production error signals detected"
                if has_prod_context
                else "Code, tests, and repository history investigation sufficient"
            ),
            requires_code_change=True,
            workflow="bug",
            summary=f"Bug: {title}",
            rationale="Matched bug keyword/pattern; conditional runtime evidence applied",
        )

    # 5. FEATURE PATTERNS
    feature_patterns = [
        r"\badd\s+support\b",
        r"\bimplement\b",
        r"\bfeature\b",
        r"\bdark\s*mode\b",
        r"\bnew\s+page\b",
        r"\bui\s+component\b",
        r"\bexport\s+to\b",
        r"\bintegrate\b",
        r"\benhance\b",
    ]
    is_feature = any(re.search(fp, full_text_lower) for fp in feature_patterns)
    if is_feature:
        return WorkTypeEnvelope(
            work_type=WorkType.FEATURE,
            confidence=0.90,
            repository_scope=repository_scope or [],
            service_scope=service_scope or [],
            environment_scope=environment_scope or [],
            region_scope=region_scope or [],
            target_files=[],
            requires_runtime_evidence=False,
            runtime_evidence_reason="Feature implementation; code exploration sufficient",
            requires_code_change=True,
            workflow="feature",
            summary=f"Feature: {title}",
            rationale="Matched feature keyword pattern",
        )

    return None


async def classify_intent(
    title: str,
    description: Optional[str] = None,
    repository_scope: Optional[List[str]] = None,
    service_scope: Optional[List[str]] = None,
    environment_scope: Optional[List[str]] = None,
    region_scope: Optional[List[str]] = None,
    target_files: Optional[List[str]] = None,
    force_work_type: Optional[WorkType] = None,
    config: Optional[LLMConfig] = None,
) -> WorkTypeEnvelope:
    """
    Classify a work item title & description into a WorkTypeEnvelope.
    Uses Tier 1 deterministic rules first; falls back to Tier 2 LLM when ambiguous.
    """
    # 0. Force work type (Only honored if provided by authorized caller)
    if force_work_type:
        workflow_map = {
            WorkType.DIRECT_TASK: "repository_task",
            WorkType.BUG: "bug",
            WorkType.FEATURE: "feature",
            WorkType.PRODUCTION_INCIDENT: "production_incident",
            WorkType.SECURITY_INCIDENT: "security_incident",
            WorkType.NEEDS_CLARIFICATION: "clarification",
        }
        return WorkTypeEnvelope(
            work_type=force_work_type,
            confidence=1.0,
            repository_scope=repository_scope or [],
            service_scope=service_scope or [],
            environment_scope=environment_scope or [],
            region_scope=region_scope or [],
            target_files=target_files or [],
            requires_runtime_evidence=(force_work_type in (WorkType.PRODUCTION_INCIDENT, WorkType.SECURITY_INCIDENT)),
            runtime_evidence_reason="Explicitly forced work type",
            requires_code_change=(force_work_type != WorkType.SECURITY_INCIDENT),
            workflow=workflow_map.get(force_work_type, "repository_task"),
            summary=f"Forced {force_work_type.value}: {title}",
            rationale="Explicit user/system override",
        )

    # 1. Tier 1 Deterministic Classification
    tier1_result = _classify_tier1_deterministic(
        title=title,
        description=description,
        repository_scope=repository_scope,
        service_scope=service_scope,
        environment_scope=environment_scope,
        region_scope=region_scope,
    )
    if tier1_result and tier1_result.confidence >= 0.85:
        if target_files and not tier1_result.target_files:
            tier1_result.target_files = target_files
        return tier1_result

    # 2. Tier 2 Nemotron LLM Structured Classification
    system_prompt = (
        "You are Sentinel's Intent Router. Classify the user request or alert into one of the following WorkTypes:\n"
        "- DIRECT_TASK: Creating or modifying a single isolated file (e.g. README.md, docker-compose.yml).\n"
        "- BUG: Software defect or error fix that does not require full incident investigation unless in production.\n"
        "- FEATURE: New capability, UI enhancement, or functional addition.\n"
        "- PRODUCTION_INCIDENT: Live outage, high CPU/memory, customer-impacting degradation.\n"
        "- SECURITY_INCIDENT: Auth attack, credential leak, CVE, suspicious login.\n"
        "- NEEDS_CLARIFICATION: The request is too vague, ambiguous, or contradictory to classify safely.\n\n"
        "Return a JSON object conforming to the WorkTypeEnvelope schema."
    )

    user_prompt = (
        f"Title: {title}\n"
        f"Description: {description or 'None'}\n"
        f"Repository Scope: {repository_scope or []}\n"
        f"Service Scope: {service_scope or []}\n"
        f"Environment Scope: {environment_scope or []}\n"
    )

    try:
        response = await generate_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            config=config,
            schema=WorkTypeEnvelope,
        )
        envelope: WorkTypeEnvelope = response.parsed

        # Ambiguity Guard: If confidence < 0.70, halt into NEEDS_CLARIFICATION
        if envelope.confidence < 0.70 or envelope.work_type == WorkType.NEEDS_CLARIFICATION:
            envelope.work_type = WorkType.NEEDS_CLARIFICATION
            envelope.workflow = "clarification"
            if not envelope.questions:
                envelope.questions = [
                    "Which repository or service should be modified?",
                    "Is this an active production issue or a code-level task?",
                ]
            envelope.rationale = envelope.rationale or "Classification confidence was below 0.70 threshold."

        return envelope

    except LLMError as err:
        logger.warning(f"Tier 2 LLM intent routing failed: {err}; evaluating fallback")
        # Safe fallback: If LLM fails and Tier 1 had a low-confidence result, return NEEDS_CLARIFICATION
        return WorkTypeEnvelope(
            work_type=WorkType.NEEDS_CLARIFICATION,
            confidence=0.40,
            repository_scope=repository_scope or [],
            service_scope=service_scope or [],
            environment_scope=environment_scope or [],
            region_scope=region_scope or [],
            target_files=target_files or [],
            requires_runtime_evidence=False,
            requires_code_change=False,
            workflow="clarification",
            summary=title,
            rationale=f"AI intent router unavailable ({err}); requires human clarification",
            questions=[
                "Could you specify if this is a DIRECT_TASK, BUG, FEATURE, or PRODUCTION_INCIDENT?",
            ],
        )
