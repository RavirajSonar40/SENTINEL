"use client";

import React, { useState, useEffect, useCallback } from "react";
import Sidebar from "@/components/Sidebar";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import {
  Deployment,
  deploymentsApi,
} from "@/lib/deploymentsApi";
import {
  Service,
  Environment,
  Region,
  Repository,
  listServices,
  listEnvironments,
  listRegions,
  listRepositories,
} from "@/lib/catalogApi";
import DeploymentDetailModal from "@/components/deployments/DeploymentDetailModal";
import CreateDeploymentModal from "@/components/deployments/CreateDeploymentModal";
import WebhookEndpointsModal from "@/components/deployments/WebhookEndpointsModal";

export default function DeploymentsPage() {
  const { token } = useAuth();
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [regions, setRegions] = useState<Region[]>([]);
  const [repositories, setRepositories] = useState<Repository[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [selectedEnv, setSelectedEnv] = useState<string>("all");
  const [selectedService, setSelectedService] = useState<string>("all");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  // Modals
  const [inspectDeployment, setInspectDeployment] = useState<Deployment | null>(null);
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [showWebhookModal, setShowWebhookModal] = useState<boolean>(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      listServices(token).catch(() => []),
      listEnvironments(token).catch(() => []),
      listRegions(token).catch(() => []),
      listRepositories(token).catch(() => []),
    ]).then(([svcList, envList, regList, repoList]) => {
      setServices(svcList);
      setEnvironments(envList);
      setRegions(regList);
      setRepositories(repoList);
    }).catch((err: unknown) => {
      console.error("Failed to load catalog metadata", err);
    });
  }, [token]);

  useEffect(() => {
    const params: { service_id?: string; environment_id?: string; status?: string; limit: number } = { limit: 100 };
    if (selectedService !== "all") params.service_id = selectedService;
    if (selectedEnv !== "all") params.environment_id = selectedEnv;
    if (selectedStatus !== "all") params.status = selectedStatus;

    deploymentsApi.getDeployments(params, token || undefined)
      .then((list) => {
        setDeployments(list);
      })
      .catch((err: unknown) => {
        setError((err as Error).message || "Failed to load deployment ledger");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [selectedService, selectedEnv, selectedStatus, token, refreshKey]);

  // 15-second Auto-refresh polling
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      reload();
    }, 15000);
    return () => clearInterval(interval);
  }, [autoRefresh, reload]);

  // Filtered Deployments
  const filteredDeployments = deployments.filter((d) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      d.commit_sha.toLowerCase().includes(q) ||
      (d.commit_message && d.commit_message.toLowerCase().includes(q)) ||
      (d.version && d.version.toLowerCase().includes(q)) ||
      (d.service_name && d.service_name.toLowerCase().includes(q)) ||
      (d.deployed_by && d.deployed_by.toLowerCase().includes(q))
    );
  });

  // Overview Metrics
  const totalReleases = deployments.length;
  const activeProdReleases = deployments.filter(
    (d) => d.is_current && d.environment_name?.toLowerCase() === "production"
  ).length;
  const failedOrRolledBack = deployments.filter(
    (d) => d.status === "failed" || d.status === "rolled_back"
  ).length;
  const avgDuration =
    deployments.filter((d) => d.duration_seconds && d.duration_seconds > 0).length > 0
      ? (
          deployments.reduce((acc, d) => acc + (d.duration_seconds || 0), 0) /
          deployments.filter((d) => d.duration_seconds && d.duration_seconds > 0).length
        ).toFixed(1)
      : "—";

  const getStatusPill = (status: string) => {
    switch (status) {
      case "succeeded":
        return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-950/80 text-emerald-400 border border-emerald-800/60">Succeeded</span>;
      case "in_progress":
        return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-cyan-950/80 text-cyan-400 border border-cyan-800/60 animate-pulse">In Progress</span>;
      case "failed":
        return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-rose-950/80 text-rose-400 border border-rose-800/60">Failed</span>;
      case "rolled_back":
        return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-950/80 text-amber-400 border border-amber-800/60">Rolled Back</span>;
      case "cancelled":
        return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-neutral-800 text-neutral-400 border border-neutral-700">Cancelled</span>;
      default:
        return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-neutral-800 text-neutral-400 border border-neutral-700">Pending</span>;
    }
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 flex">
      <Sidebar />
      <div className="flex-1 ml-[220px] flex flex-col min-w-0">
        <TopBar title="Deployments" subtitle="Release ledger & lifecycle inventory" />

        <main className="p-8 space-y-8 max-w-7xl mx-auto w-full">
          {/* Top Title & Header Actions */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
                <span className="material-symbols-outlined text-blue-400 text-3xl">rocket_launch</span>
                <span>Deployment Inventory & Release Ledger</span>
              </h1>
              <p className="text-sm text-neutral-400 mt-1">
                Real-time tracking of what is deployed, where it is deployed, active versions, and release lifecycle metrics.
              </p>
            </div>

            <div className="flex items-center gap-3">
              {/* 15s Auto-refresh Toggle */}
              <button
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`px-3 py-2 rounded-xl text-xs font-semibold transition border flex items-center gap-1.5 ${
                  autoRefresh
                    ? "bg-blue-950/60 border-blue-800/80 text-blue-300"
                    : "bg-neutral-900 border-neutral-800 text-neutral-400 hover:text-neutral-200"
                }`}
                title="Toggle 15-second live polling"
              >
                <span className={`material-symbols-outlined text-sm ${autoRefresh ? "animate-spin" : ""}`}>
                  sync
                </span>
                <span>{autoRefresh ? "Live (15s)" : "Paused"}</span>
              </button>

              <button
                onClick={() => setShowWebhookModal(true)}
                className="px-3.5 py-2 rounded-xl bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 text-xs font-semibold text-neutral-200 transition flex items-center gap-1.5"
              >
                <span className="material-symbols-outlined text-purple-400 text-sm">key</span>
                <span>Webhook Keys</span>
              </button>

              <button
                onClick={() => setShowCreateModal(true)}
                className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white transition flex items-center gap-1.5 shadow-lg shadow-blue-600/20"
              >
                <span className="material-symbols-outlined text-sm">add</span>
                <span>Register Deployment</span>
              </button>
            </div>
          </div>

          {/* Metric Overview Banner */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-5 rounded-2xl bg-neutral-900/60 border border-neutral-800/80 backdrop-blur-sm">
              <div className="text-xs font-semibold text-neutral-400 uppercase tracking-wider">Total Recorded Releases</div>
              <div className="text-2xl font-bold text-neutral-100 mt-2">{totalReleases}</div>
              <div className="text-xs text-neutral-500 mt-1">Across all environments</div>
            </div>

            <div className="p-5 rounded-2xl bg-neutral-900/60 border border-neutral-800/80 backdrop-blur-sm">
              <div className="text-xs font-semibold text-blue-400 uppercase tracking-wider flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-blue-400"></span>
                <span>Active Prod Releases</span>
              </div>
              <div className="text-2xl font-bold text-blue-400 mt-2">{activeProdReleases}</div>
              <div className="text-xs text-neutral-500 mt-1">Current live target versions</div>
            </div>

            <div className="p-5 rounded-2xl bg-neutral-900/60 border border-neutral-800/80 backdrop-blur-sm">
              <div className="text-xs font-semibold text-rose-400 uppercase tracking-wider">Failed / Rolled Back</div>
              <div className="text-2xl font-bold text-rose-400 mt-2">{failedOrRolledBack}</div>
              <div className="text-xs text-neutral-500 mt-1">Release anomalies</div>
            </div>

            <div className="p-5 rounded-2xl bg-neutral-900/60 border border-neutral-800/80 backdrop-blur-sm">
              <div className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Avg Deployment Duration</div>
              <div className="text-2xl font-bold text-emerald-400 mt-2">
                {avgDuration !== "—" ? `${avgDuration}s` : "—"}
              </div>
              <div className="text-xs text-neutral-500 mt-1">Start to completion time</div>
            </div>
          </div>

          {/* Filter Bar */}
          <div className="p-4 rounded-2xl bg-neutral-900/40 border border-neutral-800/80 flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3 flex-1 min-w-[280px]">
              {/* Search */}
              <div className="relative flex-1 min-w-[200px]">
                <span className="material-symbols-outlined absolute left-3 top-2.5 text-neutral-500 text-sm">search</span>
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Filter by SHA, version, service, author..."
                  className="w-full pl-9 pr-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-xs text-neutral-200 focus:outline-none focus:border-blue-500"
                />
              </div>

              {/* Service Filter */}
              <select
                value={selectedService}
                onChange={(e) => setSelectedService(e.target.value)}
                className="px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-xs text-neutral-300 focus:outline-none focus:border-blue-500"
              >
                <option value="all">All Services</option>
                {services.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>

              {/* Environment Filter */}
              <select
                value={selectedEnv}
                onChange={(e) => setSelectedEnv(e.target.value)}
                className="px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-xs text-neutral-300 focus:outline-none focus:border-blue-500"
              >
                <option value="all">All Environments</option>
                {environments.map((env) => (
                  <option key={env.id} value={env.id}>{env.name}</option>
                ))}
              </select>

              {/* Status Filter */}
              <select
                value={selectedStatus}
                onChange={(e) => setSelectedStatus(e.target.value)}
                className="px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-xs text-neutral-300 focus:outline-none focus:border-blue-500"
              >
                <option value="all">All Statuses</option>
                <option value="succeeded">Succeeded</option>
                <option value="in_progress">In Progress</option>
                <option value="failed">Failed</option>
                <option value="rolled_back">Rolled Back</option>
                <option value="cancelled">Cancelled</option>
                <option value="pending">Pending</option>
              </select>
            </div>

            <button
              onClick={() => {
                setSelectedService("all");
                setSelectedEnv("all");
                setSelectedStatus("all");
                setSearchQuery("");
              }}
              className="text-xs text-neutral-400 hover:text-neutral-200 transition"
            >
              Reset Filters
            </button>
          </div>

          {/* Deployment Table */}
          <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 overflow-hidden shadow-xl">
            {error && (
              <div className="p-4 bg-rose-950/50 border-b border-rose-800/60 text-rose-300 text-xs flex items-center gap-2">
                <span className="material-symbols-outlined text-sm">error</span>
                <span>{error}</span>
              </div>
            )}

            {loading ? (
              <div className="py-20 text-center text-sm text-neutral-500 animate-pulse">
                Loading deployment ledger...
              </div>
            ) : filteredDeployments.length === 0 ? (
              <div className="py-20 text-center space-y-3">
                <span className="material-symbols-outlined text-neutral-600 text-4xl">rocket</span>
                <div className="text-sm font-medium text-neutral-400">No deployments found matching filters</div>
                <p className="text-xs text-neutral-500 max-w-sm mx-auto">
                  Register a manual deployment or configure a GitHub/generic CI/CD webhook to ingest release events.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-neutral-950/60 border-b border-neutral-800 text-neutral-400 uppercase tracking-wider font-semibold">
                    <tr>
                      <th className="py-3.5 px-4">Service & Target</th>
                      <th className="py-3.5 px-4">Commit / Version</th>
                      <th className="py-3.5 px-4">Provider & Trigger</th>
                      <th className="py-3.5 px-4">Timing & Duration</th>
                      <th className="py-3.5 px-4">Status</th>
                      <th className="py-3.5 px-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-800/60 text-neutral-300">
                    {filteredDeployments.map((d) => (
                      <tr
                        key={d.id}
                        className={`hover:bg-neutral-800/40 transition cursor-pointer ${
                          d.is_current ? "bg-blue-950/10" : ""
                        }`}
                        onClick={() => setInspectDeployment(d)}
                      >
                        {/* Service & Target */}
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-neutral-100 text-sm">
                              {d.service_name || "Unknown Service"}
                            </span>
                            {d.is_current && (
                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-950 text-blue-400 border border-blue-800">
                                Current Live
                              </span>
                            )}
                          </div>
                          <div className="text-neutral-500 text-[11px] mt-0.5 flex items-center gap-1.5">
                            <span className="text-neutral-400 font-medium">{d.environment_name || "production"}</span>
                            {d.region_code && <span>• {d.region_code}</span>}
                          </div>
                        </td>

                        {/* Commit & Version */}
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-mono px-2 py-0.5 rounded bg-neutral-950 text-blue-300 font-medium">
                              {d.commit_sha.slice(0, 7)}
                            </span>
                            {d.version && (
                              <span className="text-neutral-300 font-medium">{d.version}</span>
                            )}
                          </div>
                          {d.commit_message && (
                            <div className="text-neutral-400 text-[11px] mt-0.5 max-w-xs truncate">
                              {d.commit_message}
                            </div>
                          )}
                        </td>

                        {/* Provider & Trigger */}
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-1.5">
                            <span className="capitalize font-medium text-neutral-200">{d.provider}</span>
                          </div>
                          <div className="text-neutral-500 text-[11px] mt-0.5">
                            by {d.deployed_by || "Automated"}
                          </div>
                        </td>

                        {/* Timing & Duration */}
                        <td className="py-3.5 px-4">
                          <div className="text-neutral-200">
                            {new Date(d.deployed_at).toLocaleDateString()} {new Date(d.deployed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </div>
                          <div className="text-neutral-500 text-[11px] mt-0.5">
                            Duration: {d.duration_seconds !== null && d.duration_seconds !== undefined ? `${d.duration_seconds.toFixed(1)}s` : "—"}
                          </div>
                        </td>

                        {/* Status */}
                        <td className="py-3.5 px-4">
                          {getStatusPill(d.status)}
                        </td>

                        {/* Actions */}
                        <td className="py-3.5 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => setInspectDeployment(d)}
                            className="px-2.5 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-xs font-semibold text-neutral-200 transition"
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Modals */}
      {inspectDeployment && (
        <DeploymentDetailModal
          deployment={inspectDeployment}
          token={token || undefined}
          onClose={() => setInspectDeployment(null)}
          onStatusUpdated={() => {
            reload();
          }}
        />
      )}

      {showCreateModal && (
        <CreateDeploymentModal
          services={services}
          environments={environments}
          regions={regions}
          repositories={repositories}
          token={token || undefined}
          onClose={() => setShowCreateModal(false)}
          onCreated={() => {
            reload();
          }}
        />
      )}

      {showWebhookModal && (
        <WebhookEndpointsModal
          token={token || undefined}
          onClose={() => setShowWebhookModal(false)}
        />
      )}
    </div>
  );
}
