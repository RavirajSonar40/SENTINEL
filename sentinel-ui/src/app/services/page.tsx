"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import {
  commandCenterApi,
  OperationalServiceItem,
  OperationalServicesResponse,
} from "@/lib/commandCenterApi";

const healthBadgeConfig: Record<string, { bg: string; text: string; dot: string; label: string }> = {
  healthy: { bg: "bg-emerald-500/10 border-emerald-500/30", text: "text-emerald-400", dot: "bg-emerald-400", label: "Healthy" },
  degraded: { bg: "bg-amber-500/10 border-amber-500/30", text: "text-amber-400", dot: "bg-amber-400", label: "Degraded" },
  down: { bg: "bg-red-500/10 border-red-500/30", text: "text-red-400", dot: "bg-red-500 animate-pulse", label: "Down / Critical" },
  unknown: { bg: "bg-zinc-500/10 border-zinc-500/30", text: "text-zinc-400", dot: "bg-zinc-500", label: "Unknown / Stale" },
};

export default function ServicesOperationalHub() {
  const { token } = useAuth();
  const [data, setData] = useState<OperationalServicesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Pagination state
  const [tierFilter, setTierFilter] = useState<string>("all");
  const [healthFilter, setHealthFilter] = useState<string>("all");
  const [page, setPage] = useState<number>(1);
  const pageSize = 20;

  // Active probing state
  const [probingServiceId, setProbingServiceId] = useState<string | null>(null);
  const [probeMessage, setProbeMessage] = useState<string | null>(null);

  const fetchServices = useCallback(async () => {
    try {
      setLoading(true);
      const res = await commandCenterApi.getOperationalServices({
        tier: tierFilter,
        health: healthFilter,
        page: page,
        page_size: pageSize,
      });
      setData(res);
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load services";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [tierFilter, healthFilter, page]);

  useEffect(() => {
    fetchServices();
  }, [fetchServices]);

  const handleProbe = async (svc: OperationalServiceItem) => {
    setProbingServiceId(svc.id);
    setProbeMessage(null);
    try {
      const res = await commandCenterApi.triggerQuickProbe(svc.id, svc.environment);
      setProbeMessage(`Probe executed for ${svc.name}: HTTP ${res.http_status_code} (${res.latency_ms}ms) -> ${res.health_status_after}`);
      fetchServices();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Probe failed";
      setProbeMessage(`Probe error: ${msg}`);
    } finally {
      setProbingServiceId(null);
    }
  };

  const healthyCount = data?.items.filter((s) => s.health_status === "healthy").length ?? 0;
  const degradedCount = data?.items.filter((s) => s.health_status === "degraded").length ?? 0;
  const downCount = data?.items.filter((s) => s.health_status === "down").length ?? 0;

  return (
    <>
      <TopBar
        title="Fleet Services Hub"
        subtitle="Live microservice telemetry, health rules matrix, and on-demand diagnostic probes"
        breadcrumbs={[{ label: "Services", active: true }]}
      />
      <main className="flex-1 p-6 pb-12 overflow-y-auto bg-surface text-on-surface">
        <div className="max-w-[1500px] mx-auto space-y-6">

          {/* Operational Metrics Strip */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-on-surface-variant font-mono">Total Services</div>
                <div className="text-2xl font-bold text-on-surface mt-1 font-mono">{data?.total ?? 0}</div>
              </div>
              <span className="material-symbols-outlined text-primary text-[28px]">dns</span>
            </div>

            <div className="bg-surface-container-low border border-emerald-500/30 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-emerald-400 font-mono">Healthy Fleet</div>
                <div className="text-2xl font-bold text-emerald-400 mt-1 font-mono">{healthyCount}</div>
              </div>
              <span className="material-symbols-outlined text-emerald-400 text-[28px]">check_circle</span>
            </div>

            <div className="bg-surface-container-low border border-amber-500/30 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-amber-400 font-mono">Degraded Services</div>
                <div className="text-2xl font-bold text-amber-400 mt-1 font-mono">{degradedCount}</div>
              </div>
              <span className="material-symbols-outlined text-amber-400 text-[28px]">warning</span>
            </div>

            <div className="bg-surface-container-low border border-red-500/30 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-red-400 font-mono">Down / Critical</div>
                <div className="text-2xl font-bold text-red-400 mt-1 font-mono">{downCount}</div>
              </div>
              <span className="material-symbols-outlined text-red-400 text-[28px]">crisis_alert</span>
            </div>
          </div>

          {/* Filter Bar */}
          <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-4">
              {/* Tier Filter */}
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-on-surface-variant font-mono">Tier:</span>
                <div className="flex bg-surface-container-high border border-outline-variant/80 rounded-lg p-0.5 text-[11px] font-mono">
                  {["all", "tier_1", "tier_2", "tier_3"].map((t) => (
                    <button
                      key={t}
                      onClick={() => { setTierFilter(t); setPage(1); }}
                      className={`px-3 py-1 rounded transition-all capitalize ${
                        tierFilter === t ? "bg-primary text-on-primary font-semibold shadow-sm" : "text-on-surface-variant hover:text-on-surface"
                      }`}
                    >
                      {t.replace("_", " ")}
                    </button>
                  ))}
                </div>
              </div>

              {/* Health Filter */}
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-on-surface-variant font-mono">Health:</span>
                <div className="flex bg-surface-container-high border border-outline-variant/80 rounded-lg p-0.5 text-[11px] font-mono">
                  {["all", "healthy", "degraded", "down", "unknown"].map((h) => (
                    <button
                      key={h}
                      onClick={() => { setHealthFilter(h); setPage(1); }}
                      className={`px-3 py-1 rounded transition-all capitalize ${
                        healthFilter === h ? "bg-primary text-on-primary font-semibold shadow-sm" : "text-on-surface-variant hover:text-on-surface"
                      }`}
                    >
                      {h}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => fetchServices()}
                className="px-3 py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant text-[12px] font-medium transition flex items-center gap-1.5"
              >
                <span className={`material-symbols-outlined text-[14px] ${loading ? "animate-spin" : ""}`}>
                  sync
                </span>
                Refresh
              </button>
              <Link
                href="/topology"
                className="px-3 py-1.5 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 text-[12px] font-medium transition flex items-center gap-1.5"
              >
                <span className="material-symbols-outlined text-[14px]">hub</span>
                Interactive Graph
              </Link>
            </div>
          </div>

          {probeMessage && (
            <div className="p-3 rounded-lg bg-surface-container border border-outline-variant text-[12px] font-mono text-primary flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px]">info</span>
              {probeMessage}
            </div>
          )}

          {error && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-[12px] flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px]">error</span>
              {error}
            </div>
          )}

          {/* Operational Services Table */}
          <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12px]">
                <thead className="bg-surface-container/60 border-b border-outline-variant/60 text-on-surface-variant font-mono">
                  <tr>
                    <th className="py-3 px-4">Service & Repository</th>
                    <th className="py-3 px-4">Tier & Env</th>
                    <th className="py-3 px-4">Health Status</th>
                    <th className="py-3 px-4">Runtime Telemetry</th>
                    <th className="py-3 px-4">Deployment</th>
                    <th className="py-3 px-4">Dependencies</th>
                    <th className="py-3 px-4">Incidents</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/40">
                  {loading ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-on-surface-variant font-mono">
                        Loading operational fleet matrix...
                      </td>
                    </tr>
                  ) : !data || data.items.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-on-surface-variant">
                        No services matched your filter criteria.
                      </td>
                    </tr>
                  ) : (
                    data.items.map((svc) => {
                      const badge = healthBadgeConfig[svc.health_status] || healthBadgeConfig.unknown;
                      return (
                        <tr key={svc.id} className="hover:bg-surface-container-high/40 transition">
                          {/* Service Name & Repo */}
                          <td className="py-3 px-4 space-y-0.5">
                            <div className="font-semibold text-on-surface flex items-center gap-1.5">
                              <span>{svc.name}</span>
                            </div>
                            <div className="text-[11px] text-on-surface-variant font-mono truncate max-w-[200px]">
                              {svc.repository_full_name || "No linked repository"}
                            </div>
                          </td>

                          {/* Tier & Env */}
                          <td className="py-3 px-4">
                            <span className="px-2 py-0.5 rounded bg-surface-container-high border border-outline-variant text-[10px] font-mono uppercase font-semibold">
                              {svc.tier}
                            </span>
                            <div className="text-[11px] text-on-surface-variant capitalize mt-0.5">{svc.environment}</div>
                          </td>

                          {/* Health Status & Reason */}
                          <td className="py-3 px-4 space-y-1">
                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border text-[11px] font-medium ${badge.bg} ${badge.text}`}>
                              <span className={`w-1.5 h-1.5 rounded-full ${badge.dot}`} />
                              {badge.label}
                            </span>
                            <div className="text-[10px] text-on-surface-variant/80 truncate max-w-[180px]">
                              {svc.health_reason}
                            </div>
                          </td>

                          {/* Runtime Telemetry */}
                          <td className="py-3 px-4 space-y-1 font-mono text-[11px]">
                            <div className="flex items-center gap-2">
                              <span className="text-on-surface-variant text-[10px]">ERR:</span>
                              <span className={svc.error_rate_percent && svc.error_rate_percent > 1 ? "text-amber-400 font-bold" : "text-on-surface"}>
                                {svc.error_rate_percent !== null ? `${svc.error_rate_percent}%` : "—"}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-on-surface-variant text-[10px]">p95:</span>
                              <span className="text-on-surface">{svc.p95_latency_ms ? `${svc.p95_latency_ms}ms` : "—"}</span>
                            </div>
                          </td>

                          {/* Deployment */}
                          <td className="py-3 px-4 space-y-0.5 font-mono text-[11px]">
                            <div className="text-on-surface font-semibold">{svc.version || "1.0.0"}</div>
                            <div className="text-[10px] text-on-surface-variant truncate">
                              {svc.commit_sha ? svc.commit_sha.slice(0, 7) : "HEAD"}
                            </div>
                          </td>

                          {/* Dependencies */}
                          <td className="py-3 px-4 font-mono text-[11px] space-y-0.5">
                            <div>↑ {svc.upstream_dependencies_count} Upstream</div>
                            <div className="text-on-surface-variant">↓ {svc.downstream_dependents_count} Downstream</div>
                          </td>

                          {/* Open Incidents */}
                          <td className="py-3 px-4 font-mono">
                            {svc.open_incidents_count > 0 ? (
                              <span className="px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30 text-[11px] font-bold">
                                {svc.open_incidents_count} Open
                              </span>
                            ) : (
                              <span className="text-on-surface-variant text-[11px]">0</span>
                            )}
                          </td>

                          {/* Actions */}
                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={() => handleProbe(svc)}
                              disabled={probingServiceId === svc.id}
                              className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-primary/20 hover:text-primary border border-outline-variant text-[11px] font-medium transition"
                            >
                              {probingServiceId === svc.id ? "Probing..." : "Probe"}
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {data && data.total_pages > 1 && (
              <div className="px-4 py-3 border-t border-outline-variant/60 bg-surface-container/30 flex items-center justify-between text-[11px] font-mono">
                <span className="text-on-surface-variant">
                  Showing page {data.page} of {data.total_pages} ({data.total} services)
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={data.page <= 1}
                    className="px-2.5 py-1 rounded bg-surface-container border border-outline-variant disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(data.total_pages, p + 1))}
                    disabled={data.page >= data.total_pages}
                    className="px-2.5 py-1 rounded bg-surface-container border border-outline-variant disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>

        </div>
      </main>
    </>
  );
}
