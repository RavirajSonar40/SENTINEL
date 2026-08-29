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

export interface EvidenceItem {
  id: string;
  organization_id: string;
  incident_id?: string;
  investigation_id?: string;
  source_type: string;
  category_type: 'fact' | 'inference' | 'conclusion';
  evidence_family?: string;
  source_id?: string;
  service?: string;
  environment?: string;
  region?: string;
  repository?: string;
  commit_sha?: string;
  file_path?: string;
  line_start?: number;
  line_end?: number;
  title: string;
  content?: string;
  summary?: string;
  content_hash?: string;
  is_redacted: boolean;
  payload_size_bytes: number;
  trust_level: string;
  verification_status: string;
  submitted_by_user_id?: string;
  verified_by_user_id?: string;
  verified_at?: string;
  version: number;
  superseded_by_id?: string;
  observed_at?: string;
  collected_at: string;
}

export interface EvidenceListResponse {
  incident_id: string;
  total_count: number;
  facts_count: number;
  inferences_count: number;
  conclusions_count: number;
  distinct_families: string[];
  items: EvidenceItem[];
}

export interface HypothesisItem {
  id: string;
  organization_id: string;
  incident_id?: string;
  label: string;
  description: string;
  status: 'proposed' | 'supported' | 'contradicted' | 'disproven' | 'accepted' | 'rejected';
  confidence: 'high' | 'medium' | 'low' | 'insufficient';
  temporal_fit: boolean;
  temporal_fit_score: number;
  code_path_fit: boolean;
  code_path_fit_score: number;
  operational_fit: boolean;
  operational_fit_score: number;
  distinct_families_count: number;
  supporting_evidence_count: number;
  contradicting_evidence_count: number;
  missing_evidence_count: number;
  supporting_evidence_ids?: string[];
  contradicting_evidence_ids?: string[];
  missing_evidence_json?: string[];
  disproof_attempt_notes?: string;
  disproven_at?: string;
  human_triaged: boolean;
  human_triage_notes?: string;
  evaluation_notes?: string;
  created_at: string;
  evaluated_at?: string;
}

export interface RootCauseReport {
  id: string;
  organization_id: string;
  incident_id?: string;
  summary: string;
  affected_component?: string;
  causal_explanation: string;
  confidence: 'high' | 'medium' | 'low' | 'insufficient';
  supporting_evidence_ids?: string[];
  contradicting_evidence_ids?: string[];
  evidence_sources_count: number;
  distinct_families_count: number;
  disproof_summary?: string;
  abstained: boolean;
  abstention_reason?: string;
  missing_evidence_json?: string[];
  evaluation_version: number;
  snapshot_hash?: string;
  is_current: boolean;
  human_overridden: boolean;
  human_override_notes?: string;
  identified_at: string;
}

export async function getIncidentEvidence(
  incidentId: string,
  sourceType?: string,
  categoryType?: string
): Promise<EvidenceListResponse> {
  const params = new URLSearchParams();
  if (sourceType) params.set('source_type', sourceType);
  if (categoryType) params.set('category_type', categoryType);
  const qs = params.toString();
  return request<EvidenceListResponse>(`/incidents/${incidentId}/evidence${qs ? `?${qs}` : ''}`);
}

export async function submitManualEvidence(
  incidentId: string,
  payload: {
    title: string;
    source_type?: string;
    category_type?: string;
    content?: string;
    summary?: string;
    service?: string;
  }
): Promise<EvidenceItem> {
  return request<EvidenceItem>(`/incidents/${incidentId}/evidence`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function verifyEvidence(
  incidentId: string,
  evidenceId: string,
  status: 'verified' | 'rejected',
  notes?: string
): Promise<EvidenceItem> {
  return request<EvidenceItem>(`/incidents/${incidentId}/evidence/${evidenceId}/verify`, {
    method: 'POST',
    body: JSON.stringify({ status, notes }),
  });
}

export async function submitEvidenceCorrection(
  incidentId: string,
  payload: {
    supersedes_evidence_id: string;
    title: string;
    content?: string;
    summary?: string;
    correction_reason: string;
  }
): Promise<EvidenceItem> {
  return request<EvidenceItem>(`/incidents/${incidentId}/evidence/correction`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getIncidentHypotheses(incidentId: string): Promise<HypothesisItem[]> {
  return request<HypothesisItem[]>(`/incidents/${incidentId}/hypotheses`);
}

export async function evaluateHypotheses(incidentId: string): Promise<any> {
  return request<any>(`/incidents/${incidentId}/hypotheses/evaluate`, {
    method: 'POST',
  });
}

export async function triageHypothesis(
  incidentId: string,
  hypothesisId: string,
  status: string,
  triageNotes: string
): Promise<HypothesisItem> {
  return request<HypothesisItem>(`/incidents/${incidentId}/hypotheses/${hypothesisId}/triage`, {
    method: 'POST',
    body: JSON.stringify({ status, triage_notes: triageNotes }),
  });
}

export async function getIncidentRootCause(incidentId: string): Promise<RootCauseReport> {
  return request<RootCauseReport>(`/incidents/${incidentId}/root-cause`);
}

export async function overrideRootCause(
  incidentId: string,
  payload: {
    summary: string;
    affected_component?: string;
    causal_explanation: string;
    override_notes: string;
  }
): Promise<RootCauseReport> {
  return request<RootCauseReport>(`/incidents/${incidentId}/root-cause/override`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
