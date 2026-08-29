"""Strict Pre-Flight Patch Safety and Rejection Engine for Phase 11.

Enforces:
1. Exact single replacement verification (old_code count == 1).
2. Strict scope boundaries (no path traversal, no .git/.env/.ssh, only approved scope files).
3. Automated secret scanning across new_code and test code.
4. Real AST / compiler syntax validation on all resulting files.
5. Diff bloat limit (max files and lines changed).
6. Concrete zero-boilerplate verification (rejects placeholder templates).
7. Deterministic SHA-256 snapshot hashing.
"""
import hashlib
import json
import os
import re
from typing import Dict, List, Optional, Tuple, Any
import logging

from app.services.security import scan_for_secrets
from app.services.ast_validator import validate_code_syntax

logger = logging.getLogger("sentinel.patch_safety")

MAX_FILES_CHANGED = 25
MAX_DIFF_LINES = 1500

FORBIDDEN_BOILERPLATE_PATTERNS = [
    r"TODO:\s*add content here",
    r"TODO:\s*implement later",
    r"INSERT_CODE_HERE",
    r"YOUR_API_KEY_HERE",
    r"Lorem ipsum dolor sit amet",
    r"Generic Project Title",
    r"replace with your description",
]

SENSITIVE_PATHS = [
    ".git", ".env", ".ssh", ".aws", "id_rsa", "id_ed25519", "credentials", "secrets"
]


def sensitive_data_redactor(content: str) -> str:
    """Scrub sensitive secrets, tokens, API keys, passwords, and private keys from text."""
    if not content or not isinstance(content, str):
        return "" if content is None else str(content)
    
    redacted = content
    from app.services.security import SECRET_PATTERNS
    for pattern, secret_type in SECRET_PATTERNS:
        try:
            redacted = re.sub(pattern, rf"[REDACTED_{secret_type.upper().replace(' ', '_')}]", redacted)
        except Exception:
            pass

    # Generic high-entropy token / password scrubs
    redacted = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{15,}", r"\1[REDACTED_TOKEN]", redacted)
    redacted = re.sub(r"sk-[A-Za-z0-9_\-]{15,}", "[REDACTED_API_KEY]", redacted)
    redacted = re.sub(r"(?i)(password|passwd|pwd)\s*=\s*[^\s,;]+", r"password=[REDACTED_PASSWORD]", redacted)
    return redacted



def sanitize_relative_path(file_path: str) -> Tuple[bool, Optional[str]]:
    """Verify that a path is safe and strictly relative."""
    if not file_path or not file_path.strip():
        return False, "Empty file path"
    
    clean_path = file_path.strip().replace("\\", "/")
    
    if clean_path.startswith("/") or clean_path.startswith("~"):
        return False, f"Absolute or home path not allowed: '{file_path}'"
    
    parts = clean_path.split("/")
    if ".." in parts or "." in parts:
        return False, f"Path traversal not allowed: '{file_path}'"
    
    for part in parts:
        p_lower = part.lower()
        if (
            p_lower in SENSITIVE_PATHS
            or p_lower.startswith(".env")
            or p_lower.endswith(".env")
            or p_lower.endswith(".key")
            or p_lower.endswith(".pem")
            or "secret" in p_lower
            or "credential" in p_lower
        ):
            return False, f"Access to sensitive file or directory forbidden: '{file_path}'"
            
    return True, None


def compute_patch_snapshot_hash(
    repository_id: Optional[str],
    base_commit_sha: Optional[str],
    scope_files: Optional[List[str]],
    original_files: Dict[str, str],
    final_files: Dict[str, str],
    diff_content: Optional[str] = None,
) -> str:
    """Compute a deterministic SHA-256 snapshot hash covering all inputs and outputs."""
    h = hashlib.sha256()
    h.update((str(repository_id or "")).encode("utf-8"))
    h.update((str(base_commit_sha or "")).encode("utf-8"))
    
    sorted_scope = sorted(scope_files or [])
    h.update(json.dumps(sorted_scope).encode("utf-8"))
    
    for path in sorted(original_files.keys()):
        h.update(path.encode("utf-8"))
        h.update(hashlib.sha256(original_files[path].encode("utf-8")).digest())
        
    for path in sorted(final_files.keys()):
        h.update(path.encode("utf-8"))
        h.update(hashlib.sha256(final_files[path].encode("utf-8")).digest())
        
    if diff_content:
        h.update(diff_content.encode("utf-8"))
        
    return h.hexdigest()


def check_boilerplate_hallucination(content: str) -> Tuple[bool, Optional[str]]:
    """Verify that content does not contain forbidden generic template placeholders."""
    for pattern in FORBIDDEN_BOILERPLATE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return False, f"Content contains forbidden placeholder boilerplate matching '{pattern}'"
    return True, None


def validate_patch_safety(
    changes: List[Dict[str, Any]],
    file_contents: Dict[str, str],
    scope_files: Optional[List[str]] = None,
    tests_to_add: Optional[List[Dict[str, Any]]] = None,
    repository_id: Optional[str] = None,
    base_commit_sha: Optional[str] = None,
    is_direct_task: bool = False,
    task_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Execute complete strict pre-flight safety check on a proposed patch.

    Returns:
    {
        "is_safe": bool,
        "rejection_reason": Optional[str],
        "scope_valid": bool,
        "replacements_valid": bool,
        "secrets_clean": bool,
        "ast_valid": bool,
        "bloat_valid": bool,
        "final_files": Dict[str, str],
        "snapshot_hash": str,
        "details": Dict[str, Any],
    }
    """
    scope_set = set(s.strip().replace("\\", "/") for s in (scope_files or []))
    
    # 1. Diff Bloat Check
    if len(changes) > MAX_FILES_CHANGED:
        return {
            "is_safe": False,
            "rejection_reason": f"Patch modifies {len(changes)} files, exceeding limit of {MAX_FILES_CHANGED}",
            "scope_valid": True,
            "replacements_valid": True,
            "secrets_clean": True,
            "ast_valid": True,
            "bloat_valid": False,
            "final_files": {},
            "snapshot_hash": "",
            "details": {"file_count": len(changes)},
        }

    total_lines_changed = 0
    final_files: Dict[str, str] = {}
    original_files: Dict[str, str] = {}

    for change in changes:
        file_path = change.get("file", "").strip().replace("\\", "/")
        action = change.get("action", "modify").lower()
        old_code = change.get("old_code", "")
        new_code = change.get("new_code", "")

        # 2. Scope & Path Sanitization
        is_path_safe, path_err = sanitize_relative_path(file_path)
        if not is_path_safe:
            return {
                "is_safe": False,
                "rejection_reason": f"Unsafe file path: {path_err}",
                "scope_valid": False,
                "replacements_valid": True,
                "secrets_clean": True,
                "ast_valid": True,
                "bloat_valid": True,
                "final_files": {},
                "snapshot_hash": "",
                "details": {"violating_file": file_path},
            }

        if scope_set and file_path not in scope_set:
            return {
                "is_safe": False,
                "rejection_reason": f"File '{file_path}' is outside approved scope: {list(scope_set)}",
                "scope_valid": False,
                "replacements_valid": True,
                "secrets_clean": True,
                "ast_valid": True,
                "bloat_valid": True,
                "final_files": {},
                "snapshot_hash": "",
                "details": {"out_of_scope_file": file_path},
            }

        # 3. Secret Scanning in new_code
        secrets_found = scan_for_secrets(new_code)
        if secrets_found:
            return {
                "is_safe": False,
                "rejection_reason": f"Secret detected in patch for '{file_path}': {secrets_found[0].get('type', 'credential')}",
                "scope_valid": True,
                "replacements_valid": True,
                "secrets_clean": False,
                "ast_valid": True,
                "bloat_valid": True,
                "final_files": {},
                "snapshot_hash": "",
                "details": {"secrets": secrets_found},
            }

        # 4. Boilerplate Hallucination Check
        bp_ok, bp_err = check_boilerplate_hallucination(new_code)
        if not bp_ok:
            return {
                "is_safe": False,
                "rejection_reason": f"Boilerplate check failed in '{file_path}': {bp_err}",
                "scope_valid": True,
                "replacements_valid": True,
                "secrets_clean": True,
                "ast_valid": True,
                "bloat_valid": True,
                "final_files": {},
                "snapshot_hash": "",
                "details": {"error": bp_err},
            }

        # 5. Replacement Integrity & Action Logic
        existing_content = file_contents.get(file_path, "")
        original_files[file_path] = existing_content

        if action == "create":
            resulting_content = new_code
            total_lines_changed += len(new_code.splitlines())
        elif action == "delete":
            resulting_content = ""
            total_lines_changed += len(existing_content.splitlines())
        elif action == "modify":
            if not old_code or not old_code.strip():
                return {
                    "is_safe": False,
                    "rejection_reason": f"Action 'modify' requires non-empty old_code for '{file_path}'",
                    "scope_valid": True,
                    "replacements_valid": False,
                    "secrets_clean": True,
                    "ast_valid": True,
                    "bloat_valid": True,
                    "final_files": {},
                    "snapshot_hash": "",
                    "details": {"file": file_path},
                }

            match_count = existing_content.count(old_code)
            if match_count == 0:
                return {
                    "is_safe": False,
                    "rejection_reason": f"old_code not found in source file '{file_path}' (0 occurrences)",
                    "scope_valid": True,
                    "replacements_valid": False,
                    "secrets_clean": True,
                    "ast_valid": True,
                    "bloat_valid": True,
                    "final_files": {},
                    "snapshot_hash": "",
                    "details": {"file": file_path, "match_count": 0},
                }
            elif match_count > 1:
                return {
                    "is_safe": False,
                    "rejection_reason": f"old_code is ambiguous in '{file_path}' ({match_count} occurrences; exactly 1 required)",
                    "scope_valid": True,
                    "replacements_valid": False,
                    "secrets_clean": True,
                    "ast_valid": True,
                    "bloat_valid": True,
                    "final_files": {},
                    "snapshot_hash": "",
                    "details": {"file": file_path, "match_count": match_count},
                }

            resulting_content = existing_content.replace(old_code, new_code, 1)
            total_lines_changed += abs(len(new_code.splitlines()) - len(old_code.splitlines())) + len(old_code.splitlines())
        else:
            return {
                "is_safe": False,
                "rejection_reason": f"Unknown action '{action}' on file '{file_path}'",
                "scope_valid": True,
                "replacements_valid": False,
                "secrets_clean": True,
                "ast_valid": True,
                "bloat_valid": True,
                "final_files": {},
                "snapshot_hash": "",
                "details": {"action": action},
            }

        # 6. AST Syntax Check on Resulting Content
        if action in ("create", "modify"):
            ast_ok, ast_err = validate_code_syntax(file_path, resulting_content)
            if not ast_ok:
                return {
                    "is_safe": False,
                    "rejection_reason": f"AST Syntax validation failed for '{file_path}': {ast_err}",
                    "scope_valid": True,
                    "replacements_valid": True,
                    "secrets_clean": True,
                    "ast_valid": False,
                    "bloat_valid": True,
                    "final_files": {},
                    "snapshot_hash": "",
                    "details": {"ast_error": ast_err, "file": file_path},
                }

        final_files[file_path] = resulting_content

    # 7. Check Test Code Safety & Syntax
    if tests_to_add:
        for t in tests_to_add:
            t_file = t.get("file", "test.py").strip().replace("\\", "/")
            t_code = t.get("test_code", "")

            # Path check
            t_safe, t_err = sanitize_relative_path(t_file)
            if not t_safe:
                return {
                    "is_safe": False,
                    "rejection_reason": f"Unsafe test file path: {t_err}",
                    "scope_valid": False,
                    "replacements_valid": True,
                    "secrets_clean": True,
                    "ast_valid": True,
                    "bloat_valid": True,
                    "final_files": {},
                    "snapshot_hash": "",
                    "details": {"test_file": t_file},
                }

            # Secret check
            t_secrets = scan_for_secrets(t_code)
            if t_secrets:
                return {
                    "is_safe": False,
                    "rejection_reason": f"Secret detected in test code for '{t_file}'",
                    "scope_valid": True,
                    "replacements_valid": True,
                    "secrets_clean": False,
                    "ast_valid": True,
                    "bloat_valid": True,
                    "final_files": {},
                    "snapshot_hash": "",
                    "details": {"secrets": t_secrets},
                }

            # AST check
            t_ast_ok, t_ast_err = validate_code_syntax(t_file, t_code)
            if not t_ast_ok:
                return {
                    "is_safe": False,
                    "rejection_reason": f"AST Syntax validation failed for test file '{t_file}': {t_ast_err}",
                    "scope_valid": True,
                    "replacements_valid": True,
                    "secrets_clean": True,
                    "ast_valid": False,
                    "bloat_valid": True,
                    "final_files": {},
                    "snapshot_hash": "",
                    "details": {"ast_error": t_ast_err, "test_file": t_file},
                }

    # 8. Total Line Count Bloat Check
    if total_lines_changed > MAX_DIFF_LINES:
        return {
            "is_safe": False,
            "rejection_reason": f"Patch changes {total_lines_changed} lines, exceeding safe limit of {MAX_DIFF_LINES}",
            "scope_valid": True,
            "replacements_valid": True,
            "secrets_clean": True,
            "ast_valid": True,
            "bloat_valid": False,
            "final_files": {},
            "snapshot_hash": "",
            "details": {"total_lines_changed": total_lines_changed},
        }

    # 9. Direct Task Concrete Keyword / Content Validation
    if is_direct_task and task_keywords:
        all_new_text = " ".join(f["new_code"] for f in changes)
        missing_kw = [kw for kw in task_keywords if kw.lower() not in all_new_text.lower()]
        if missing_kw:
            return {
                "is_safe": False,
                "rejection_reason": f"Direct task output missing required contextual content: {missing_kw}",
                "scope_valid": True,
                "replacements_valid": True,
                "secrets_clean": True,
                "ast_valid": True,
                "bloat_valid": True,
                "final_files": final_files,
                "snapshot_hash": "",
                "details": {"missing_keywords": missing_kw},
            }

    # 10. Compute Final Snapshot Hash
    snapshot_hash = compute_patch_snapshot_hash(
        repository_id=repository_id,
        base_commit_sha=base_commit_sha,
        scope_files=scope_files,
        original_files=original_files,
        final_files=final_files,
    )

    return {
        "is_safe": True,
        "rejection_reason": None,
        "scope_valid": True,
        "replacements_valid": True,
        "secrets_clean": True,
        "ast_valid": True,
        "bloat_valid": True,
        "final_files": final_files,
        "snapshot_hash": snapshot_hash,
        "details": {
            "files_changed_count": len(changes),
            "total_lines_changed": total_lines_changed,
        },
    }
