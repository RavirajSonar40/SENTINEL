"""Hypothesis engine — generates competing hypotheses, critiques them, identifies root cause."""
import hashlib
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from app.services.investigation_engine import InvestigationState
from app.services.llm import generate_json


@dataclass
class Hypothesis:
    id: str
    label: str
    description: str
    confidence: str  # high, medium, low
    supporting_evidence: List[Dict] = field(default_factory=list)
    contradicting_evidence: List[Dict] = field(default_factory=list)
    supporting_count: int = 0
    contradicting_count: int = 0
    status: str = "active"  # active, supported, rejected
    rejection_reason: Optional[str] = None
    severity: str = "medium"  # low, medium, high, critical
    category: str = "unknown"  # deployment, dependency, code_change, config, infrastructure, data

    def __post_init__(self):
        if not self.id:
            raw = f"{self.label}:{self.description}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:12]


# --- Pattern Libraries ---

ERROR_PATTERNS = {
    "null_pointer": {
        "keywords": ["null", "undefined", "None", "nil", "cannot read property", "type error"],
        "category": "code_change",
        "severity": "high",
    },
    "database": {
        "keywords": ["connection refused", "timeout", "deadlock", "duplicate key", "foreign key", "sql"],
        "category": "infrastructure",
        "severity": "critical",
    },
    "memory": {
        "keywords": ["out of memory", "heap", "stack overflow", "oom", "memory leak"],
        "category": "code_change",
        "severity": "critical",
    },
    "network": {
        "keywords": ["timeout", "connection refused", "dns", "econnreset", "socket"],
        "category": "infrastructure",
        "severity": "high",
    },
    "dependency": {
        "keywords": ["module not found", "cannot import", "no module named", "version mismatch"],
        "category": "dependency",
        "severity": "high",
    },
    "authentication": {
        "keywords": ["unauthorized", "forbidden", "401", "403", "token expired", "invalid token"],
        "category": "config",
        "severity": "medium",
    },
    "deployment": {
        "keywords": ["container", "pod", "restart", "crashloop", "imagepull", "health check"],
        "category": "deployment",
        "severity": "high",
    },
}


def detect_error_patterns(signals: List[str], description: str) -> Dict[str, float]:
    """Detect which error patterns are present in the incident."""
    combined_text = " ".join(signals + [description]).lower()
    patterns = {}

    for pattern_name, pattern_info in ERROR_PATTERNS.items():
        score = 0
        for keyword in pattern_info["keywords"]:
            if keyword.lower() in combined_text:
                score += 1
        if score > 0:
            patterns[pattern_name] = score / len(pattern_info["keywords"])

    return patterns


def generate_hypotheses(state: InvestigationState) -> List[Hypothesis]:
    """Generate competing hypotheses based on incident data and evidence."""
    hypotheses = []
    seen = set()

    # Detect patterns
    patterns = detect_error_patterns(state.error_signals, state.incident_description)

    # Generate pattern-based hypotheses
    for pattern_name, score in patterns.items():
        pattern_info = ERROR_PATTERNS[pattern_name]
        label = f"{pattern_name.replace('_', ' ').title()} Issue"
        desc = f"The incident is caused by a {pattern_name.replace('_', ' ')} related error"

        if pattern_name in ("null_pointer", "memory", "dependency"):
            desc += " likely introduced by a recent code change or dependency update"
        elif pattern_name in ("database", "network", "authentication"):
            desc += " possibly due to infrastructure or configuration issues"
        elif pattern_name == "deployment":
            desc += " possibly related to a recent deployment"

        h = Hypothesis(
            id="",
            label=label,
            description=desc,
            confidence="high" if score > 0.3 else "medium",
            severity=pattern_info["severity"],
            category=pattern_info["category"],
        )
        if h.id not in seen:
            seen.add(h.id)
            hypotheses.append(h)

    # Generate evidence-based hypotheses from code search results
    evidence_groups = {}
    for ev in state.evidence_collected:
        file = ev.get("file", "unknown")
        if file not in evidence_groups:
            evidence_groups[file] = []
        evidence_groups[file].append(ev)

    for file_path, file_evidence in list(evidence_groups.items())[:5]:
        symbols = [e.get("symbol") for e in file_evidence if e.get("symbol")]
        symbol_str = ", ".join(symbols[:3]) if symbols else file_path.split("/")[-1]

        h = Hypothesis(
            id="",
            label=f"Issue in {symbol_str}",
            description=f"Code in {file_path} may contain the bug based on semantic similarity to error signals",
            confidence="medium",
            severity="medium",
            category="code_change",
            supporting_evidence=file_evidence,
            supporting_count=len(file_evidence),
        )
        if h.id not in seen:
            seen.add(h)
            hypotheses.append(h)

    # Add catch-all hypotheses if too few
    if len(hypotheses) < 3:
        catch_alls = [
            ("Recent Deployment", "A recent deployment introduced a regression", "deployment", "medium"),
            ("Dependency Version Mismatch", "A dependency update caused compatibility issues", "dependency", "medium"),
            ("Configuration Change", "A configuration change altered expected behavior", "config", "low"),
            ("Infrastructure Failure", "An underlying infrastructure component is degraded", "infrastructure", "medium"),
            ("Data State Issue", "An unexpected data state triggered the error", "data", "low"),
        ]
        for label, desc, category, confidence in catch_alls:
            h = Hypothesis(
                id="",
                label=label,
                description=desc,
                confidence=confidence,
                severity="medium",
                category=category,
            )
            if h.id not in seen:
                seen.add(h)
                hypotheses.append(h)

    # Sort by confidence
    conf_order = {"high": 0, "medium": 1, "low": 2}
    hypotheses.sort(key=lambda h: conf_order.get(h.confidence, 3))

    return hypotheses


async def generate_hypotheses_llm(state: InvestigationState, evidence: List[Dict]) -> List[Hypothesis]:
    """Use LLM to generate hypotheses based on incident and evidence."""
    system_prompt = """You are an expert incident investigator. Given an incident and collected evidence, generate competing hypotheses about the root cause.

Respond with JSON:
{
  "hypotheses": [
    {
      "label": "Short name for the hypothesis",
      "description": "Detailed explanation of what might be causing the incident",
      "confidence": "high|medium|low",
      "category": "code_change|dependency|config|deployment|infrastructure|data",
      "severity": "low|medium|high|critical",
      "evidence_for": ["list of evidence supporting this"],
      "evidence_against": ["list of evidence contradicting this"]
    }
  ]
}

Generate 3-5 competing hypotheses. Be specific and technical."""

    evidence_text = json.dumps(evidence[:10], indent=2) if evidence else "No evidence collected yet."

    user_prompt = f"""Incident: {state.incident_title}
Description: {state.incident_description}
Error signals: {', '.join(state.error_signals[:5]) if state.error_signals else 'None'}
Service: {state.service or 'Unknown'}

Collected evidence:
{evidence_text}"""

    try:
        result = await generate_json(system_prompt, user_prompt)
        hypotheses = []
        for h_data in result.get("hypotheses", []):
            h = Hypothesis(
                id="",
                label=h_data.get("label", "Unknown"),
                description=h_data.get("description", ""),
                confidence=h_data.get("confidence", "medium"),
                category=h_data.get("category", "unknown"),
                severity=h_data.get("severity", "medium"),
                supporting_count=len(h_data.get("evidence_for", [])),
                contradicting_count=len(h_data.get("evidence_against", [])),
            )
            hypotheses.append(h)
        return hypotheses
    except Exception as e:
        print(f"LLM hypothesis generation failed, using fallback: {e}")
        return generate_hypotheses(state)


def critique_hypotheses(hypotheses: List[Hypothesis], evidence: List[Dict]) -> List[Hypothesis]:
    """Evaluate each hypothesis against collected evidence."""
    for h in hypotheses:
        supporting = 0
        contradicting = 0

        for ev in evidence:
            ev_text = f"{ev.get('file', '')} {ev.get('symbol', '')} {ev.get('content_preview', '')}".lower()
            h_text = f"{h.label} {h.description}".lower()

            # Check for alignment
            overlap = sum(1 for word in h_text.split() if word in ev_text)
            if overlap > 1:
                supporting += 1
            elif h.category == "code_change" and "code_search" in ev.get("source", ""):
                supporting += 1

        h.supporting_count = supporting
        h.contradicting_count = contradicting

        # Update confidence based on evidence
        if supporting >= 3 and contradicting == 0:
            h.confidence = "high"
            h.status = "supported"
        elif contradicting > supporting:
            h.confidence = "low"
            h.status = "rejected"
            h.rejection_reason = "Contradicted by more evidence than supports it"

    return hypotheses


def identify_root_cause(
    state: InvestigationState,
    hypotheses: List[Hypothesis],
) -> Optional[Dict]:
    """Identify root cause from supported hypotheses, or abstain."""
    # Filter to supported hypotheses
    supported = [h for h in hypotheses if h.status == "supported"]
    if not supported:
        supported = [h for h in hypotheses if h.status != "rejected"]

    if not supported:
        return None  # Abstain

    # Pick highest confidence
    conf_order = {"high": 0, "medium": 1, "low": 2}
    supported.sort(key=lambda h: conf_order.get(h.confidence, 3))
    winner = supported[0]

    # Collect related evidence
    related_evidence = [
        ev for ev in state.evidence_collected
        if ev.get("category") == winner.category
        or winner.label.lower() in str(ev).lower()
    ]

    return {
        "hypothesis_id": winner.id,
        "label": winner.label,
        "description": winner.description,
        "category": winner.category,
        "severity": winner.severity,
        "confidence": winner.confidence,
        "supporting_evidence": related_evidence[:5],
        "alternatives": [
            {"label": h.label, "confidence": h.confidence, "status": h.status}
            for h in hypotheses[:5]
        ],
    }


def generate_proposed_fixes(root_cause: Optional[Dict], state: InvestigationState) -> List[Dict]:
    """Generate proposed fixes based on root cause analysis."""
    if not root_cause:
        return []

    fixes = []
    category = root_cause.get("category", "unknown")

    if category == "code_change":
        fixes.append({
            "type": "code_fix",
            "title": f"Fix {root_cause['label'].lower()}",
            "description": f"Address the root cause identified in {root_cause['label']}",
            "files_to_modify": [
                ev.get("file") for ev in root_cause.get("supporting_evidence", [])
                if ev.get("file")
            ][:3],
            "approach": "manual",
        })
    elif category == "dependency":
        fixes.append({
            "type": "dependency_update",
            "title": "Update or revert problematic dependency",
            "description": "Pin or update the dependency causing compatibility issues",
            "files_to_modify": ["package.json", "requirements.txt", "go.mod"],
            "approach": "automated",
        })
    elif category == "config":
        fixes.append({
            "type": "config_fix",
            "title": "Revert or update configuration",
            "description": "Correct the configuration change that caused the incident",
            "files_to_modify": [".env", "config.yaml"],
            "approach": "automated",
        })
    elif category == "deployment":
        fixes.append({
            "type": "rollback",
            "title": "Rollback to previous deployment",
            "description": "Revert the deployment that introduced the issue",
            "files_to_modify": [],
            "approach": "automated",
        })
    elif category == "infrastructure":
        fixes.append({
            "type": "infra_fix",
            "title": "Infrastructure remediation",
            "description": "Address the underlying infrastructure issue",
            "files_to_modify": ["docker-compose.yml", "k8s/"],
            "approach": "manual",
        })

    return fixes
