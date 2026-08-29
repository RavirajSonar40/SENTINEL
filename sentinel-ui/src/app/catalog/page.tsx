"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/AuthContext";
import {
  Organization, OrganizationMembership, Service, Repository,
  Environment, Region, Team,
  getActiveOrg, listMemberships, listServices, listRepositories,
  listEnvironments, listRegions, listTeams, createService,
  createRepository, createTeam, createEnvironment, createRegion,
  activateOrganization, createOrganization
} from "@/lib/catalogApi";

export default function CatalogPage() {
  const { token, userId, username } = useAuth();
  const [activeTab, setActiveTab] = useState<"services" | "repositories" | "environments" | "teams">("services");
  
  // State
  const [activeOrg, setActiveOrg] = useState<Organization | null>(null);
  const [memberships, setMemberships] = useState<OrganizationMembership[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [tierFilter, setTierFilter] = useState("");

  // Modals
  const [showCreateService, setShowCreateService] = useState(false);
  const [showCreateRepo, setShowCreateRepo] = useState(false);
  const [showCreateOrg, setShowCreateOrg] = useState(false);
  const [showCreateTeam, setShowCreateTeam] = useState(false);
  const [showCreateEnv, setShowCreateEnv] = useState(false);
  const [showCreateRegion, setShowCreateRegion] = useState(false);

  // Form states
  const [newServiceName, setNewServiceName] = useState("");
  const [newServiceTier, setNewServiceTier] = useState("medium");
  const [newServiceDesc, setNewServiceDesc] = useState("");

  const [newRepoName, setNewRepoName] = useState("");
  const [newRepoFullName, setNewRepoFullName] = useState("");
  const [newRepoLang, setNewRepoLang] = useState("Python");

  const [newOrgName, setNewOrgName] = useState("");
  const [newTeamName, setNewTeamName] = useState("");
  const [newEnvName, setNewEnvName] = useState("");
  const [newEnvType, setNewEnvType] = useState("production");
  const [newRegionName, setNewRegionName] = useState("");
  const [newRegionCode, setNewRegionCode] = useState("us-east-1");

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      getActiveOrg(token).catch(() => null),
      listMemberships(token).catch(() => []),
      listServices(token, { search: search || undefined, tier: tierFilter || undefined }).catch(() => []),
      listRepositories(token).catch(() => []),
      listEnvironments(token).catch(() => []),
      listRegions(token).catch(() => []),
      listTeams(token).catch(() => []),
    ])
      .then(([org, mems, svcs, repos, envs, regs, tms]) => {
        setActiveOrg(org);
        setMemberships(mems);
        setServices(svcs);
        setRepositories(repos);
        setEnvironments(envs);
        setRegions(regs);
        setTeams(tms);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load catalog data.";
        setError(msg);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [token, search, tierFilter, refreshKey]);

  const handleCreateService = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newServiceName.trim()) return;
    try {
      await createService(token, {
        name: newServiceName.trim(),
        tier: newServiceTier,
        description: newServiceDesc.trim() || undefined,
      });
      setShowCreateService(false);
      setNewServiceName("");
      setNewServiceDesc("");
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create service";
      alert(msg);
    }
  };

  const handleCreateRepo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newRepoName.trim() || !newRepoFullName.trim()) return;
    try {
      await createRepository(token, {
        name: newRepoName.trim(),
        full_name: newRepoFullName.trim(),
        language: newRepoLang,
      });
      setShowCreateRepo(false);
      setNewRepoName("");
      setNewRepoFullName("");
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to register repository";
      alert(msg);
    }
  };

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newOrgName.trim()) return;
    try {
      await createOrganization(token, newOrgName.trim());
      setShowCreateOrg(false);
      setNewOrgName("");
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create organization";
      alert(msg);
    }
  };

  const handleCreateTeam = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newTeamName.trim()) return;
    try {
      await createTeam(token, { name: newTeamName.trim() });
      setShowCreateTeam(false);
      setNewTeamName("");
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create team";
      alert(msg);
    }
  };

  const handleCreateEnv = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newEnvName.trim()) return;
    try {
      await createEnvironment(token, { name: newEnvName.trim(), env_type: newEnvType });
      setShowCreateEnv(false);
      setNewEnvName("");
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create environment";
      alert(msg);
    }
  };

  const handleCreateRegion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newRegionName.trim() || !newRegionCode.trim()) return;
    try {
      await createRegion(token, { name: newRegionName.trim(), code: newRegionCode.trim() });
      setShowCreateRegion(false);
      setNewRegionName("");
      setNewRegionCode("");
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create region";
      alert(msg);
    }
  };

  const handleActivateOrg = async (orgId: string) => {
    if (!token) return;
    try {
      await activateOrganization(token, orgId);
      reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to switch organization";
      alert(msg);
    }
  };

  const myMembership = memberships.find((m) => m.user_id === userId) || memberships[0];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header with Organization Switcher */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight text-white">System Catalog & Topology</h1>
              {activeOrg && (
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                  {activeOrg.name}
                </span>
              )}
              {myMembership && (
                <span className="px-2 py-0.5 rounded text-[11px] font-mono uppercase bg-slate-800 text-slate-300">
                  {myMembership.role}
                </span>
              )}
            </div>
            <p className="text-sm text-slate-400 mt-1">
              Multi-entity catalog modeling services, multiple repositories, dependencies, and deployment topology.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowCreateOrg(true)}
              className="px-3 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition-colors border border-slate-700"
            >
              + New Org
            </button>
            {activeTab === "services" && (
              <button
                onClick={() => setShowCreateService(true)}
                className="px-4 py-2 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors shadow-lg shadow-indigo-600/20"
              >
                + Register Service
              </button>
            )}
            {activeTab === "repositories" && (
              <button
                onClick={() => setShowCreateRepo(true)}
                className="px-4 py-2 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors shadow-lg shadow-indigo-600/20"
              >
                + Connect Repository
              </button>
            )}
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="p-4 bg-red-950/50 border border-red-800/60 rounded-xl text-red-300 text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => reload()} className="underline text-xs">Retry</button>
          </div>
        )}

        {/* Navigation Tabs */}
        <div className="flex border-b border-slate-800 gap-6 text-sm font-medium">
          <button
            onClick={() => setActiveTab("services")}
            className={`pb-3 border-b-2 transition-colors ${
              activeTab === "services"
                ? "border-indigo-500 text-indigo-400 font-semibold"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            Services ({services.length})
          </button>
          <button
            onClick={() => setActiveTab("repositories")}
            className={`pb-3 border-b-2 transition-colors ${
              activeTab === "repositories"
                ? "border-indigo-500 text-indigo-400 font-semibold"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            Repositories ({repositories.length})
          </button>
          <button
            onClick={() => setActiveTab("environments")}
            className={`pb-3 border-b-2 transition-colors ${
              activeTab === "environments"
                ? "border-indigo-500 text-indigo-400 font-semibold"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            Environments & Regions
          </button>
          <button
            onClick={() => setActiveTab("teams")}
            className={`pb-3 border-b-2 transition-colors ${
              activeTab === "teams"
                ? "border-indigo-500 text-indigo-400 font-semibold"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            Teams & Ownership ({teams.length})
          </button>
        </div>

        {/* TAB 1: SERVICES */}
        {activeTab === "services" && (
          <div className="space-y-4">
            {/* Filters */}
            <div className="flex flex-col sm:flex-row gap-3">
              <input
                type="text"
                placeholder="Search services by name..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
              />
              <select
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="">All Tiers</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>

            {loading ? (
              <div className="p-12 text-center text-slate-500">Loading services...</div>
            ) : services.length === 0 ? (
              <div className="p-12 bg-slate-900 border border-slate-800 rounded-xl text-center space-y-3">
                <div className="text-3xl">📦</div>
                <h3 className="text-base font-semibold text-white">No services found</h3>
                <p className="text-xs text-slate-400 max-w-md mx-auto">
                  Register your first service to start tracking multi-repository topologies, dependencies, and deployments.
                </p>
                <button
                  onClick={() => setShowCreateService(true)}
                  className="px-4 py-2 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
                >
                  + Register Service
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {services.map((svc) => (
                  <Link
                    key={svc.id}
                    href={`/catalog/services/${svc.id}`}
                    className="block p-5 bg-slate-900 border border-slate-800 hover:border-indigo-500/50 rounded-xl transition-all hover:shadow-xl hover:shadow-indigo-950/20 group"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <h3 className="text-base font-bold text-white group-hover:text-indigo-400 transition-colors">
                          {svc.name}
                        </h3>
                        <p className="text-xs text-slate-400 line-clamp-2 mt-0.5">
                          {svc.description || "No description provided."}
                        </p>
                      </div>
                      <span
                        className={`text-[10px] uppercase font-mono px-2 py-0.5 rounded font-semibold ${
                          svc.tier === "critical"
                            ? "bg-rose-950/80 text-rose-300 border border-rose-800/50"
                            : svc.tier === "high"
                            ? "bg-amber-950/80 text-amber-300 border border-amber-800/50"
                            : "bg-slate-800 text-slate-300"
                        }`}
                      >
                        {svc.tier}
                      </span>
                    </div>

                    <div className="pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
                      <div>
                        {svc.primary_repository ? (
                          <span className="text-indigo-300 font-mono text-[11px]">
                            {svc.primary_repository}
                          </span>
                        ) : (
                          <span className="text-slate-500 italic">No primary repo</span>
                        )}
                      </div>
                      <span className="capitalize text-emerald-400 font-medium">
                        ● {svc.health}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}

        {/* TAB 2: REPOSITORIES */}
        {activeTab === "repositories" && (
          <div className="space-y-4">
            {loading ? (
              <div className="p-12 text-center text-slate-500">Loading repositories...</div>
            ) : repositories.length === 0 ? (
              <div className="p-12 bg-slate-900 border border-slate-800 rounded-xl text-center space-y-3">
                <div className="text-3xl">📚</div>
                <h3 className="text-base font-semibold text-white">No repositories connected</h3>
                <p className="text-xs text-slate-400 max-w-md mx-auto">
                  Connect GitHub or internal git repositories to associate with services.
                </p>
                <button
                  onClick={() => setShowCreateRepo(true)}
                  className="px-4 py-2 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
                >
                  + Connect Repository
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {repositories.map((repo) => (
                  <div
                    key={repo.id}
                    className="p-5 bg-slate-900 border border-slate-800 rounded-xl space-y-3"
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <h4 className="text-sm font-bold text-white">{repo.full_name}</h4>
                        <p className="text-xs text-slate-400 font-mono mt-0.5">
                          branch: {repo.default_branch}
                        </p>
                      </div>
                      <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-300">
                        {repo.language || "code"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-800">
                      <span>Status: {repo.sync_status || "synced"}</span>
                      <span className={repo.is_active ? "text-emerald-400" : "text-slate-500"}>
                        {repo.is_active ? "Active" : "Inactive"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* TAB 3: ENVIRONMENTS & REGIONS */}
        {activeTab === "environments" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Environments */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-base font-bold text-white">Environments</h3>
                  <p className="text-xs text-slate-400">Deployment lifecycle stages</p>
                </div>
                <button
                  onClick={() => setShowCreateEnv(true)}
                  className="px-3 py-1.5 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition-colors"
                >
                  + Add Environment
                </button>
              </div>
              <div className="space-y-2">
                {environments.map((env) => (
                  <div
                    key={env.id}
                    className="flex items-center justify-between p-3 bg-slate-950/60 border border-slate-800/80 rounded-lg text-sm"
                  >
                    <span className="font-medium text-slate-200">{env.name}</span>
                    <span className="text-xs uppercase font-mono px-2 py-0.5 bg-indigo-950/60 text-indigo-300 rounded border border-indigo-800/40">
                      {env.env_type}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Regions */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-base font-bold text-white">Cloud & Multi-Regions</h3>
                  <p className="text-xs text-slate-400">Regional infrastructure targets</p>
                </div>
                <button
                  onClick={() => setShowCreateRegion(true)}
                  className="px-3 py-1.5 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition-colors"
                >
                  + Add Region
                </button>
              </div>
              <div className="space-y-2">
                {regions.length === 0 ? (
                  <div className="p-4 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-lg">
                    No regions registered yet.
                  </div>
                ) : (
                  regions.map((reg) => (
                    <div
                      key={reg.id}
                      className="flex items-center justify-between p-3 bg-slate-950/60 border border-slate-800/80 rounded-lg text-sm"
                    >
                      <span className="font-medium text-slate-200">{reg.name}</span>
                      <span className="text-xs font-mono text-slate-400">
                        {reg.code} ({reg.cloud_provider})
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: TEAMS & OWNERSHIP */}
        {activeTab === "teams" && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-white">Teams & Service Ownership</h3>
                <p className="text-xs text-slate-400">Engineering teams and escalation policies</p>
              </div>
              <button
                onClick={() => setShowCreateTeam(true)}
                className="px-3 py-1.5 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
              >
                + Create Team
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {teams.map((tm) => (
                <div key={tm.id} className="p-4 bg-slate-950/60 border border-slate-800 rounded-lg space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-white">{tm.name}</h4>
                    <span className="text-xs text-slate-500 font-mono">slug: {tm.slug}</span>
                  </div>
                  <p className="text-xs text-slate-400">{tm.description || "No description."}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* MODAL: CREATE SERVICE */}
        {showCreateService && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Register New Service</h3>
              <form onSubmit={handleCreateService} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Service Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. checkout-api"
                    value={newServiceName}
                    onChange={(e) => setNewServiceName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Service Tier</label>
                  <select
                    value={newServiceTier}
                    onChange={(e) => setNewServiceTier(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Description</label>
                  <textarea
                    rows={3}
                    placeholder="Primary backend service for checkout processing..."
                    value={newServiceDesc}
                    onChange={(e) => setNewServiceDesc(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowCreateService(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Create Service
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* MODAL: CONNECT REPOSITORY */}
        {showCreateRepo && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Connect Git Repository</h3>
              <form onSubmit={handleCreateRepo} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Repository Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. checkout-api"
                    value={newRepoName}
                    onChange={(e) => setNewRepoName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Full Repository Name (org/repo) *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. acme/checkout-api"
                    value={newRepoFullName}
                    onChange={(e) => setNewRepoFullName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Primary Language</label>
                  <input
                    type="text"
                    value={newRepoLang}
                    onChange={(e) => setNewRepoLang(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowCreateRepo(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Register Repository
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* MODAL: CREATE ORGANIZATION */}
        {showCreateOrg && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Create New Organization</h3>
              <form onSubmit={handleCreateOrg} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Organization Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Acme Enterprise"
                    value={newOrgName}
                    onChange={(e) => setNewOrgName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowCreateOrg(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Create & Switch
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* MODAL: CREATE TEAM */}
        {showCreateTeam && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Create Engineering Team</h3>
              <form onSubmit={handleCreateTeam} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Team Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Payments Platform"
                    value={newTeamName}
                    onChange={(e) => setNewTeamName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowCreateTeam(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Create Team
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* MODAL: CREATE ENVIRONMENT */}
        {showCreateEnv && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Add Environment</h3>
              <form onSubmit={handleCreateEnv} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Environment Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. preview"
                    value={newEnvName}
                    onChange={(e) => setNewEnvName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Environment Type</label>
                  <select
                    value={newEnvType}
                    onChange={(e) => setNewEnvType(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="production">Production</option>
                    <option value="staging">Staging</option>
                    <option value="preview">Preview</option>
                    <option value="development">Development</option>
                  </select>
                </div>
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowCreateEnv(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Add Environment
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* MODAL: CREATE REGION */}
        {showCreateRegion && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Add Regional Target</h3>
              <form onSubmit={handleCreateRegion} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Region Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. US East (N. Virginia)"
                    value={newRegionName}
                    onChange={(e) => setNewRegionName(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Region Code *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. us-east-1"
                    value={newRegionCode}
                    onChange={(e) => setNewRegionCode(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowCreateRegion(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Add Region
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
