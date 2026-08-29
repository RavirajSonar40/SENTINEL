"use client";

import React, { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/AuthContext";
import {
  ServiceDetail, ServiceGraphResponse, Repository, Environment, Region, Team,
  getServiceDetail, getServiceGraph, listRepositories, listEnvironments,
  listRegions, listTeams, createServiceRepository, deleteServiceRepository,
  createDependency, deleteDependency, createOwnership, deleteOwnership,
  createDeployment, deleteService
} from "@/lib/catalogApi";
import { ServiceRepoModal } from "@/components/catalog/ServiceRepoModal";
import { DependencyGraphView } from "@/components/catalog/DependencyGraphView";
import { ConfirmDeleteModal } from "@/components/catalog/ConfirmDeleteModal";

export default function ServiceDetailPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const { token } = useAuth();

  const [service, setService] = useState<ServiceDetail | null>(null);
  const [graph, setGraph] = useState<ServiceGraphResponse | null>(null);
  const [allRepos, setAllRepos] = useState<Repository[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modals
  const [showRepoModal, setShowRepoModal] = useState(false);
  const [showDepModal, setShowDepModal] = useState(false);
  const [showOwnModal, setShowOwnModal] = useState(false);
  const [showDeployModal, setShowDeployModal] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: "service" | "repo_mapping" | "dependency" | "ownership";
    id: string;
    name: string;
  } | null>(null);

  // Form states for Dependency
  const [depTargetServiceId, setDepTargetServiceId] = useState("");
  const [depType, setDepType] = useState<"synchronous" | "asynchronous" | "database" | "cache" | "external">("synchronous");
  const [depCrit, setDepCrit] = useState<"hard" | "soft">("hard");

  // Form states for Ownership
  const [ownTeamId, setOwnTeamId] = useState("");
  const [ownType, setOwnType] = useState<"primary_owner" | "secondary_owner" | "oncall">("primary_owner");
  const [ownEscalation, setOwnEscalation] = useState("");

  // Form states for Deployment Config
  const [deployEnvId, setDeployEnvId] = useState("");
  const [deployRegionId, setDeployRegionId] = useState("");
  const [deployHealthUrl, setDeployHealthUrl] = useState("");
  const [deployPrometheus, setDeployPrometheus] = useState("");
  const [deploySentry, setDeploySentry] = useState("");

  useEffect(() => {
    if (!token || !id) return;
    Promise.all([
      getServiceDetail(token, id),
      getServiceGraph(token, id).catch(() => null),
      listRepositories(token).catch(() => []),
      listEnvironments(token).catch(() => []),
      listRegions(token).catch(() => []),
      listTeams(token).catch(() => []),
    ])
      .then(([svc, grp, repos, envs, regs, tms]) => {
        setService(svc);
        setGraph(grp);
        setAllRepos(repos);
        setEnvironments(envs);
        setRegions(regs);
        setTeams(tms);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load service topology.";
        setError(msg);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [token, id]);

  const handleLinkRepo = async (data: {
    service_id: string;
    repository_id: string;
    role: "application" | "configuration" | "infrastructure" | "dependency";
    is_primary: boolean;
    confidence: number;
    selection_reason: string;
  }) => {
    if (!token) return;
    await createServiceRepository(token, data);
    const updated = await getServiceDetail(token, id);
    setService(updated);
  };

  const handleAddDependency = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !depTargetServiceId) return;
    try {
      await createDependency(token, {
        dependent_service_id: id,
        upstream_service_id: depTargetServiceId,
        dependency_type: depType,
        criticality: depCrit,
      });
      setShowDepModal(false);
      const [updatedSvc, updatedGraph] = await Promise.all([
        getServiceDetail(token, id),
        getServiceGraph(token, id).catch(() => null),
      ]);
      setService(updatedSvc);
      setGraph(updatedGraph);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to link dependency";
      alert(msg);
    }
  };

  const handleAddOwnership = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !ownTeamId) return;
    try {
      await createOwnership(token, {
        service_id: id,
        team_id: ownTeamId,
        ownership_type: ownType,
        escalation_policy: ownEscalation || undefined,
      });
      setShowOwnModal(false);
      const updated = await getServiceDetail(token, id);
      setService(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to assign ownership";
      alert(msg);
    }
  };

  const handleAddDeployment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !deployEnvId) return;
    try {
      await createDeployment(token, id, {
        environment_id: deployEnvId,
        region_id: deployRegionId || undefined,
        health_check_url: deployHealthUrl || undefined,
        observability_identifiers: {
          prometheus_job: deployPrometheus || undefined,
          sentry_project: deploySentry || undefined,
        },
      });
      setShowDeployModal(false);
      const updated = await getServiceDetail(token, id);
      setService(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to add deployment config";
      alert(msg);
    }
  };

  const handleConfirmDelete = async () => {
    if (!token || !deleteConfirm) return;
    try {
      if (deleteConfirm.type === "service") {
        await deleteService(token, id);
        router.push("/catalog");
      } else if (deleteConfirm.type === "repo_mapping") {
        await deleteServiceRepository(token, deleteConfirm.id);
        const updated = await getServiceDetail(token, id);
        setService(updated);
      } else if (deleteConfirm.type === "dependency") {
        await deleteDependency(token, deleteConfirm.id);
        const [updatedSvc, updatedGraph] = await Promise.all([
          getServiceDetail(token, id),
          getServiceGraph(token, id).catch(() => null),
        ]);
        setService(updatedSvc);
        setGraph(updatedGraph);
      } else if (deleteConfirm.type === "ownership") {
        await deleteOwnership(token, deleteConfirm.id);
        const updated = await getServiceDetail(token, id);
        setService(updated);
      }
      setDeleteConfirm(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete item";
      alert(msg);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        <div className="text-slate-500 text-sm">Loading service topology...</div>
      </div>
    );
  }

  if (error || !service) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100 p-8">
        <div className="max-w-4xl mx-auto p-6 bg-red-950/40 border border-red-800/60 rounded-xl space-y-3">
          <h2 className="text-lg font-bold text-red-300">Error Loading Service</h2>
          <p className="text-sm text-red-400">{error || "Service not found."}</p>
          <Link href="/catalog" className="inline-block text-xs font-semibold text-white bg-slate-800 px-4 py-2 rounded-lg">
            ← Back to Catalog
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Navigation Breadcrumb */}
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Link href="/catalog" className="hover:text-indigo-400">Catalog</Link>
          <span>/</span>
          <Link href="/catalog" className="hover:text-indigo-400">Services</Link>
          <span>/</span>
          <span className="text-slate-200 font-medium">{service.name}</span>
        </div>

        {/* Service Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-extrabold text-white">{service.name}</h1>
              <span
                className={`text-xs uppercase font-mono px-2.5 py-0.5 rounded font-semibold ${
                  service.tier === "critical"
                    ? "bg-rose-950/80 text-rose-300 border border-rose-800/50"
                    : "bg-indigo-950/80 text-indigo-300 border border-indigo-800/50"
                }`}
              >
                {service.tier} tier
              </span>
              <span className="capitalize text-xs font-medium text-emerald-400">
                ● {service.health}
              </span>
            </div>
            <p className="text-sm text-slate-400 mt-1 max-w-2xl">
              {service.description || "No description provided."}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowRepoModal(true)}
              className="px-4 py-2 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors shadow-lg shadow-indigo-600/20"
            >
              + Link Repository
            </button>
            <button
              onClick={() =>
                setDeleteConfirm({
                  type: "service",
                  id: service.id,
                  name: service.name,
                })
              }
              className="px-3 py-2 text-xs font-medium text-red-400 hover:text-white bg-red-950/30 hover:bg-red-600 rounded-lg border border-red-800/40 transition-colors"
            >
              Delete Service
            </button>
          </div>
        </div>

        {/* SECTION 1: REPOSITORY TOPOLOGY MATRIX */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
              <h2 className="text-base font-bold text-white">Repository Topology Matrix</h2>
              <p className="text-xs text-slate-400">
                Multi-repository links with architectural roles, confidence, and selection reasons
              </p>
            </div>
            <button
              onClick={() => setShowRepoModal(true)}
              className="text-xs font-medium text-indigo-400 hover:underline"
            >
              + Add Repo Binding
            </button>
          </div>

          {service.repositories.length === 0 ? (
            <div className="p-8 text-center border border-dashed border-slate-800 rounded-xl space-y-2">
              <p className="text-xs text-slate-500">No repositories linked yet.</p>
              <button
                onClick={() => setShowRepoModal(true)}
                className="px-3 py-1.5 text-xs font-semibold bg-slate-800 text-slate-200 rounded-lg hover:bg-slate-700"
              >
                Link First Repository
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {service.repositories.map((repo) => (
                <div
                  key={repo.id}
                  className="p-4 bg-slate-950/70 border border-slate-800 rounded-xl space-y-3 relative group"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-bold text-white">
                          {repo.repository_full_name || repo.repository_name}
                        </h4>
                        {repo.is_primary && (
                          <span className="px-1.5 py-0.5 bg-indigo-600 text-white rounded text-[10px] font-bold uppercase tracking-wider">
                            Primary
                          </span>
                        )}
                      </div>
                      <span className="text-xs font-mono uppercase text-indigo-300">
                        {repo.role} role
                      </span>
                    </div>
                    <button
                      onClick={() =>
                        setDeleteConfirm({
                          type: "repo_mapping",
                          id: repo.id,
                          name: repo.repository_full_name || "Repository mapping",
                        })
                      }
                      className="text-slate-500 hover:text-red-400 text-xs p-1"
                    >
                      ✕
                    </button>
                  </div>

                  <p className="text-xs text-slate-300 bg-slate-900 p-2.5 rounded-lg border border-slate-800/80">
                    <span className="text-slate-500 block text-[10px] uppercase font-semibold mb-0.5">Selection Reason:</span>
                    {repo.selection_reason}
                  </p>

                  <div className="flex items-center justify-between text-[11px] text-slate-500">
                    <span>Source: {repo.source}</span>
                    <span>Confidence: {(repo.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* SECTION 2: TOPOLOGY GRAPH & DEPENDENCIES */}
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-sm font-bold text-white">Dependency Topology & Blast Radius</span>
            <button
              onClick={() => setShowDepModal(true)}
              className="text-xs font-medium text-indigo-400 hover:underline"
            >
              + Link Upstream Dependency
            </button>
          </div>
          {graph && (
            <DependencyGraphView
              graph={graph}
              onSelectService={(targetId) => router.push(`/catalog/services/${targetId}`)}
            />
          )}
        </div>

        {/* SECTION 3: OWNERSHIP & DEPLOYMENT CONFIGURATIONS */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Ownership */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-white">Service Ownership & Escalation</h3>
                <p className="text-xs text-slate-400">Primary teams and on-call policies</p>
              </div>
              <button
                onClick={() => setShowOwnModal(true)}
                className="text-xs font-medium text-indigo-400 hover:underline"
              >
                + Assign Owner
              </button>
            </div>

            {service.ownerships.length === 0 ? (
              <div className="p-6 text-center border border-dashed border-slate-800 rounded-xl text-xs text-slate-500">
                No ownership assigned yet.
              </div>
            ) : (
              <div className="space-y-3">
                {service.ownerships.map((own) => (
                  <div
                    key={own.id}
                    className="p-4 bg-slate-950/60 border border-slate-800 rounded-xl flex items-start justify-between"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-white">
                          {own.team_name || own.username}
                        </span>
                        <span className="text-[10px] uppercase font-mono px-2 py-0.5 bg-slate-800 text-slate-300 rounded">
                          {own.ownership_type}
                        </span>
                      </div>
                      {own.escalation_policy && (
                        <p className="text-xs text-indigo-300/90 mt-1">
                          Escalation: {own.escalation_policy}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={() =>
                        setDeleteConfirm({
                          type: "ownership",
                          id: own.id,
                          name: own.team_name || own.username || "Ownership",
                        })
                      }
                      className="text-slate-500 hover:text-red-400 text-xs p-1"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Deployment Configs */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-white">Environments & Observability</h3>
                <p className="text-xs text-slate-400">Monitoring targets and active versions</p>
              </div>
              <button
                onClick={() => setShowDeployModal(true)}
                className="text-xs font-medium text-indigo-400 hover:underline"
              >
                + Add Target
              </button>
            </div>

            {service.deployments.length === 0 ? (
              <div className="p-6 text-center border border-dashed border-slate-800 rounded-xl text-xs text-slate-500">
                No environment deployment configurations.
              </div>
            ) : (
              <div className="space-y-3">
                {service.deployments.map((dep) => (
                  <div
                    key={dep.id}
                    className="p-4 bg-slate-950/60 border border-slate-800 rounded-xl space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-bold text-white">
                        {dep.environment_name} {dep.region_code && `(${dep.region_code})`}
                      </span>
                      <span className="text-xs text-emerald-400 font-medium">Active</span>
                    </div>
                    {dep.health_check_url && (
                      <p className="text-xs font-mono text-slate-400 truncate">
                        health: {dep.health_check_url}
                      </p>
                    )}
                    {dep.observability_identifiers && (
                      <div className="flex flex-wrap gap-2 pt-1 text-[11px] font-mono text-slate-400">
                        {dep.observability_identifiers.prometheus_job ? (
                          <span className="px-2 py-0.5 bg-slate-800 rounded">
                            prom: {String(dep.observability_identifiers.prometheus_job)}
                          </span>
                        ) : null}
                        {dep.observability_identifiers.sentry_project ? (
                          <span className="px-2 py-0.5 bg-slate-800 rounded">
                            sentry: {String(dep.observability_identifiers.sentry_project)}
                          </span>
                        ) : null}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* MODALS */}
        <ServiceRepoModal
          isOpen={showRepoModal}
          serviceId={id}
          repositories={allRepos}
          onClose={() => setShowRepoModal(false)}
          onSave={handleLinkRepo}
        />

        <ConfirmDeleteModal
          isOpen={!!deleteConfirm}
          title={`Delete ${deleteConfirm?.name}`}
          message="Are you sure you want to delete this resource? This action cannot be undone."
          onConfirm={handleConfirmDelete}
          onCancel={() => setDeleteConfirm(null)}
        />

        {/* MODAL: ASSIGN OWNERSHIP */}
        {showOwnModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Assign Service Owner</h3>
              <form onSubmit={handleAddOwnership} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Select Team *</label>
                  <select
                    value={ownTeamId}
                    onChange={(e) => setOwnTeamId(e.target.value)}
                    required
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="">Select a team</option>
                    {teams.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Ownership Type</label>
                  <select
                    value={ownType}
                    onChange={(e) => setOwnType(e.target.value as "primary_owner" | "secondary_owner" | "oncall")}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="primary_owner">Primary Owner</option>
                    <option value="secondary_owner">Secondary Owner</option>
                    <option value="oncall">On-Call Escalation</option>
                  </select>
                </div>
                {ownType === "oncall" && (
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Escalation Policy *</label>
                    <input
                      type="text"
                      required
                      placeholder="e.g. PagerDuty Level 1 -> Team Lead"
                      value={ownEscalation}
                      onChange={(e) => setOwnEscalation(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                )}
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowOwnModal(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Assign Owner
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* MODAL: ADD DEPENDENCY */}
        {showDepModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Link Upstream Dependency</h3>
              <form onSubmit={handleAddDependency} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Upstream Provider Service ID / Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="Enter UUID of upstream service"
                    value={depTargetServiceId}
                    onChange={(e) => setDepTargetServiceId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                  <p className="text-[10px] text-slate-500 mt-1">This service calls the upstream service.</p>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Dependency Type</label>
                  <select
                    value={depType}
                    onChange={(e) => setDepType(e.target.value as "synchronous" | "asynchronous" | "database" | "cache" | "external")}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="synchronous">Synchronous (HTTP/gRPC)</option>
                    <option value="asynchronous">Asynchronous (Queue/Kafka)</option>
                    <option value="database">Database</option>
                    <option value="cache">Cache (Redis/Memcached)</option>
                    <option value="external">External Third-Party</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Criticality</label>
                  <select
                    value={depCrit}
                    onChange={(e) => setDepCrit(e.target.value as "hard" | "soft")}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="hard">Hard (Outage of upstream breaks this service)</option>
                    <option value="soft">Soft (Degraded or cached fallback available)</option>
                  </select>
                </div>
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowDepModal(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Link Dependency
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* MODAL: ADD DEPLOYMENT TARGET */}
        {showDeployModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
              <h3 className="text-lg font-bold text-white mb-4">Add Deployment Target</h3>
              <form onSubmit={handleAddDeployment} className="space-y-4">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Environment *</label>
                  <select
                    value={deployEnvId}
                    onChange={(e) => setDeployEnvId(e.target.value)}
                    required
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="">Select Environment</option>
                    {environments.map((e) => (
                      <option key={e.id} value={e.id}>{e.name} ({e.env_type})</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Region (Optional)</label>
                  <select
                    value={deployRegionId}
                    onChange={(e) => setDeployRegionId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="">Global / Default</option>
                    {regions.map((r) => (
                      <option key={r.id} value={r.id}>{r.name} ({r.code})</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Health Check URL</label>
                  <input
                    type="url"
                    placeholder="https://api.example.com/healthz"
                    value={deployHealthUrl}
                    onChange={(e) => setDeployHealthUrl(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                  <p className="text-[10px] text-slate-500 mt-1">Must be a public/safe URL (SSRF protection enabled).</p>
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Prometheus Job Name</label>
                  <input
                    type="text"
                    placeholder="e.g. checkout-api-production"
                    value={deployPrometheus}
                    onChange={(e) => setDeployPrometheus(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Sentry Project Slug</label>
                  <input
                    type="text"
                    placeholder="e.g. checkout-api"
                    value={deploySentry}
                    onChange={(e) => setDeploySentry(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="flex justify-end gap-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setShowDeployModal(false)}
                    className="px-4 py-2 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg"
                  >
                    Add Deployment Target
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
