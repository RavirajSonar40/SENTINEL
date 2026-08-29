"""Production detection rules registry and evaluators for Phase 5."""

from typing import Dict, Any, Optional, List, Tuple
from app.models.incident import SignalType, IncidentSeverity


class TriggeredRuleResult:
    """Structured result when a detection rule triggers."""
    def __init__(
        self,
        rule_name: str,
        signal_type: SignalType,
        severity: str,
        metric_name: Optional[str],
        metric_value: Optional[float],
        threshold_value: Optional[float],
        title: str,
        description: str,
        error_signature: Optional[str] = None,
    ):
        self.rule_name = rule_name
        self.signal_type = signal_type
        self.severity = severity
        self.metric_name = metric_name
        self.metric_value = metric_value
        self.threshold_value = threshold_value
        self.title = title
        self.description = description
        self.error_signature = error_signature


class BaseDetectionRule:
    rule_name: str = "base_rule"
    signal_type: SignalType = SignalType.ERROR_RATE
    default_threshold: float = 0.0
    default_severity: str = "SEV-2"
    description: str = ""

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        raise NotImplementedError


class CPUThresholdRule(BaseDetectionRule):
    rule_name = "cpu_threshold"
    signal_type = SignalType.CPU_THRESHOLD
    default_threshold = 90.0  # percentage
    default_severity = "SEV-2"
    description = "Detects sustained high CPU utilization exceeding threshold"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("cpu_usage_pct") or context.get("cpu_percent") or context.get("value")
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="cpu_usage_pct",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"CPU threshold breached ({val:.1f}% >= {threshold:.1f}%) on {service}",
                description=f"Service CPU utilization reached {val:.1f}%, exceeding the configured threshold of {threshold:.1f}%.",
                error_signature=f"cpu_spike:{service}",
            )
        return None


class MemoryThresholdRule(BaseDetectionRule):
    rule_name = "memory_threshold"
    signal_type = SignalType.MEMORY_THRESHOLD
    default_threshold = 90.0  # percentage
    default_severity = "SEV-2"
    description = "Detects memory pressure and out-of-memory risks"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("memory_usage_pct") or context.get("mem_percent") or context.get("value")
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="memory_usage_pct",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Memory threshold breached ({val:.1f}% >= {threshold:.1f}%) on {service}",
                description=f"Service memory utilization reached {val:.1f}%, exceeding the configured threshold of {threshold:.1f}%.",
                error_signature=f"memory_pressure:{service}",
            )
        return None


class ErrorRateRule(BaseDetectionRule):
    rule_name = "error_rate"
    signal_type = SignalType.ERROR_RATE
    default_threshold = 0.05  # 5% error rate
    default_severity = "SEV-1"
    description = "Detects HTTP 5xx or general error rate spikes"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("error_rate") or context.get("http_error_rate")
        if val is None and context.get("metric_name") == "error_rate":
            val = context.get("value") or context.get("metric_value")

        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            rate_pct = float(val) * 100 if float(val) <= 1.0 else float(val)
            thresh_pct = threshold * 100 if threshold <= 1.0 else threshold
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="http_error_rate",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Error rate spike ({rate_pct:.1f}% >= {thresh_pct:.1f}%) on {service}",
                description=f"HTTP/API error rate elevated to {rate_pct:.2f}%, surpassing the SLA threshold of {thresh_pct:.2f}%.",
                error_signature=f"error_rate_spike:{service}",
            )
        return None


class LatencySpikeRule(BaseDetectionRule):
    rule_name = "latency_spike"
    signal_type = SignalType.LATENCY_SPIKE
    default_threshold = 1000.0  # ms
    default_severity = "SEV-2"
    description = "Detects high response tail latency degradation"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("p99_latency_ms") or context.get("latency_ms") or context.get("value")
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="p99_latency_ms",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"P99 latency degradation ({val:.0f}ms >= {threshold:.0f}ms) on {service}",
                description=f"P99 tail response latency degraded to {val:.1f}ms, exceeding the threshold of {threshold:.1f}ms.",
                error_signature=f"latency_degradation:{service}",
            )
        return None


class HealthCheckFailureRule(BaseDetectionRule):
    rule_name = "health_check_failure"
    signal_type = SignalType.HEALTH_CHECK_FAILURE
    default_threshold = 3.0  # consecutive failures
    default_severity = "SEV-1"
    description = "Detects consecutive health check probe failures"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("consecutive_failures") or (1 if context.get("is_healthy") is False else 0)
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            url = context.get("url") or context.get("health_check_url") or "probe"
            err = context.get("error_message") or "Unreachable"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="consecutive_probe_failures",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Health check failing ({int(val)} consecutive probes) on {service}",
                description=f"Automated health probes to {url} failed {int(val)} times consecutively: {err}",
                error_signature=f"health_probe_down:{service}",
            )
        return None


class CrashLoopRule(BaseDetectionRule):
    rule_name = "crash_loop"
    signal_type = SignalType.CRASH_LOOP
    default_threshold = 3.0  # restarts
    default_severity = "SEV-1"
    description = "Detects rapid container restart crash loops"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("restart_count") or context.get("restarts")
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="restart_count",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Container crash loop detected ({int(val)} restarts) on {service}",
                description=f"Service instance restarted {int(val)} times within recent window.",
                error_signature=f"crash_loop:{service}",
            )
        return None


class RestartSpikeRule(BaseDetectionRule):
    rule_name = "restart_spike"
    signal_type = SignalType.RESTART_SPIKE
    default_threshold = 5.0  # restarts
    default_severity = "SEV-2"
    description = "Detects aggregate pod/process restart spikes across fleet"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("restart_spike_count") or context.get("pod_restarts")
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="aggregate_restarts",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Pod restart spike ({int(val)} restarts) on {service}",
                description=f"Multiple pods/instances restarted rapidly ({int(val)} total restarts).",
                error_signature=f"restart_spike:{service}",
            )
        return None


class DiskThresholdRule(BaseDetectionRule):
    rule_name = "disk_threshold"
    signal_type = SignalType.DISK_THRESHOLD
    default_threshold = 90.0  # percentage
    default_severity = "SEV-3"
    description = "Detects near-capacity storage exhaustion"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("disk_usage_pct") or context.get("disk_percent")
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="disk_usage_pct",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Disk capacity threshold breached ({val:.1f}%) on {service}",
                description=f"Storage volume utilization reached {val:.1f}%, exceeding {threshold:.1f}%.",
                error_signature=f"disk_full:{service}",
            )
        return None


class QueueBacklogRule(BaseDetectionRule):
    rule_name = "queue_backlog"
    signal_type = SignalType.QUEUE_BACKLOG
    default_threshold = 10000.0  # messages
    default_severity = "SEV-2"
    description = "Detects message queue lag and consumer starvation"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("queue_lag") or context.get("queue_size") or context.get("backlog_count")
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="queue_backlog",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Queue backlog spike ({int(val):,} messages) for {service}",
                description=f"Message backlog reached {int(val):,} messages, exceeding processing SLA.",
                error_signature=f"queue_backlog:{service}",
            )
        return None


class DatabaseSaturationRule(BaseDetectionRule):
    rule_name = "database_saturation"
    signal_type = SignalType.DATABASE_SATURATION
    default_threshold = 85.0  # percentage
    default_severity = "SEV-1"
    description = "Detects database connection pool exhaustion"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("db_connection_pool_pct") or context.get("db_connections_pct") or context.get("db_pool_utilization")
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="db_connection_pool_pct",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Database connection saturation ({val:.1f}%) on {service}",
                description=f"Database connection pool capacity utilized {val:.1f}%, risking connection starvation.",
                error_signature=f"db_saturation:{service}",
            )
        return None


class DeploymentRegressionRule(BaseDetectionRule):
    rule_name = "deployment_regression"
    signal_type = SignalType.DEPLOYMENT_REGRESSION
    default_threshold = 1.0  # flag
    default_severity = "SEV-1"
    description = "Detects error rate or latency spike correlated with a recent release"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        is_regression = context.get("is_deployment_regression") or context.get("has_recent_deployment")
        if is_regression:
            service = context.get("service_name") or "service"
            commit = context.get("recent_deployment_commit") or "HEAD"
            version = context.get("recent_deployment_version") or ""
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="deployment_regression_flag",
                metric_value=1.0,
                threshold_value=1.0,
                title=f"Deployment regression detected on {service} ({version or commit[:7]})",
                description=f"Service exhibited an incident anomaly shortly following deployment of {version or commit[:7]}.",
                error_signature=f"deployment_regression:{service}:{commit[:7]}",
            )
        return None


class RepeatedExceptionRule(BaseDetectionRule):
    rule_name = "repeated_exception"
    signal_type = SignalType.REPEATED_EXCEPTION
    default_threshold = 10.0  # occurrences
    default_severity = "SEV-2"
    description = "Detects recurring Sentry or unhandled application exception spikes"

    def evaluate(self, context: Dict[str, Any], custom_threshold: Optional[float] = None) -> Optional[TriggeredRuleResult]:
        threshold = custom_threshold if custom_threshold is not None else self.default_threshold
        val = context.get("exception_count") or (1 if context.get("exception_type") or context.get("error_signature") else 0)
        if val is not None and float(val) >= threshold:
            service = context.get("service_name") or "service"
            exc_type = context.get("exception_type") or context.get("error_signature") or "UnhandledException"
            msg = context.get("error_message") or context.get("description") or "Repeated exception observed"
            return TriggeredRuleResult(
                rule_name=self.rule_name,
                signal_type=self.signal_type,
                severity=self.default_severity,
                metric_name="exception_occurrences",
                metric_value=float(val),
                threshold_value=threshold,
                title=f"Repeated exception spike ({exc_type}) on {service}",
                description=f"{exc_type}: {msg} ({int(val)} occurrences).",
                error_signature=f"exception:{service}:{exc_type}",
            )
        return None


# ============================================================================
# RULES REGISTRY
# ============================================================================

ALL_RULES: List[BaseDetectionRule] = [
    CPUThresholdRule(),
    MemoryThresholdRule(),
    ErrorRateRule(),
    LatencySpikeRule(),
    HealthCheckFailureRule(),
    CrashLoopRule(),
    RestartSpikeRule(),
    DiskThresholdRule(),
    QueueBacklogRule(),
    DatabaseSaturationRule(),
    DeploymentRegressionRule(),
    RepeatedExceptionRule(),
]

RULE_REGISTRY: Dict[str, BaseDetectionRule] = {r.rule_name: r for r in ALL_RULES}
SIGNAL_TYPE_TO_RULE: Dict[SignalType, BaseDetectionRule] = {r.signal_type: r for r in ALL_RULES}


def evaluate_all_rules(
    context: Dict[str, Any],
    custom_thresholds: Optional[Dict[str, float]] = None,
    enabled_rules: Optional[Dict[str, bool]] = None,
) -> List[TriggeredRuleResult]:
    """
    Evaluate all 12 detection rules against context.
    Returns list of triggered rule results.
    """
    custom_thresholds = custom_thresholds or {}
    enabled_rules = enabled_rules or {}
    triggered = []

    for rule in ALL_RULES:
        # Check if rule is disabled for this organization
        if enabled_rules.get(rule.rule_name) is False:
            continue

        custom_thresh = custom_thresholds.get(rule.rule_name)
        res = rule.evaluate(context, custom_threshold=custom_thresh)
        if res:
            triggered.append(res)

    return triggered
