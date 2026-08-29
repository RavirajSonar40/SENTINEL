"""Sandboxed Subprocess Command and Regression Test Runner for Phase 11.

Enforces:
1. Structured argument arrays with shell=False execution.
2. Binary allowlist (pytest, python, npm, npx, jest, go, cargo).
3. Shell metacharacter rejection (;, &&, ||, |, >, <, $(), `).
4. Subprocess environment isolation: scrubbed credentials, unreachable proxy endpoints, package manager offline mode.
5. Independent runner-level workspace path containment (rejecting traversal, absolute paths, and symlink escapes).
6. Strict patch application (fail-fast on missing files or non-unique replacement counts).
7. Two-phase bug regression execution: Base commit FAIL -> Patched workspace PASS.
8. Process tree termination on 30s timeout (taskkill /F /T /PID on Windows).
"""
import os
import sys
import shutil
import subprocess
import tempfile
import re
from typing import Dict, List, Optional, Tuple, Any
import logging

from app.services.security import sanitize_file_for_indexing

logger = logging.getLogger("sentinel.patch_test_runner")

MAX_OUTPUT_BYTES = 50 * 1024  # 50 KB
DEFAULT_TIMEOUT_SECONDS = 30

ALLOWED_COMMAND_BINARIES = {
    "pytest",
    "python",
    "python3",
    "npm",
    "npx",
    "jest",
    "go",
    "cargo",
}

FORBIDDEN_METACHARACTERS = [";", "&&", "||", "|", ">", "<", "$(", "`", "\n", "\r", "&"]

SCRUBBED_ENV_VARS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "NVIDIA_API_KEY",
    "PINECONE_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "GITHUB_TOKEN",
    "GITHUB_CLIENT_SECRET",
    "GITHUB_WEBHOOK_SECRET",
    "SENTRY_AUTH_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SESSION_TOKEN",
    "SECRET_KEY",
    "JWT_SECRET",
]


def resolve_contained_workspace_path(workspace: str, rel_path: str) -> str:
    """Independently resolve and validate that rel_path is strictly contained within workspace.
    
    Rejects:
    - Absolute paths (/etc/passwd, C:\\Windows, \\\\network)
    - Traversal sequences (../, ./)
    - Sensitive files (.env, .git, .ssh, private keys)
    - Symlinks pointing outside the workspace directory
    """
    if not rel_path or not rel_path.strip():
        raise ValueError("File path cannot be empty")

    clean = rel_path.strip().replace("\\", "/")
    
    # 1. Reject absolute or home-relative paths
    if clean.startswith("/") or clean.startswith("~") or (len(clean) > 1 and clean[1] == ":"):
        raise ValueError(f"Absolute or home paths forbidden: '{rel_path}'")

    parts = [p for p in clean.split("/") if p]
    if not parts:
        raise ValueError("File path contains no valid segments")

    # 2. Reject path traversal
    if ".." in parts or "." in parts:
        raise ValueError(f"Path traversal forbidden: '{rel_path}'")

    # 3. Reject sensitive names
    for p in parts:
        p_low = p.lower()
        if (
            p_low in (".git", ".env", ".ssh", ".aws", "credentials", "secrets")
            or p_low.startswith(".env")
            or p_low.endswith(".env")
            or p_low.endswith(".key")
            or p_low.endswith(".pem")
            or "secret" in p_low
            or "credential" in p_low
        ):
            raise ValueError(f"Access to sensitive file or directory forbidden: '{rel_path}'")

    # 4. Canonical workspace resolution
    workspace_real = os.path.realpath(os.path.abspath(workspace))
    target_abs = os.path.abspath(os.path.join(workspace_real, *parts))

    # 5. Check symlink escape
    if os.path.islink(target_abs):
        link_target = os.path.realpath(target_abs)
        if not (link_target == workspace_real or link_target.startswith(workspace_real + os.sep)):
            raise ValueError(f"Symlink escape detected: '{rel_path}' points outside workspace")

    # 6. Verify directory boundary containment
    if not (target_abs == workspace_real or target_abs.startswith(workspace_real + os.sep)):
        raise ValueError(f"Path escape detected: '{rel_path}' escapes workspace boundary")

    return target_abs


def validate_command_array(cmd_args: List[str]) -> Tuple[bool, Optional[str], List[str]]:
    """Validate that command is a structured array using allowlisted binaries without shell operators."""
    if not isinstance(cmd_args, list) or len(cmd_args) == 0:
        return False, "Test command must be a non-empty list of argument strings", []

    # Check for shell metacharacters in every argument
    for arg in cmd_args:
        if not isinstance(arg, str):
            return False, f"All command arguments must be strings, got {type(arg)}", []
        for meta in FORBIDDEN_METACHARACTERS:
            if meta in arg:
                return False, f"Command contains forbidden shell metacharacter '{meta}' in argument: '{arg}'", []

    binary_raw = cmd_args[0].lower()
    base_bin = os.path.splitext(os.path.basename(binary_raw))[0]

    # Resolve Python runner
    if base_bin in ("pytest", "python", "python3") or binary_raw == sys.executable.lower():
        if base_bin == "pytest":
            resolved_cmd = [sys.executable, "-m", "pytest", "-o", "rootdir=.", "-c", "none"] + cmd_args[1:]
        else:
            resolved_cmd = [sys.executable] + cmd_args[1:]
        return True, None, resolved_cmd

    # Check against allowlist
    if base_bin in ALLOWED_COMMAND_BINARIES:
        real_bin = shutil.which(cmd_args[0])
        if not real_bin:
            return False, f"Allowlisted executable '{cmd_args[0]}' is not installed on system", []
        resolved_cmd = [real_bin] + cmd_args[1:]
        return True, None, resolved_cmd
    else:
        return False, f"Executable '{cmd_args[0]}' is not in allowed test runner allowlist: {sorted(ALLOWED_COMMAND_BINARIES)}", []


def build_sandboxed_environment() -> Dict[str, str]:
    """Create a scrubbed, network-restricted environment without production credentials."""
    env = os.environ.copy()

    # 1. Scrub credentials and sensitive tokens
    for var in SCRUBBED_ENV_VARS:
        env.pop(var, None)

    # 2. Block outbound networking via invalid proxies and offline flags
    env["HTTP_PROXY"] = "http://127.0.0.1:1"
    env["HTTPS_PROXY"] = "http://127.0.0.1:1"
    env["ALL_PROXY"] = "socks5://127.0.0.1:1"
    env["NO_PROXY"] = ""
    env["CURL_CA_BUNDLE"] = "/dev/null"
    env["SSL_CERT_FILE"] = "/dev/null"
    
    # 3. Package manager offline mode enforcement
    env["PIP_NO_INDEX"] = "1"
    env["NPM_CONFIG_OFFLINE"] = "true"
    env["GOPROXY"] = "off"
    env["CARGO_NET_OFFLINE"] = "true"

    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    return env


def run_sandboxed_command(
    cmd_args: List[str],
    cwd: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Execute a single test command inside the sandbox with OS-level timeout enforcement and shell=False."""
    is_valid, err_msg, resolved_args = validate_command_array(cmd_args)
    if not is_valid:
        return {
            "passed": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command validation rejected: {err_msg}",
            "timed_out": False,
            "command": cmd_args,
        }

    env = build_sandboxed_environment()

    try:
        proc = subprocess.Popen(
            resolved_args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            shell=False,
        )

        try:
            stdout_raw, stderr_raw = proc.communicate(timeout=timeout_seconds)
            timed_out = False
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = -1
            # Terminate entire process tree
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()
            stdout_raw, stderr_raw = proc.communicate()
            stderr_raw = (stderr_raw or "") + f"\n[Process terminated after {timeout_seconds}s timeout]"

        # Sanitize and truncate outputs
        clean_stdout_str, _ = sanitize_file_for_indexing(stdout_raw or "", "output.log")
        clean_stderr_str, _ = sanitize_file_for_indexing(stderr_raw or "", "output.log")

        clean_stdout = clean_stdout_str[:MAX_OUTPUT_BYTES]
        clean_stderr = clean_stderr_str[:MAX_OUTPUT_BYTES]

        return {
            "passed": exit_code == 0 and not timed_out,
            "exit_code": exit_code,
            "stdout": clean_stdout,
            "stderr": clean_stderr,
            "timed_out": timed_out,
            "command": resolved_args,
        }
    except Exception as e:
        logger.error(f"Execution error running {resolved_args}: {e}")
        return {
            "passed": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Failed to spawn subprocess: {str(e)}",
            "timed_out": False,
            "command": resolved_args,
        }


def apply_patch_to_workspace(workspace: str, patch_changes: List[Dict[str, Any]]) -> None:
    """Strictly apply patch changes to workspace with fail-fast validation."""
    for change in patch_changes:
        rel_file = change.get("file", "")
        action = change.get("action", "modify").lower()
        old_c = change.get("old_code", "")
        new_c = change.get("new_code", "")

        target_f = resolve_contained_workspace_path(workspace, rel_file)

        if action == "create":
            if os.path.exists(target_f):
                raise ValueError(f"Cannot create already-existing file: '{rel_file}'")
            os.makedirs(os.path.dirname(target_f), exist_ok=True)
            with open(target_f, "w", encoding="utf-8") as f:
                f.write(new_c or "")

        elif action == "delete":
            if not os.path.exists(target_f):
                raise ValueError(f"Cannot delete non-existent file: '{rel_file}'")
            os.remove(target_f)

        elif action == "modify":
            if not os.path.exists(target_f):
                raise ValueError(f"Cannot modify non-existent file: '{rel_file}'")
            with open(target_f, "r", encoding="utf-8") as f:
                current_content = f.read()

            matches = current_content.count(old_c)
            if matches == 0:
                raise ValueError(f"Patch modification failed: old_code not found (0 matches) in '{rel_file}'")
            if matches > 1:
                raise ValueError(f"Patch modification failed: ambiguous old_code ({matches} matches) in '{rel_file}'")

            updated_content = current_content.replace(old_c, new_c or "", 1)
            with open(target_f, "w", encoding="utf-8") as f:
                f.write(updated_content)

        else:
            raise ValueError(f"Unsupported patch action '{action}' for file '{rel_file}'")


def execute_two_phase_regression_test(
    file_contents: Dict[str, str],
    patch_changes: List[Dict[str, Any]],
    regression_tests: List[Dict[str, Any]],
    test_commands: Optional[List[List[str]]] = None,
) -> Dict[str, Any]:
    """Execute complete two-phase regression verification:

    Phase 1: Pre-patch in base workspace -> Regression test must FAIL.
    Phase 2: Apply patch in workspace with strict application validation -> Regression test must PASS.
    """
    if not regression_tests:
        return {
            "status": "not_applicable",
            "pre_patch_failed": False,
            "post_patch_passed": False,
            "message": "No regression tests specified",
            "runs": [],
        }

    workspace = tempfile.mkdtemp(prefix="sentinel_reg_")
    runs_log = []

    try:
        # 1. Write base files into workspace with path containment check
        for path, content in file_contents.items():
            full_path = resolve_contained_workspace_path(workspace, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

        # 2. Write regression tests into workspace with path containment check
        test_file_paths = []
        for t in regression_tests:
            t_path = t.get("file", "test_regression.py")
            t_code = t.get("test_code", "")
            full_t_path = resolve_contained_workspace_path(workspace, t_path)
            os.makedirs(os.path.dirname(full_t_path), exist_ok=True)
            with open(full_t_path, "w", encoding="utf-8") as f:
                f.write(t_code)
            test_file_paths.append(t_path)

        # 3. Determine test command (isolated rootdir prevents scanning parent repos)
        commands_to_execute = test_commands or [[sys.executable, "-m", "pytest", "-v", "-o", "rootdir=.", "-c", "none", p] for p in test_file_paths]

        # =====================================================================
        # Phase 1: Pre-patch execution -> MUST FAIL
        # =====================================================================
        pre_patch_results = []
        for cmd in commands_to_execute:
            res = run_sandboxed_command(cmd, cwd=workspace)
            res["phase"] = "pre_patch"
            pre_patch_results.append(res)
            runs_log.append(res)

        pre_patch_failed = any(not r["passed"] for r in pre_patch_results)
        if not pre_patch_failed:
            return {
                "status": "failed_pre_check",
                "pre_patch_failed": False,
                "post_patch_passed": False,
                "message": "Regression test passed before patch was applied; reproduction failed.",
                "runs": runs_log,
            }

        # =====================================================================
        # Phase 2: Apply patch with strict fail-fast validation
        # =====================================================================
        try:
            apply_patch_to_workspace(workspace, patch_changes)
        except ValueError as patch_err:
            return {
                "status": "failed_post_check",
                "pre_patch_failed": pre_patch_failed,
                "post_patch_passed": False,
                "message": f"Strict patch application rejected: {str(patch_err)}",
                "runs": runs_log,
            }

        # =====================================================================
        # Phase 3: Post-patch execution -> MUST PASS
        # =====================================================================
        post_patch_results = []
        for cmd in commands_to_execute:
            res = run_sandboxed_command(cmd, cwd=workspace)
            res["phase"] = "post_patch"
            post_patch_results.append(res)
            runs_log.append(res)

        post_patch_passed = all(r["passed"] for r in post_patch_results)
        if not post_patch_passed:
            return {
                "status": "failed_post_check",
                "pre_patch_failed": True,
                "post_patch_passed": False,
                "message": "Regression test failed after applying patch; fix is incomplete.",
                "runs": runs_log,
            }

        return {
            "status": "reproduced_and_fixed",
            "pre_patch_failed": True,
            "post_patch_passed": True,
            "message": "Regression test failed before patch and passed after patch.",
            "runs": runs_log,
        }
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def validate_workspace_path_containment(workspace: str, rel_path: str) -> Tuple[bool, Optional[str]]:
    """Validate that rel_path is strictly contained within workspace."""
    try:
        resolve_contained_workspace_path(workspace, rel_path)
        return True, None
    except Exception as e:
        return False, str(e)


def execute_sandboxed_subprocess(
    workspace_path: str,
    command: List[str],
    timeout_sec: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Execute command in sandbox and return normalized output dict."""
    import time
    start = time.perf_counter()
    res = run_sandboxed_command(cmd_args=command, cwd=workspace_path, timeout_seconds=timeout_sec)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    return {
        "success": res.get("passed", False),
        "status": "passed" if res.get("passed") else ("timeout" if res.get("timed_out") else "failed"),
        "exit_code": res.get("exit_code"),
        "stdout": res.get("stdout", ""),
        "stderr": res.get("stderr", ""),
        "duration_ms": duration_ms,
        "error": res.get("stderr") if not res.get("passed") else None,
    }

