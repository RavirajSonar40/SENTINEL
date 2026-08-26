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
    throw new Error(error.detail || "API error");
  }
  return res.json();
}

// Auth
export async function login(username: string, password: string) {
  return request<{ access_token: string; user_id: string; username: string }>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ username, password }) }
  );
}

export async function register(username: string, email: string, password: string) {
  return request<{ access_token: string; user_id: string; username: string }>(
    "/auth/register",
    { method: "POST", body: JSON.stringify({ username, email, password }) }
  );
}

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  role?: string;
}

export async function getMe(token: string): Promise<UserProfile> {
  return request<UserProfile>("/auth/me", { token });
}

// Repositories
export interface Repository {
  id: string;
  name: string;
  full_name: string;
  default_branch: string;
  service_id?: string;
  github_url?: string;
  sync_status: string;
  last_synced_at?: string;
}

export async function listRepositories(token: string): Promise<Repository[]> {
  return request<Repository[]>("/repositories", { token });
}

// Incidents
export interface InvestigationSummary {
  id: string;
  status: string;
  progress_percent: number;
  confidence: string | null;
  root_cause_found: boolean;
}

export interface Incident {
  id: string;
  number: number;
  title: string;
  description: string | null;
  severity: string;
  service: string | null;
  status: string;
  source: string;
  confidence: string | null;
  root_cause_summary: string | null;
  started_at: string | null;
  detected_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string | null;
  repositories: Repository[];
  investigation: InvestigationSummary | null;
}

export interface IncidentCreate {
  title: string;
  description?: string;
  severity: string;
  service: string;
  source?: string;
  started_at?: string;
  repository_ids: string[];
}

export async function createIncident(token: string, data: IncidentCreate): Promise<Incident> {
  return request<Incident>("/incidents", {
    method: "POST",
    body: JSON.stringify(data),
    token,
  });
}

export async function listIncidents(token: string): Promise<Incident[]> {
  return request<Incident[]>("/incidents", { token });
}

export async function getIncident(token: string, id: string): Promise<Incident> {
  return request<Incident>(`/incidents/${id}`, { token });
}

export async function updateIncident(
  token: string,
  id: string,
  data: Partial<IncidentCreate & { status: string }>
): Promise<Incident> {
  return request<Incident>(`/incidents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
    token,
  });
}

export async function startInvestigation(token: string, incidentId: string): Promise<{ investigation_id: string; status: string }> {
  return request(`/incidents/${incidentId}/investigate`, {
    method: "POST",
    token,
  });
}

// Investigations
export interface Investigation {
  id: string;
  incident_id: string;
  status: string;
  current_step: string | null;
  progress_percent: number;
  root_cause_found: boolean;
  confidence: string | null;
  llm_model: string | null;
  total_tokens: number;
  total_cost_usd: number;
  started_at: string;
  completed_at: string | null;
}

export interface InvestigationTask {
  id: string;
  task_type: string;
  description: string | null;
  status: string;
  order: number;
  tool_name: string | null;
  error_message: string | null;
  attempt: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface Evidence {
  id: string;
  source_type: string;
  source_id: string | null;
  repository: string | null;
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  title: string;
  content: string | null;
  summary: string | null;
  timestamp: string | null;
  source_url: string | null;
  relevance_score: number | null;
  collected_at: string;
}

export interface Hypothesis {
  id: string;
  label: string;
  description: string;
  status: string;
  confidence: string;
  supporting_evidence_count: number;
  contradicting_evidence_count: number;
  missing_evidence_count: number;
  evaluation_notes: string | null;
  rejection_reason: string | null;
  created_at: string;
  evaluated_at: string | null;
}

export interface RootCause {
  id: string;
  summary: string;
  affected_component: string | null;
  causal_explanation: string;
  confidence: string;
  relevant_commits: string[] | null;
  relevant_files: string[] | null;
  timeline: { time: string; event: string }[] | null;
  identified_at: string;
}

export async function getInvestigation(token: string, id: string): Promise<Investigation> {
  return request(`/investigations/${id}`, { token });
}

export async function listTasks(token: string, investigationId: string): Promise<InvestigationTask[]> {
  return request(`/investigations/${investigationId}/tasks`, { token });
}

export async function listEvidence(token: string, investigationId: string): Promise<Evidence[]> {
  return request(`/investigations/${investigationId}/evidence`, { token });
}

export async function listHypotheses(token: string, investigationId: string): Promise<Hypothesis[]> {
  return request(`/investigations/${investigationId}/hypotheses`, { token });
}

export async function getRootCause(token: string, investigationId: string): Promise<RootCause> {
  return request(`/investigations/${investigationId}/root-cause`, { token });
}

// Investigation Engine
export interface InvestigateResponse {
  status: string;
  investigation_id: string | null;
  tasks_completed: number;
  tasks_failed: number;
  evidence_count: number;
  hypotheses_count: number;
  confidence: string;
  root_cause_found: boolean;
  message: string;
}

export async function triggerInvestigation(
  token: string,
  incidentId: string,
  repository?: string,
  service?: string,
): Promise<InvestigateResponse> {
  return request<InvestigateResponse>("/investigate", {
    method: "POST",
    body: JSON.stringify({ incident_id: incidentId, repository, service }),
    token,
  });
}

export interface InvestigationStep {
  step: string;
  status: "active" | "completed";
  message: string;
  detail: string | string[] | Record<string, unknown>;
}

export function triggerInvestigationStream(
  token: string,
  incidentId: string,
  onStep: (step: InvestigationStep) => void,
  onComplete: (data: Record<string, unknown>) => void,
  onError: (msg: string) => void,
  repository?: string,
  service?: string,
): EventSource {
  const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

  // POST via fetch, then read the stream with EventSource-like handling
  fetch(`${API_BASE}/investigate/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ incident_id: incidentId, repository, service }),
  }).then(async (response) => {
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      onError(`HTTP ${response.status}: ${text.slice(0, 200)}`);
      return;
    }
    const reader = response.body?.getReader();
    if (!reader) { onError("No response body"); return; }
    const decoder = new TextDecoder();
    let buffer = "";
    let gotComplete = false;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        let eventType = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) eventType = line.slice(7).trim();
          else if (line.startsWith("data: ")) {
            const dataStr = line.slice(6);
            try {
              const data = JSON.parse(dataStr);
              if (eventType === "step") onStep(data as InvestigationStep);
              else if (eventType === "complete") { gotComplete = true; onComplete(data); }
              else if (eventType === "error") onError(data.message || "Unknown error");
            } catch {}
          }
        }
      }
    } catch (e) {
      onError("Stream interrupted: " + (e instanceof Error ? e.message : String(e)));
      return;
    }

    // If stream ended without a complete event, try to refresh data anyway
    if (!gotComplete) {
      onComplete({ status: "completed", evidence_count: 0, hypotheses_count: 0, root_cause_found: false, tasks_completed: 0, tasks_failed: 0, confidence: "low" });
    }
  }).catch((e) => onError(e.message || "Network error"));

  // Return a dummy EventSource for compatibility (actual reading is via fetch)
  return new EventSource("data:text/event-stream,");
}

export async function getEngineStatus(token: string, investigationId: string) {
  return request(`/investigations/${investigationId}/engine-status`, { token });
}

// Indexing
export interface IndexResponse {
  status: string;
  files_indexed: number;
  chunks_indexed: number;
  message: string;
}

export async function indexRepository(
  token: string,
  data: { repository?: string; local_path?: string; file_paths?: string[] },
): Promise<IndexResponse> {
  return request<IndexResponse>("/index", {
    method: "POST",
    body: JSON.stringify(data),
    token,
  });
}

export async function getIndexStats(token: string) {
  return request("/index/stats", { token });
}

export async function searchIndex(token: string, query: string, repository?: string) {
  const params = new URLSearchParams({ q: query });
  if (repository) params.set("repository", repository);
  return request(`/index/search?${params.toString()}`, { token });
}

// Remediation
export interface ProposedFix {
  id: string;
  investigation_id: string;
  root_cause_id: string | null;
  fix_type: string;
  title: string;
  description: string;
  approach: string;
  status: string;
  repository?: string | null;
  diff?: string | null;
  patch?: Record<string, unknown> | null;
  branch_name?: string | null;
  pr_number?: number | null;
  pr_url?: string | null;
  created_at: string | null;
}

export async function listFixes(token: string, investigationId: string): Promise<ProposedFix[]> {
  return request<ProposedFix[]>(`/remediation/fixes?investigation_id=${investigationId}`, { token });
}

export async function generateDraftPR(
  token: string,
  investigationId: string,
  fixId: string,
): Promise<{ status: string; branch_name: string; message: string }> {
  return request("/remediation/generate-pr", {
    method: "POST",
    body: JSON.stringify({ investigation_id: investigationId, fix_id: fixId }),
    token,
  });
}

export async function getPRConfig(token: string) {
  return request("/remediation/pr-config", { token });
}

// Approvals
export interface PendingApproval {
  fix_id: string;
  title: string;
  description: string;
  fix_type: string;
  investigation_id: string;
  incident_number: number | null;
  incident_title: string | null;
  auto_merge_eligible: boolean;
  created_at: string | null;
}

export async function listPendingApprovals(token: string): Promise<PendingApproval[]> {
  return request<PendingApproval[]>("/approvals/pending", { token });
}

export async function submitApproval(
  token: string,
  fixId: string,
  action: "approve" | "reject" | "request_changes",
  comment?: string,
): Promise<{ status: string; approval_id: string; message: string }> {
  return request("/approvals", {
    method: "POST",
    body: JSON.stringify({ fix_id: fixId, action, comment }),
    token,
  });
}

export async function getApprovalHistory(token: string, fixId: string) {
  return request(`/approvals/${fixId}/history`, { token });
}

// Service Health
export async function getServiceHealth(token: string) {
  return request("/services/health", { token });
}

export async function getDetectionRules(token: string) {
  return request("/detect/rules", { token });
}

export async function getDetectionStatus(token: string) {
  return request("/detect/status", { token });
}

// Timeline
export interface TimelineEvent {
  time: string;
  type: string;
  label: string;
  detail: string;
  icon: string;
  color: string;
}

export async function getInvestigationTimeline(token: string, investigationId: string): Promise<TimelineEvent[]> {
  return request<TimelineEvent[]>(`/investigations/${investigationId}/timeline`, { token });
}

// Historical Search
export async function searchSimilarIncidents(token: string, query: string, service?: string) {
  const params = new URLSearchParams({ q: query });
  if (service) params.set("service", service);
  return request(`/investigations/search-similar?${params.toString()}`, { token });
}

// Evaluation
export async function getBenchmarkDataset(token: string) {
  return request("/eval/benchmark", { token });
}

export async function evaluateGrounding(token: string, claim: string, evidence: any[], files?: string[]) {
  const params = new URLSearchParams({ root_cause_claim: claim });
  if (files) params.set("affected_files", JSON.stringify(files));
  return request(`/eval/grounding?${params.toString()}`, {
    method: "POST",
    body: JSON.stringify({ evidence }),
    token,
  });
}

// Metrics
export async function getMetrics(token: string) {
  return request("/metrics", { token });
}

// Audit Logs
export interface AuditLog {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  user_id: string;
  details: any;
  created_at: string | null;
}

export async function listAuditLogs(token: string, limit = 50): Promise<AuditLog[]> {
  return request<AuditLog[]>(`/audit-logs?limit=${limit}`, { token });
}

// Settings
export interface Settings {
  llm_provider: string;
  llm_model: string;
  auto_investigate: boolean;
  auto_merge: boolean;
  notification_email: string;
}

export async function getSettings(token: string): Promise<Settings> {
  return request<Settings>("/settings", { token });
}

export async function updateSettings(token: string, settings: Partial<Settings>) {
  return request("/settings", { method: "PUT", body: JSON.stringify(settings), token });
}

// Alert Rules
export interface AlertRule {
  id: string;
  name: string;
  type: string;
  threshold: string;
  severity: string;
  enabled: boolean;
  services: string[];
}

export async function listAlertRules(token: string): Promise<AlertRule[]> {
  return request<AlertRule[]>("/detect/rules", { token });
}

export async function toggleAlertRule(token: string, ruleId: string) {
  return request(`/detect/rules/${ruleId}/toggle`, { method: "PUT", token });
}

// Users
export interface User {
  id: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string | null;
  last_login: string | null;
}

export async function listUsers(token: string): Promise<User[]> {
  return request<User[]>("/auth/users", { token });
}

export async function updateUser(token: string, userId: string, data: Partial<User>) {
  return request(`/auth/users/${userId}`, { method: "PUT", body: JSON.stringify(data), token });
}

// System Health
export interface SystemHealth {
  status: string;
  checks: Record<string, { status: string; error?: string; latency_ms?: number; provider?: string; model?: string }>;
}

export async function getSystemHealth(token: string): Promise<SystemHealth> {
  return request<SystemHealth>("/system/health", { token });
}

// GitHub Commits, PRs, Branches for investigation
export async function getGithubStatus(token: string): Promise<{configured: boolean; installations: number; repositories: number; connected: boolean}> {
  return request("/github/status", { token });
}

export async function getRepoCommits(token: string, owner: string, repo: string, since?: string) {
  const params = since ? `?since=${since}` : "";
  return request(`/github/repos/${owner}/${repo}/commits${params}`, { token });
}

export async function getRepoPRs(token: string, owner: string, repo: string, state = "all") {
  return request(`/github/repos/${owner}/${repo}/pulls?state=${state}`, { token });
}

export async function getRepoBranches(token: string, owner: string, repo: string) {
  return request(`/github/repos/${owner}/${repo}/branches`, { token });
}

export async function getPRDiff(token: string, owner: string, repo: string, number: number) {
  return request(`/github/repos/${owner}/${repo}/pulls/${number}/diff`, { token });
}

export async function sendChatMessage(token: string, message: string, history: { role: string; content: string }[] = []) {
  return request<{ response: string }>("/chat", {
    token,
    method: "POST",
    body: JSON.stringify({ message, history }),
  });
}
