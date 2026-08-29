/**
 * Investigation Workflow API Client (Phase 8).
 * 
 * Supports:
 * - Workflow execution controls (start, pause, cancel).
 * - Secure single-use SSE stream ticket handshakes.
 * - Live EventSource progress subscription.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface InvestigationTask {
  id: string;
  investigation_id: string;
  step_name: string;
  task_type: string;
  description?: string;
  status: "pending" | "running" | "completed" | "failed" | "retrying" | "skipped";
  order: number;
  tool_name?: string;
  tool_input?: any;
  tool_output?: any;
  result_json?: any;
  duration_ms: number;
  error_message?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface InvestigationDetail {
  id: string;
  organization_id: string;
  incident_id?: string;
  work_item_id?: string;
  workflow_type: string;
  status: "created" | "queued" | "running" | "paused" | "waiting_for_input" | "abstained" | "completed" | "failed" | "cancelled" | "blocked";
  current_step?: string;
  current_step_index: number;
  total_steps: number;
  progress_percent: number;
  root_cause_found: boolean;
  abstained: boolean;
  abstention_reason?: string;
  security_case_id?: string;
  confidence?: string;
  llm_model?: string;
  plan_json?: any;
  logs_json?: Array<{
    step_name: string;
    status: string;
    duration_ms: number;
    timestamp: string;
    summary: string;
  }>;
  evidence_snapshot_id?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  tasks: InvestigationTask[];
}

export interface WorkflowStreamEvent {
  event_id: number;
  timestamp: string;
  event_type: "step_started" | "log" | "step_completed" | "workflow_finished" | "workflow_failed" | "abstained" | "paused" | "heartbeat";
  step_name?: string;
  message: string;
  progress_percent: number;
  data: any;
}

export async function fetchInvestigation(investigationId: string, token: string): Promise<InvestigationDetail> {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch investigation: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchInvestigationTasks(investigationId: string, token: string): Promise<InvestigationTask[]> {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}/tasks`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch investigation tasks: ${res.statusText}`);
  }
  return res.json();
}

export async function startInvestigation(
  investigationId: string,
  token: string,
  workflowType?: string,
  lookbackMinutes?: number
): Promise<InvestigationDetail> {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      workflow_type: workflowType,
      lookback_window_minutes: lookbackMinutes || 120,
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to start investigation: ${res.statusText}`);
  }
  return res.json();
}

export async function pauseInvestigation(investigationId: string, token: string): Promise<InvestigationDetail> {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}/pause`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Failed to pause investigation: ${res.statusText}`);
  }
  return res.json();
}

export async function cancelInvestigation(investigationId: string, token: string): Promise<InvestigationDetail> {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}/cancel`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Failed to cancel investigation: ${res.statusText}`);
  }
  return res.json();
}

export async function getStreamTicket(investigationId: string, token: string): Promise<string> {
  const res = await fetch(`${API_BASE}/investigations/${investigationId}/stream-ticket`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Failed to obtain stream ticket: ${res.statusText}`);
  }
  const data = await res.json();
  return data.stream_ticket;
}

export function subscribeInvestigationStream(
  investigationId: string,
  streamTicket: string,
  onEvent: (event: WorkflowStreamEvent) => void,
  onError?: (err: any) => void
): () => void {
  const url = `${API_BASE}/investigations/${investigationId}/stream?ticket=${encodeURIComponent(streamTicket)}`;
  const es = new EventSource(url);

  es.onmessage = (e) => {
    try {
      const data: WorkflowStreamEvent = JSON.parse(e.data);
      onEvent(data);
    } catch (err) {
      console.error("Error parsing stream event", err);
    }
  };

  es.onerror = (err) => {
    if (onError) onError(err);
    es.close();
  };

  return () => {
    es.close();
  };
}
