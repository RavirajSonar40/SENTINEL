"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listPendingApprovals, submitApproval, PendingApproval } from "@/lib/api";

const typeStyles: Record<string, string> = {
  code_fix: "bg-primary/10 text-primary border-primary/20",
  dependency_update: "bg-tertiary/10 text-tertiary border-tertiary/20",
  config_fix: "bg-surface-container-high text-on-surface-variant border-outline-variant",
  rollback: "bg-red-500/10 text-red-400 border-red-500/20",
  infra_fix: "bg-secondary/10 text-secondary border-secondary/20",
};

const typeLabels: Record<string, string> = {
  code_fix: "Code Fix",
  dependency_update: "Dependency Update",
  config_fix: "Config Fix",
  rollback: "Rollback",
  infra_fix: "Infra Fix",
};

export default function PullRequestsGatewayPage() {
  const { token } = useAuth();
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [selectedApproval, setSelectedApproval] = useState<PendingApproval | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);

  const fetchApprovals = useCallback(async () => {
    if (!token) return;
    try {
      setLoading(true);
      const res = await listPendingApprovals(token);
      setApprovals(res);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchApprovals();
  }, [fetchApprovals]);

  const handleApprovalDecision = async (fixId: string, action: "approve" | "reject") => {
    if (!token) return;
    setActionLoading(fixId);
    try {
      await submitApproval(token, fixId, action);
      setFeedbackMessage(`Approval decision submitted: ${action.toUpperCase()} for fix ${fixId.slice(0, 8)}`);
      setApprovals((prev) => prev.filter((a) => a.fix_id !== fixId));
      setSelectedApproval(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Action failed";
      setFeedbackMessage(`Error: ${msg}`);
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <>
      <TopBar
        title="Draft PR & Policy Gateway"
        subtitle="Review, approve, and publish verified remediation draft pull requests"
        breadcrumbs={[{ label: "Pull Requests", active: true }]}
      />
      <main className="flex-1 p-6 pb-12 overflow-y-auto bg-surface text-on-surface">
        <div className="max-w-[1400px] mx-auto space-y-6">

          {/* Policy Safety Banner */}
          <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 flex items-start gap-3 shadow-sm">
            <span className="material-symbols-outlined text-amber-400 text-[22px] mt-0.5">policy</span>
            <div className="space-y-1 text-[12px]">
              <strong className="text-amber-200 text-[13px]">Strict Safety & Dual-Gated Workflow</strong>
              <p className="text-amber-300/90 leading-relaxed">
                Sentinel strictly separates <strong>Policy Gateway Approval</strong> from <strong>Draft PR Publishing</strong>. Once approved, Draft PRs are created in GitHub with base commit verification checksums and unified rollback instructions. Human peer review and CI checks in GitHub are strictly required before merging. Sentinel <strong>never</strong> auto-merges or deploys directly to production.
              </p>
            </div>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-on-surface-variant font-mono">Pending Decisions</div>
                <div className="text-2xl font-bold text-amber-400 mt-1 font-mono">{approvals.length}</div>
              </div>
              <span className="material-symbols-outlined text-amber-400 text-[28px]">pending_actions</span>
            </div>

            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-on-surface-variant font-mono">Code Fixes</div>
                <div className="text-2xl font-bold text-primary mt-1 font-mono">
                  {approvals.filter((a) => a.fix_type === "code_fix").length}
                </div>
              </div>
              <span className="material-symbols-outlined text-primary text-[28px]">code</span>
            </div>

            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-on-surface-variant font-mono">Rollback Plans</div>
                <div className="text-2xl font-bold text-red-400 mt-1 font-mono">
                  {approvals.filter((a) => a.fix_type === "rollback").length}
                </div>
              </div>
              <span className="material-symbols-outlined text-red-400 text-[28px]">history</span>
            </div>

            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-on-surface-variant font-mono">Enforced Policy</div>
                <div className="text-xl font-bold text-emerald-400 mt-1 font-mono">HUMAN-IN-LOOP</div>
              </div>
              <span className="material-symbols-outlined text-emerald-400 text-[28px]">verified_user</span>
            </div>
          </div>

          {feedbackMessage && (
            <div className="p-3 rounded-lg bg-surface-container border border-outline-variant text-[12px] font-mono text-primary flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px]">info</span>
              {feedbackMessage}
            </div>
          )}

          {/* Pending Approvals Table */}
          <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-outline-variant/60 bg-surface-container/40">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-on-surface-variant text-[18px]">checklist</span>
                <h2 className="text-[14px] font-semibold text-on-surface">Policy Approval Gateway Queue</h2>
              </div>
              <button
                onClick={fetchApprovals}
                className="text-[12px] text-primary hover:underline font-medium flex items-center gap-1"
              >
                <span className={`material-symbols-outlined text-[14px] ${loading ? "animate-spin" : ""}`}>sync</span>
                Refresh
              </button>
            </div>

            {loading ? (
              <div className="p-12 text-center text-on-surface-variant font-mono text-[12px]">
                Loading approval queue...
              </div>
            ) : approvals.length === 0 ? (
              <div className="p-12 text-center text-on-surface-variant space-y-2">
                <span className="material-symbols-outlined text-emerald-400 text-[36px]">check_circle</span>
                <p className="text-[13px] font-medium text-on-surface">No Pending Policy Approvals</p>
                <p className="text-[11px]">All generated fixes have been reviewed or are in drafting status.</p>
              </div>
            ) : (
              <div className="divide-y divide-outline-variant/40">
                {approvals.map((appr) => (
                  <div key={appr.fix_id} className="p-4 hover:bg-surface-container-high/40 transition flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="space-y-1.5 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold border font-mono ${typeStyles[appr.fix_type] || "bg-zinc-600"}`}>
                          {typeLabels[appr.fix_type] || appr.fix_type}
                        </span>
                        <span className="text-[13px] font-semibold text-on-surface">
                          {appr.title}
                        </span>
                        <span className="text-[11px] text-on-surface-variant font-mono">
                          (Fix ID: {appr.fix_id.slice(0, 8)})
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-3 text-[11px] text-on-surface-variant font-mono">
                        <span>Incident: {appr.incident_title || (appr.incident_number ? `Incident #${appr.incident_number}` : "Linked Incident")}</span>
                        <span>•</span>
                        <span className="text-on-surface-variant truncate max-w-md">{appr.description}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 self-end sm:self-center">
                      <button
                        onClick={() => setSelectedApproval(appr)}
                        className="px-3 py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant text-[12px] font-medium transition"
                      >
                        Inspect Details
                      </button>

                      <button
                        onClick={() => handleApprovalDecision(appr.fix_id, "reject")}
                        disabled={actionLoading === appr.fix_id}
                        className="px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 text-[12px] font-semibold transition"
                      >
                        Reject
                      </button>

                      <button
                        onClick={() => handleApprovalDecision(appr.fix_id, "approve")}
                        disabled={actionLoading === appr.fix_id}
                        className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-on-primary text-[12px] font-semibold transition shadow-sm"
                      >
                        {actionLoading === appr.fix_id ? "Submitting..." : "Submit Approval"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Details Inspection Modal */}
          {selectedApproval && (
            <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
              <div className="bg-surface-container-low border border-outline-variant rounded-xl max-w-2xl w-full max-h-[85vh] flex flex-col overflow-hidden shadow-2xl">
                <div className="px-5 py-4 border-b border-outline-variant flex items-center justify-between bg-surface-container/60">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-[20px]">code</span>
                    <h3 className="text-[14px] font-semibold text-on-surface">
                      Remediation Details & Policy Checklist
                    </h3>
                  </div>
                  <button
                    onClick={() => setSelectedApproval(null)}
                    className="text-on-surface-variant hover:text-on-surface"
                  >
                    <span className="material-symbols-outlined text-[18px]">close</span>
                  </button>
                </div>

                <div className="p-5 overflow-y-auto space-y-4 text-[12px]">
                  <div className="grid grid-cols-2 gap-3 p-3 bg-surface-container rounded-lg font-mono text-[11px]">
                    <div><span className="text-on-surface-variant">Fix ID:</span> {selectedApproval.fix_id}</div>
                    <div><span className="text-on-surface-variant">Type:</span> {selectedApproval.fix_type}</div>
                    <div><span className="text-on-surface-variant">Investigation:</span> {selectedApproval.investigation_id.slice(0, 8)}</div>
                    <div><span className="text-on-surface-variant">Incident:</span> {selectedApproval.incident_title || selectedApproval.incident_number || "—"}</div>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[11px] font-semibold text-on-surface">Title & Description</label>
                    <div className="p-3 rounded-lg bg-surface-container border border-outline-variant space-y-1">
                      <div className="font-semibold text-on-surface">{selectedApproval.title}</div>
                      <p className="text-on-surface-variant text-[11px]">{selectedApproval.description}</p>
                    </div>
                  </div>

                  <div className="p-3 rounded-lg bg-primary/10 border border-primary/20 text-[11px] text-primary space-y-1">
                    <strong>Policy Checklist:</strong>
                    <ul className="list-disc list-inside space-y-0.5 text-on-surface-variant">
                      <li>Base commit snapshot hash verified against target repository.</li>
                      <li>Evidence-only regression tests compiled and passed.</li>
                      <li>Rollback plan attached and recorded in audit ledger.</li>
                      <li>Human operator code review required in GitHub before production deployment.</li>
                    </ul>
                  </div>
                </div>

                <div className="px-5 py-3 border-t border-outline-variant flex items-center justify-end gap-2 bg-surface-container/60">
                  <button
                    onClick={() => setSelectedApproval(null)}
                    className="px-3 py-1.5 rounded-lg bg-surface-container border border-outline-variant text-[12px]"
                  >
                    Close
                  </button>
                  <button
                    onClick={() => handleApprovalDecision(selectedApproval.fix_id, "reject")}
                    className="px-3 py-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 text-[12px] font-semibold"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => handleApprovalDecision(selectedApproval.fix_id, "approve")}
                    className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-on-primary text-[12px] font-semibold"
                  >
                    Submit Approval Decision
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
