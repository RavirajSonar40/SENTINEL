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
    throw new Error(error.detail || `Request failed with status ${res.status}`);
  }
  if (res.status === 204) {
    return null as unknown as T;
  }
  return res.json();
}

// ============================================================================
// TYPES
// ============================================================================

export type MembershipRole = "owner" | "admin" | "member" | "viewer";
export type ServiceRepositoryRole = "application" | "configuration" | "infrastructure" | "dependency";
export type ServiceDependencyType = "synchronous" | "asynchronous" | "database" | "cache" | "external";
export type ServiceCriticality = "hard" | "soft";
export type OwnershipType = "primary_owner" | "secondary_owner" | "oncall";
export type ServiceHealth = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at?: string;
}

export interface OrganizationMembership {
  id: string;
  user_id: string;
  organization_id: string;
  role: MembershipRole;
  username?: string;
  email?: string;
  created_at?: string;
}

export interface Team {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description?: string;
  member_count?: number;
  created_at?: string;
}

export interface Region {
  id: string;
  organization_id: string;
  name: string;
  code: string;
  cloud_provider: string;
  created_at?: string;
}

export interface Environment {
  id: string;
  organization_id: string;
  name: string;
  env_type: string;
  region?: string;
  created_at?: string;
}

export interface Repository {
  id: string;
  organization_id: string;
  name: string;
  full_name: string;
  default_branch: string;
  language?: string;
  github_url?: string;
  sync_status?: string;
  is_active: boolean;
  created_at?: string;
}

export interface ServiceRepository {
  id: string;
  organization_id: string;
  service_id: string;
  repository_id: string;
  role: ServiceRepositoryRole;
  is_primary: boolean;
  confidence: number;
  source: string;
  selection_reason: string;
  repository_name?: string;
  repository_full_name?: string;
  created_at?: string;
}

export interface ServiceDependency {
  id: string;
  organization_id: string;
  service_id: string;
  depends_on_service_id: string;
  dependent_service_name?: string;
  upstream_service_name?: string;
  dependency_type: ServiceDependencyType;
  criticality: ServiceCriticality;
  description?: string;
  created_at?: string;
}

export interface ServiceOwnership {
  id: string;
  organization_id: string;
  service_id: string;
  team_id?: string;
  user_id?: string;
  team_name?: string;
  username?: string;
  ownership_type: OwnershipType;
  escalation_policy?: string;
  created_at?: string;
}

export interface ServiceDeploymentConfig {
  id: string;
  organization_id: string;
  service_id: string;
  environment_id: string;
  region_id?: string;
  environment_name?: string;
  region_code?: string;
  health_check_url?: string;
  health_check_interval_seconds: number;
  observability_identifiers?: Record<string, unknown>;
  current_commit_sha?: string;
  current_version?: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface Service {
  id: string;
  organization_id: string;
  name: string;
  slug?: string;
  description?: string;
  tier: string;
  health: ServiceHealth;
  primary_repository?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ServiceDetail extends Service {
  repositories: ServiceRepository[];
  upstream_dependencies: ServiceDependency[];
  downstream_dependents: ServiceDependency[];
  ownerships: ServiceOwnership[];
  deployments: ServiceDeploymentConfig[];
}

export interface ServiceGraphNode {
  id: string;
  name: string;
  tier: string;
  health: string;
}

export interface ServiceGraphEdge {
  id: string;
  source: string;
  target: string;
  dependency_type: string;
  criticality: string;
}

export interface ServiceGraphResponse {
  service_id: string;
  service_name: string;
  upstream_dependencies: Array<{
    service_id: string;
    name: string;
    tier: string;
    criticality: string;
    dependency_type: string;
    depth: number;
  }>;
  downstream_dependents: Array<{
    service_id: string;
    name: string;
    tier: string;
    criticality: string;
    dependency_type: string;
    depth: number;
  }>;
  nodes: ServiceGraphNode[];
  edges: ServiceGraphEdge[];
}

// ============================================================================
// API CLIENT FUNCTIONS
// ============================================================================

// Organizations
export async function getActiveOrg(token: string): Promise<Organization> {
  return request<Organization>("/organizations/me", { token });
}

export async function createOrganization(token: string, name: string, slug?: string): Promise<Organization> {
  return request<Organization>("/organizations", {
    method: "POST",
    token,
    body: JSON.stringify({ name, slug }),
  });
}

export async function activateOrganization(
  token: string,
  organizationId: string
): Promise<{ organization_id: string; organization_name: string; organization_slug: string; role: MembershipRole }> {
  return request(`/organizations/${organizationId}/activate`, {
    method: "POST",
    token,
  });
}

export async function listMemberships(token: string): Promise<OrganizationMembership[]> {
  return request<OrganizationMembership[]>("/organizations/memberships", { token });
}

export async function addMembership(
  token: string,
  data: { user_id?: string; email?: string; username?: string; role: MembershipRole }
): Promise<OrganizationMembership> {
  return request<OrganizationMembership>("/organizations/memberships", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

export async function updateMembershipRole(token: string, membershipId: string, role: MembershipRole): Promise<OrganizationMembership> {
  return request<OrganizationMembership>(`/organizations/memberships/${membershipId}/role`, {
    method: "PATCH",
    token,
    body: JSON.stringify({ role }),
  });
}

export async function removeMembership(token: string, membershipId: string): Promise<void> {
  return request<void>(`/organizations/memberships/${membershipId}`, {
    method: "DELETE",
    token,
  });
}

// Services
export async function listServices(
  token: string,
  params?: { search?: string; tier?: string; limit?: number; offset?: number }
): Promise<Service[]> {
  const q = new URLSearchParams();
  if (params?.search) q.set("search", params.search);
  if (params?.tier) q.set("tier", params.tier);
  if (params?.limit) q.set("limit", params.limit.toString());
  if (params?.offset) q.set("offset", params.offset.toString());
  return request<Service[]>(`/services?${q.toString()}`, { token });
}

export async function getServiceDetail(token: string, serviceId: string): Promise<ServiceDetail> {
  return request<ServiceDetail>(`/services/${serviceId}`, { token });
}

export async function createService(
  token: string,
  data: { name: string; tier?: string; description?: string; slug?: string }
): Promise<Service> {
  return request<Service>("/services", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

export async function deleteService(token: string, serviceId: string): Promise<void> {
  return request<void>(`/services/${serviceId}`, {
    method: "DELETE",
    token,
  });
}

// Repositories
export async function listRepositories(
  token: string,
  params?: { search?: string; limit?: number; offset?: number }
): Promise<Repository[]> {
  const q = new URLSearchParams();
  if (params?.search) q.set("search", params.search);
  if (params?.limit) q.set("limit", params.limit.toString());
  if (params?.offset) q.set("offset", params.offset.toString());
  return request<Repository[]>(`/repositories?${q.toString()}`, { token });
}

export async function createRepository(
  token: string,
  data: { name: string; full_name: string; default_branch?: string; language?: string; github_url?: string }
): Promise<Repository> {
  return request<Repository>("/repositories", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

// Service-Repository Mappings
export async function listServiceRepositories(
  token: string,
  params?: { service_id?: string; repository_id?: string }
): Promise<ServiceRepository[]> {
  const q = new URLSearchParams();
  if (params?.service_id) q.set("service_id", params.service_id);
  if (params?.repository_id) q.set("repository_id", params.repository_id);
  return request<ServiceRepository[]>(`/service-repositories?${q.toString()}`, { token });
}

export async function createServiceRepository(
  token: string,
  data: {
    service_id: string;
    repository_id: string;
    role: ServiceRepositoryRole;
    is_primary?: boolean;
    confidence?: number;
    selection_reason: string;
  }
): Promise<ServiceRepository> {
  return request<ServiceRepository>("/service-repositories", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

export async function deleteServiceRepository(token: string, mappingId: string): Promise<void> {
  return request<void>(`/service-repositories/${mappingId}`, {
    method: "DELETE",
    token,
  });
}

// Dependencies & Graph
export async function listDependencies(token: string, serviceId?: string): Promise<ServiceDependency[]> {
  const path = serviceId ? `/dependencies?service_id=${serviceId}` : "/dependencies";
  return request<ServiceDependency[]>(path, { token });
}

export async function createDependency(
  token: string,
  data: {
    dependent_service_id: string;
    upstream_service_id: string;
    dependency_type?: ServiceDependencyType;
    criticality?: ServiceCriticality;
    description?: string;
  }
): Promise<ServiceDependency> {
  return request<ServiceDependency>("/dependencies", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

export async function deleteDependency(token: string, dependencyId: string): Promise<void> {
  return request<void>(`/dependencies/${dependencyId}`, {
    method: "DELETE",
    token,
  });
}

export async function getServiceGraph(token: string, serviceId: string, maxDepth: number = 5): Promise<ServiceGraphResponse> {
  return request<ServiceGraphResponse>(`/services/${serviceId}/graph?max_depth=${maxDepth}`, { token });
}

// Ownership
export async function listOwnerships(token: string, serviceId?: string): Promise<ServiceOwnership[]> {
  const path = serviceId ? `/ownership?service_id=${serviceId}` : "/ownership";
  return request<ServiceOwnership[]>(path, { token });
}

export async function createOwnership(
  token: string,
  data: {
    service_id: string;
    team_id?: string;
    user_id?: string;
    ownership_type: OwnershipType;
    escalation_policy?: string;
  }
): Promise<ServiceOwnership> {
  return request<ServiceOwnership>("/ownership", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

export async function deleteOwnership(token: string, ownershipId: string): Promise<void> {
  return request<void>(`/ownership/${ownershipId}`, {
    method: "DELETE",
    token,
  });
}

// Teams
export async function listTeams(token: string): Promise<Team[]> {
  return request<Team[]>("/teams", { token });
}

export async function createTeam(token: string, data: { name: string; slug?: string; description?: string }): Promise<Team> {
  return request<Team>("/teams", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

// Environments & Regions
export async function listEnvironments(token: string): Promise<Environment[]> {
  return request<Environment[]>("/environments", { token });
}

export async function createEnvironment(token: string, data: { name: string; env_type: string; region?: string }): Promise<Environment> {
  return request<Environment>("/environments", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

export async function listRegions(token: string): Promise<Region[]> {
  return request<Region[]>("/regions", { token });
}

export async function createRegion(token: string, data: { name: string; code: string; cloud_provider?: string }): Promise<Region> {
  return request<Region>("/regions", {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}

// Deployments
export async function listDeployments(token: string, serviceId: string): Promise<ServiceDeploymentConfig[]> {
  return request<ServiceDeploymentConfig[]>(`/services/${serviceId}/deployment-configs`, { token });
}

export async function createDeployment(
  token: string,
  serviceId: string,
  data: {
    environment_id: string;
    region_id?: string;
    health_check_url?: string;
    health_check_interval_seconds?: number;
    observability_identifiers?: Record<string, unknown>;
    current_commit_sha?: string;
    current_version?: string;
  }
): Promise<ServiceDeploymentConfig> {
  return request<ServiceDeploymentConfig>(`/services/${serviceId}/deployment-configs`, {
    method: "POST",
    token,
    body: JSON.stringify(data),
  });
}
