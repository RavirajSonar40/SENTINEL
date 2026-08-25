"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listIncidents, Incident } from "@/lib/api";

const statusLabels: Record<string, string> = {
  detected: "Detected",
  created: "Created",
  investigation_queued: "Queued",
  investigating: "Investigating",
  root_cause_analysis: "Analyzing",
  root_cause_identified: "Root Cause Found",
  fix_generated: "Fix Generated",
  fix_validating: "Validating",
  awaiting_approval: "Awaiting Approval",
  approved: "Approved",
  resolved: "Resolved",
  insufficient_evidence: "Insufficient Evidence",
  investigation_failed: "Failed",
  cancelled: "Cancelled",
  evidence_collected: "Evidence Collected",
};

const statusColors: Record<string, string> = {
  detected: "bg-error/10 text-error",
  investigating: "bg-primary/10 text-primary",
  root_cause_identified: "bg-tertiary/10 text-tertiary",
  resolved: "bg-green-500/10 text-green-400",
  evidence_collected: "bg-yellow-500/10 text-yellow-400",
};

export default function InvestigationsPage() {
  const { token } = useAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    if (!token) return;
    listIncidents(token)
      .then(setIncidents)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token]);

  const investigated = incidents.filter((i) => i.investigation);
  const filtered = filter === "all"
    ? investigated
    : investigated.filter((i) => i.status === filter);

  return (
    <>
      <TopBar
        title="Investigations"
        subtitle="Track all ongoing and completed investigations"
        breadcrumbs={[{ label: "Investigations", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto">
          {/* Stats */}
          <div className="grid grid-cols-4 gap-3 mb-6">
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant">Total</div>
              <div className="text-[24px] font-semibold text-on-surface">{investigated.length}</div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant">In Progress</div>
              <div className="text-[24px] font-semibold text-primary">
                {investigated.filter((i) => ["investigating", "root_cause_analysis"].includes(i.status)).length}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant">Root Cause Found</div>
              <div className="text-[24px] font-semibold text-tertiary">
                {investigated.filter((i) => i.investigation?.root_cause_found).length}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant">Resolved</div>
              <div className="text-[24px] font-semibold text-green-400">
                {investigated.filter((i) => i.status === "resolved").length}
              </div>
            </div>
          </div>

          {/* Filters */}
          <div className="flex gap-2 mb-4">
            {["all", "investigating", "root_cause_identified", "resolved"].map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded text-[11px] font-medium transition-all ${
                  filter === f
                    ? "bg-primary text-on-primary"
                    : "bg-surface-container border border-outline-variant text-on-surface-variant hover:bg-surface-container-high"
                }`}
              >
                {f === "all" ? "All" : statusLabels[f] || f}
              </button>
            ))}
          </div>

          {/* Investigation List */}
          <div className="bg-surface-container-low border border-outline-variant rounded">
            {loading ? (
              <div className="p-8 text-center text-on-surface-variant font-mono text-[12px]">Loading...</div>
            ) : filtered.length === 0 ? (
              <div className="p-8 text-center">
                <span className="material-symbols-outlined text-[48px] text-on-surface-variant/20 block mb-2">psychology</span>
                <div className="text-[13px] text-on-surface-variant">No investigations found</div>
              </div>
            ) : (
              <div className="divide-y divide-outline-variant">
                {filtered.map((inc) => (
                  <Link
                    key={inc.id}
                    href={`/incidents/${inc.id}`}
                    className="block p-4 hover:bg-surface-container-high/50 transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="text-[11px] font-mono text-on-surface-variant">
                          INC-{String(inc.number).padStart(4, "0")}
                        </span>
                        <span className="text-[13px] font-medium text-on-surface">{inc.title}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {inc.investigation?.root_cause_found && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-tertiary/10 text-tertiary">
                            Root Cause Found
                          </span>
                        )}
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${
                          statusColors[inc.status] || "bg-surface-container-high text-on-surface-variant"
                        }`}>
                          {statusLabels[inc.status] || inc.status}
                        </span>
                      </div>
                    </div>
                    {inc.investigation && (
                      <div className="flex gap-4 mt-2 font-mono text-[10px] text-on-surface-variant">
                        <span>Confidence: {inc.investigation.confidence || "—"}</span>
                        <span>Progress: {inc.investigation.progress_percent}%</span>
                        <span>Service: {inc.service || "—"}</span>
                      </div>
                    )}
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
