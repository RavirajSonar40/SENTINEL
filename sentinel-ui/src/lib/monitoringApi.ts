export interface TelemetrySignal {
  id: string;
  organization_id: string;
  provider: "prometheus" | "sentry" | "health_check" | "generic" | "datadog" | "cloudwatch";
  provider_event_id: string;
  signal_type: string;
  rule_name: string;
  service_id?: string;
  service_name?: string;
  environment_id?: string;
  environment_name?: string;
  region_id?: string;
  region_code?: string;
  metric_name?: string;
  metric_value?: number;
  threshold_value?: number;
  fingerprint: string;
  correlation_key: string;
  title: string;
  description?: string;
  error_signature?: string;
  raw_payload?: Record<string, unknown>;
  status: "ingested" | "correlated" | "triggered_incident" | "resolved" | "suppressed_non_prod";
  incident_id?: string;
  incident_number?: number;
  observed_at: string;
  created_at?: string;
}

export interface AlertRuleConfigDTO {
  id: string;
  organization_id: string;
  rule_name: string;
  is_enabled: boolean;
  threshold_value?: number;
  window_minutes: number;
  severity_override?: string;
  created_at?: string;
  updated_at?: string;
}

export interface HealthCheckStatus {
  id: string;
  service_id: string;
  service_name: string;
  environment_id: string;
  environment_name: string;
  region_id?: string;
  region_code?: string;
  health_check_url: string;
  is_healthy?: boolean | null;
  consecutive_failures: number;
  last_probe_status_code?: number;
  last_probe_latency_ms?: number;
  last_probe_error?: string;
  last_probed_at?: string;
}

export interface CorrelationSummary {
  total_signals_24h: number;
  auto_incidents_24h: number;
  open_incidents: number;
  healthy_probes: number;
  failing_probes: number;
}

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

function getAuthHeaders(token?: string): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const effectiveToken = token || (typeof window !== "undefined" ? localStorage.getItem("sentinel_token") : null);
  if (effectiveToken) {
    headers["Authorization"] = `Bearer ${effectiveToken}`;
  }
  return headers;
}

export const monitoringApi = {
  async fetchTelemetrySignals(token?: string, params?: {
    service_id?: string;
    environment_id?: string;
    provider?: string;
    signal_type?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }): Promise<TelemetrySignal[]> {
    const query = new URLSearchParams();
    if (params?.service_id) query.append("service_id", params.service_id);
    if (params?.environment_id) query.append("environment_id", params.environment_id);
    if (params?.provider) query.append("provider", params.provider);
    if (params?.signal_type) query.append("signal_type", params.signal_type);
    if (params?.status) query.append("status", params.status);
    if (params?.limit) query.append("limit", String(params.limit));
    if (params?.offset) query.append("offset", String(params.offset));

    const res = await fetch(`${API_BASE}/monitoring/signals?${query.toString()}`, {
      headers: getAuthHeaders(token),
    });
    if (!res.ok) throw new Error("Failed to fetch telemetry signals");
    return res.json();
  },

  async fetchHealthCheckStatuses(token?: string): Promise<HealthCheckStatus[]> {
    const res = await fetch(`${API_BASE}/monitoring/health-checks`, {
      headers: getAuthHeaders(token),
    });
    if (!res.ok) throw new Error("Failed to fetch health check statuses");
    return res.json();
  },

  async probeHealthCheckNow(configId: string, token?: string): Promise<{
    config_id: string;
    is_healthy: boolean;
    status_code?: number;
    latency_ms: number;
    error_message?: string;
    probed_at: string;
  }> {
    const res = await fetch(`${API_BASE}/monitoring/health-checks/probe-now`, {
      method: "POST",
      headers: getAuthHeaders(token),
      body: JSON.stringify({ config_id: configId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "On-demand probe failed");
    }
    return res.json();
  },

  async fetchAlertRules(token?: string): Promise<AlertRuleConfigDTO[]> {
    const res = await fetch(`${API_BASE}/monitoring/rules`, {
      headers: getAuthHeaders(token),
    });
    if (!res.ok) throw new Error("Failed to fetch alert rule configs");
    return res.json();
  },

  async updateAlertRule(
    ruleName: string,
    payload: {
      is_enabled?: boolean;
      threshold_value?: number;
      window_minutes?: number;
      severity_override?: string;
    },
    token?: string
  ): Promise<AlertRuleConfigDTO> {
    const res = await fetch(`${API_BASE}/monitoring/rules/${ruleName}`, {
      method: "PUT",
      headers: getAuthHeaders(token),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to update alert rule config");
    }
    return res.json();
  },

  async fetchCorrelationSummary(token?: string): Promise<CorrelationSummary> {
    const res = await fetch(`${API_BASE}/monitoring/correlation-summary`, {
      headers: getAuthHeaders(token),
    });
    if (!res.ok) throw new Error("Failed to fetch correlation summary");
    return res.json();
  },
};
