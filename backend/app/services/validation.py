"""Validation engine — run lint, tests, build checks on proposed fixes."""
import asyncio
import os
import subprocess
import json
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ValidationResult:
    check_type: str  # lint, test, build, security
    status: str  # passed, failed, error, skipped
    message: str = ""
    details: str = ""
    duration_ms: int = 0


@dataclass
class ValidationReport:
    fix_id: str
    status: str  # passed, failed, error
    results: List[ValidationResult] = field(default_factory=list)
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    started_at: str = ""
    completed_at: str = ""


async def run_command(cmd: str, cwd: str = None, timeout: int = 120) -> Dict:
    """Run a shell command and return output."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }
    except asyncio.TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


async def validate_lint(project_path: str, language: str = "python") -> ValidationResult:
    """Run lint checks."""
    start = datetime.now(timezone.utc)
    checks = {
        "python": [
            ("python -m py_compile {file}", "Syntax check"),
            ("python -m ruff check {file} --output-format=text", "Ruff lint"),
        ],
        "javascript": [
            ("npx next lint", "ESLint"),
        ],
        "typescript": [
            ("npx tsc --noEmit", "TypeScript check"),
            ("npx next lint", "ESLint"),
        ],
        "go": [
            ("go vet ./...", "Go vet"),
        ],
        "rust": [
            ("cargo clippy --all-targets", "Clippy"),
        ],
    }

    lang_checks = checks.get(language, checks.get("python", []))
    all_output = []

    for cmd_template, name in lang_checks:
        cmd = cmd_template.replace("{file}", project_path)
        result = await run_command(cmd, cwd=os.path.dirname(project_path) if os.path.isfile(project_path) else project_path)
        status = "passed" if result["returncode"] == 0 else "failed"
        all_output.append(f"[{status}] {name}\n{result['stderr'] or result['stdout'][:500]}")

    duration = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    failed = any("[failed]" in o for o in all_output)

    return ValidationResult(
        check_type="lint",
        status="failed" if failed else "passed",
        message="Lint checks failed" if failed else "All lint checks passed",
        details="\n\n".join(all_output),
        duration_ms=duration,
    )


async def validate_tests(project_path: str, language: str = "python") -> ValidationResult:
    """Run test suite."""
    start = datetime.now(timezone.utc)
    test_commands = {
        "python": "python -m pytest --tb=short -q 2>&1 | head -50",
        "javascript": "npm test -- --watchAll=false 2>&1 | head -50",
        "typescript": "npm test -- --watchAll=false 2>&1 | head -50",
        "go": "go test ./... -short 2>&1 | head -50",
        "rust": "cargo test 2>&1 | head -50",
    }

    cmd = test_commands.get(language, test_commands["python"])
    result = await run_command(cmd, cwd=project_path, timeout=180)

    duration = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    output = result["stdout"] + result["stderr"]
    failed = result["returncode"] != 0

    return ValidationResult(
        check_type="test",
        status="failed" if failed else "passed",
        message="Tests failed" if failed else "All tests passed",
        details=output[:2000],
        duration_ms=duration,
    )


async def validate_build(project_path: str, language: str = "python") -> ValidationResult:
    """Run build check."""
    start = datetime.now(timezone.utc)
    build_commands = {
        "python": "python -m py_compile $(find . -name '*.py' | head -20 | tr '\\n' ' ') 2>&1",
        "javascript": "npm run build 2>&1 | tail -20",
        "typescript": "npm run build 2>&1 | tail -20",
        "go": "go build ./... 2>&1",
        "rust": "cargo build 2>&1 | tail -20",
    }

    cmd = build_commands.get(language, build_commands["python"])
    result = await run_command(cmd, cwd=project_path, timeout=300)

    duration = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    output = result["stdout"] + result["stderr"]
    failed = result["returncode"] != 0

    return ValidationResult(
        check_type="build",
        status="failed" if failed else "passed",
        message="Build failed" if failed else "Build succeeded",
        details=output[:2000],
        duration_ms=duration,
    )


async def validate_security(project_path: str) -> ValidationResult:
    """Run basic security checks."""
    start = datetime.now(timezone.utc)
    issues = []

    # Check for common security issues in modified files
    try:
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__"}]
            for fname in files[:50]:  # Limit
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read(50000)
                    from app.services.security import scan_for_secrets
                    findings = scan_for_secrets(content, fpath)
                    for finding in findings:
                        if finding.get("type") == "secret":
                            issues.append(f"{fpath}:{finding.get('line', '?')} - {finding.get('secret_type', 'Unknown secret')}")
                except Exception:
                    pass
    except Exception as e:
        issues.append(f"Security scan error: {e}")

    duration = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    return ValidationResult(
        check_type="security",
        status="failed" if issues else "passed",
        message=f"{len(issues)} security issues found" if issues else "No security issues found",
        details="\n".join(issues) if issues else "Clean",
        duration_ms=duration,
    )


async def run_validation(
    fix_id: str,
    project_path: str,
    language: str = "python",
    checks: List[str] = None,
) -> ValidationReport:
    """Run full validation suite on a proposed fix."""
    if checks is None:
        checks = ["lint", "test", "build", "security"]

    report = ValidationReport(
        fix_id=fix_id,
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    # Run checks in parallel
    check_fns = {
        "lint": lambda: validate_lint(project_path, language),
        "test": lambda: validate_tests(project_path, language),
        "build": lambda: validate_build(project_path, language),
        "security": lambda: validate_security(project_path),
    }

    results = await asyncio.gather(
        *[check_fns[c]() for c in checks if c in check_fns],
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, ValidationResult):
            report.results.append(result)
            report.total_checks += 1
            if result.status == "passed":
                report.passed_checks += 1
            elif result.status == "failed":
                report.failed_checks += 1
        elif isinstance(result, Exception):
            report.results.append(ValidationResult(
                check_type="unknown",
                status="error",
                message=str(result),
            ))
            report.total_checks += 1
            report.failed_checks += 1

    report.status = "passed" if report.failed_checks == 0 else "failed"
    report.completed_at = datetime.now(timezone.utc).isoformat()

    return report
