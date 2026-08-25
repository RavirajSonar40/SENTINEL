"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listIncidents, Incident, getMetrics, getSystemHealth, listPendingApprovals, PendingApproval, SystemHealth } from "@/lib/api";

const statusColors: Record<string, string> = {
  detected: "bg-tertiary/15 text-tertiary",
  created: "bg-outline/15 text-outline",
  investigation_queued: "bg-tertiary/15 text-tertiary",
  investigating: "bg-primary/15 text-primary",
  root_cause_analysis: "bg-primary/15 text-primary",
  root_cause_identified: "bg-primary/15 text-primary",
  fix_generated: "bg-tertiary/15 text-tertiary",
  fix_validating: "bg-tertiary/15 text-tertiary",
  awaiting_approval: "bg-tertiary/15 text-tertiary",
  approved: "bg-primary/15 text-primary",
  resolved: "bg-outline/15 text-outline",
  insufficient_evidence: "bg-error/15 text-error",
  investigation_failed: "bg-error/15 text-error",
  cancelled: "bg-outline/15 text-outline",
};

const severityDot: Record<string, string> = {
  "SEV-1": "bg-error",
  "SEV-2": "bg-tertiary",
  "SEV-3": "bg-primary",
  "SEV-4": "bg-outline",
};

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function Dashboard() {
  const { token } = useAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [metrics, setMetrics] = useState<any>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      listIncidents(token).catch(() => []),
      listPendingApprovals(token).catch(() => []),
      getMetrics(token).catch(() => null),
      getSystemHealth(token).catch(() => null),
    ]).then(([inc, appr, met, hlt]) => {
      setIncidents(inc);
      setApprovals(appr);
      setMetrics(met);
      setHealth(hlt);
    }).finally(() => setLoading(false));
  }, [token]);

  const active = incidents.filter((i) => !["resolved", "cancelled"].includes(i.status));
  const investigating = incidents.filter((i) => i.status === "investigating");
  const resolved = incidents.filter((i) => i.status === "resolved");
  const critical = incidents.filter((i) => i.severity === "SEV-1" && !["resolved", "cancelled"].includes(i.status));

  const computeMTTR = () => {
    const resolvedIncidents = incidents.filter((i) => i.status === "resolved" && i.resolved_at && i.created_at);
    if (resolvedIncidents.length === 0) return { value: "—", detail: "No resolved incidents" };
    const totalMinutes = resolvedIncidents.reduce((sum, inc) => {
      const diff = new Date(inc.resolved_at!).getTime() - new Date(inc.created_at).getTime();
      return sum + diff / 60000;
    }, 0);
    const avgMinutes = totalMinutes / resolvedIncidents.length;
    if (avgMinutes < 60) return { value: `${Math.round(avgMinutes)}m`, detail: `Based on ${resolvedIncidents.length} incidents` };
    const hrs = Math.floor(avgMinutes / 60);
    const mins = Math.round(avgMinutes % 60);
    return { value: `${hrs}h ${mins}m`, detail: `Based on ${resolvedIncidents.length} incidents` };
  };
  const mttr = computeMTTR();

  return (
    <>
      <TopBar title="Overview" />
      <main className="flex-1 p-6 overflow-y-auto pb-10">
        <div className="max-w-[1400px] mx-auto">

          {/* Stat Cards */}
          <div className="grid grid-cols-5 gap-4 mb-6">
            <StatCard
              label="Active Incidents"
              value={active.length}
              detail={`${critical.length} Critical`}
              icon="warning"
              color="error"
              trend={null}
            />
            <StatCard
              label="Investigations"
              value={investigating.length}
              detail={`${incidents.filter((i) => i.status === "awaiting_approval").length} Awaiting Review`}
              icon="psychology"
              color="primary"
              trend={null}
            />
            <StatCard
              label="MTTR (30d)"
              value={mttr.value}
              detail={mttr.detail}
              icon="schedule"
              color="tertiary"
              trend={null}
            />
            <StatCard
              label="Incidents Resolved"
              value={resolved.length}
              detail={`${metrics?.incidents?.last_24h || 0} in 24h`}
              icon="check_circle"
              color="primary"
              trend="up"
            />
            <StatCard
              label="Draft PRs"
              value={approvals.length}
              detail={`${approvals.length} Awaiting Approval`}
              icon="merge"
              color="tertiary"
              trend={null}
            />
          </div>

          <div className="grid grid-cols-3 gap-4">
            {/* Left Column - 2/3 */}
            <div className="col-span-2 flex flex-col gap-4">

              {/* Recent Incidents */}
              <div className="bg-surface-container-low border border-outline-variant rounded-lg overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant">
                  <h2 className="text-[13px] font-semibold text-on-surface">Recent Incidents</h2>
                  <Link href="/incidents" className="text-[12px] text-primary hover:underline">View all</Link>
                </div>
                {loading ? (
                  <div className="p-8 text-center text-on-surface-variant text-[12px] font-mono">Loading...</div>
                ) : incidents.length === 0 ? (
                  <div className="p-8 text-center text-on-surface-variant text-[12px]">No incidents yet</div>
                ) : (
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-outline-variant bg-surface-container">
                        <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">ID</th>
                        <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">SEV</th>
                        <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">SERVICE</th>
                        <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">TITLE</th>
                        <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">STATUS</th>
                        <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">DETECTED</th>
                        <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">UPDATED</th>
                      </tr>
                    </thead>
                    <tbody className="font-mono text-[11px]">
                      {incidents.slice(0, 5).map((inc) => (
                        <tr key={inc.id} className="border-b border-outline-variant/50 hover:bg-surface-container-high/50 transition-colors">
                          <td className="py-2.5 px-4">
                            <Link href={`/incidents/${inc.id}`} className="text-primary hover:underline">
                              INC-{inc.number}
                            </Link>
                          </td>
                          <td className="py-2.5 px-4">
                            <span className={`inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                              inc.severity === "SEV-1" ? "bg-error/10 text-error border-error/20" :
                              inc.severity === "SEV-2" ? "bg-tertiary/10 text-tertiary border-tertiary/20" :
                              inc.severity === "SEV-3" ? "bg-primary/10 text-primary border-primary/20" :
                              "bg-surface-variant text-on-surface-variant border-outline-variant"
                            }`}>
                              <span className={`w-1.5 h-1.5 rounded-full ${severityDot[inc.severity]}`} />
                              {inc.severity}
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-on-surface-variant">{inc.service || "—"}</td>
                          <td className="py-2.5 px-4 text-on-surface truncate max-w-[200px]">{inc.title}</td>
                          <td className="py-2.5 px-4">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${statusColors[inc.status] || "bg-outline/15 text-outline"}`}>
                              {inc.status.replace(/_/g, " ")}
                            </span>
                          </td>
                          <td className="py-2.5 px-4 text-on-surface-variant">{timeAgo(inc.created_at)}</td>
                          <td className="py-2.5 px-4 text-on-surface-variant">{timeAgo(inc.updated_at || inc.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Investigation Pipeline */}
              <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
                <div className="flex items-center gap-3 mb-4">
                  <h2 className="text-[13px] font-semibold text-on-surface">Investigation Pipeline</h2>
                  {incidents.length > 0 && (
                    <span className="text-[11px] text-on-surface-variant">
                      INC-{incidents[0].number} &bull; {incidents[0].title}
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between px-2">
                  {["Detected", "Collected", "Analyzing", "Hypotheses", "Root Cause", "Fix", "Validation", "Review", "PR"].map((step, i) => {
                    const progress = incidents[0]?.investigation?.progress_percent || 35;
                    const stepProgress = (i / 8) * 100;
                    const isComplete = progress > stepProgress;
                    const isCurrent = !isComplete && progress > stepProgress - 12;
                    return (
                      <div key={step} className="flex flex-col items-center gap-1.5 relative">
                        {i > 0 && (
                          <div className={`absolute top-3 right-1/2 w-[calc(100%+20px)] h-0.5 ${
                            isComplete ? "bg-primary" : "bg-outline-variant"
                          }`} style={{ zIndex: 0 }} />
                        )}
                        <div className={`w-6 h-6 rounded-full flex items-center justify-center relative z-10 ${
                          isComplete ? "bg-primary text-on-primary" :
                          isCurrent ? "bg-primary/20 text-primary border border-primary" :
                          "bg-surface-container-highest text-on-surface-variant border border-outline-variant"
                        }`}>
                          <span className="material-symbols-outlined text-[14px]">
                            {isComplete ? "check" : i === 0 ? "warning" : i < 4 ? "search" : "code"}
                          </span>
                        </div>
                        <span className={`text-[10px] ${isCurrent ? "text-primary font-semibold" : "text-on-surface-variant"}`}>{step}</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* System Health */}
              <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-[13px] font-semibold text-on-surface">System Health</h2>
                  <Link href="/health" className="text-[11px] text-primary hover:underline">Details</Link>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    {health?.checks && Object.keys(health.checks).length > 0 ? Object.entries(health.checks).map(([name, check]) => (
                      <div key={name} className="flex items-center justify-between text-[12px]">
                        <span className="text-on-surface-variant font-mono">{name}</span>
                        <span className={`flex items-center gap-1.5 ${check.status === "operational" || check.status === "configured" ? "text-primary" : "text-error"}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${check.status === "operational" || check.status === "configured" ? "bg-primary" : "bg-error"}`} />
                          {check.status}
                        </span>
                      </div>
                    )) : (
                      <div className="text-[12px] text-on-surface-variant">No data yet</div>
                    )}
                  </div>
                  <div className="bg-surface-container rounded border border-outline-variant p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] text-on-surface-variant">Active Incidents</span>
                      <span className="text-[11px] font-mono text-on-surface">{active.length}</span>
                    </div>
                    <div className="space-y-1">
                      {["SEV-1", "SEV-2", "SEV-3", "SEV-4"].map((sev) => {
                        const count = active.filter((i) => i.severity === sev).length;
                        return (
                          <div key={sev} className="flex items-center gap-2 text-[11px]">
                            <span className={`w-2 h-2 rounded-full ${severityDot[sev]}`} />
                            <span className="text-on-surface-variant">{sev}</span>
                            <span className="ml-auto font-mono">{count}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Column - 1/3 */}
            <div className="flex flex-col gap-4">

              {/* Quick Actions */}
              <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
                <h2 className="text-[13px] font-semibold text-on-surface mb-3">Quick Actions</h2>
                <div className="grid grid-cols-1 gap-2">
                  {[
                    { label: "Report Error", desc: "Manual investigation", icon: "add_circle", href: "/incidents/new" },
                    { label: "View Services", desc: "Service health", icon: "settings_input_component", href: "/services" },
                    { label: "View Integrations", desc: "Manage connections", icon: "hub", href: "/integrations" },
                    { label: "View PRs", desc: "Approval queue", icon: "merge", href: "/pull-requests" },
                  ].map((action) => (
                    <Link
                      key={action.label}
                      href={action.href}
                      className="flex items-center gap-3 p-3 bg-surface-container rounded border border-outline-variant hover:border-primary/30 transition-colors group"
                    >
                      <span className="material-symbols-outlined text-[18px] text-on-surface-variant group-hover:text-primary transition-colors">
                        {action.icon}
                      </span>
                      <div className="flex-1">
                        <div className="text-[12px] font-medium text-on-surface">{action.label}</div>
                        <div className="text-[10px] text-on-surface-variant">{action.desc}</div>
                      </div>
                      <span className="material-symbols-outlined text-[14px] text-on-surface-variant group-hover:text-primary transition-colors">
                        chevron_right
                      </span>
                    </Link>
                  ))}
                </div>
              </div>

              {/* Recent Draft PRs */}
              <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-[13px] font-semibold text-on-surface">Awaiting Approval</h2>
                  <Link href="/pull-requests" className="text-primary text-[11px] hover:underline">View all</Link>
                </div>
                <div className="space-y-3">
                  {approvals.length === 0 ? (
                    <div className="text-[12px] text-on-surface-variant">No pending approvals</div>
                  ) : (
                    approvals.slice(0, 4).map((pr) => (
                      <div key={pr.fix_id} className="text-[12px]">
                        <div className="flex items-center gap-2">
                          <span className="text-on-surface truncate flex-1">{pr.title}</span>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          {pr.incident_number && <span className="text-on-surface-variant text-[11px]">INC-{pr.incident_number}</span>}
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-tertiary/10 text-tertiary">Awaiting Approval</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* AI Investigator */}
              <div className="bg-gradient-to-br from-primary/10 to-tertiary/5 border border-primary/20 rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-[20px] text-primary">smart_toy</span>
                  <h2 className="text-[13px] font-semibold text-on-surface">AI Investigator</h2>
                </div>
                <p className="text-[12px] text-on-surface-variant leading-relaxed mb-3">
                  I automatically investigate incidents, find root causes, and suggest fixes.
                </p>
                <Link href="/incidents/new" className="block w-full py-2 bg-primary/10 hover:bg-primary/20 text-primary text-[12px] font-semibold rounded-md transition-colors text-center">
                  Report New Incident
                </Link>
              </div>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

function StatCard({ label, value, detail, icon, color, trend }: {
  label: string;
  value: number | string;
  detail: string;
  icon: string;
  color: string;
  trend: "up" | "down" | null;
}) {
  return (
    <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">{label}</span>
        <span className={`material-symbols-outlined text-[18px] text-${color}`}>{icon}</span>
      </div>
      <div className="text-[28px] font-bold text-on-surface leading-none mb-1">{value}</div>
      <div className="flex items-center gap-1 text-[11px] text-on-surface-variant">
        {trend && (
          <span className={`material-symbols-outlined text-[12px] ${trend === "up" ? "text-primary" : "text-error"}`}>
            {trend === "up" ? "trending_up" : "trending_down"}
          </span>
        )}
        {detail}
      </div>
    </div>
  );
}
