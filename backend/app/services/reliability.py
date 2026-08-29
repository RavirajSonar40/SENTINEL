"""Core service for Phase 16: Advanced Reliability, SLO Tracking & Predictions."""
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from uuid import UUID
import math
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.incident import (
    Incident,
    Service,
    TelemetrySignal,
    HealthCheckLog,
    SLOConfig,
    SLOBurnRateSnapshot,
    PredictiveAnomaly,
    BusinessImpactConfig,
    IncidentBusinessImpact,
)
from app.schemas.command_center import FreshnessMetadata
from app.schemas.reliability import (
    SLOBurnRateOut,
    SLOTimeToExhaustionOut,
    SLOConfigOut,
    PredictiveAnomalyOut,
    IncidentBusinessImpactOut,
    SLOBurnDownPoint,
    SLOBurnDownResponse,
)


def _compute_freshness(observed_at: Optional[datetime], source: str) -> FreshnessMetadata:
    now = datetime.now(timezone.utc)
    if not observed_at:
        return FreshnessMetadata(
            observed_at=now,
            source=source,
            freshness_seconds=0.0,
            is_stale=False,
        )
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    diff = max(0.0, (now - observed_at).total_seconds())
    return FreshnessMetadata(
        observed_at=observed_at,
        source=source,
        freshness_seconds=round(diff, 1),
        is_stale=(diff > 300.0),
    )


# =============================================================================
# 1. SLO TRACKING & MULTI-WINDOW BURN RATE ENGINE
# =============================================================================

def calculate_slo_burn_rates(
    db: Session,
    slo: SLOConfig,
    now: Optional[datetime] = None,
) -> Tuple[SLOBurnRateOut, SLOTimeToExhaustionOut, Optional[float], Optional[float], int, FreshnessMetadata, str]:
    """
    Calculate Google SRE multi-window error budget burn rates and time-to-exhaustion.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    window_days = slo.window_days or 30
    total_window_hours = float(window_days * 24)
    t_30d = now - timedelta(days=window_days)
    t_24h = now - timedelta(hours=24)
    t_6h = now - timedelta(hours=6)
    t_1h = now - timedelta(hours=1)

    # Allowed error fraction (e.g., 99.9% target -> 0.0010 allowed error fraction)
    allowed_error_fraction = max(0.0, (100.0 - slo.target_percent) / 100.0)

    # Query telemetry and probes for service within 30-day window
    probes_30d = (
        db.query(HealthCheckLog)
        .filter(HealthCheckLog.service_id == slo.service_id, HealthCheckLog.probed_at >= t_30d)
        .order_by(desc(HealthCheckLog.probed_at))
        .all()
    )
    signals_30d = (
        db.query(TelemetrySignal)
        .filter(TelemetrySignal.service_id == slo.service_id, TelemetrySignal.observed_at >= t_30d)
        .order_by(desc(TelemetrySignal.observed_at))
        .all()
    )

    total_samples = len(probes_30d) + len(signals_30d)
    latest_timestamp = None
    if probes_30d and signals_30d:
        p_ts = probes_30d[0].probed_at
        s_ts = signals_30d[0].observed_at
        latest_timestamp = max(p_ts if p_ts.tzinfo else p_ts.replace(tzinfo=timezone.utc),
                               s_ts if s_ts.tzinfo else s_ts.replace(tzinfo=timezone.utc))
    elif probes_30d:
        p_ts = probes_30d[0].probed_at
        latest_timestamp = p_ts if p_ts.tzinfo else p_ts.replace(tzinfo=timezone.utc)
    elif signals_30d:
        s_ts = signals_30d[0].observed_at
        latest_timestamp = s_ts if s_ts.tzinfo else s_ts.replace(tzinfo=timezone.utc)

    freshness = _compute_freshness(latest_timestamp, "telemetry_and_synthetic_probes")

    # Edge Case: Zero Traffic / No Samples Observed
    if total_samples == 0:
        burn_rates = SLOBurnRateOut(
            burn_rate_1h=None,
            burn_rate_6h=None,
            burn_rate_24h=None,
            burn_status_1h="insufficient_data",
            burn_status_6h="insufficient_data",
            burn_status_24h="insufficient_data",
        )
        time_to_exhaustion = SLOTimeToExhaustionOut(
            hours_remaining=None,
            display="—",
            status="insufficient_data",
        )
        return burn_rates, time_to_exhaustion, None, None, 0, freshness, "insufficient_data"

    # Evaluate Good vs Bad samples per SLI type
    def is_sample_good(item) -> bool:
        if isinstance(item, HealthCheckLog):
            code = getattr(item, "status_code", getattr(item, "http_status_code", 200)) or 200
            if slo.sli_type == "availability":
                return bool(item.is_healthy and code < 500)
            elif slo.sli_type == "latency":
                threshold = slo.threshold_value or 200.0
                return bool(item.latency_ms is not None and item.latency_ms <= threshold)
            elif slo.sli_type == "error_rate":
                return bool(item.is_healthy)
            return bool(item.is_healthy)
        elif isinstance(item, TelemetrySignal):
            val = float(item.metric_value or 0.0)
            m_name = (item.metric_name or "").lower()
            if slo.sli_type == "availability":
                return val >= 1.0 or val == 200.0 or "up" in m_name
            elif slo.sli_type == "latency":
                threshold = slo.threshold_value or 200.0
                return val <= threshold
            elif slo.sli_type == "error_rate":
                threshold = slo.threshold_value or 0.10
                return val <= threshold
            return True
        return True

    def get_timestamp(item) -> datetime:
        ts = getattr(item, "probed_at", getattr(item, "executed_at", getattr(item, "observed_at", None)))
        if ts is None:
            ts = datetime.now(timezone.utc)
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


    all_samples = probes_30d + signals_30d
    good_30d = sum(1 for s in all_samples if is_sample_good(s))
    total_30d = len(all_samples)
    compliance_30d = (good_30d / total_30d) * 100.0
    actual_error_fraction_30d = (total_30d - good_30d) / float(total_30d)

    # Budget Remaining %
    if allowed_error_fraction > 0:
        budget_remaining_percent = max(0.0, ((allowed_error_fraction - actual_error_fraction_30d) / allowed_error_fraction) * 100.0)
    else:
        budget_remaining_percent = 100.0 if actual_error_fraction_30d == 0 else 0.0

    # Multi-window error rates and burn rate calculation
    def calc_window_burn_rate(cutoff: datetime) -> Tuple[Optional[float], str]:
        w_samples = [s for s in all_samples if get_timestamp(s) >= cutoff]
        if not w_samples:
            # An empty window is missing data, not a zero-error (stable) window.
            return None, "insufficient_data"
        w_good = sum(1 for s in w_samples if is_sample_good(s))
        w_err_fraction = (len(w_samples) - w_good) / float(len(w_samples))
        if allowed_error_fraction <= 0:
            return (0.0 if w_err_fraction == 0 else 100.0), ("critical_page" if w_err_fraction > 0 else "normal")
        rate = round(w_err_fraction / allowed_error_fraction, 2)
        return rate, rate

    rate_1h, _ = calc_window_burn_rate(t_1h)
    rate_6h, _ = calc_window_burn_rate(t_6h)
    rate_24h, _ = calc_window_burn_rate(t_24h)

    def classify_burn(rate: Optional[float], critical: float, elevated: float) -> str:
        if rate is None:
            return "insufficient_data"
        return "critical_page" if rate >= critical else ("elevated" if rate >= elevated else "normal")

    status_1h = classify_burn(rate_1h, 14.4, 6.0)
    status_6h = classify_burn(rate_6h, 6.0, 3.0)
    status_24h = classify_burn(rate_24h, 3.0, 1.0)

    burn_rates = SLOBurnRateOut(
        burn_rate_1h=rate_1h,
        burn_rate_6h=rate_6h,
        burn_rate_24h=rate_24h,
        burn_status_1h=status_1h,
        burn_status_6h=status_6h,
        burn_status_24h=status_24h,
    )

    # Time to Exhaustion: Hours = (Remaining Budget Fraction * Window Hours) / Burn Rate
    R = budget_remaining_percent / 100.0
    valid_rates = [rate for rate in (rate_1h, rate_6h, rate_24h) if rate is not None]
    if not valid_rates:
        effective_burn_rate = None
    elif any(r > 0 for r in valid_rates):
        effective_burn_rate = next(r for r in valid_rates if r > 0)
    else:
        effective_burn_rate = 0.0


    if budget_remaining_percent <= 0.0:
        time_to_exhaustion = SLOTimeToExhaustionOut(
            hours_remaining=0.0,
            display="0h (Exhausted)",
            status="exhausted",
        )
        overall_status = "exhausted"
    elif effective_burn_rate is None:
        time_to_exhaustion = SLOTimeToExhaustionOut(
            hours_remaining=None,
            display="—",
            status="insufficient_data",
        )
        overall_status = "insufficient_data"
    elif effective_burn_rate <= 0.0:
        time_to_exhaustion = SLOTimeToExhaustionOut(
            hours_remaining=None,
            display="∞ (Stable)",
            status="healthy",
        )
        overall_status = "healthy"
    else:
        hours_rem = (R * total_window_hours) / effective_burn_rate
        overall_status = "critical_burn" if effective_burn_rate >= 14.4 else ("warning" if effective_burn_rate >= 6.0 else "healthy")
        time_to_exhaustion = SLOTimeToExhaustionOut(
            hours_remaining=round(hours_rem, 1),
            display=f"{hours_rem:.1f}h",
            status=overall_status,
        )

    # Upsert hourly snapshot for database idempotency
    captured_hour = now.replace(minute=0, second=0, microsecond=0)
    existing_snapshot = (
        db.query(SLOBurnRateSnapshot)
        .filter(SLOBurnRateSnapshot.slo_id == slo.id, SLOBurnRateSnapshot.captured_hour == captured_hour)
        .first()
    )
    if existing_snapshot:
        existing_snapshot.compliance_percent = round(compliance_30d, 2)
        existing_snapshot.burn_rate_1h = rate_1h
        existing_snapshot.burn_rate_6h = rate_6h
        existing_snapshot.burn_rate_24h = rate_24h
        existing_snapshot.budget_remaining_percent = round(budget_remaining_percent, 2)
        existing_snapshot.time_to_exhaustion_hours = time_to_exhaustion.hours_remaining
        existing_snapshot.status = overall_status
    else:
        new_snapshot = SLOBurnRateSnapshot(
            slo_id=slo.id,
            organization_id=slo.organization_id,
            compliance_percent=round(compliance_30d, 2),
            burn_rate_1h=rate_1h,
            burn_rate_6h=rate_6h,
            burn_rate_24h=rate_24h,
            budget_remaining_percent=round(budget_remaining_percent, 2),
            time_to_exhaustion_hours=time_to_exhaustion.hours_remaining,
            captured_hour=captured_hour,
            status=overall_status,
        )
        db.add(new_snapshot)
    db.commit()

    return (
        burn_rates,
        time_to_exhaustion,
        round(compliance_30d, 2),
        round(budget_remaining_percent, 2),
        total_samples,
        freshness,
        overall_status,
    )


# =============================================================================
# 2. STATISTICAL PREDICTIVE ANOMALY & DRIFT ENGINE
# =============================================================================

def detect_predictive_anomalies(
    db: Session,
    organization_id: UUID,
    now: Optional[datetime] = None,
) -> List[PredictiveAnomaly]:
    """
    Run OLS linear regression on telemetry trends to project threshold breaches with safeguards.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    lookback_60m = now - timedelta(minutes=60)
    services = db.query(Service).filter(Service.organization_id == organization_id).all()
    created_or_updated_anomalies = []

    tracked_metrics = [
        {"name": "cpu_usage", "threshold": 90.0, "severity_breach": "CRITICAL"},
        {"name": "memory_usage", "threshold": 85.0, "severity_breach": "CRITICAL"},
        {"name": "p95_latency", "threshold": 1000.0, "severity_breach": "WARNING"},
        {"name": "error_rate", "threshold": 5.0, "severity_breach": "CRITICAL"},
        {"name": "queue_backlog", "threshold": 500.0, "severity_breach": "WARNING"},
    ]

    for svc in services:
        for m_cfg in tracked_metrics:
            m_name = m_cfg["name"]
            threshold = float(m_cfg["threshold"])

            signals = (
                db.query(TelemetrySignal)
                .filter(
                    TelemetrySignal.service_id == svc.id,
                    TelemetrySignal.observed_at >= lookback_60m,
                )
                .order_by(TelemetrySignal.observed_at.asc())
                .all()
            )

            # Filter signals by metric name
            matching = [s for s in signals if m_name in (s.metric_name or "").lower()]
            if not matching:
                continue

            # Safeguard 1: Minimum sample count (>= 6)
            if len(matching) < 6:
                continue

            timestamps = [s.observed_at if s.observed_at.tzinfo else s.observed_at.replace(tzinfo=timezone.utc) for s in matching]
            values = [float(s.metric_value) for s in matching]

            # Safeguard 2: Minimum time span (>= 15 minutes)
            span_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
            if span_seconds < 900.0:  # 15 mins
                continue

            # Safeguard 3: Sampling gap check (no gap > 300s)
            has_gap = False
            for i in range(1, len(timestamps)):
                if (timestamps[i] - timestamps[i - 1]).total_seconds() > 300.0:
                    has_gap = True
                    break
            if has_gap:
                continue

            current_val = values[-1]

            # Safeguard 4: Metric Already Beyond Threshold
            if current_val >= threshold:
                anomaly = _upsert_predictive_anomaly(
                    db=db,
                    org_id=organization_id,
                    svc_id=svc.id,
                    metric_name=m_name,
                    current_value=current_val,
                    threshold_value=threshold,
                    projected_breach_at=now,
                    time_to_breach_minutes=0.0,
                    growth_rate_per_minute=0.0,
                    r_squared=1.0,
                    confidence_score=1.0,
                    severity="CRITICAL_BREACH_ACTIVE",
                    recommendation=f"Active breach: {m_name} is currently at {current_val:.1f} (exceeds threshold {threshold:.1f}). Immediate operator triage required.",
                    now=now,
                )
                created_or_updated_anomalies.append(anomaly)
                continue

            # Safeguard 5: Ordinary Least Squares (OLS) Linear Regression
            t0 = timestamps[0]
            x = [(t - t0).total_seconds() / 60.0 for t in timestamps]  # in minutes
            y = values
            N = len(x)

            sum_x = sum(x)
            sum_y = sum(y)
            sum_x2 = sum(xi * xi for xi in x)
            sum_y2 = sum(yi * yi for yi in y)
            sum_xy = sum(x[i] * y[i] for i in range(N))

            denom = (N * sum_x2 - sum_x * sum_x)
            if denom == 0:
                continue

            slope = (N * sum_xy - sum_x * sum_y) / denom
            intercept = (sum_y - slope * sum_x) / N

            # Safeguard 6: Negative or Zero Slope (metric is decreasing or flat)
            if slope <= 0.0001:
                continue

            # Pearson Correlation / R^2
            denom_r = math.sqrt(max(1e-9, (N * sum_x2 - sum_x * sum_x) * (N * sum_y2 - sum_y * sum_y)))
            r = (N * sum_xy - sum_x * sum_y) / denom_r if denom_r > 0 else 0.0
            r_squared = min(1.0, max(0.0, r * r))

            # Safeguard 7: Confidence Threshold (R^2 >= 0.70)
            if r_squared < 0.70:
                continue

            # Time to Breach Projection: minutes = (threshold - current_val) / slope
            minutes_to_breach = (threshold - current_val) / slope

            # Safeguard 8: Project within [2 mins, 120 mins]
            if 2.0 <= minutes_to_breach <= 120.0:
                projected_breach_at = now + timedelta(minutes=minutes_to_breach)
                severity = "CRITICAL" if minutes_to_breach <= 30.0 else "WARNING"
                recommendation = (
                    f"Projected {m_name} exhaustion: growth rate +{slope:.2f}/min (R²={r_squared:.2f}) "
                    f"predicts threshold breach ({threshold:.1f}) in {minutes_to_breach:.0f} minutes. "
                    "Recommend horizontal autoscaling, garbage collection trigger, or traffic throttling."
                )

                anomaly = _upsert_predictive_anomaly(
                    db=db,
                    org_id=organization_id,
                    svc_id=svc.id,
                    metric_name=m_name,
                    current_value=current_val,
                    threshold_value=threshold,
                    projected_breach_at=projected_breach_at,
                    time_to_breach_minutes=round(minutes_to_breach, 1),
                    growth_rate_per_minute=round(slope, 3),
                    r_squared=round(r_squared, 2),
                    confidence_score=round(r_squared, 2),
                    severity=severity,
                    recommendation=recommendation,
                    now=now,
                )
                created_or_updated_anomalies.append(anomaly)

    return created_or_updated_anomalies


def _upsert_predictive_anomaly(
    db: Session,
    org_id: UUID,
    svc_id: UUID,
    metric_name: str,
    current_value: float,
    threshold_value: float,
    projected_breach_at: Optional[datetime],
    time_to_breach_minutes: float,
    growth_rate_per_minute: float,
    r_squared: float,
    confidence_score: float,
    severity: str,
    recommendation: str,
    now: datetime,
) -> PredictiveAnomaly:
    """Upsert active anomaly with 30-minute cooldown window to prevent duplicates."""
    cooldown_cutoff = now - timedelta(minutes=30)
    existing = (
        db.query(PredictiveAnomaly)
        .filter(
            PredictiveAnomaly.organization_id == org_id,
            PredictiveAnomaly.service_id == svc_id,
            PredictiveAnomaly.metric_name == metric_name,
            PredictiveAnomaly.is_active == True,
            PredictiveAnomaly.created_at >= cooldown_cutoff,
        )
        .first()
    )

    if existing:
        existing.current_value = current_value
        existing.threshold_value = threshold_value
        existing.projected_breach_at = projected_breach_at
        existing.time_to_breach_minutes = time_to_breach_minutes
        existing.growth_rate_per_minute = growth_rate_per_minute
        existing.r_squared = r_squared
        existing.confidence_score = confidence_score
        existing.severity = severity
        existing.recommendation = recommendation
        existing.updated_at = now
        db.commit()
        return existing

    anomaly = PredictiveAnomaly(
        organization_id=org_id,
        service_id=svc_id,
        metric_name=metric_name,
        current_value=current_value,
        threshold_value=threshold_value,
        projected_breach_at=projected_breach_at,
        time_to_breach_minutes=time_to_breach_minutes,
        growth_rate_per_minute=growth_rate_per_minute,
        r_squared=r_squared,
        confidence_score=confidence_score,
        severity=severity,
        is_active=True,
        status="ACTIVE",
        recommendation=recommendation,
    )
    db.add(anomaly)
    db.commit()
    db.refresh(anomaly)
    return anomaly


# =============================================================================
# 3. REAL-TIME BUSINESS & FINANCIAL IMPACT ESTIMATION ENGINE
# =============================================================================

def estimate_incident_business_impact(
    db: Session,
    incident_id: UUID,
    organization_id: UUID,
) -> IncidentBusinessImpactOut:
    """
    Calculate financial revenue at risk and customer impact without silent fallbacks.
    """
    inc = db.query(Incident).filter(Incident.id == incident_id, Incident.organization_id == organization_id).first()
    if not inc:
        raise ValueError("Incident not found or unauthorized")

    svc = db.query(Service).filter(Service.id == inc.service_id).first() if inc.service_id else None
    svc_name = svc.name if svc else (inc.service_name or "Unknown Service")

    # Duration calculation
    start = inc.started_at or inc.created_at
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = inc.resolved_at or datetime.now(timezone.utc)
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    duration_minutes = max(1.0, (end - (start or end)).total_seconds() / 60.0)
    duration_hours = duration_minutes / 60.0

    # Severity degradation factor
    deg_factor = 1.0
    if inc.severity == "SEV-1":
        deg_factor = 1.0
    elif inc.severity == "SEV-2":
        deg_factor = 0.6
    elif inc.severity == "SEV-3":
        deg_factor = 0.2
    elif inc.severity == "SEV-4":
        deg_factor = 0.05

    # Look up BusinessImpactConfig:
    # 1. Service-specific
    # 2. Tier-specific
    # 3. Organization-level default
    impact_cfg = None
    is_estimated_default = False
    if svc:
        impact_cfg = (
            db.query(BusinessImpactConfig)
            .filter(BusinessImpactConfig.organization_id == organization_id, BusinessImpactConfig.service_id == svc.id)
            .first()
        )
        if not impact_cfg and svc.tier:
            impact_cfg = (
                db.query(BusinessImpactConfig)
                .filter(BusinessImpactConfig.organization_id == organization_id, BusinessImpactConfig.tier == svc.tier)
                .first()
            )

    if not impact_cfg:
        # Check org default
        impact_cfg = (
            db.query(BusinessImpactConfig)
            .filter(BusinessImpactConfig.organization_id == organization_id, BusinessImpactConfig.service_id == None, BusinessImpactConfig.tier == None)
            .first()
        )
        if impact_cfg:
            is_estimated_default = True

    # No Silent Fallback: if completely unconfigured, return unconfigured status
    if not impact_cfg:
        return IncidentBusinessImpactOut(
            id=inc.id,
            incident_id=inc.id,
            incident_title=inc.title,
            service_id=svc.id if svc else None,
            service_name=svc_name,
            outage_duration_minutes=round(duration_minutes, 1),
            degradation_factor=deg_factor,
            hourly_revenue_rate_usd=None,
            estimated_financial_loss_usd=None,
            financial_loss_display="— (Unconfigured)",
            affected_user_count=0,
            sla_breach_detected=False,
            currency="USD",
            status="unconfigured",
            is_estimated_default=False,
            calculated_at=datetime.now(timezone.utc),
        )

    # Calculate financial loss
    financial_loss = duration_hours * deg_factor * impact_cfg.hourly_revenue_rate_usd
    affected_users = int(duration_hours * deg_factor * impact_cfg.active_users_baseline)
    sla_breach = bool(duration_hours >= 1.0 and inc.severity in ("SEV-1", "SEV-2"))

    # Upsert into IncidentBusinessImpact table
    existing_impact = db.query(IncidentBusinessImpact).filter(IncidentBusinessImpact.incident_id == inc.id).first()
    if existing_impact:
        existing_impact.estimated_financial_loss_usd = round(financial_loss, 2)
        existing_impact.affected_user_count = affected_users
        existing_impact.degradation_factor = deg_factor
        existing_impact.sla_breach_detected = sla_breach
        existing_impact.currency = impact_cfg.currency
        existing_impact.is_estimated_default = is_estimated_default
        existing_impact.calculated_at = datetime.now(timezone.utc)
        db_obj = existing_impact
    else:
        new_impact = IncidentBusinessImpact(
            incident_id=inc.id,
            organization_id=organization_id,
            estimated_financial_loss_usd=round(financial_loss, 2),
            affected_user_count=affected_users,
            degradation_factor=deg_factor,
            sla_breach_detected=sla_breach,
            currency=impact_cfg.currency,
            is_estimated_default=is_estimated_default,
        )
        db.add(new_impact)
        db_obj = new_impact
    db.commit()

    return IncidentBusinessImpactOut(
        id=db_obj.id,
        incident_id=inc.id,
        incident_title=inc.title,
        service_id=svc.id if svc else None,
        service_name=svc_name,
        outage_duration_minutes=round(duration_minutes, 1),
        degradation_factor=deg_factor,
        hourly_revenue_rate_usd=impact_cfg.hourly_revenue_rate_usd,
        estimated_financial_loss_usd=round(financial_loss, 2),
        financial_loss_display=f"${financial_loss:,.2f} USD" + (" (Configured Org Baseline Estimate)" if is_estimated_default else ""),
        affected_user_count=affected_users,
        sla_breach_detected=sla_breach,
        currency=impact_cfg.currency,
        status="calculated",
        is_estimated_default=is_estimated_default,
        calculated_at=db_obj.calculated_at,
    )
