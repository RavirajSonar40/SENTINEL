/**
 * Phase 17: Security Incident Mode, Evidence Manifests, Dual Sign-Off & Audit Chaining API Client
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface SecurityCaseItem {
  id: string;
  organization_id: string;
  incident_id: string | null;
  work_item_id: string | null;
  case_number: string;
  title: string;
  description: string | null;
  category: string;
  severity: string;
  status: string;
  containment_status: string;
  scope_summary_json: Record<string, any> | null;
  security_lead_id: string | null;
  security_lead_name: string | null;
  created_by_user_id: string | null;
  created_by_name: string | null;
  resolution_summary: string | null;
  contained_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface SecurityEvidenceSnapshot {
  id: string;
  organization_id: string;
  security_case_id: string;
  manifest_hash: string;
  manifest_json: Record<string, any>;
  completeness_status: string;
  captured_by_user_id: string | null;
  sealed_at: string;
}

export interface SecurityContainmentAction {
  id: string;
  organization_id: string;
  security_case_id: string;
  idempotency_key: string | null;
  action_type: string;
  target_type: string;
  target_id: string;
  title: string;
  description: string | null;
  parameters_json: Record<string, any> | null;
  status: string;
  is_automated_blocked: boolean;
  proposed_by_user_id: string | null;
  proposed_by_name: string | null;
  approver_1_user_id: string | null;
  approver_1_name: string | null;
  approver_1_at: string | null;
  approver_2_user_id: string | null;
  approver_2_name: string | null;
  approver_2_at: string | null;
  approval_expires_at: string | null;
  execution_output: string | null;
  rollback_status: string;
  executed_at: string | null;
  created_at: string;
}

export interface SecurityForensicAuditEntry {
  id: string;
  organization_id: string;
  security_case_id: string;
  sequence_number: number;
  event_type: string;
  actor_id: string | null;
  actor_name: string | null;
  payload_json: Record<string, any> | null;
  previous_hash: string;
  current_hash: string;
  timestamp: string;
}

export interface SecurityAuditChainVerification {
  is_valid: boolean;
  total_entries: number;
  entries: SecurityForensicAuditEntry[];
  broken_link_sequence: number | null;
  message: string;
}

function getAuthHeaders(): HeadersInit {
  const token = typeof window !== "undefined" ? localStorage.getItem("sentinel_token") : null;
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function fetchSecurityCases(
  category?: string,
  severity?: string,
  status?: string,
): Promise<SecurityCaseItem[]> {
  const params = new URLSearchParams();
  if (category) params.append("category", category);
  if (severity) params.append("severity", severity);
  if (status) params.append("status", status);

  const res = await fetch(`${API_BASE}/security/cases?${params.toString()}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch security cases: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchSecurityCase(caseId: string): Promise<SecurityCaseItem> {
  const res = await fetch(`${API_BASE}/security/cases/${caseId}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch security case: ${res.statusText}`);
  }
  return res.json();
}

export async function createSecurityCase(payload: {
  title: string;
  description?: string;
  category?: string;
  severity?: string;
  scope_summary_json?: Record<string, any>;
}): Promise<SecurityCaseItem> {
  const res = await fetch(`${API_BASE}/security/cases`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to create security case");
  }
  return res.json();
}

export async function fetchSecurityEvidence(caseId: string): Promise<SecurityEvidenceSnapshot> {
  const res = await fetch(`${API_BASE}/security/cases/${caseId}/evidence`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch evidence snapshot: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchAuditChain(caseId: string): Promise<SecurityAuditChainVerification> {
  const res = await fetch(`${API_BASE}/security/cases/${caseId}/audit-chain`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch audit chain: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchContainmentActions(caseId: string): Promise<SecurityContainmentAction[]> {
  const res = await fetch(`${API_BASE}/security/cases/${caseId}/containment`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch containment actions: ${res.statusText}`);
  }
  return res.json();
}

export async function proposeContainmentAction(
  caseId: string,
  payload: {
    action_type: string;
    target_type: string;
    target_id: string;
    title: string;
    description?: string;
    parameters_json?: Record<string, any>;
    idempotency_key?: string;
  },
): Promise<SecurityContainmentAction> {
  const res = await fetch(`${API_BASE}/security/cases/${caseId}/containment`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to propose containment action");
  }
  return res.json();
}

export async function approveContainmentAction(
  actionId: string,
  comment?: string,
): Promise<SecurityContainmentAction> {
  const res = await fetch(`${API_BASE}/security/containment/${actionId}/approve`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ comment }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to approve containment action");
  }
  return res.json();
}

export async function executeContainmentAction(
  actionId: string,
  dryRun: boolean = false,
): Promise<SecurityContainmentAction> {
  const res = await fetch(`${API_BASE}/security/containment/${actionId}/execute`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ dry_run: dryRun }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to execute containment action");
  }
  return res.json();
}

export async function resolveSecurityCase(
  caseId: string,
  resolutionSummary: string,
): Promise<SecurityCaseItem> {
  const res = await fetch(`${API_BASE}/security/cases/${caseId}/resolve`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ resolution_summary: resolutionSummary }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to resolve security case");
  }
  return res.json();
}
