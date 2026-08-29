"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listIncidents, Incident } from "@/lib/api";
import {
  fetchInvestigation,
  startInvestigation,
  pauseInvestigation,
  cancelInvestigation,
  getStreamTicket,
  subscribeInvestigationStream,
  InvestigationDetail,
  WorkflowStreamEvent,
} from "@/lib/investigationApi";

const statusLabels: Record<string, string> = {
  created: "Created",
  queued: "Queued",
  running: "Running",
  paused: "Paused",
  waiting_for_input: "Waiting Approval (Quarantined)",
  abstained: "Abstained (Low Confidence)",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  blocked: "Blocked",
};

const statusColors: Record<string, string> = {
  created: "bg-surface-container-high text-on-surface-variant",
  queued: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
  running: "bg-primary/10 text-primary border-primary/30 animate-pulse",
  paused: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  waiting_for_input: "bg-error/10 text-error border-error/30",
  abstained: "bg-purple-500/10 text-purple-400 border-purple-500/30",
  completed: "bg-green-500/10 text-green-400 border-green-500/30",
  failed: "bg-error/10 text-error border-error/30",
  cancelled: "bg-surface-container-high text-on-surface-variant",
  blocked: "bg-error/10 text-error border-error/30",
};

const workflowBadges: Record<string, { label: string; bg: string }> = {
  production_incident: { label: "Production Incident", bg: "bg-error/10 text-error border-error/20" },
  repository_task: { label: "Direct Task", bg: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
  bug: { label: "Bug Investigation", bg: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  feature: { label: "Feature Planning", bg: "bg-purple-500/10 text-purple-400 border-purple-500/20" },
  security_incident: { label: "Security Quarantine", bg: "bg-red-500/15 text-red-300 border-red-500/40" },
};

export default function InvestigationsPage() {
  const { token } = useAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [workflowFilter, setWorkflowFilter] = useState("all");
  const [activeStreamLogs, setActiveStreamLogs] = useState<Record<string, WorkflowStreamEvent[]>>({});

  useEffect(() => {
    if (!token) return;
    listIncidents(token)
      .then(setIncidents)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token]);

  const investigated = incidents.filter((i) => i.investigation);
  const filtered = workflowFilter === "all"
    ? investigated
    : investigated.filter((i) => (i.investigation?.workflow_type || "production_incident") === workflowFilter);

  const handleStartWorkflow = async (invId: string, workflowType?: string) => {
    if (!token) return;
    try {
      await startInvestigation(invId, token, workflowType);
      const updated = await listIncidents(token);
      setIncidents(updated);

      // Connect to live SSE stream
      const ticket = await getStreamTicket(invId, token);
      subscribeInvestigationStream(invId, ticket, (ev) => {
        setActiveStreamLogs((prev) => ({
          ...prev,
          [invId]: [...(prev[invId] || []), ev],
        }));
      });
    } catch (err) {
      console.error("Failed to start workflow:", err);
    }
  };

  const handleCancelWorkflow = async (invId: string) => {
    if (!token) return;
    try {
      await cancelInvestigation(invId, token);
      const updated = await listIncidents(token);
      setIncidents(updated);
    } catch (err) {
      console.error("Failed to cancel workflow:", err);
    }
  };

  return (
    <>
      <TopBar
        title="Investigations"
        subtitle="Orchestrate type-specific safe investigation and remediation workflows"
        breadcrumbs={[{ label: "Investigations", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto">
          {/* Stats Overview */}
          <div className="grid grid-cols-5 gap-3 mb-6">
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant font-medium">Total Investigations</div>
              <div className="text-[24px] font-semibold text-on-surface">{investigated.length}</div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant font-medium">Running Workflows</div>
              <div className="text-[24px] font-semibold text-primary">
                {investigated.filter((i) => ["running", "investigating"].includes(i.investigation?.status || i.status)).length}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant font-medium">Root Causes Isolated</div>
              <div className="text-[24px] font-semibold text-tertiary">
                {investigated.filter((i) => i.investigation?.root_cause_found).length}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant font-medium">Safe Abstentions</div>
              <div className="text-[24px] font-semibold text-purple-400">
                {investigated.filter((i) => i.investigation?.abstained || i.status === "insufficient_evidence").length}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant font-medium">Security Quarantined</div>
              <div className="text-[24px] font-semibold text-red-400">
                {investigated.filter((i) => i.investigation?.security_case_id).length}
              </div>
            </div>
          </div>

          {/* Workflow Filters */}
          <div className="flex gap-2 mb-4 overflow-x-auto pb-1">
            {[
              { key: "all", label: "All Workflows" },
              { key: "production_incident", label: "Production Incident" },
              { key: "repository_task", label: "Direct Task" },
              { key: "bug", label: "Bug Investigation" },
              { key: "feature", label: "Feature Implementation" },
              { key: "security_incident", label: "Security Quarantine" },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setWorkflowFilter(tab.key)}
                className={`px-3 py-1.5 rounded text-[11px] font-medium transition-all ${
                  workflowFilter === tab.key
                    ? "bg-primary text-on-primary shadow-sm"
                    : "bg-surface-container border border-outline-variant text-on-surface-variant hover:bg-surface-container-high"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Investigations Ledger Table */}
          <div className="bg-surface-container-low border border-outline-variant rounded overflow-hidden">
            <div className="p-3 border-b border-outline-variant text-[12px] font-semibold text-on-surface flex items-center justify-between">
              <span>Investigation Pipeline Executions</span>
              <span className="text-[11px] text-on-surface-variant font-normal">{filtered.length} active records</span>
            </div>

            {loading ? (
              <div className="p-8 text-center text-on-surface-variant text-[12px]">Loading investigations...</div>
            ) : filtered.length === 0 ? (
              <div className="p-8 text-center text-on-surface-variant text-[12px]">
                No investigations found matching the selected workflow category.
              </div>
            ) : (
              <div className="divide-y divide-outline-variant/40">
                {filtered.map((inc) => {
                  const inv = inc.investigation;
                  const wBadge = workflowBadges[inv?.workflow_type || "production_incident"] || workflowBadges.production_incident;
                  const st = inv?.status || inc.status;

                  return (
                    <div key={inc.id} className="p-4 hover:bg-surface-container transition-colors">
                      <div className="flex items-start justify-between gap-4 mb-2">
                        <div className="flex items-center gap-2">
                          <Link
                            href={`/incidents/${inc.id}`}
                            className="text-[13px] font-semibold text-primary hover:underline"
                          >
                            INC-{inc.number}: {inc.title}
                          </Link>
                          <span className={`text-[10px] px-2 py-0.5 rounded border font-medium ${wBadge.bg}`}>
                            {wBadge.label}
                          </span>
                          {inv?.security_case_id && (
                            <span className="text-[10px] px-2 py-0.5 rounded border bg-red-950/80 text-red-300 border-red-500/50 font-mono font-bold">
                              {inv.security_case_id} [STRICT PRESERVE]
                            </span>
                          )}
                        </div>

                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] px-2.5 py-1 rounded-full border font-semibold ${statusColors[st] || statusColors.created}`}>
                            {statusLabels[st] || st}
                          </span>

                          {inv && (
                            <div className="flex items-center gap-1.5 ml-2">
                              {["created", "paused", "waiting_for_input"].includes(inv.status) && (
                                <button
                                  onClick={() => handleStartWorkflow(inv.id, inv.workflow_type)}
                                  className="text-[10px] px-2.5 py-1 rounded bg-primary text-on-primary font-medium hover:bg-primary/90 transition-colors"
                                >
                                  Execute
                                </button>
                              )}
                              {inv.status === "running" && (
                                <button
                                  onClick={() => handleCancelWorkflow(inv.id)}
                                  className="text-[10px] px-2.5 py-1 rounded border border-error/40 text-error font-medium hover:bg-error/10 transition-colors"
                                >
                                  Cancel
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Progress Bar & Details */}
                      {inv && (
                        <div className="mt-3">
                          <div className="flex items-center justify-between text-[11px] text-on-surface-variant mb-1">
                            <span>Step: {inv.current_step || "Execution in progress"}</span>
                            <span>{inv.progress_percent}%</span>
                          </div>
                          <div className="w-full bg-surface-container-highest rounded-full h-1.5 overflow-hidden">
                            <div
                              className="bg-primary h-1.5 rounded-full transition-all duration-300"
                              style={{ width: `${inv.progress_percent}%` }}
                            />
                          </div>

                          {/* Abstention Banner if Applicable */}
                          {inv.abstained && (
                            <div className="mt-2.5 p-2.5 bg-purple-950/30 border border-purple-500/30 rounded text-[11px] text-purple-200">
                              <span className="font-semibold text-purple-300">Safe Abstention: </span>
                              {inv.abstention_reason || "Evidence inconclusive; automated RCA withheld."}
                            </div>
                          )}

                          {/* Live SSE Stream Console if logs received */}
                          {activeStreamLogs[inv.id] && activeStreamLogs[inv.id].length > 0 && (
                            <div className="mt-2.5 p-2 bg-black/60 border border-outline-variant/60 rounded font-mono text-[10px] text-green-400 max-h-28 overflow-y-auto">
                              {activeStreamLogs[inv.id].map((ev) => (
                                <div key={ev.event_id}>
                                  <span className="text-on-surface-variant">[{new Date(ev.timestamp).toLocaleTimeString()}]</span> {ev.message}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
