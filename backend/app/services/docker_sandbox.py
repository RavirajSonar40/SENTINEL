"""Hardened Docker Sandbox Runner for Isolated Validation & Replay.

Enforces zero-network, read-only rootfs, stripped Linux capabilities, non-root execution,
and memory/CPU caps for untrusted validation checks.
"""
import os
import shutil
import subprocess
import logging
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# Standardized hardened execution parameters
DOCKER_DEFAULT_USER = "65534:65534"
DOCKER_DEFAULT_MEMORY = "512m"
DOCKER_DEFAULT_CPUS = "1.0"
DOCKER_DEFAULT_PIDS_LIMIT = "100"
DOCKER_DEFAULT_TMPFS = "/tmp:rw,noexec,nosuid,size=64m"
DOCKER_DEFAULT_TIMEOUT_SEC = 30
MAX_OUTPUT_BYTES = 64 * 1024  # 64KB

# Default pinned trusted base images
DEFAULT_IMAGE_MAP = {
    "python": "python:3.11-slim@sha256:4b4074127ab0d60c443685e135a513ca0ad49520e2ef5b47cb8be9a90409a25b",
    "node": "node:20-slim@sha256:0d2c0ecb39d1b764b8bb26c36199677334790ccb8db4ef99df3d8208764030a5",
    "golang": "golang:1.22-alpine@sha256:05bc56bfb9d0124ad568779be35f4dfa1ebae88f8d672807f66a9fd0ac6679fb",
    "rust": "rust:1.77-slim@sha256:f5ea9b69b03652cb93297a7e841f3e7925e0a02b70f074d2fc151593c6833b3b",
}

FORBIDDEN_DOCKER_FLAGS = [
    "--privileged",
    "--net=host",
    "--network=host",
    "/var/run/docker.sock",
    "-v /",
    "--volume /",
    "--cap-add",
    "--security-opt=apparmor=unconfined",
    "--security-opt=seccomp=unconfined",
]


def is_docker_available() -> bool:
    """Check if Docker executable and daemon are responsive."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        res = subprocess.run(
            [docker_bin, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            shell=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def build_hardened_docker_args(
    workspace_path: str,
    image_name: str,
    command: List[str],
    user: str = DOCKER_DEFAULT_USER,
    memory: str = DOCKER_DEFAULT_MEMORY,
    cpus: str = DOCKER_DEFAULT_CPUS,
    pids_limit: str = DOCKER_DEFAULT_PIDS_LIMIT,
    read_only: bool = True,
    network: str = "none",
) -> List[str]:
    """Assemble hardened, least-privilege Docker run CLI arguments."""
    norm_workspace = os.path.abspath(workspace_path)

    # Validate workspace path exists
    if not os.path.exists(norm_workspace):
        raise ValueError(f"Workspace path does not exist: {norm_workspace}")

    # Build container argument array
    args = [
        "docker", "run", "--rm",
        f"--network={network}",
        f"--memory={memory}",
        f"--cpus={cpus}",
        f"--pids-limit={pids_limit}",
        f"--user={user}",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--tmpfs={DOCKER_DEFAULT_TMPFS}",
        "-v", f"{norm_workspace}:/workspace:rw",
        "-w", "/workspace",
    ]

    if read_only:
        args.append("--read-only")

    args.append(image_name)
    args.extend(command)

    # Pre-execution safety verification against forbidden flags
    cmd_str = " ".join(args).lower()
    for forbidden in FORBIDDEN_DOCKER_FLAGS:
        if forbidden.lower() in cmd_str:
            raise ValueError(f"Forbidden Docker flag detected: {forbidden}")

    return args


def execute_in_docker_sandbox(
    workspace_path: str,
    command: List[str],
    language: str = "python",
    image: Optional[str] = None,
    timeout_sec: int = DOCKER_DEFAULT_TIMEOUT_SEC,
    user: str = DOCKER_DEFAULT_USER,
) -> Dict[str, Any]:
    """Execute command inside an isolated ephemeral Docker container with resource caps."""
    from app.services.patch_safety_engine import sensitive_data_redactor

    target_image = image or DEFAULT_IMAGE_MAP.get(language, DEFAULT_IMAGE_MAP["python"])
    
    try:
        docker_args = build_hardened_docker_args(
            workspace_path=workspace_path,
            image_name=target_image,
            command=command,
            user=user,
        )
    except Exception as e:
        return {
            "success": False,
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Docker argument assembly error: {str(e)}",
            "duration_ms": 0.0,
            "error": str(e),
        }

    import time
    start_time = time.perf_counter()

    try:
        proc = subprocess.run(
            docker_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
            shell=False,
        )
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Truncate and scrub outputs
        stdout = (proc.stdout or "")[:MAX_OUTPUT_BYTES]
        stderr = (proc.stderr or "")[:MAX_OUTPUT_BYTES]

        redacted_stdout = sensitive_data_redactor(stdout)
        redacted_stderr = sensitive_data_redactor(stderr)

        return {
            "success": proc.returncode == 0,
            "status": "passed" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode,
            "stdout": redacted_stdout,
            "stderr": redacted_stderr,
            "duration_ms": duration_ms,
            "error": None if proc.returncode == 0 else f"Command exited with code {proc.returncode}",
        }

    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "success": False,
            "status": "timeout",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout_sec} seconds.",
            "duration_ms": duration_ms,
            "error": f"Timeout after {timeout_sec}s",
        }
    except Exception as e:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "success": False,
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Execution failed: {str(e)}",
            "duration_ms": duration_ms,
            "error": str(e),
        }
