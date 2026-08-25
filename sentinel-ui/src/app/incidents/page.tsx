"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listIncidents, Incident } from "@/lib/api";

const severityStyles: Record<string, string> = {
  "SEV-1": "bg-error/10 text-error border-error/20",
  "SEV-2": "bg-tertiary/10 text-tertiary border-tertiary/20",
  "SEV-3": "bg-primary/10 text-primary border-primary/20",
  "SEV-4": "bg-surface-variant text-on-surface-variant border-outline-variant",
};

const statusColors: Record<string, string> = {
  detected: "bg-tertiary/15 text-tertiary",
  created: "bg-outline/15 text-outline",
  investigating: "bg-primary/15 text-primary",
  root_cause_identified: "bg-primary/15 text-primary",
  fix_generated: "bg-tertiary/15 text-tertiary",
  awaiting_approval: "bg-tertiary/15 text-tertiary",
  approved: "bg-primary/15 text-primary",
  resolved: "bg-primary/15 text-primary",
  insufficient_evidence: "bg-error/15 text-error",
  cancelled: "bg-outline/15 text-outline",
};

const sourceIcons: Record<string, string> = {
  manual: "edit",
  alert: "notification_important",
  prometheus: "monitoring",
  sentry: "bug_report",
  webhook: "webhook",
  deployment_regression: "update",
};

const services = ["All Services", "payment-api", "auth-api", "core-api-gateway", "billing-api", "fraud-service"];
const severities = ["All Severities", "SEV-1", "SEV-2", "SEV-3", "SEV-4"];
const statuses = ["All Statuses", "created", "investigating", "root_cause_identified", "fix_generated", "awaiting_approval", "resolved", "insufficient_evidence"];
const sources = ["All Sources", "manual", "alert", "prometheus", "sentry", "webhook", "deployment_regression"];

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function IncidentsPage() {
  const { token } = useAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterSeverity, setFilterSeverity] = useState("All Severities");
  const [filterStatus, setFilterStatus] = useState("All Statuses");
  const [filterSource, setFilterSource] = useState("All Sources");
  const [filterService, setFilterService] = useState("All Services");
  const [page, setPage] = useState(1);
  const perPage = 10;

  useEffect(() => {
    if (!token) return;
    listIncidents(token)
      .then(setIncidents)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token]);

  const filtered = incidents.filter((i) => {
    if (filterSeverity !== "All Severities" && i.severity !== filterSeverity) return false;
    if (filterStatus !== "All Statuses" && i.status !== filterStatus) return false;
    if (filterSource !== "All Sources" && i.source !== filterSource) return false;
    if (filterService !== "All Services" && i.service !== filterService) return false;
    return true;
  });

  const totalPages = Math.ceil(filtered.length / perPage);
  const paged = filtered.slice((page - 1) * perPage, page * perPage);

  return (
    <>
      <TopBar
        title="Incidents"
        subtitle="View and manage all incidents across your systems. Click an incident to view full investigation."
        actions={
          <div className="flex gap-2 mr-4">
            <Link
              href="/automatic-response"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-container-high border border-outline-variant text-on-surface text-[11px] font-semibold uppercase tracking-wider rounded-md hover:bg-surface-bright transition-colors"
            >
              <span className="material-symbols-outlined text-[14px]">bolt</span>
              Automatic Response
            </Link>
            <Link
              href="/incidents/new"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-container text-on-primary-container text-[11px] font-semibold uppercase tracking-wider rounded-md border border-primary hover:bg-primary hover:text-on-primary-fixed transition-colors"
            >
              <span className="material-symbols-outlined text-[14px]">add</span>
              Report Incident
            </Link>
          </div>
        }
      />
      <main className="flex-1 p-6 overflow-x-auto pb-10">
        <div className="max-w-[1400px] mx-auto">

          {/* Filters */}
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <SelectFilter label="Severity" options={severities} value={filterSeverity} onChange={setFilterSeverity} />
            <SelectFilter label="Status" options={statuses} value={filterStatus} onChange={setFilterStatus} />
            <SelectFilter label="Source" options={sources} value={filterSource} onChange={setFilterSource} />
            <SelectFilter label="Service" options={services} value={filterService} onChange={setFilterService} />
            <button
              onClick={() => { setFilterSeverity("All Severities"); setFilterStatus("All Statuses"); setFilterSource("All Sources"); setFilterService("All Services"); }}
              className="text-[11px] text-on-surface-variant hover:text-primary transition-colors ml-2"
            >
              Clear
            </button>
          </div>

          <div className="text-[12px] text-on-surface-variant mb-3">
            Showing {filtered.length} incidents
          </div>

          {loading ? (
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-8 text-center">
              <div className="text-on-surface-variant font-mono text-[12px]">Loading incidents...</div>
            </div>
          ) : filtered.length === 0 ? (
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-8 text-center">
              <span className="material-symbols-outlined text-[48px] text-on-surface-variant/20 block mb-2">emergency</span>
              <div className="text-[13px] text-on-surface-variant">No incidents yet</div>
              <Link href="/incidents/new" className="text-[12px] text-primary hover:underline mt-2 inline-block">Report your first incident</Link>
            </div>
          ) : (
            <div className="bg-surface-container-low border border-outline-variant rounded-lg overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-outline-variant bg-surface-container">
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">ID</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">SEVERITY</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">SOURCE</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">SERVICE</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">TITLE</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">STATUS</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">INVESTIGATION</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">DETECTED</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">UPDATED</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4 text-right">ACTIONS</th>
                  </tr>
                </thead>
                <tbody className="font-mono text-[11px]">
                  {paged.map((inc) => (
                    <tr key={inc.id} className="border-b border-outline-variant/50 hover:bg-surface-container-high/50 transition-colors group">
                      <td className="py-3 px-4">
                        <Link href={`/incidents/${inc.id}`} className="text-primary hover:underline font-semibold">
                          INC-{inc.number}
                        </Link>
                      </td>
                      <td className="py-3 px-4">
                        <span className={`inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold border ${severityStyles[inc.severity] || ""}`}>
                          {inc.severity}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <span className="inline-flex items-center gap-1 text-on-surface-variant">
                          <span className="material-symbols-outlined text-[12px]">{sourceIcons[inc.source] || "help"}</span>
                          {inc.source}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-on-surface-variant">{inc.service || "—"}</td>
                      <td className="py-3 px-4 text-on-surface truncate max-w-[200px]">{inc.title}</td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${statusColors[inc.status] || "bg-outline/15 text-outline"}`}>
                          {inc.status.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {inc.investigation ? (
                          <div className="flex items-center gap-2">
                            <div className="w-16 h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                              <div
                                className="h-full bg-primary rounded-full"
                                style={{ width: `${inc.investigation.progress_percent}%` }}
                              />
                            </div>
                            <span className="text-on-surface-variant">{inc.investigation.progress_percent}%</span>
                          </div>
                        ) : (
                          <span className="text-on-surface-variant">—</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-on-surface-variant">{timeAgo(inc.created_at)}</td>
                      <td className="py-3 px-4 text-on-surface-variant">{timeAgo(inc.updated_at || inc.created_at)}</td>
                      <td className="py-3 px-4 text-right">
                        <button className="text-on-surface-variant hover:text-primary transition-colors">
                          <span className="material-symbols-outlined text-[16px]">more_horiz</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Pagination */}
              <div className="flex items-center justify-between px-4 py-3 border-t border-outline-variant">
                <div className="flex items-center gap-2 text-[12px] text-on-surface-variant">
                  <span>Rows per page:</span>
                  <span className="text-on-surface font-semibold">10</span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={page === 1}
                    className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-high text-on-surface-variant disabled:opacity-30 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[16px]">chevron_left</span>
                  </button>
                  {Array.from({ length: totalPages }, (_, i) => (
                    <button
                      key={i}
                      onClick={() => setPage(i + 1)}
                      className={`w-8 h-8 flex items-center justify-center rounded text-[12px] font-semibold transition-colors ${
                        page === i + 1 ? "bg-primary text-on-primary" : "text-on-surface-variant hover:bg-surface-container-high"
                      }`}
                    >
                      {i + 1}
                    </button>
                  ))}
                  <button
                    onClick={() => setPage(Math.min(totalPages, page + 1))}
                    disabled={page === totalPages}
                    className="w-8 h-8 flex items-center justify-center rounded hover:bg-surface-container-high text-on-surface-variant disabled:opacity-30 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[16px]">chevron_right</span>
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </>
  );
}

function SelectFilter({ label, options, value, onChange }: {
  label: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-3 py-1.5 pr-8 font-mono text-[12px] text-on-surface bg-surface-container-high border border-outline-variant rounded-md appearance-none cursor-pointer hover:border-primary/50 transition-colors"
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
      <span className="material-symbols-outlined absolute right-2 top-1.5 text-on-surface-variant pointer-events-none text-[14px]">
        expand_more
      </span>
    </div>
  );
}
