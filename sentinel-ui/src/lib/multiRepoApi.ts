/**
 * Phase 14: Multi-Repository Remediation TypeScript API Client.
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

export interface CandidateRepository {
  repository_id: string;
  name: string;
  full_name: string;
  role: "primary_defect" | "downstream_affected" | "configuration" | "evidence_only" | string;
  score: number;
  reasons: string[];
  requires_code_change: boolean;
  base_commit_sha?: string;
  service_id?: string;
  service_name?: string;
}

export interface MultiRepoResolveResponse {
  incident_id: string;
  candidates: CandidateRepository[];
  total_candidates: number;
}

export interface ChildInvestigation {
  id: string;
  parent_investigation_id?: string;
  repository_id?: string;
  repository_name?: string;
  repository_role?: string;
  base_commit_sha?: string;
  status: string;
  workflow_type: string;
  progress_percent: number;
  created_at?: string;
}

export interface MultiRepoFanOutResponse {
  parent_investigation_id: string;
  child_investigations: ChildInvestigation[];
  message: string;
}

export interface RemediationPlanItem {
  id: string;
  repository_id: string;
  repository_name?: string;
  repository_role: string;
  investigation_id?: string;
  fix_id?: string;
  execution_order: number;
  requires_code_change: boolean;
  validation_status: string;
  approval_status: string;
  patch_version?: number;
  snapshot_hash?: string;
  base_commit_sha?: string;
  pr_status: "pending" | "created" | "failed" | "skipped_evidence_only" | string;
  pr_url?: string;
  pr_number?: number;
  commit_sha?: string;
  error_message?: string;
}

export interface RemediationPlan {
  id: string;
  organization_id: string;
  incident_id: string;
  parent_investigation_id?: string;
  status: string;
  title: string;
  summary: string;
  dependency_order: string[];
  cycle_detected: boolean;
  cycle_details?: {
    cyclic_repository_ids?: string[];
    message?: string;
    recommended_resolution?: string;
  };
  cross_repo_rollback_plan?: string;
  items: RemediationPlanItem[];
  created_at: string;
  updated_at?: string;
}

export interface MultiRepoPRItemResult {
  repository_id: string;
  repository_name: string;
  pr_status: string;
  pr_url?: string;
  pr_number?: number;
  commit_sha?: string;
  error_message?: string;
}

export interface MultiRepoPRPublishResponse {
  plan_id: string;
  overall_status: "completed" | "partially_failed" | "failed" | string;
  items: MultiRepoPRItemResult[];
  rollback_instructions?: string;
  message: string;
}

export const multiRepoApi = {
  async resolveCandidates(incidentId: string, token: string, threshold = 0.50): Promise<MultiRepoResolveResponse> {
    const res = await fetch(`${API_BASE}/multi-repo/resolve-candidates`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ incident_id: incidentId, threshold }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to resolve candidate repositories");
    }
    return res.json();
  },

  async fanOutInvestigations(
    incidentId: string,
    token: string,
    candidateRepoIds?: string[]
  ): Promise<MultiRepoFanOutResponse> {
    const res = await fetch(`${API_BASE}/multi-repo/incidents/${incidentId}/fan-out`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ candidate_repository_ids: candidateRepoIds }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to fan out child investigations");
    }
    return res.json();
  },

  async getIncidentInvestigations(incidentId: string, token: string) {
    const res = await fetch(`${API_BASE}/multi-repo/incidents/${incidentId}/investigations`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to fetch multi-repo investigations");
    }
    return res.json();
  },

  async createRemediationPlan(
    incidentId: string,
    token: string,
    overrideDependencyOrder?: string[]
  ): Promise<RemediationPlan> {
    const res = await fetch(`${API_BASE}/multi-repo/incidents/${incidentId}/remediation-plans`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        incident_id: incidentId,
        override_dependency_order: overrideDependencyOrder,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to create remediation plan");
    }
    return res.json();
  },

  async getLatestRemediationPlan(incidentId: string, token: string): Promise<RemediationPlan | null> {
    const res = await fetch(`${API_BASE}/multi-repo/incidents/${incidentId}/remediation-plans`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to fetch remediation plan");
    }
    return res.json();
  },

  async publishDraftPRs(planId: string, token: string): Promise<MultiRepoPRPublishResponse> {
    const res = await fetch(`${API_BASE}/multi-repo/remediation-plans/${planId}/generate-prs`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ plan_id: planId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to publish multi-repo Draft PRs");
    }
    return res.json();
  },
};
