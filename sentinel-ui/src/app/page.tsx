"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import {
  commandCenterApi,
  CommandCenterOverview,
  ActiveCommandIncidentItem,
} from "@/lib/commandCenterApi";

const severityDot: Record<string, string> = {
  "SEV-1": "bg-red-500 text-red-100 ring-red-500/30",
  "SEV-2": "bg-amber-500 text-amber-100 ring-amber-500/30",
  "SEV-3": "bg-blue-500 text-blue-100 ring-blue-500/30",
  "SEV-4": "bg-zinc-500 text-zinc-100 ring-zinc-500/30",
};

const healthBadge: Record<string, { bg: string; text: string; dot: string }> = {
  healthy: { bg: "bg-emerald-500/10 border-emerald-500/30", text: "text-emerald-400", dot: "bg-emerald-400" },
  degraded: { bg: "bg-amber-500/10 border-amber-500/30", text: "text-amber-400", dot: "bg-amber-400" },
  down: { bg: "bg-red-500/10 border-red-500/30", text: "text-red-400", dot: "bg-red-500 animate-pulse" },
  unknown: { bg: "bg-zinc-500/10 border-zinc-500/30", text: "text-zinc-400", dot: "bg-zinc-500" },
};

function formatTimeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function OperationsCommandCenter() {
  const { token } = useAuth();
  const [overview, setOverview] = useState<CommandCenterOverview | null>(null);

  const [activeFeed, setActiveFeed] = useState<ActiveCommandIncidentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Polling configuration: 5s, 15s, 30s, or 0 (paused)
  const [pollInterval, setPollInterval] = useState<number>(5000);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date>(new Date());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [probeServiceId, setProbeServiceId] = useState<string>("");
  const [probeResult, setProbeResult] = useState<string | null>(null);
  const [isProbing, setIsProbing] = useState(false);

  const fetchOperationalData = useCallback(async (isManual = false) => {
    if (isManual) setIsRefreshing(true);
    try {
      const [ovData, actData] = await Promise.all([
        commandCenterApi.getOverview(),
        commandCenterApi.getActiveCommandFeed(),
      ]);
      setOverview(ovData);
      setActiveFeed(actData.active_incidents);
      setLastRefreshedAt(new Date());
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load command center data";
      setError(msg);
    } finally {
      setLoading(false);
      if (isManual) setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchOperationalData();
    if (pollInterval <= 0) return;

    const timer = setInterval(() => {
      // Adaptive backoff: if document is hidden, poll less frequently
      if (document.hidden && pollInterval < 15000) return;
      fetchOperationalData();
    }, pollInterval);

    return () => clearInterval(timer);
  }, [pollInterval, fetchOperationalData]);

  const handleQuickProbe = async (serviceId: string) => {
    if (!serviceId) return;
    setIsProbing(true);
    setProbeResult(null);
    try {
      const res = await commandCenterApi.triggerQuickProbe(serviceId);
      setProbeResult(`Probe success: ${res.service_name} status is ${res.health_status_after} (${res.latency_ms}ms)`);
      fetchOperationalData(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Probe failed";
      setProbeResult(`Probe failed: ${msg}`);
    } finally {
      setIsProbing(false);
    }
  };

  const inc = overview?.incidents_summary;
  const fleet = overview?.service_fleet;
  const dep = overview?.deployments_summary;
  const rem = overview?.remediation_summary;
  const rel = overview?.reliability_summary;

  return (
    <>
      <TopBar title="Operations Command Center" />
      <main className="flex-1 p-6 overflow-y-auto pb-12 bg-surface text-on-surface">
        <div className="max-w-[1500px] mx-auto space-y-6">

          {/* Top Live Operations Header & Transport Controls */}
          <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 shadow-sm">
            <div className="flex items-center gap-3">
              <div className="relative flex h-3.5 w-3.5">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${pollInterval > 0 ? "bg-emerald-400" : "bg-zinc-500"}`} />
                <span className={`relative inline-flex rounded-full h-3.5 w-3.5 ${pollInterval > 0 ? "bg-emerald-500" : "bg-zinc-500"}`} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold tracking-wide uppercase text-on-surface">
                    Live Operations Stream
                  </span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-surface-container-high border border-outline-variant text-primary font-mono font-medium">
                    {overview?.organization_name || "Sentinel"}
                  </span>
                </div>
                <p className="text-[11px] text-on-surface-variant">
                  Transport: Live Polling (Adaptive 5s–30s) • Refreshed: {lastRefreshedAt.toLocaleTimeString()}
                </p>
              </div>
            </div>

            {/* Interval Controls & Refresh */}
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-on-surface-variant font-mono">Interval:</span>
              <div className="flex bg-surface-container-high border border-outline-variant/80 rounded-lg p-0.5 text-[11px] font-mono">
                {[
                  { label: "5s", value: 5000 },
                  { label: "15s", value: 15000 },
                  { label: "30s", value: 30000 },
                  { label: "Pause", value: 0 },
                ].map((item) => (
                  <button
                    key={item.label}
                    onClick={() => setPollInterval(item.value)}
                    className={`px-2.5 py-1 rounded transition-all ${
                      pollInterval === item.value
                        ? "bg-primary text-on-primary font-semibold shadow-sm"
                        : "text-on-surface-variant hover:text-on-surface"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              <button
                onClick={() => fetchOperationalData(true)}
                disabled={isRefreshing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant text-[12px] font-medium transition"
              >
                <span className={`material-symbols-outlined text-[14px] ${isRefreshing ? "animate-spin" : ""}`}>
                  sync
                </span>
                Refresh
              </button>

              <Link
                href="/topology"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 text-[12px] font-medium transition"
              >
                <span className="material-symbols-outlined text-[14px]">hub</span>
                Topology
              </Link>
            </div>
          </div>

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 text-red-300 p-3 rounded-lg text-[12px] flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px]">error</span>
              {error}
            </div>
          )}

          {/* 8 Core Operational KPI Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
            {/* 1. Active Incidents */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-on-surface-variant text-[11px] font-medium">
                <span>Active Incidents</span>
                <span className="material-symbols-outlined text-red-400 text-[16px]">crisis_alert</span>
              </div>
              <div className="my-2">
                <span className="text-2xl font-bold text-on-surface font-mono">{inc?.active_total ?? 0}</span>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-red-400 font-mono">
                <span className="px-1.5 py-0.2 rounded bg-red-500/20 font-bold">{inc?.critical_sev1 ?? 0} SEV-1</span>
                <span>{inc?.major_sev2 ?? 0} SEV-2</span>
              </div>
            </div>

            {/* 2. Service Fleet Health */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-on-surface-variant text-[11px] font-medium">
                <span>Fleet Health</span>
                <span className="material-symbols-outlined text-emerald-400 text-[16px]">dns</span>
              </div>
              <div className="my-2">
                <span className="text-2xl font-bold text-emerald-400 font-mono">
                  {fleet?.total_services ? `${Math.round((fleet.healthy / fleet.total_services) * 100)}%` : "—"}
                </span>
              </div>
              <div className="text-[10px] text-on-surface-variant font-mono">
                {fleet?.healthy ?? 0}/{fleet?.total_services ?? 0} Healthy
              </div>
            </div>

            {/* 3. Deployment Velocity */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-on-surface-variant text-[11px] font-medium">
                <span>Deployments (24h)</span>
                <span className="material-symbols-outlined text-blue-400 text-[16px]">rocket_launch</span>
              </div>
              <div className="my-2">
                <span className="text-2xl font-bold text-on-surface font-mono">{dep?.total_last_24h ?? 0}</span>
              </div>
              <div className="text-[10px] text-on-surface-variant font-mono">
                {dep?.failure_rate_percent ?? 0}% Fail Rate
              </div>
            </div>

            {/* 4. Multi-Repo Draft PRs */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-on-surface-variant text-[11px] font-medium">
                <span>Draft PR Queue</span>
                <span className="material-symbols-outlined text-amber-400 text-[16px]">call_split</span>
              </div>
              <div className="my-2">
                <span className="text-2xl font-bold text-amber-400 font-mono">{rem?.pending_approvals ?? 0}</span>
              </div>
              <div className="text-[10px] text-on-surface-variant font-mono">
                {rem?.active_plans ?? 0} Multi-Repo Plans
              </div>
            </div>

            {/* 5. Error Budget */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-on-surface-variant text-[11px] font-medium">
                <span>Error Budget</span>
                <span className="material-symbols-outlined text-indigo-400 text-[16px]">pie_chart</span>
              </div>
              <div className="my-2">
                <span className={`text-2xl font-bold font-mono ${rel?.error_budget?.status === "exhausted" ? "text-red-400" : "text-on-surface"}`}>
                  {rel?.error_budget?.display ?? "—"}
                </span>
              </div>
              <div className="text-[10px] text-on-surface-variant font-mono">
                SLO: {rel?.error_budget?.slo_target_percent ?? 99.9}%
              </div>
            </div>

            {/* 6. MTTD & MTTR */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-on-surface-variant text-[11px] font-medium">
                <span>MTTD / MTTR</span>
                <span className="material-symbols-outlined text-cyan-400 text-[16px]">timer</span>
              </div>
              <div className="my-2">
                <span className="text-xl font-bold text-on-surface font-mono">
                  {inc?.mttd?.display ?? "—"} / {inc?.mttr?.display ?? "—"}
                </span>
              </div>
              <div className="text-[10px] text-on-surface-variant font-mono">
                Sample: {inc?.mttr?.sample_size ?? 0} Incidents
              </div>
            </div>

            {/* 7. Auto-Remediation */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-on-surface-variant text-[11px] font-medium">
                <span>Remediation Rate</span>
                <span className="material-symbols-outlined text-teal-400 text-[16px]">auto_fix_high</span>
              </div>
              <div className="my-2">
                <span className="text-2xl font-bold text-teal-400 font-mono">
                  {rem?.remediation_success_display ?? "—"}
                </span>
              </div>
              <div className="text-[10px] text-on-surface-variant font-mono">Validated Fixes (7d)</div>
            </div>

            {/* 8. Policy Protection */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-3.5 flex flex-col justify-between">
              <div className="flex items-center justify-between text-on-surface-variant text-[11px] font-medium">
                <span>Policy Gateway</span>
                <span className="material-symbols-outlined text-emerald-400 text-[16px]">verified_user</span>
              </div>
              <div className="my-2">
                <span className="text-xl font-bold text-emerald-400 font-mono">ENFORCED</span>
              </div>
              <div className="text-[10px] text-on-surface-variant font-mono">Zero Auto-Merge</div>
            </div>
          </div>

          {/* Main 2-Column Command Workspace */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

            {/* Left 2 Columns: Live Incident Command Feed & Multi-Repo Queue */}
            <div className="lg:col-span-2 space-y-6">

              {/* Active Incident Command Feed */}
              <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
                <div className="flex items-center justify-between px-5 py-3.5 border-b border-outline-variant/60 bg-surface-container/40">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-[18px]">radiology</span>
                    <h2 className="text-[14px] font-semibold text-on-surface">Active Incident Command Matrix</h2>
                    <span className="px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary text-[11px] font-mono font-medium">
                      {activeFeed.length} In-Flight
                    </span>
                  </div>
                  <Link href="/incidents" className="text-[12px] text-primary hover:underline font-medium">
                    All Incidents →
                  </Link>
                </div>

                {loading ? (
                  <div className="p-12 text-center text-on-surface-variant text-[12px] font-mono">
                    Loading live incident stream...
                  </div>
                ) : activeFeed.length === 0 ? (
                  <div className="p-12 text-center text-on-surface-variant space-y-2">
                    <span className="material-symbols-outlined text-emerald-400 text-[36px]">verified</span>
                    <p className="text-[13px] font-medium text-on-surface">Zero Active Incidents</p>
                    <p className="text-[11px]">Microservice fleet is operating within normal reliability thresholds.</p>
                  </div>
                ) : (
                  <div className="divide-y divide-outline-variant/40">
                    {activeFeed.map((item) => (
                      <div key={item.id} className="p-4 hover:bg-surface-container-high/40 transition flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                        <div className="space-y-1.5 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`px-2 py-0.5 text-[10px] font-bold rounded-full ring-1 ${severityDot[item.severity] || "bg-zinc-600"}`}>
                              {item.severity}
                            </span>
                            <Link href={`/incidents/${item.id}`} className="text-[13px] font-semibold text-on-surface hover:text-primary transition">
                              {item.title}
                            </Link>
                          </div>

                          <div className="flex flex-wrap items-center gap-3 text-[11px] text-on-surface-variant font-mono">
                            <span className="flex items-center gap-1">
                              <span className="material-symbols-outlined text-[13px]">cloud</span>
                              {item.service_name || "Unassigned Service"}
                            </span>
                            <span>•</span>
                            <span className="flex items-center gap-1">
                              <span className="material-symbols-outlined text-[13px]">hub</span>
                              Blast Radius: {item.blast_radius_service_count} services
                            </span>
                            <span>•</span>
                            <span className="flex items-center gap-1">
                              <span className="material-symbols-outlined text-[13px]">folder_copy</span>
                              {item.candidate_repos_count} Candidate Repos
                            </span>
                            <span>•</span>
                            <span className="text-zinc-400">Duration: {item.duration_minutes}m</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-2 self-end sm:self-center">
                          {item.has_active_remediation_plan && (
                            <span className="px-2 py-1 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-[11px] font-mono">
                              Plan: {item.remediation_plan_status || "Active"}
                            </span>
                          )}

                          <Link
                            href={`/incidents/${item.id}`}
                            className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-on-primary text-[12px] font-semibold transition shadow-sm flex items-center gap-1"
                          >
                            <span>Enter Workspace</span>
                            <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                          </Link>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Multi-Repo Draft PR & In-Flight Remediation Queue */}
              <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
                <div className="flex items-center justify-between px-5 py-3.5 border-b border-outline-variant/60 bg-surface-container/40">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-amber-400 text-[18px]">rule_folder</span>
                    <h2 className="text-[14px] font-semibold text-on-surface">Multi-Repository Draft PR & Policy Gate Queue</h2>
                  </div>
                  <Link href="/pull-requests" className="text-[12px] text-primary hover:underline font-medium">
                    Review Queue ({rem?.pending_approvals ?? 0}) →
                  </Link>
                </div>

                <div className="p-4 space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className="p-3 rounded-lg bg-surface-container border border-outline-variant/50">
                      <div className="text-[11px] text-on-surface-variant font-mono">Active Coordinated Plans</div>
                      <div className="text-xl font-bold text-on-surface mt-1 font-mono">{rem?.active_plans ?? 0}</div>
                    </div>
                    <div className="p-3 rounded-lg bg-surface-container border border-outline-variant/50">
                      <div className="text-[11px] text-on-surface-variant font-mono">Pending Policy Approvals</div>
                      <div className="text-xl font-bold text-amber-400 mt-1 font-mono">{rem?.pending_approvals ?? 0}</div>
                    </div>
                    <div className="p-3 rounded-lg bg-surface-container border border-outline-variant/50">
                      <div className="text-[11px] text-on-surface-variant font-mono">Published GitHub Draft PRs</div>
                      <div className="text-xl font-bold text-emerald-400 mt-1 font-mono">{rem?.draft_prs_published ?? 0}</div>
                    </div>
                  </div>

                  <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-[11px] text-amber-200/90 flex items-start gap-2">
                    <span className="material-symbols-outlined text-[16px] text-amber-400 mt-0.5">policy</span>
                    <div>
                      <strong className="text-amber-200">Strict Safety Invariant:</strong> Sentinel generates GitHub Draft PRs with verified base commit snapshots and rollback plans. Human peer review in GitHub is strictly required before any code merges or deploys to production.
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Column: Service Fleet Status & Live Diagnostic Quick Actions */}
            <div className="space-y-6">

              {/* Service Fleet Health Matrix */}
              <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
                <div className="flex items-center justify-between px-5 py-3.5 border-b border-outline-variant/60 bg-surface-container/40">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-emerald-400 text-[18px]">health_metrics</span>
                    <h2 className="text-[14px] font-semibold text-on-surface">Service Fleet Status</h2>
                  </div>
                  <Link href="/services" className="text-[12px] text-primary hover:underline font-medium">
                    View Fleet Matrix →
                  </Link>
                </div>

                <div className="p-4 space-y-4">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-between">
                      <span className="text-[11px] text-emerald-300 font-medium">Healthy</span>
                      <span className="text-base font-bold text-emerald-400 font-mono">{fleet?.healthy ?? 0}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-between">
                      <span className="text-[11px] text-amber-300 font-medium">Degraded</span>
                      <span className="text-base font-bold text-amber-400 font-mono">{fleet?.degraded ?? 0}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center justify-between">
                      <span className="text-[11px] text-red-300 font-medium">Down / Critical</span>
                      <span className="text-base font-bold text-red-400 font-mono">{fleet?.down ?? 0}</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-zinc-500/10 border border-zinc-500/20 flex items-center justify-between">
                      <span className="text-[11px] text-zinc-300 font-medium">Unknown / Stale</span>
                      <span className="text-base font-bold text-zinc-400 font-mono">{fleet?.unknown ?? 0}</span>
                    </div>
                  </div>

                  {/* Tier 1 Breakdown */}
                  <div className="p-3 rounded-lg bg-surface-container border border-outline-variant/40 space-y-1.5">
                    <div className="text-[11px] font-semibold text-on-surface flex items-center justify-between">
                      <span>Tier-1 Critical Services</span>
                      <span className="text-primary font-mono">{fleet?.tier1_healthy ?? 0}/{fleet?.tier1_total ?? 0} Healthy</span>
                    </div>
                    <div className="w-full bg-surface-container-high h-2 rounded-full overflow-hidden flex">
                      <div
                        className="bg-emerald-400 h-full"
                        style={{ width: `${fleet?.tier1_total ? ((fleet.tier1_healthy / fleet.tier1_total) * 100) : 100}%` }}
                      />
                      <div
                        className="bg-amber-400 h-full"
                        style={{ width: `${fleet?.tier1_total ? ((fleet.tier1_degraded / fleet.tier1_total) * 100) : 0}%` }}
                      />
                      <div
                        className="bg-red-400 h-full"
                        style={{ width: `${fleet?.tier1_total ? ((fleet.tier1_down / fleet.tier1_total) * 100) : 0}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Synthetic Diagnostic Probe Launcher */}
              <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
                <div className="px-5 py-3.5 border-b border-outline-variant/60 bg-surface-container/40 flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[18px]">network_check</span>
                  <h2 className="text-[14px] font-semibold text-on-surface">Diagnostic Synthetic Probe</h2>
                </div>

                <div className="p-4 space-y-3">
                  <p className="text-[11px] text-on-surface-variant">
                    Trigger an immediate synthetic health probe for a microservice (Member role required).
                  </p>

                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="Enter Service ID / UUID"
                      value={probeServiceId}
                      onChange={(e) => setProbeServiceId(e.target.value)}
                      className="flex-1 px-3 py-1.5 text-[12px] bg-surface-container border border-outline-variant rounded-lg font-mono focus:outline-none focus:border-primary"
                    />
                    <button
                      onClick={() => handleQuickProbe(probeServiceId)}
                      disabled={isProbing || !probeServiceId}
                      className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 disabled:opacity-50 text-on-primary text-[12px] font-semibold transition shadow-sm"
                    >
                      {isProbing ? "Probing..." : "Run Probe"}
                    </button>
                  </div>

                  {probeResult && (
                    <div className="p-2.5 rounded-lg bg-surface-container border border-outline-variant text-[11px] font-mono text-on-surface">
                      {probeResult}
                    </div>
                  )}
                </div>
              </div>

              {/* Chronological Activity Feed */}
              <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
                <div className="px-5 py-3.5 border-b border-outline-variant/60 bg-surface-container/40 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-on-surface-variant text-[18px]">history</span>
                    <h2 className="text-[14px] font-semibold text-on-surface">Live Event Stream</h2>
                  </div>
                  <span className="text-[10px] text-on-surface-variant font-mono">Last 24h</span>
                </div>

                <div className="p-4 max-h-[360px] overflow-y-auto space-y-3 divide-y divide-outline-variant/30">
                  {overview?.recent_activity?.length ? (
                    overview.recent_activity.map((act) => (
                      <div key={act.id} className="pt-2 first:pt-0 space-y-0.5">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-semibold text-on-surface">{act.title}</span>
                          <span className="text-[10px] text-on-surface-variant font-mono">{formatTimeAgo(act.timestamp)}</span>
                        </div>
                        <p className="text-[11px] text-on-surface-variant truncate">{act.description}</p>
                      </div>
                    ))
                  ) : (
                    <div className="text-center text-[11px] text-on-surface-variant py-6">
                      No events in the last 24 hours.
                    </div>
                  )}
                </div>
              </div>

            </div>
          </div>

        </div>
      </main>
    </>
  );
}
