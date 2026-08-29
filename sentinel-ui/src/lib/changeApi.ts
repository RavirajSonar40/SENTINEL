const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface RequestOptions extends RequestInit {
  token?: string;
}

function getStoredToken(): string | undefined {
  if (typeof window !== "undefined") {
    return localStorage.getItem("sentinel_token") || undefined;
  }
  return undefined;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = options.token || getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Request failed with status ${res.status}`);
  }

  return res.json();
}

export type ChangeType =
  | "CODE_COMMIT"
  | "PULL_REQUEST"
  | "CONFIGURATION"
  | "ENVIRONMENT_VARIABLE"
  | "DEPENDENCY_UPGRADE"
  | "DATABASE_MIGRATION"
  | "INFRASTRUCTURE"
  | "FEATURE_FLAG"
  | "API_CONTRACT"
  | "DEPLOYMENT"
  | "SCALING_CHANGE";

export type ChangeRiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type CorrelationStatus =
  | "SUSPECTED_ROOT_CAUSE"
  | "CONTRIBUTING_FACTOR"
  | "COINCIDENTAL"
  | "DISMISSED";

export interface ChangeEvent {
  id: string;
  organization_id: string;
  service_id?: string;
  environment_id?: string;
  repository_id?: string;
  deployment_id?: string;
  provider: string;
  provider_event_id?: string;
  auth_source?: string;
  integration_id?: string;
  change_type: ChangeType;
  title: string;
  description?: string;
  external_id: string;
  commit_sha?: string;
  author?: string;
  risk_level: ChangeRiskLevel;
  effective_at: string;
  observed_at: string;
  source_url?: string;
  affected_components?: string[];
  diff_summary?: Record<string, any>;
  metadata_json?: Record<string, any>;
  created_at: string;
}

export interface IncidentChangeCorrelation {
  id: string;
  organization_id: string;
  incident_id: string;
  change_event_id: string;
  time_delta_seconds: number;
  topological_distance: number;
  correlation_score: number;
  rank: number;
  is_causal_candidate: boolean;
  triage_status: CorrelationStatus;
  triage_reason?: string;
  triaged_by_user_id?: string;
  triaged_at?: string;
  previous_status?: string;
  reasoning?: string;
  change_event?: ChangeEvent;
  created_at: string;
  updated_at?: string;
}

export interface ChangeCorrelationReport {
  id?: string;
  organization_id?: string;
  incident_id: string;
  version: number;
  is_current: boolean;
  snapshot_hash?: string;
  calculated_at: string;
  lookback_window_minutes: number;
  correlations: IncidentChangeCorrelation[];
  causal_candidates_count: number;
  top_suspect?: IncidentChangeCorrelation;
  summary: string;
}

export interface CreateChangeEventPayload {
  title: string;
  description?: string;
  change_type: ChangeType;
  provider?: string;
  provider_event_id?: string;
  service_id?: string;
  environment_id?: string;
  repository_id?: string;
  deployment_id?: string;
  external_id?: string;
  commit_sha?: string;
  author?: string;
  risk_level?: ChangeRiskLevel;
  effective_at?: string;
  source_url?: string;
  affected_components?: string[];
  diff_summary?: Record<string, any>;
  metadata_json?: Record<string, any>;
}

export interface TriageCorrelationPayload {
  triage_status: CorrelationStatus;
  reason?: string;
}

export const changeApi = {
  getChanges: (
    params?: {
      service_id?: string;
      environment_id?: string;
      repository_id?: string;
      change_type?: string;
      provider?: string;
      limit?: number;
      offset?: number;
    },
    token?: string
  ) => {
    const q = new URLSearchParams();
    if (params?.service_id) q.set("service_id", params.service_id);
    if (params?.environment_id) q.set("environment_id", params.environment_id);
    if (params?.repository_id) q.set("repository_id", params.repository_id);
    if (params?.change_type) q.set("change_type", params.change_type);
    if (params?.provider) q.set("provider", params.provider);
    if (params?.limit) q.set("limit", params.limit.toString());
    if (params?.offset) q.set("offset", params.offset.toString());
    const queryStr = q.toString() ? `?${q.toString()}` : "";
    return request<ChangeEvent[]>(`/changes${queryStr}`, { token });
  },

  getChangeDetail: (id: string, token?: string) =>
    request<ChangeEvent>(`/changes/${id}`, { token }),

  createChange: (data: CreateChangeEventPayload, token?: string) =>
    request<ChangeEvent>("/changes", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    }),

  getIncidentChanges: (incidentId: string, lookbackMinutes: number = 120, token?: string) =>
    request<ChangeCorrelationReport>(
      `/changes/incidents/${incidentId}/changes?lookback_window_minutes=${lookbackMinutes}`,
      { token }
    ),

  correlateIncidentChanges: (incidentId: string, lookbackMinutes: number = 120, token?: string) =>
    request<ChangeCorrelationReport>(
      `/changes/incidents/${incidentId}/changes/correlate?lookback_window_minutes=${lookbackMinutes}`,
      {
        method: "POST",
        token,
      }
    ),

  triageCorrelation: (
    incidentId: string,
    correlationId: string,
    payload: TriageCorrelationPayload,
    token?: string
  ) =>
    request<IncidentChangeCorrelation>(
      `/changes/incidents/${incidentId}/changes/${correlationId}/triage`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
        token,
      }
    ),
};
