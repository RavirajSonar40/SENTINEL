"""Security — secret scanning and prompt injection defense."""
import re
from typing import List, Dict, Tuple


# --- Secret Patterns ---

SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]([A-Za-z0-9_\-]{20,})['\"]", "API Key"),
    (r"(?i)(secret[_-]?key|secretkey)\s*[:=]\s*['\"]([A-Za-z0-9_\-]{20,})['\"]", "Secret Key"),
    (r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]([^\s'\"]{8,})['\"]", "Password"),
    (r"(?i)(token|auth[_-]?token|access[_-]?token)\s*[:=]\s*['\"]([A-Za-z0-9_\-\.]{20,})['\"]", "Auth Token"),
    (r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", "Private Key"),
    (r"(?i)(AWS_SECRET_ACCESS_KEY|aws_secret_access_key)\s*[:=]\s*['\"]([A-Za-z0-9/+=]{40})['\"]", "AWS Secret"),
    (r"(?i)(AWS_ACCESS_KEY_ID|aws_access_key_id)\s*[:=]\s*['\"]?(AKIA[A-Z0-9]{16})['\"]?", "AWS Access Key"),
    (r"(?i)ghp_[A-Za-z0-9]{36}", "GitHub PAT"),
    (r"(?i)gho_[A-Za-z0-9]{36}", "GitHub OAuth Token"),
    (r"(?i)sk-[A-Za-z0-9]{32,}", "OpenAI API Key"),
    (r"(?i)xox[bpsa]-[A-Za-z0-9\-]+", "Slack Token"),
    (r"(?i)(DATABASE_URL|REDIS_URL|MONGODB_URI)\s*[:=]\s*['\"]([^\s'\"]+)['\"]", "Connection String"),
]

# Files to always skip
SKIP_FILES = {
    ".env", ".env.local", ".env.production", ".env.staging",
    ".env.development", ".env.test",
    "credentials.json", "service-account.json",
    "id_rsa", "id_ed25519", "id_rsa.pub", "id_ed25519.pub",
    "*.pem", "*.key", "*.p12", "*.pfx",
}

# Directories to always skip
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv",
    "dist", "build", ".next", ".cache",
}


def scan_for_secrets(content: str, file_path: str = "") -> List[Dict]:
    """Scan content for secrets and sensitive data."""
    findings = []

    # Check if file should be skipped
    if _should_skip_file(file_path):
        return [{"type": "skipped", "message": f"File skipped from indexing: {file_path}"}]

    for pattern, secret_type in SECRET_PATTERNS:
        matches = re.finditer(pattern, content)
        for match in matches:
            line_num = content[:match.start()].count("\n") + 1
            findings.append({
                "type": "secret",
                "secret_type": secret_type,
                "line": line_num,
                "file": file_path,
                "match": match.group()[:20] + "...",  # Truncate
                "severity": "critical",
            })

    return findings


def _should_skip_file(file_path: str) -> bool:
    """Check if a file should be skipped entirely."""
    import os
    basename = os.path.basename(file_path).lower()
    for skip in SKIP_FILES:
        if skip.startswith("*"):
            if basename.endswith(skip[1:]):
                return True
        elif basename == skip.lower():
            return True

    parts = file_path.replace("\\", "/").split("/")
    for part in parts:
        if part.lower() in SKIP_DIRS:
            return True

    return False


def sanitize_file_for_indexing(content: str, file_path: str) -> Tuple[str, List[Dict]]:
    """Remove secrets from content before indexing. Returns (sanitized, findings)."""
    findings = scan_for_secrets(content, file_path)
    sanitized = content

    for finding in findings:
        if finding.get("type") == "secret":
            # Replace the secret with a placeholder
            original = finding.get("match", "")
            if original:
                sanitized = sanitized.replace(original.split("...")[0], "[REDACTED]")

    return sanitized, findings


# --- Prompt Injection Defense ---

INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?previous\s+instructions",
    r"(?i)disregard\s+(all\s+)?prior\s+instructions",
    r"(?i)forget\s+(all\s+)?previous",
    r"(?i)you\s+are\s+now\s+(a|an)\s+",
    r"(?i)system\s*prompt\s*:",
    r"(?i)new\s+instructions?\s*:",
    r"(?i)override\s+(all\s+)?instructions",
    r"(?i)act\s+as\s+if\s+you",
    r"(?i)pretend\s+you\s+are",
    r"(?i)from\s+now\s+on\s+you",
    r"(?i)<!\-\-\s*system\s*:",
    r"(?i)\[system\]",
    r"(?i)ADMIN\s*MODE",
    r"(?i)DEBUG\s*MODE",
    r"(?i)DAN\s*MODE",
    r"(?i)jailbreak",
    r"(?i)you\s+must\s+obey",
]


def detect_prompt_injection(text: str) -> Dict:
    """Detect potential prompt injection in user-provided text."""
    findings = []

    for pattern in INJECTION_PATTERNS:
        matches = re.finditer(pattern, text)
        for match in matches:
            line_num = text[:match.start()].count("\n") + 1
            findings.append({
                "type": "prompt_injection",
                "pattern": match.group(),
                "line": line_num,
                "severity": "high",
                "action": "blocked",
            })

    return {
        "injection_detected": len(findings) > 0,
        "findings": findings,
        "safe_text": _sanitize_injection(text, findings) if findings else text,
    }


def _sanitize_injection(text: str, findings: List[Dict]) -> str:
    """Remove injection patterns from text."""
    sanitized = text
    for f in findings:
        pattern = f.get("pattern", "")
        if pattern:
            sanitized = re.sub(pattern, "[CONTENT REMOVED - POTENTIAL INJECTION]", sanitized, flags=re.IGNORECASE)
    return sanitized


def validate_input(text: str, context: str = "general") -> Dict:
    """Validate user input for security issues."""
    issues = []

    # Check for secrets
    secret_findings = scan_for_secrets(text)
    if secret_findings:
        issues.extend([f for f in secret_findings if f.get("type") == "secret"])

    # Check for prompt injection
    injection = detect_prompt_injection(text)
    if injection["injection_detected"]:
        issues.extend(injection["findings"])

    return {
        "safe": len(issues) == 0,
        "issues": issues,
        "sanitized_text": injection.get("safe_text", text),
    }
