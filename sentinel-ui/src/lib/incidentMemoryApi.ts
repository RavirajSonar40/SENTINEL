const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface RequestOptions extends RequestInit {
  token?: string;
}

function getStoredToken(): string | undefined {
  if (typeof window !== "undefined") {
    return localStorage.getItem("token") || undefined;
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

export interface TimelineEvent {
  id: string;
  time?: string;
  type: string;
  category: string;
  label: string;
  detail?: string;
  icon?: string;
  color?: string;
  actor: 'ai' | 'human' | 'system';
  parent_event_id?: string;
  causal_relation?: string;
  inferred_timestamp: boolean;
  metadata?: Record<string, any>;
}

export interface TimelineMilestones {
  mttd_seconds?: number;
  mtta_seconds?: number;
  mttrc_seconds?: number;
  mttm_seconds?: number;
  mttr_seconds?: number;
  started_at?: string;
  detected_at?: string;
  acknowledged_at?: string;
  root_cause_at?: string;
  mitigated_at?: string;
  resolved_at?: string;
}

export interface ExplainableTimelineResponse {
  incident_id: string;
  milestones: TimelineMilestones;
  total_events: number;
  events: TimelineEvent[];
}

export interface ActionItem {
  id: string;
  organization_id: string;
  post_mortem_id: string;
  incident_id?: string;
  assigned_to_user_id?: string;
  created_by_user_id?: string;
  title: string;
  description?: string;
  category: 'code_hardening' | 'monitoring_gap' | 'architectural_debt' | 'runbook_improvement' | 'infrastructure_resilience';
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  status: 'open' | 'in_progress' | 'completed' | 'wont_fix';
  due_date?: string;
  completed_at?: string;
  external_issue_url?: string;
  notes?: string;
  created_at: string;
  updated_at?: string;
}

export interface PostMortem {
  id: string;
  organization_id: string;
  incident_id: string;
  work_item_id?: string;
  author_id?: string;
  signed_off_by_user_id?: string;
  title: string;
  summary: string;
  root_cause_summary: string;
  impact_summary?: string;
  trigger_event?: string;
  detection_summary?: string;
  resolution_summary?: string;
  contributing_factors_json?: any[];
  timeline_summary_json?: any[];
  lessons_learned_json?: any[];
  time_to_detect_seconds?: number;
  time_to_acknowledge_seconds?: number;
  time_to_root_cause_seconds?: number;
  time_to_mitigate_seconds?: number;
  time_to_resolve_seconds?: number;
  downtime_minutes: number;
  affected_user_count_estimate?: number;
  slo_impact_percent?: number;
  resolution_type: string;
  severity_actual: string;
  status: 'draft' | 'under_review' | 'approved' | 'published' | 'archived';
  snapshot_hash?: string;
  abstained: boolean;
  human_reviewed: boolean;
  is_current: boolean;
  version: number;
  memory_indexing_status: 'pending' | 'indexed' | 'failed';
  memory_indexing_error?: string;
  signed_off_at?: string;
  published_at?: string;
  created_at: string;
  updated_at?: string;
  action_items?: ActionItem[];
}

export interface ActionItemCreate {
  title: string;
  description?: string;
  category?: string;
  priority?: string;
  due_date?: string;
  assigned_to_user_id?: string;
  external_issue_url?: string;
  notes?: string;
}

export interface IncidentMemorySearchResult {
  id: string;
  score: number;
  title: string;
  service?: string;
  severity?: string;
  root_cause?: string;
  resolution?: string;
  lessons_learned?: any[];
  resolved_at?: string;
}

export interface IncidentMemorySearchResponse {
  results: IncidentMemorySearchResult[];
  total: number;
  source: string;
}

export async function fetchIncidentTimeline(incidentId: string): Promise<ExplainableTimelineResponse> {
  return request<ExplainableTimelineResponse>(`/incidents/${incidentId}/timeline`);
}

export async function generatePostMortem(incidentId: string): Promise<PostMortem> {
  return request<PostMortem>(`/incidents/${incidentId}/post-mortem/generate`, {
    method: "POST",
  });
}

export async function fetchPostMortem(incidentId: string): Promise<PostMortem> {
  return request<PostMortem>(`/incidents/${incidentId}/post-mortem`);
}

export async function updatePostMortem(incidentId: string, data: Partial<PostMortem>): Promise<PostMortem> {
  return request<PostMortem>(`/incidents/${incidentId}/post-mortem`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function publishPostMortem(incidentId: string, signOffNotes?: string): Promise<PostMortem> {
  return request<PostMortem>(`/incidents/${incidentId}/post-mortem/publish`, {
    method: "POST",
    body: JSON.stringify({ sign_off_notes: signOffNotes }),
  });
}

export async function createActionItem(incidentId: string, data: ActionItemCreate): Promise<ActionItem> {
  return request<ActionItem>(`/incidents/${incidentId}/post-mortem/action-items`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function fetchActionItems(params?: { status?: string; priority?: string; category?: string }): Promise<ActionItem[]> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.priority) query.set("priority", params.priority);
  if (params?.category) query.set("category", params.category);
  const qStr = query.toString();
  return request<ActionItem[]>(`/incident-memory/action-items${qStr ? `?${qStr}` : ""}`);
}

export async function updateActionItem(itemId: string, data: Partial<ActionItem>): Promise<ActionItem> {
  return request<ActionItem>(`/incident-memory/action-items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function searchIncidentMemory(query: string, service?: string, limit: number = 5): Promise<IncidentMemorySearchResponse> {
  return request<IncidentMemorySearchResponse>(`/incident-memory/search`, {
    method: "POST",
    body: JSON.stringify({ query, service, limit }),
  });
}
