/**
 * Phase 16: Advanced Reliability, SLO Tracking & Predictions API Client
 */

import { FreshnessMetadata } from "./commandCenterApi";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface SLOBurnRateOut {
  burn_rate_1h: number | null;
  burn_rate_6h: number | null;
  burn_rate_24h: number | null;
  burn_status_1h: string;
  burn_status_6h: string;
  burn_status_24h: string;
}

export interface SLOTimeToExhaustionOut {
  hours_remaining: number | null;
  display: string;
  status: string;
}

export interface SLOConfigItem {
  id: string;
  organization_id: string;
  service_id: string;
  service_name: string;
  name: string;
  target_percent: number;
  sli_type: string;
  threshold_value: number | null;
  window_days: number;
  is_active: boolean;
  current_compliance_percent: number | null;
  compliance_display: string;
  budget_remaining_percent: number | null;
  budget_display: string;
  burn_rates: SLOBurnRateOut;
  time_to_exhaustion: SLOTimeToExhaustionOut;
  total_samples_observed: number;
  freshness: FreshnessMetadata;
  status: string;
  created_at: string;
  updated_at: string | null;
}

export interface SLOBurnDownPoint {
  timestamp: string;
  budget_remaining_percent: number;
  burn_rate: number;
  event_note: string | null;
}

export interface SLOBurnDownResponse {
  slo_id: string;
  slo_name: string;
  service_name: string;
  target_percent: number;
  current_budget_remaining: number | null;
  points: SLOBurnDownPoint[];
}

export interface PredictiveAnomalyItem {
  id: string;
  organization_id: string;
  service_id: string;
  service_name: string;
  metric_name: string;
  current_value: number;
  threshold_value: number;
  projected_breach_at: string | null;
  time_to_breach_minutes: number;
  growth_rate_per_minute: number;
  r_squared: number;
  confidence_score: number;
  severity: string;
  is_active: boolean;
  status: string;
  recommendation: string | null;
  created_at: string;
}

export interface BusinessImpactConfigItem {
  id: string;
  organization_id: string;
  service_id: string | null;
  service_name: string | null;
  tier: string | null;
  hourly_revenue_rate_usd: number;
  active_users_baseline: number;
  currency: string;
  is_org_default: boolean;
}

export interface IncidentBusinessImpactItem {
  id: string;
  incident_id: string;
  incident_title: string;
  service_id: string | null;
  service_name: string;
  outage_duration_minutes: number;
  degradation_factor: number;
  hourly_revenue_rate_usd: number | null;
  estimated_financial_loss_usd: number | null;
  financial_loss_display: string;
  affected_user_count: number;
  sla_breach_detected: boolean;
  currency: string;
  status: string;
  is_estimated_default: boolean;
  calculated_at: string;
}

async function authFetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("sentinel_token") : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const errorText = await res.text();
    let detail = `API error ${res.status}`;
    try {
      const parsed = JSON.parse(errorText);
      detail = parsed.detail || detail;
    } catch {
      // keep fallback
    }
    throw new Error(detail);
  }

  return res.json();
}

export const reliabilityApi = {
  getSLOs: (serviceId?: string, isActive?: boolean): Promise<SLOConfigItem[]> => {
    const params = new URLSearchParams();
    if (serviceId) params.append("service_id", serviceId);
    if (isActive !== undefined) params.append("is_active", String(isActive));
    const qs = params.toString();
    return authFetch<SLOConfigItem[]>(`/reliability/slos${qs ? `?${qs}` : ""}`);
  },

  createSLO: (data: {
    service_id: string;
    name: string;
    target_percent?: number;
    sli_type?: string;
    threshold_value?: number;
    window_days?: number;
  }): Promise<SLOConfigItem> => {
    return authFetch<SLOConfigItem>("/reliability/slos", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getSLOBurnDown: (sloId: string): Promise<SLOBurnDownResponse> => {
    return authFetch<SLOBurnDownResponse>(`/reliability/slos/${sloId}/burn-down`);
  },

  getPredictions: (statusFilter: string = "ACTIVE"): Promise<PredictiveAnomalyItem[]> => {
    return authFetch<PredictiveAnomalyItem[]>(`/reliability/predictions?status_filter=${encodeURIComponent(statusFilter)}`);
  },

  acknowledgePrediction: (anomalyId: string, comment?: string): Promise<{ message: string; id: string; status: string }> => {
    return authFetch<{ message: string; id: string; status: string }>(`/reliability/predictions/${anomalyId}/acknowledge`, {
      method: "POST",
      body: JSON.stringify({ comment }),
    });
  },

  getIncidentBusinessImpact: (incidentId: string): Promise<IncidentBusinessImpactItem> => {
    return authFetch<IncidentBusinessImpactItem>(`/reliability/business-impact/${incidentId}`);
  },

  getBusinessImpactConfigs: (): Promise<BusinessImpactConfigItem[]> => {
    return authFetch<BusinessImpactConfigItem[]>("/reliability/business-impact/config");
  },

  setBusinessImpactConfig: (data: {
    service_id?: string;
    tier?: string;
    hourly_revenue_rate_usd: number;
    active_users_baseline: number;
    currency?: string;
  }): Promise<BusinessImpactConfigItem> => {
    return authFetch<BusinessImpactConfigItem>("/reliability/business-impact/config", {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },
};
