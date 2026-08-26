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
    missing_evidence_count: int = 0
    missing_evidence_details: List[str] = field(default_factory=list)
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

    # Detect direct code task / file creation requests (e.g. 'add hello.txt', 'create component')
    combined_text = f"{state.incident_title} {state.incident_description}".lower()
    task_match = re.search(r'(?:add|create|update|implement|modify|generate|fix)\s+([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)', combined_text)
    if task_match:
        target_filename = task_match.group(1)
        if target_filename not in seen:
            seen.add(target_filename)
            hypotheses.append(Hypothesis(
                id=f"hyp_{len(hypotheses)}",
                label=f"Implement {target_filename}",
                description=f"Create or modify {target_filename} to satisfy the incident request",
                confidence="high",
                severity="low",
                category="code_change",
                supporting_evidence=[{"file": target_filename, "type": "task_target", "score": 1.0}],
                supporting_count=1,
            ))

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

        if label not in seen:
            seen.add(label)
            hypotheses.append(Hypothesis(
                id=f"hyp_{len(hypotheses)}",
                label=label,
                description=desc,
                confidence="high" if score > 0.3 else "medium",
                severity=pattern_info["severity"],
                category=pattern_info["category"],
            ))

    # Generate evidence-based hypotheses from code search results
    evidence_groups = {}
    for ev in state.evidence_collected:
        file = ev.get("file", "unknown")
        if file not in evidence_groups:
            evidence_groups[file] = []
        evidence_groups[file].append(ev)

    incident_lower = f"{state.incident_title} {state.incident_description}".lower()

    def group_score(item):
        fpath, evs = item
        max_ev_score = max((e.get("score", 0.5) for e in evs), default=0.5)
        keyword_bonus = sum(2.0 for term in incident_lower.split() if len(term) > 3 and term in fpath.lower())
        if any(w in incident_lower for w in ("logo", "ui", "frontend", "sidebar", "topbar", "login", "header")):
            if any(ext in fpath.lower() for ext in (".tsx", ".jsx", "sentinel-ui", "components", "app/")):
                keyword_bonus += 5.0
            if any(ext in fpath.lower() for ext in ("alembic", "test_", "conftest", ".md")):
                keyword_bonus -= 3.0
        return max_ev_score + keyword_bonus

    sorted_groups = sorted(evidence_groups.items(), key=group_score, reverse=True)

    for file_path, file_evidence in sorted_groups[:8]:
        symbols = [e.get("symbol") for e in file_evidence if e.get("symbol")]
        symbol_str = ", ".join(symbols[:3]) if symbols else file_path.replace("\\", "/").split("/")[-1]
        label = f"Issue in {symbol_str}"

        # High confidence if domain-matched
        conf = "high" if group_score((file_path, file_evidence)) > 3.0 else "medium"

        if label not in seen:
            seen.add(label)
            hypotheses.append(Hypothesis(
                id=f"hyp_{len(hypotheses)}",
                label=label,
                description=f"Code in {file_path} requires modification based on incident signals",
                confidence=conf,
                severity="medium",
                category="code_change",
                supporting_evidence=file_evidence,
                supporting_count=len(file_evidence),
            ))

    # If no hypotheses found yet, formulate a grounded hypothesis from title
    if not hypotheses:
        hypotheses.append(Hypothesis(
            id=f"hyp_{len(hypotheses)}",
            label=f"Code Fix: {state.incident_title[:50]}",
            description=f"Implement the requested code change described in: {state.incident_description[:120]}",
            confidence="high",
            severity="medium",
            category="code_change",
        ))

    # Sort by confidence
    conf_order = {"high": 0, "medium": 1, "low": 2}
    hypotheses.sort(key=lambda h: conf_order.get(h.confidence, 3))

    return hypotheses


async def generate_hypotheses_llm(state: InvestigationState, evidence: List[Dict]) -> List[Hypothesis]:
    """Use LLM to generate hypotheses based on incident and evidence."""
    system_prompt = """You are an expert incident response and code investigation agent.
Given an incident description and collected evidence, generate 1-3 precise, technical hypotheses explaining the root cause or the exact code change needed.

RULES:
- Be strictly grounded in the incident text and evidence.
- DO NOT generate generic boilerplate hypotheses like 'Disk space full', 'Local git corruption', 'Branch protection rules', or 'Filesystem issue' unless explicitly mentioned in log traces.
- If the incident asks to create, modify, or fix a file, generate a direct code remediation hypothesis.

Respond with JSON:
{
  "hypotheses": [
    {
      "label": "Short name for the hypothesis",
      "description": "Precise explanation of what code/component is broken or needs modification",
      "confidence": "high|medium|low",
      "category": "code_change|dependency|config|deployment|infrastructure|data",
      "severity": "low|medium|high|critical",
      "evidence_for": ["list of supporting evidence"],
      "evidence_against": []
    }
  ]
}"""

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
        missing_indicators = []

        h_words = set(h.label.lower().split() + h.description.lower().split())
        # Remove very common words
        common = {"the", "a", "an", "is", "was", "in", "on", "at", "to", "for", "of", "and", "or", "not", "this", "that", "with", "from"}
        h_words -= common

        for ev in evidence:
            ev_text = f"{ev.get('file', '')} {ev.get('symbol', '')} {ev.get('content_preview', '')}".lower()
            ev_words = set(ev_text.split()) - common

            # Supporting: meaningful word overlap
            overlap = h_words & ev_words
            if len(overlap) >= 2:
                supporting += 1
            elif h.category == "code_change" and "code_search" in ev.get("source", ""):
                supporting += 1

            # Contradicting: hypothesis mentions a file/function that has error indicators
            if ev.get("file") and ev["file"].lower() in h.description.lower():
                # Check for error indicators in the evidence
                error_terms = ["error", "exception", "fail", "crash", "timeout", "null", "panic"]
                if any(term in ev_text for term in error_terms):
                    contradicting += 1

        # Detect missing evidence: what would strengthen or weaken this hypothesis?
        if h.category == "code_change":
            has_code = any("code_search" in ev.get("source", "") or "diff" in ev.get("source", "") for ev in evidence)
            if not has_code:
                missing_indicators.append("code_changes_or_diffs")
        if h.category in ("database", "dependency"):
            has_deps = any("dependencies" in ev.get("source", "") for ev in evidence)
            if not has_deps:
                missing_indicators.append("dependency_analysis")
        if not any(ev.get("commit_sha") for ev in evidence):
            missing_indicators.append("commit_history")
        if not any("deployment" in ev.get("source", "") for ev in evidence):
            missing_indicators.append("deployment_correlation")

        h.supporting_count = supporting
        h.contradicting_count = contradicting
        h.missing_evidence_count = len(missing_indicators)
        if not hasattr(h, "missing_evidence_details"):
            h.missing_evidence_details = missing_indicators

        # Update confidence based on evidence
        if contradicting > supporting:
            h.confidence = "low"
            h.status = "rejected"
            h.rejection_reason = "Contradicted by more evidence than supports it"
        elif supporting >= 3 and contradicting == 0:
            h.confidence = "high"
            h.status = "supported"
        elif supporting >= 1:
            h.confidence = "medium"
            h.status = "supported"
        else:
            h.confidence = "low"
            h.missing_evidence_count += 1  # No direct evidence is itself a gap

    return hypotheses


MIN_EVIDENCE_THRESHOLD = 2


def identify_root_cause(
    state: InvestigationState,
    hypotheses: List[Hypothesis],
) -> Optional[Dict]:
    """Identify root cause from supported hypotheses, or abstain.

    Abstains when minimum evidence is not met or no hypothesis is supported.
    Uses diversity-aware ranking: prefers hypotheses from different categories.
    """
    # Gate: minimum evidence threshold
    evidence_count = len(state.evidence_collected)
    if evidence_count < MIN_EVIDENCE_THRESHOLD:
        return None  # Abstain — insufficient evidence

    # Filter to supported hypotheses
    supported = [h for h in hypotheses if h.status == "supported"]
    if not supported:
        supported = [h for h in hypotheses if h.status != "rejected"]

    if not supported:
        supported = hypotheses[:1]

    if not supported:
        return None  # Abstain

    # Diversity-aware ranking: score by confidence, then prefer category diversity
    conf_order = {"high": 0, "medium": 1, "low": 2}
    seen_categories = set()

    def rank_key(h):
        conf_score = conf_order.get(h.confidence, 3)
        # Penalize if we already have a candidate in this category
        category_penalty = 0.5 if h.category in seen_categories else 0
        # Bonus for supporting evidence count
        evidence_bonus = -min(h.supporting_count, 5) * 0.1
        return conf_score + category_penalty + evidence_bonus

    supported.sort(key=rank_key)
    winner = supported[0]
    seen_categories.add(winner.category)

    # Collect related evidence
    related_evidence = winner.supporting_evidence or [
        ev for ev in state.evidence_collected
        if ev.get("category") == winner.category
        or winner.label.lower() in str(ev).lower()
    ]
    if not related_evidence and state.evidence_collected:
        related_evidence = state.evidence_collected[:5]

    return {
        "hypothesis_id": winner.id,
        "label": winner.label,
        "summary": winner.label,
        "description": winner.description,
        "causal_explanation": winner.description,
        "category": winner.category,
        "affected_component": winner.category,
        "severity": winner.severity,
        "confidence": winner.confidence,
        "supporting_evidence": related_evidence[:5],
        "missing_evidence": winner.missing_evidence_details,
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

    # Determine files to modify from root cause evidence or all collected evidence
    evidence_files = [
        ev.get("file") for ev in root_cause.get("supporting_evidence", [])
        if ev.get("file")
    ]
    if state.evidence_collected:
        evidence_files.extend([ev.get("file") for ev in state.evidence_collected if ev.get("file")])
    
    # Prioritize files that match keywords in incident title / description
    incident_text = f"{state.incident_title} {state.incident_description}".lower()
    
    def file_relevance(fpath: str) -> float:
        score = 0.0
        fname = fpath.lower()
        for term in incident_text.split():
            if len(term) > 3 and term in fname:
                score += 3.0
        if any(w in incident_text for w in ("logo", "ui", "frontend", "sidebar", "topbar", "login", "header", "page", "view")):
            if any(ext in fname for ext in (".tsx", ".jsx", "sentinel-ui", "components", "app/")):
                score += 5.0
            if any(ext in fname for ext in ("alembic", "test_", "conftest", ".md")):
                score -= 2.0
        return score

    # Deduplicate while preserving order
    unique_files = list(dict.fromkeys(evidence_files))
    unique_files.sort(key=file_relevance, reverse=True)

    if category in ("code_change", "unknown") or not fixes:
        fixes.append({
            "type": "code_fix",
            "title": f"Fix {root_cause.get('label', root_cause.get('summary', 'issue')).lower()}",
            "description": f"Address the root cause identified in {root_cause.get('label', root_cause.get('summary', 'the codebase'))}",
            "files_to_modify": unique_files[:3],
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
