"""Diff generation — create actual code patches from root cause analysis.

Downloads files from GitHub at a specific SHA, generates precise diffs,
and verifies replacement safety (exact count must be exactly 1).
"""
import base64
import os
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
import logging

logger = logging.getLogger("sentinel.diff_generator")


async def download_file_from_github(
    owner: str,
    repo: str,
    file_path: str,
    sha: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """Download a file's content from GitHub at a specific commit SHA."""
    try:
        from app.services.github import GitHubClient
        client = GitHubClient(token=token)
        result = await client.get_file(owner, repo, file_path, ref=sha)
        if result and "content" in result:
            content = base64.b64decode(result["content"]).decode("utf-8", errors="replace")
            return content
        return None
    except Exception as e:
        logger.warning(f"Failed to download {file_path} from GitHub: {e}")
        return None


def verify_replacement_count(old_code: str, file_content: str) -> Tuple[bool, int]:
    """Verify that old_code appears exactly once in the file.

    Returns (is_safe, count). Patch is safe only if count == 1.
    """
    if not old_code or not old_code.strip():
        return False, 0
    count = file_content.count(old_code)
    return count == 1, count


def apply_replacement(file_content: str, old_code: str, new_code: str) -> Optional[str]:
    """Apply a single replacement to file content.

    Returns None if old_code doesn't appear exactly once.
    """
    is_safe, count = verify_replacement_count(old_code, file_content)
    if not is_safe:
        return None
    return file_content.replace(old_code, new_code, 1)


async def generate_patch(
    root_cause: Dict,
    affected_files: List[str],
    repository: Optional[str] = None,
    sha: Optional[str] = None,
    project_path: str = ".",
    token: Optional[str] = None,
) -> Dict:
    """Generate a code patch based on root cause analysis.

    If repository and sha are provided, downloads files from GitHub.
    Otherwise falls back to local files.
    Verifies each replacement appears exactly once before accepting.
    """
    system_prompt = """You are a code remediation expert. Given a root cause and affected files, generate a precise code patch.

Respond with JSON:
{
  "summary": "One-line description of the fix",
  "changes": [
    {
      "file": "path/to/file.py",
      "action": "modify|create|delete",
      "description": "What changed and why",
      "old_code": "exact code to replace (for modify)",
      "new_code": "replacement code",
      "line_start": 42,
      "line_end": 48
    }
  ],
  "commit_message": "fix: concise commit message",
  "risk": "low|medium|high",
  "risk_explanation": "why this risk level"
}

Rules:
- old_code must be EXACT text from the file (copy-paste precisely)
- Each old_code block must appear exactly ONCE in the file
- Be precise — match exact code including whitespace
- Minimal changes — fix only what's broken
- Preserve existing code style
- Include error handling if the fix touches error paths
- Don't refactor unrelated code"""

    # Download or read file contents
    files_context = []
    file_contents = {}
    owner, repo = None, None
    if repository and "/" in repository:
        owner, repo = repository.split("/", 1)

    for fpath in affected_files[:5]:
        content = None
        if owner and repo:
            content = await download_file_from_github(owner, repo, fpath, sha=sha, token=token)
        if content is None:
            full_path = os.path.join(project_path, fpath)
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(10000)
            except FileNotFoundError:
                content = None

        if content:
            file_contents[fpath] = content
            # Truncate for LLM context but keep enough for accurate matching
            display = content[:8000]
            files_context.append(f"FILE: {fpath}\n```\n{display}\n```")
        else:
            files_context.append(f"FILE: {fpath}\n[NOT FOUND]")

    rc_summary = root_cause.get('label') or root_cause.get('summary') or 'Identified issue'
    rc_explanation = root_cause.get('description') or root_cause.get('causal_explanation') or 'Fix the bug based on error signals'
    rc_component = root_cause.get('category') or root_cause.get('affected_component') or 'code'

    user_prompt = f"""Root Cause: {rc_summary}
Causal Explanation: {rc_explanation}
Affected Component: {rc_component}

Relevant Files:
{chr(10).join(files_context)}

Generate the minimal fix for this root cause. old_code must be an EXACT copy of code from the file above."""

    try:
        from app.services.llm import generate_json
        result = await generate_json(system_prompt, user_prompt)
    except Exception as e:
        logger.warning(f"LLM patch generation failed: {e}")
        result = {
            "summary": f"Fix for: {rc_summary}",
            "changes": [],
            "commit_message": f"fix: {rc_summary[:72]}",
            "risk": "medium",
            "risk_explanation": "Generated by AI — requires human review",
        }

    # Verify each change's replacement count
    verified_changes = []
    rejected_changes = []
    for change in result.get("changes", []):
        fpath = change.get("file", "")
        action = change.get("action", "modify")
        old_code = change.get("old_code", "")
        new_code = change.get("new_code", "")

        if not new_code:
            rejected_changes.append({**change, "rejection_reason": "empty new_code"})
            continue

        if action == "create":
            change["patched_content"] = new_code
            change["original_content"] = ""
            verified_changes.append(change)
            continue

        if not old_code:
            rejected_changes.append({**change, "rejection_reason": "empty old_code for modify action"})
            continue

        file_content = file_contents.get(fpath, "")
        if not file_content:
            rejected_changes.append({**change, "rejection_reason": "file not available for verification"})
            continue

        is_safe, count = verify_replacement_count(old_code, file_content)
        if is_safe:
            # Build the actual patched content for diff generation
            patched = apply_replacement(file_content, old_code, new_code)
            change["patched_content"] = patched
            change["original_content"] = file_content
            verified_changes.append(change)
        else:
            rejected_changes.append({
                **change,
                "rejection_reason": f"old_code matches {count} times (must be exactly 1)",
            })
            logger.warning(f"Rejected patch for {fpath}: old_code appears {count} times")

    # Build diffs for verified changes
    diffs = []
    for change in verified_changes:
        old = change.get("original_content", "")
        new = change.get("patched_content", "")
        if new:
            diff = generate_diff(old, new, change.get("file", ""))
            change["diff"] = diff
            diffs.append(diff)
        change.pop("original_content", None)
        change.pop("patched_content", None)

    result["changes"] = verified_changes
    result["rejected_changes"] = rejected_changes
    result["diffs"] = diffs
    result["safe"] = len(rejected_changes) == 0 and len(verified_changes) > 0

    if not result["safe"] and verified_changes:
        result["risk"] = "high"
        result["risk_explanation"] = f"{len(rejected_changes)} changes rejected as unsafe"

    return result


def generate_diff(old_code: str, new_code: str, file_path: str) -> str:
    """Generate a unified diff between old and new code."""
    old_lines = old_code.splitlines(keepends=True)
    new_lines = new_code.splitlines(keepends=True)

    diff_lines = [f"--- a/{file_path}\n", f"+++ b/{file_path}\n"]

    max_len = max(len(old_lines), len(new_lines))
    for i in range(max_len):
        old_line = old_lines[i] if i < len(old_lines) else None
        new_line = new_lines[i] if i < len(new_lines) else None

        if old_line is None:
            diff_lines.append(f"+{new_line}")
        elif new_line is None:
            diff_lines.append(f"-{old_line}")
        elif old_line != new_line:
            diff_lines.append(f"-{old_line}")
            diff_lines.append(f"+{new_line}")

    return "".join(diff_lines)


def format_patch_for_pr(patch: Dict) -> str:
    """Format a patch dict into a PR-ready markdown description."""
    sections = []

    sections.append(f"## Summary\n\n{patch.get('summary', 'No summary')}\n")
    sections.append(f"## Commit Message\n\n`{patch.get('commit_message', 'fix: update')}`\n")
    sections.append(f"## Risk\n\n**{patch.get('risk', 'medium').upper()}** — {patch.get('risk_explanation', '')}\n")

    changes = patch.get("changes", [])
    if changes:
        sections.append("## Changes\n")
        for change in changes:
            sections.append(f"### `{change.get('file', 'unknown')}`\n")
            sections.append(f"**Action:** {change.get('action', 'modify')}\n")
            sections.append(f"**Description:** {change.get('description', '')}\n")
            if change.get("diff"):
                sections.append("```diff")
                sections.append(change["diff"])
                sections.append("```\n")
            elif change.get("old_code") and change.get("new_code"):
                sections.append("```diff")
                sections.append(generate_diff(change["old_code"], change["new_code"], change.get("file", "")))
                sections.append("```\n")

    rejected = patch.get("rejected_changes", [])
    if rejected:
        sections.append("## Rejected Changes\n")
        for r in rejected:
            sections.append(f"- `{r.get('file', '?')}`: {r.get('rejection_reason', 'unknown')}\n")

    return "\n".join(sections)
