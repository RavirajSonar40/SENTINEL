const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface RequestOptions extends RequestInit {
  token?: string;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { token, ...fetchOptions } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...fetchOptions,
    headers,
  });

  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("sentinel_token");
      window.location.href = "/login";
      throw new Error("Session expired. Please log in again.");
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Request failed with status ${res.status}`);
  }
  if (res.status === 204) {
    return null as unknown as T;
  }
  return res.json();
}

// ============================================================================
// TYPES
// ============================================================================

export type DeploymentStatus = "pending" | "in_progress" | "succeeded" | "failed" | "rolled_back" | "cancelled";
export type DeploymentProvider = "manual" | "github" | "generic_webhook" | "argo_cd" | "kubernetes" | "gitlab";

export interface Deployment {
  id: string;
  organization_id: string;
  service_id: string;
  environment_id: string;
  region_id?: string | null;
  repository_id?: string | null;
  service_name?: string | null;
  environment_name?: string | null;
  region_code?: string | null;
  repository_full_name?: string | null;
  commit_sha: string;
  commit_message?: string | null;
  version?: string | null;
  provider: string;
  provider_event_id?: string | null;
  external_deployment_id?: string | null;
  status: DeploymentStatus;
  url?: string | null;
  deployed_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  deployed_by?: string | null;
  is_current: boolean;
  metadata?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface DeploymentCreateInput {
  service_id: string;
  environment_id: string;
  region_id?: string | null;
  repository_id?: string | null;
  commit_sha: string;
  commit_message?: string | null;
  version?: string | null;
  provider?: string;
  provider_event_id?: string | null;
  external_deployment_id?: string | null;
  status?: string;
  url?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface DeploymentStatusUpdateInput {
  status: DeploymentStatus;
  finished_at?: string | null;
  error_message?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WebhookEndpoint {
  id: string;
  organization_id: string;
  name: string;
  provider?: string;
  key_id: string;
  raw_secret?: string | null;
  is_active: boolean;
  created_at?: string;
}

export interface CommitSummary {
  sha: string;
  message: string;
  author?: string | null;
  timestamp?: string | null;
}

export interface DeploymentCommitComparison {
  status: "available" | "unavailable";
  reason?: string | null;
  repository_full_name?: string | null;
  base_commit_sha: string;
  head_commit_sha: string;
  total_commits: number;
  commits: CommitSummary[];
}

// ============================================================================
// API METHODS
// ============================================================================

export const deploymentsApi = {
  getDeployments(params: {
    service_id?: string;
    environment_id?: string;
    region_id?: string;
    status?: string;
    commit_sha?: string;
    limit?: number;
    offset?: number;
  } = {}, token?: string): Promise<Deployment[]> {
    const q = new URLSearchParams();
    if (params.service_id) q.set("service_id", params.service_id);
    if (params.environment_id) q.set("environment_id", params.environment_id);
    if (params.region_id) q.set("region_id", params.region_id);
    if (params.status) q.set("status", params.status);
    if (params.commit_sha) q.set("commit_sha", params.commit_sha);
    if (params.limit) q.set("limit", params.limit.toString());
    if (params.offset) q.set("offset", params.offset.toString());
    return request<Deployment[]>(`/deployments?${q.toString()}`, { token });
  },

  getCurrentDeployment(serviceId: string, environmentId: string, regionId?: string, token?: string): Promise<Deployment | null> {
    const q = new URLSearchParams({ service_id: serviceId, environment_id: environmentId });
    if (regionId) q.set("region_id", regionId);
    return request<Deployment | null>(`/deployments/current?${q.toString()}`, { token });
  },

  getDeploymentsInWindow(serviceId: string, windowStart: string, windowEnd: string, environmentId?: string, token?: string): Promise<Deployment[]> {
    const q = new URLSearchParams({
      service_id: serviceId,
      window_start: windowStart,
      window_end: windowEnd,
    });
    if (environmentId) q.set("environment_id", environmentId);
    return request<Deployment[]>(`/deployments/window?${q.toString()}`, { token });
  },

  getDeploymentDetail(id: string, token?: string): Promise<Deployment> {
    return request<Deployment>(`/deployments/${id}`, { token });
  },

  createDeployment(payload: DeploymentCreateInput, token?: string): Promise<Deployment> {
    return request<Deployment>("/deployments", {
      method: "POST",
      body: JSON.stringify(payload),
      token,
    });
  },

  updateDeploymentStatus(id: string, payload: DeploymentStatusUpdateInput, token?: string): Promise<Deployment> {
    return request<Deployment>(`/deployments/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify(payload),
      token,
    });
  },

  getPreviousStableDeployment(id: string, token?: string): Promise<Deployment | null> {
    return request<Deployment | null>(`/deployments/${id}/previous-stable`, { token });
  },

  getDeploymentCommitsBetween(id: string, token?: string): Promise<DeploymentCommitComparison> {
    return request<DeploymentCommitComparison>(`/deployments/${id}/commits-between`, { token });
  },

  getWebhookEndpoints(token?: string): Promise<WebhookEndpoint[]> {
    return request<WebhookEndpoint[]>("/webhook-endpoints", { token });
  },

  createWebhookEndpoint(name: string, provider: string = "generic", token?: string): Promise<WebhookEndpoint> {
    return request<WebhookEndpoint>("/webhook-endpoints", {
      method: "POST",
      body: JSON.stringify({ name, provider }),
      token,
    });
  },

  deleteWebhookEndpoint(id: string, token?: string): Promise<void> {
    return request<void>(`/webhook-endpoints/${id}`, {
      method: "DELETE",
      token,
    });
  },
};
