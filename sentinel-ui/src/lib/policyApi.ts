/**
 * Phase 13: Policy Gateway & Approval Lifecycle API Client
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getAuthHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('sentinel_token') : null;
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export interface PolicyRule {
  id: string;
  organization_id?: string | null;
  name: string;
  description?: string | null;
  action_type: string;
  decision: string;
  conditions_json?: Record<string, any> | null;
  required_approvals_count: number;
  required_roles_json?: string[] | null;
  priority: number;
  is_active: boolean;
  is_mandatory: boolean;
  created_at: string;
  updated_at?: string | null;
}

export interface PolicyStepCheck {
  step_number: number;
  name: string;
  status: 'passed' | 'failed' | 'warning' | 'required_action';
  message: string;
  details?: Record<string, any> | null;
}

export interface PolicyEvaluationResult {
  action_type: string;
  decision: 'allow' | 'block' | 'require_human' | 'multi_approval' | 'security_approval';
  allowed: boolean;
  requires_approval: boolean;
  required_approvals_count: number;
  required_roles: string[];
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  steps: PolicyStepCheck[];
  matched_rule?: string | null;
  reasons: string[];
  fix_id?: string | null;
  patch_version?: number | null;
  snapshot_hash?: string | null;
  base_commit_sha?: string | null;
  evaluated_at?: string;
}

export interface ComplianceChecklist {
  scope_contained: boolean;
  ast_syntax_valid: boolean;
  secrets_clean: boolean;
  diff_bloat_acceptable: boolean;
  base_sha_verified: boolean;
  pre_patch_reproduced: boolean;
  post_patch_regressions_passed: boolean;
  details?: Record<string, any> | null;
}

export interface ApprovalDecision {
  id: string;
  approval_id: string;
  approver_id: string;
  approver_name?: string | null;
  approver_email?: string | null;
  role?: string | null;
  decision: 'approved' | 'rejected' | 'changes_requested';
  notes?: string | null;
  created_at: string;
}

export interface ApprovalRequest {
  id: string;
  organization_id: string;
  incident_id?: string | null;
  fix_id?: string | null;
  work_item_id?: string | null;
  action_type: string;
  status: 'pending' | 'approved' | 'rejected' | 'changes_requested' | 'invalidated_stale' | 'cancelled' | 'expired';
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  patch_version: number;
  snapshot_hash?: string | null;
  base_commit_sha?: string | null;
  validation_run_id?: string | null;
  required_approvals: number;
  approvals_received: number;
  compliance_checklist?: ComplianceChecklist | null;
  decisions: ApprovalDecision[];
  notes?: string | null;
  requested_at: string;
  decided_at?: string | null;
  expires_at?: string | null;
}

export async function fetchPolicies(): Promise<PolicyRule[]> {
  const res = await fetch(`${API_BASE}/policies`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch policy rules (${res.status})`);
  }
  return res.json();
}

export async function evaluatePolicy(payload: {
  action_type: string;
  fix_id?: string;
  work_item_id?: string;
  incident_id?: string;
  target_branch?: string;
  context?: Record<string, any>;
}): Promise<PolicyEvaluationResult> {
  const res = await fetch(`${API_BASE}/policies/evaluate`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Evaluation failed' }));
    throw new Error(err.detail || `Policy evaluation failed (${res.status})`);
  }
  return res.json();
}

export async function fetchApprovals(statusFilter?: string, fixId?: string): Promise<ApprovalRequest[]> {
  const params = new URLSearchParams();
  if (statusFilter) params.append('status_filter', statusFilter);
  if (fixId) params.append('fix_id', fixId);

  const res = await fetch(`${API_BASE}/approvals?${params.toString()}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch approvals (${res.status})`);
  }
  return res.json();
}

export async function fetchApprovalDetail(approvalId: string): Promise<ApprovalRequest> {
  const res = await fetch(`${API_BASE}/approvals/${approvalId}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch approval detail (${res.status})`);
  }
  return res.json();
}

export async function requestApprovalForFix(fixId: string, notes?: string): Promise<ApprovalRequest> {
  const params = new URLSearchParams();
  if (notes) params.append('notes', notes);

  const res = await fetch(`${API_BASE}/approvals/request/${fixId}?${params.toString()}`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(err.detail || `Failed to request approval (${res.status})`);
  }
  return res.json();
}

export async function submitApprovalDecision(
  approvalId: string,
  decision: 'approved' | 'rejected' | 'changes_requested',
  notes?: string
): Promise<ApprovalRequest> {
  const res = await fetch(`${API_BASE}/approvals/${approvalId}/decision`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ decision, notes }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Decision failed' }));
    throw new Error(err.detail || `Failed to submit approval decision (${res.status})`);
  }
  return res.json();
}
