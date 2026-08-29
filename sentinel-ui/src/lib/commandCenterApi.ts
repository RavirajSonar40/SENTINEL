/**
 * Command Center API client for Sentinel Operations Command Center (Phase 15).
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getAuthHeaders(): HeadersInit {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export interface FreshnessMetadata {
  observed_at: string;
  source: string;
  freshness_seconds: number;
  is_stale: boolean;
}


export interface ErrorBudgetMetric {
  value: number | null;
  display: string;
  status: "healthy" | "degraded" | "exhausted" | "insufficient_data";
  slo_target_percent: number;
  actual_availability_percent?: number | null;
}

export interface TimeMetric {
  value_minutes?: number | null;
  display: string;
  sample_size: number;
}

export interface IncidentsSummary {
  active_total: number;
  critical_sev1: number;
  major_sev2: number;
  minor_sev3: number;
  low_sev4: number;
  investigating_count: number;
  awaiting_approval_count: number;
  resolved_last_24h: number;
  mttd: TimeMetric;
  mttr: TimeMetric;
  freshness: FreshnessMetadata;
}

export interface ServiceFleetSummary {
  total_services: number;
  healthy: number;
  degraded: number;
  down: number;
  unknown: number;
  tier1_total: number;
  tier1_healthy: number;
  tier1_degraded: number;
  tier1_down: number;
  freshness: FreshnessMetadata;
}

export interface DeploymentsSummary {
  total_last_24h: number;
  in_progress: number;
  successful: number;
  failed: number;
  rolled_back: number;
  failure_rate_percent: number;
  freshness: FreshnessMetadata;
}

export interface RemediationSummary {
  active_plans: number;
  pending_approvals: number;
  draft_prs_published: number;
  blocked_cyclic_plans: number;
  remediation_success_rate_percent?: number | null;
  remediation_success_display: string;
}

export interface ReliabilitySummary {
  system_status: string;
  error_budget: ErrorBudgetMetric;
  p95_latency_ms?: number | null;
  overall_compliance_score: number;
}

export interface RecentActivityItem {
  id: string;
  event_type: "incident_created" | "deployment_completed" | "root_cause_identified" | "pr_published" | "probe_failed" | string;
  title: string;
  description: string;
  severity?: string;
  service_name?: string;
  timestamp: string;
  link_url?: string;
}

export interface CommandCenterOverview {
  organization_id: string;
  organization_name: string;
  incidents_summary: IncidentsSummary;
  service_fleet: ServiceFleetSummary;
  deployments_summary: DeploymentsSummary;
  remediation_summary: RemediationSummary;
  reliability_summary: ReliabilitySummary;
  recent_activity: RecentActivityItem[];
  polled_at: string;
}

export interface OperationalServiceItem {
  id: string;
  name: string;
  slug: string;
  tier: string;
  environment: string;
  owner_team?: string | null;
  oncall_contact?: string | null;
  health_status: "healthy" | "degraded" | "down" | "unknown";
  health_reason: string;
  version?: string | null;
  commit_sha?: string | null;
  repository_full_name?: string | null;
  cpu_percent?: number | null;
  memory_percent?: number | null;
  error_rate_percent?: number | null;
  p95_latency_ms?: number | null;
  consecutive_probe_failures: number;
  latest_deployment_at?: string | null;
  latest_deployment_author?: string | null;
  open_incidents_count: number;
  upstream_dependencies_count: number;
  downstream_dependents_count: number;
  freshness: FreshnessMetadata;
}

export interface OperationalServicesResponse {
  items: OperationalServiceItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  freshness: FreshnessMetadata;
}

export interface ActiveCommandIncidentItem {
  id: string;
  title: string;
  severity: string;
  status: string;
  detection_source: string;
  service_name?: string | null;
  primary_defect_repo?: string | null;
  candidate_repos_count: number;
  blast_radius_service_count: number;
  created_at: string;
  duration_minutes: number;
  has_active_remediation_plan: boolean;
  remediation_plan_status?: string | null;
  pending_approval_id?: string | null;
}

export interface ActiveCommandResponse {
  active_incidents: ActiveCommandIncidentItem[];
  total_active: number;
  freshness: FreshnessMetadata;
}

export interface QuickProbeResponse {
  service_id: string;
  service_name: string;
  probe_status: "success" | "failure";
  http_status_code?: number | null;
  latency_ms: number;
  message: string;
  health_status_after: string;
  observed_at: string;
}

export const commandCenterApi = {
  async getOverview(): Promise<CommandCenterOverview> {
    const res = await fetch(`${API_BASE}/command-center/overview`, {
      headers: getAuthHeaders(),
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Failed to fetch command center overview: ${res.statusText}`);
    }
    return res.json();
  },

  async getOperationalServices(params?: {
    tier?: string;
    environment?: string;
    health?: string;
    page?: number;
    page_size?: number;
  }): Promise<OperationalServicesResponse> {
    const query = new URLSearchParams();
    if (params?.tier && params.tier !== "all") query.append("tier", params.tier);
    if (params?.environment && params.environment !== "all") query.append("environment", params.environment);
    if (params?.health && params.health !== "all") query.append("health", params.health);
    if (params?.page) query.append("page", params.page.toString());
    if (params?.page_size) query.append("page_size", params.page_size.toString());

    const res = await fetch(`${API_BASE}/command-center/services-operational?${query.toString()}`, {
      headers: getAuthHeaders(),
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Failed to fetch operational services: ${res.statusText}`);
    }
    return res.json();
  },

  async getActiveCommandFeed(): Promise<ActiveCommandResponse> {
    const res = await fetch(`${API_BASE}/command-center/active-command`, {
      headers: getAuthHeaders(),
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Failed to fetch active command feed: ${res.statusText}`);
    }
    return res.json();
  },

  async triggerQuickProbe(serviceId: string, environment: string = "production"): Promise<QuickProbeResponse> {
    const res = await fetch(`${API_BASE}/command-center/quick-probe`, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ service_id: serviceId, environment }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Quick probe failed");
    }
    return res.json();
  },
};
