/**
 * Phase 12: Isolated Validation & Replay API Client
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getAuthHeaders(): HeadersInit {
  const token = typeof window !== 'undefined' ? localStorage.getItem('sentinel_token') : null;
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export interface ValidationCheckRun {
  id: string;
  check_type: string;
  name: string;
  command: string[];
  status: 'passed' | 'failed' | 'timeout' | 'skipped' | 'error' | 'pending' | 'running';
  exit_code?: number | null;
  stdout?: string | null;
  stderr?: string | null;
  duration_ms: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ValidationReport {
  validation_id: string;
  fix_id: string;
  organization_id: string;
  repository_id?: string | null;
  base_commit_sha: string;
  verified_base_sha?: string | null;
  workspace_id: string;
  status: string;
  compilation_status: string;
  tests_status: string;
  original_failure_reproduced: string;
  failure_absent_after_patch: string;
  scenario_replay_status: string;
  production_outcome: string;
  overall_status: string;
  total_checks: number;
  passed_checks: number;
  failed_checks: number;
  started_at?: string | null;
  completed_at?: string | null;
  summary_report?: {
    matrix?: {
      compilation: string;
      tests: string;
      original_failure_reproduced: string;
      failure_absent_after_patch: string;
      scenario_replay: string;
      production_outcome: string;
    };
    verified_base_sha?: string;
    workspace_id?: string;
  } | null;
  check_runs: ValidationCheckRun[];
}

export async function validateFixIsolated(fixId: string): Promise<ValidationReport> {
  const res = await fetch(`${API_BASE}/remediation/fixes/${fixId}/validate`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to run isolated validation' }));
    throw new Error(err.detail || 'Validation failed');
  }
  return res.json();
}

export async function getValidationReport(fixId: string): Promise<ValidationReport> {
  const res = await fetch(`${API_BASE}/remediation/fixes/${fixId}/validation-report`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'No validation report found' }));
    throw new Error(err.detail || 'Report not found');
  }
  return res.json();
}

export async function listValidationRuns(fixId: string): Promise<ValidationReport[]> {
  const res = await fetch(`${API_BASE}/remediation/fixes/${fixId}/validation-runs`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to list validation runs' }));
    throw new Error(err.detail || 'Failed to list runs');
  }
  return res.json();
}

export async function replayScenario(fixId: string, timeoutSec: number = 30): Promise<any> {
  const res = await fetch(`${API_BASE}/remediation/fixes/${fixId}/replay-scenario`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ timeout_sec: timeoutSec }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Scenario replay failed' }));
    throw new Error(err.detail || 'Replay failed');
  }
  return res.json();
}
