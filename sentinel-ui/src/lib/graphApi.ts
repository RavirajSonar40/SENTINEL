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
  const { token, ...fetchOptions } = options;
  const authToken = token || getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
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

export interface GraphNode {
  id: string;
  organization_id: string;
  name: string;
  node_type: string;
  identifier: string;
  tier?: string;
  entity_id?: string;
  metadata_json?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

export interface GraphEdge {
  id: string;
  organization_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_type: string;
  source: string;
  confidence: number;
  criticality: "hard" | "soft";
  is_stale: boolean;
  metadata_json?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

export interface TopologyGraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  node_count: number;
  edge_count: number;
  nodes_by_type: Record<string, number>;
}

export interface BlastRadiusNodeImpact {
  service_id: string;
  name: string;
  tier?: string;
  impact_type: "observed" | "inferred";
  impact_level: "outage" | "degraded" | "unaffected";
  criticality: "hard" | "soft";
  distance: number;
  path: string[];
  observed_signals: Array<Record<string, any>>;
}

export interface CustomerImpactEstimate {
  traffic_percent?: number;
  user_percent?: number;
  traffic_impact_mode: "measured" | "estimated";
  traffic_confidence: "high" | "medium" | "low";
  calculation_basis: string;
}

export interface IncidentBlastRadiusReport {
  id: string;
  organization_id: string;
  incident_id: string;
  root_service?: { id: string; name: string; tier?: string };
  version: number;
  is_current: boolean;
  calculated_at: string;
  engine_version: string;
  telemetry_window_minutes: number;
  graph_snapshot_hash?: string;
  direct_services: Array<Record<string, any>>;
  indirect_services: BlastRadiusNodeImpact[];
  affected_endpoints: Array<Record<string, any>>;
  affected_repositories: Array<{
    repository_id: string;
    name: string;
    url?: string;
    role: string;
    is_primary: boolean;
    remediation_target: boolean;
    evidence_only: boolean;
    service_id: string;
  }>;
  affected_environments: Array<Record<string, any>>;
  affected_regions: Array<Record<string, any>>;
  customer_impact: CustomerImpactEstimate;
  criticality_summary: Record<string, any>;
  unknowns: string[];
}

export const graphApi = {
  async getTopology(params?: { node_type?: string; tier?: string; include_stale?: boolean }, token?: string): Promise<TopologyGraphResponse> {
    const query = new URLSearchParams();
    if (params?.node_type) query.append("node_type", params.node_type);
    if (params?.tier) query.append("tier", params.tier);
    if (params?.include_stale !== undefined) query.append("include_stale", String(params.include_stale));
    const qs = query.toString() ? `?${query.toString()}` : "";
    return request<TopologyGraphResponse>(`/graph/topology${qs}`, { method: "GET", token });
  },

  async syncCatalog(token?: string): Promise<{ status: string; stats: Record<string, number> }> {
    return request<{ status: string; stats: Record<string, number> }>("/graph/sync-catalog", {
      method: "POST",
      token,
    });
  },

  async createNode(data: Partial<GraphNode>, token?: string): Promise<GraphNode> {
    return request<GraphNode>("/graph/nodes", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    });
  },

  async createEdge(data: Partial<GraphEdge>, token?: string): Promise<GraphEdge> {
    return request<GraphEdge>("/graph/edges", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    });
  },

  async deleteEdge(edgeId: string, token?: string): Promise<void> {
    return request<void>(`/graph/edges/${edgeId}`, {
      method: "DELETE",
      token,
    });
  },

  async simulateBlastRadius(payload: { service_id: string; environment_id?: string; max_depth?: number }, token?: string): Promise<IncidentBlastRadiusReport> {
    return request<IncidentBlastRadiusReport>("/graph/blast-radius", {
      method: "POST",
      body: JSON.stringify(payload),
      token,
    });
  },

  async getIncidentBlastRadius(incidentId: string, token?: string): Promise<IncidentBlastRadiusReport> {
    return request<IncidentBlastRadiusReport>(`/graph/incidents/${incidentId}/blast-radius`, {
      method: "GET",
      token,
    });
  },

  async recalculateIncidentBlastRadius(incidentId: string, token?: string): Promise<IncidentBlastRadiusReport> {
    return request<IncidentBlastRadiusReport>(`/graph/incidents/${incidentId}/blast-radius/recalculate`, {
      method: "POST",
      token,
    });
  },

  async importManifest(data: { manifest_type: string; service_id?: string; content: Record<string, any> }, token?: string): Promise<any> {
    return request<any>("/graph/manifests/import", {
      method: "POST",
      body: JSON.stringify(data),
      token,
    });
  },
};
