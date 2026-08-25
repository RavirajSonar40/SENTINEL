"use client";

import { useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listPendingApprovals, submitApproval, PendingApproval } from "@/lib/api";

const typeStyles: Record<string, string> = {
  code_fix: "bg-primary/10 text-primary border-primary/20",
  dependency_update: "bg-tertiary/10 text-tertiary border-tertiary/20",
  config_fix: "bg-surface-container-high text-on-surface-variant border-outline-variant",
  rollback: "bg-error/10 text-error border-error/20",
  infra_fix: "bg-secondary/10 text-secondary border-secondary/20",
};

const typeLabels: Record<string, string> = {
  code_fix: "Code Fix",
  dependency_update: "Dependency Update",
  config_fix: "Config Fix",
  rollback: "Rollback",
  infra_fix: "Infra Fix",
};

export default function PullRequestsPage() {
  const { token } = useAuth();
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    listPendingApprovals(token)
      .then(setApprovals)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token]);

  const handleApproval = async (fixId: string, action: "approve" | "reject") => {
    if (!token) return;
    setActionLoading(fixId);
    try {
      await submitApproval(token, fixId, action);
      setApprovals((prev) => prev.filter((a) => a.fix_id !== fixId));
    } catch (err) {
      console.error(err);
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <>
      <TopBar
        title="Pull Requests"
        subtitle="Review and approve draft PRs created by Sentinel"
        breadcrumbs={[{ label: "Pull Requests", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto">
          {/* Stats */}
          <div className="grid grid-cols-4 gap-3 mb-6">
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant">Pending</div>
              <div className="text-[24px] font-semibold text-on-surface">{approvals.length}</div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant">Auto-Merge Eligible</div>
              <div className="text-[24px] font-semibold text-tertiary">
                {approvals.filter((a) => a.auto_merge_eligible).length}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant">Code Fixes</div>
              <div className="text-[24px] font-semibold text-primary">
                {approvals.filter((a) => a.fix_type === "code_fix").length}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-3">
              <div className="text-[11px] text-on-surface-variant">Rollbacks</div>
              <div className="text-[24px] font-semibold text-error">
                {approvals.filter((a) => a.fix_type === "rollback").length}
              </div>
            </div>
          </div>

          {/* Approval Queue */}
          <div className="bg-surface-container-low border border-outline-variant rounded">
            <div className="p-4 border-b border-outline-variant">
              <h2 className="text-[13px] font-semibold text-on-surface">Approval Queue</h2>
            </div>
            {loading ? (
              <div className="p-8 text-center text-on-surface-variant font-mono text-[12px]">
                Loading...
              </div>
            ) : approvals.length === 0 ? (
              <div className="p-8 text-center">
                <span className="material-symbols-outlined text-[48px] text-on-surface-variant/20 block mb-2">check_circle</span>
                <div className="text-[13px] text-on-surface-variant">No pending approvals</div>
              </div>
            ) : (
              <div className="divide-y divide-outline-variant">
                {approvals.map((approval) => (
                  <div key={approval.fix_id} className="p-4 hover:bg-surface-container-high/50 transition-colors">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`px-2 py-0.5 rounded text-[11px] font-mono border ${
                            typeStyles[approval.fix_type] || ""
                          }`}>
                            {typeLabels[approval.fix_type] || approval.fix_type}
                          </span>
                          {approval.auto_merge_eligible && (
                            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-tertiary/10 text-tertiary border border-tertiary/20">
                              Auto-merge eligible
                            </span>
                          )}
                          {approval.incident_number && (
                            <span className="text-[11px] font-mono text-on-surface-variant">
                              INC-{String(approval.incident_number).padStart(4, "0")}
                            </span>
                          )}
                        </div>
                        <h3 className="text-[13px] font-medium text-on-surface mb-1">
                          {approval.title}
                        </h3>
                        <p className="text-[11px] text-on-surface-variant line-clamp-2">
                          {approval.description}
                        </p>
                        {approval.incident_title && (
                          <div className="text-[11px] text-on-surface-variant/60 mt-1">
                            Incident: {approval.incident_title}
                          </div>
                        )}
                      </div>
                      <div className="flex gap-2 ml-4">
                        <button
                          onClick={() => handleApproval(approval.fix_id, "approve")}
                          disabled={actionLoading === approval.fix_id}
                          className="px-3 py-1.5 bg-primary text-on-primary rounded text-[11px] font-medium hover:bg-primary/90 disabled:opacity-50"
                        >
                          {actionLoading === approval.fix_id ? "..." : "Approve"}
                        </button>
                        <button
                          onClick={() => handleApproval(approval.fix_id, "reject")}
                          disabled={actionLoading === approval.fix_id}
                          className="px-3 py-1.5 bg-surface-container-high text-on-surface border border-outline-variant rounded text-[11px] font-medium hover:bg-surface-container-highest disabled:opacity-50"
                        >
                          {actionLoading === approval.fix_id ? "..." : "Reject"}
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
