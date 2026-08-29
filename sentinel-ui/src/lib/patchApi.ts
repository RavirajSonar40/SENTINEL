/**
 * Phase 11: Patch Studio & Test Generation API Client
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getAuthHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export interface PatchChange {
  file: string;
  action: 'modify' | 'create' | 'delete' | 'rename';
  description?: string;
  old_code?: string;
  new_code?: string;
  line_start?: number;
  line_end?: number;
}

export interface TestToAdd {
  file: string;
  test_type: 'unit' | 'regression' | 'integration';
  framework: string;
  test_name: string;
  test_code: string;
  target_symbol?: string;
}

export interface PatchSafetyResult {
  is_safe: boolean;
  rejection_reason?: string;
  scope_valid: boolean;
  replacements_valid: boolean;
  secrets_clean: boolean;
  ast_valid: boolean;
  bloat_valid: boolean;
  snapshot_hash?: string;
  details?: Record<string, any>;
}

export interface GeneratedTest {
  id: string;
  file_path: string;
  test_type: string;
  framework: string;
  test_name: string;
  test_code: string;
  target_symbol?: string;
  pre_patch_result?: string;
  post_patch_result?: string;
  created_at?: string;
}

export interface PatchVersion {
  id: string;
  version_number: number;
  editor_user_id?: string;
  patch_data: Record<string, any>;
  diff_content?: string;
  previous_snapshot_hash?: string;
  new_snapshot_hash: string;
  revalidation_status: string;
  revalidation_details?: Record<string, any>;
  created_at?: string;
}

export interface ProposedFixDetail {
  id: string;
  organization_id?: string;
  incident_id?: string;
  work_item_id?: string;
  repository_id?: string;
  repository?: string;
  base_commit_sha?: string;
  target_branch?: string;
  title?: string;
  description?: string;
  status?: string;
  diff?: string;
  patch_json?: {
    changes: PatchChange[];
  };
  scope_files?: string[];
  tests_to_add?: TestToAdd[];
  tests_to_run?: string[][];
  rollback_plan?: string;
  regression_test_status?: string;
  is_rejected?: boolean;
  rejection_reason?: string;
  snapshot_hash?: string;
  version: number;
  generated_tests?: GeneratedTest[];
  versions?: PatchVersion[];
  created_at?: string;
  updated_at?: string;
}

export interface PatchGenerateRequest {
  incident_id?: string;
  work_item_id?: string;
  repository_id?: string;
  scope_files?: string[];
  instructions?: string;
  base_commit_sha?: string;
  target_branch?: string;
}

export interface PatchEditRequest {
  changes: PatchChange[];
  tests_to_add?: TestToAdd[];
  tests_to_run?: string[][];
  rollback_plan?: string;
}

export const patchApi = {
  /** Generate repository-bound patch, tests, and two-phase regression verification */
  async generatePatch(req: PatchGenerateRequest): Promise<ProposedFixDetail> {
    const res = await fetch(`${API_BASE}/remediation/patches/generate`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to generate patch');
    }
    return res.json();
  },

  /** Manual patch edit: increments version, invalidates previous safety checks, and revalidates */
  async editPatch(fixId: string, req: PatchEditRequest): Promise<ProposedFixDetail> {
    const res = await fetch(`${API_BASE}/remediation/patches/${fixId}/edit`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to edit and revalidate patch');
    }
    return res.json();
  },

  /** Dry-run pre-flight safety check for a patch payload */
  async validatePatch(req: {
    changes: PatchChange[];
    scope_files?: string[];
    repository_id?: string;
    base_commit_sha?: string;
  }): Promise<PatchSafetyResult> {
    const res = await fetch(`${API_BASE}/remediation/patches/validate`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to validate patch safety');
    }
    return res.json();
  },

  /** Get full structured patch details, diff, tests, and version history for a fix */
  async getPatchDetail(fixId: string): Promise<ProposedFixDetail> {
    const res = await fetch(`${API_BASE}/remediation/fixes/${fixId}/patch`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to get patch details');
    }
    return res.json();
  },

  /** List generated tests for a proposed fix */
  async getFixTests(fixId: string): Promise<GeneratedTest[]> {
    const res = await fetch(`${API_BASE}/remediation/fixes/${fixId}/tests`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to get fix tests');
    }
    return res.json();
  },

  /** Get complete version history and audit log for a fix */
  async getFixHistory(fixId: string): Promise<PatchVersion[]> {
    const res = await fetch(`${API_BASE}/remediation/fixes/${fixId}/history`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to get fix history');
    }
    return res.json();
  },
};
