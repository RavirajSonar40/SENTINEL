"use client";

import React, { useState, useEffect } from "react";
import {
  multiRepoApi,
  CandidateRepository,
  ChildInvestigation,
  RemediationPlan,
  RemediationPlanItem,
} from "@/lib/multiRepoApi";

interface MultiRepoRemediationStudioProps {
  incidentId: string;
  token: string;
  onRefreshParent?: () => void;
}

export const MultiRepoRemediationStudio: React.FC<MultiRepoRemediationStudioProps> = ({
  incidentId,
  token,
  onRefreshParent,
}) => {
  const [candidates, setCandidates] = useState<CandidateRepository[]>([]);
  const [childInvs, setChildInvs] = useState<ChildInvestigation[]>([]);
  const [plan, setPlan] = useState<RemediationPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [showOverrideModal, setShowOverrideModal] = useState(false);
  const [overrideOrderInput, setOverrideOrderInput] = useState("");

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Resolve candidates
      const candRes = await multiRepoApi.resolveCandidates(incidentId, token);
      setCandidates(candRes.candidates || []);

      // 2. Fetch investigations
      const invsRes = await multiRepoApi.getIncidentInvestigations(incidentId, token);
      setChildInvs(invsRes.child_investigations || []);

      // 3. Fetch latest plan
      const latestPlan = await multiRepoApi.getLatestRemediationPlan(incidentId, token);
      setPlan(latestPlan);
    } catch (err: any) {
      setError(err.message || "Failed to load multi-repository data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (incidentId && token) {
      fetchData();
    }
  }, [incidentId, token]);

  const handleFanOut = async () => {
    setActionLoading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await multiRepoApi.fanOutInvestigations(incidentId, token);
      setSuccessMsg(res.message || "Successfully fanned out child investigations.");
      await fetchData();
      if (onRefreshParent) onRefreshParent();
    } catch (err: any) {
      setError(err.message || "Fan-out failed.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreatePlan = async (overrideOrder?: string[]) => {
    setActionLoading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const createdPlan = await multiRepoApi.createRemediationPlan(incidentId, token, overrideOrder);
      setPlan(createdPlan);
      setSuccessMsg("Coordinated multi-repository remediation plan compiled.");
      setShowOverrideModal(false);
      await fetchData();
    } catch (err: any) {
      setError(err.message || "Failed to compile remediation plan.");
    } finally {
      setActionLoading(false);
    }
  };

  const handlePublishPRs = async () => {
    if (!plan) return;
    setActionLoading(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await multiRepoApi.publishDraftPRs(plan.id, token);
      setSuccessMsg(res.message);
      await fetchData();
      if (onRefreshParent) onRefreshParent();
    } catch (err: any) {
      setError(err.message || "Failed to publish Draft PRs.");
    } finally {
      setActionLoading(false);
    }
  };

  const getRoleBadge = (role: string) => {
    switch (role?.toLowerCase()) {
      case "primary_defect":
        return <span className="px-2 py-0.5 text-xs font-semibold rounded bg-red-950/40 text-red-400 border border-red-800/50">PRIMARY DEFECT</span>;
      case "downstream_affected":
        return <span className="px-2 py-0.5 text-xs font-semibold rounded bg-blue-950/40 text-blue-400 border border-blue-800/50">DOWNSTREAM AFFECTED</span>;
      case "configuration":
        return <span className="px-2 py-0.5 text-xs font-semibold rounded bg-purple-950/40 text-purple-400 border border-purple-800/50">CONFIGURATION / IAC</span>;
      case "evidence_only":
        return <span className="px-2 py-0.5 text-xs font-semibold rounded bg-zinc-800 text-zinc-400 border border-zinc-700">EVIDENCE ONLY</span>;
      default:
        return <span className="px-2 py-0.5 text-xs font-semibold rounded bg-zinc-800 text-zinc-300">{role}</span>;
    }
  };

  const getPrStatusBadge = (status: string) => {
    switch (status?.toLowerCase()) {
      case "created":
        return <span className="px-2 py-0.5 text-xs font-bold rounded bg-emerald-950/40 text-emerald-400 border border-emerald-800/50">PR PUBLISHED</span>;
      case "failed":
        return <span className="px-2 py-0.5 text-xs font-bold rounded bg-red-950/40 text-red-400 border border-red-800/50">FAILED</span>;
      case "skipped_evidence_only":
        return <span className="px-2 py-0.5 text-xs font-medium rounded bg-zinc-800/60 text-zinc-400">NO PR (EVIDENCE ONLY)</span>;
      default:
        return <span className="px-2 py-0.5 text-xs font-medium rounded bg-amber-950/40 text-amber-400 border border-amber-800/50">PENDING</span>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-2xl">account_tree</span>
              <h2 className="text-xl font-bold text-zinc-100">Multi-Repository Remediation Orchestrator</h2>
            </div>
            <p className="text-sm text-zinc-400 mt-1">
              Deterministic cross-service candidate resolution, independent repository investigations, and topological Draft PR rollout.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleFanOut}
              disabled={actionLoading}
              className="px-4 py-2 text-sm font-semibold rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-100 border border-zinc-700 transition flex items-center gap-1.5"
            >
              <span className="material-symbols-outlined text-sm">call_split</span>
              Fan Out Child Invs
            </button>
            <button
              onClick={() => handleCreatePlan()}
              disabled={actionLoading}
              className="px-4 py-2 text-sm font-semibold rounded-lg bg-primary/20 hover:bg-primary/30 text-primary border border-primary/40 transition flex items-center gap-1.5"
            >
              <span className="material-symbols-outlined text-sm">schema</span>
              Compile Rollout Plan
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 p-3 bg-red-950/30 border border-red-800/50 rounded-lg text-sm text-red-300 flex items-center gap-2">
            <span className="material-symbols-outlined text-base text-red-400">error</span>
            {error}
          </div>
        )}
        {successMsg && (
          <div className="mt-4 p-3 bg-emerald-950/30 border border-emerald-800/50 rounded-lg text-sm text-emerald-300 flex items-center gap-2">
            <span className="material-symbols-outlined text-base text-emerald-400">check_circle</span>
            {successMsg}
          </div>
        )}
      </div>

      {/* Cyclic Dependency Alert Banner */}
      {plan?.cycle_detected && (
        <div className="bg-amber-950/30 border border-amber-800/60 rounded-xl p-5 text-amber-200">
          <div className="flex items-start gap-3">
            <span className="material-symbols-outlined text-amber-400 text-2xl mt-0.5">sync_problem</span>
            <div className="flex-1">
              <h3 className="text-base font-bold text-amber-300">Topological Cycle Detected</h3>
              <p className="text-sm mt-1 text-amber-200/90">
                Service dependency graph contains cyclic dependencies. Autonomous Draft PR publishing is blocked to prevent race conditions.
              </p>
              {plan.cycle_details && (
                <div className="mt-2 text-xs bg-zinc-900/60 p-2.5 rounded border border-amber-800/30 text-zinc-300">
                  {plan.cycle_details.message}
                </div>
              )}
              <button
                onClick={() => setShowOverrideModal(true)}
                className="mt-3 px-3.5 py-1.5 text-xs font-bold rounded-lg bg-amber-600 hover:bg-amber-500 text-zinc-950 transition"
              >
                Configure Break-Order Override
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Section 1: Resolved Candidate Repositories */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
        <h3 className="text-base font-bold text-zinc-100 mb-4 flex items-center gap-2">
          <span className="material-symbols-outlined text-base text-primary">hub</span>
          Resolved Candidate Repositories ({candidates.length})
        </h3>

        {candidates.length === 0 ? (
          <p className="text-sm text-zinc-500 italic">No candidate repositories resolved above the scoring threshold.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {candidates.map((c) => (
              <div
                key={c.repository_id}
                className="bg-zinc-950 border border-zinc-800 rounded-lg p-4 flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-mono text-sm font-semibold text-zinc-200">{c.full_name}</span>
                    {getRoleBadge(c.role)}
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                    <span>Score: <strong className="text-primary">{(c.score * 100).toFixed(0)}%</strong></span>
                    {c.base_commit_sha && (
                      <span className="font-mono bg-zinc-800/50 px-1.5 py-0.5 rounded text-[11px]">
                        SHA: {c.base_commit_sha.slice(0, 8)}
                      </span>
                    )}
                  </div>
                  <ul className="mt-2 space-y-1 text-xs text-zinc-400">
                    {c.reasons.map((r, idx) => (
                      <li key={idx} className="flex items-center gap-1.5">
                        <span className="w-1 h-1 rounded-full bg-zinc-500" />
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>
                {c.role === "evidence_only" && (
                  <div className="mt-3 text-[11px] text-zinc-500 bg-zinc-900/60 p-1.5 rounded border border-zinc-800 text-center">
                    🔒 Evidence-Only: Diagnostic context only (no code mutation)
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Section 2: Active Coordinated Remediation Plan */}
      {plan && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-emerald-400">account_tree</span>
                <h3 className="text-base font-bold text-zinc-100">{plan.title}</h3>
                <span className="px-2 py-0.5 text-xs font-bold rounded bg-zinc-800 text-zinc-300 uppercase">
                  {plan.status}
                </span>
              </div>
              <p className="text-xs text-zinc-400 mt-0.5">{plan.summary}</p>
            </div>
            <button
              onClick={handlePublishPRs}
              disabled={actionLoading || plan.cycle_detected}
              className="px-4 py-2 text-sm font-bold rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-zinc-950 transition flex items-center gap-1.5 self-start sm:self-auto"
            >
              <span className="material-symbols-outlined text-base">merge_type</span>
              Publish All Draft PRs
            </button>
          </div>

          {/* Plan Items Table */}
          <div className="overflow-x-auto mt-4">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-400 font-semibold uppercase">
                  <th className="py-2.5 px-3">Order</th>
                  <th className="py-2.5 px-3">Repository</th>
                  <th className="py-2.5 px-3">Role</th>
                  <th className="py-2.5 px-3">Base SHA</th>
                  <th className="py-2.5 px-3">Validation</th>
                  <th className="py-2.5 px-3">Approval</th>
                  <th className="py-2.5 px-3">PR Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800 text-zinc-300">
                {plan.items.map((item) => (
                  <tr key={item.id} className="hover:bg-zinc-800/30">
                    <td className="py-3 px-3 font-mono font-bold text-primary">{item.execution_order}</td>
                    <td className="py-3 px-3 font-mono font-semibold">{item.repository_name}</td>
                    <td className="py-3 px-3">{getRoleBadge(item.repository_role)}</td>
                    <td className="py-3 px-3 font-mono text-[11px] text-zinc-400">
                      {item.base_commit_sha ? item.base_commit_sha.slice(0, 8) : "Pending SHA"}
                    </td>
                    <td className="py-3 px-3">
                      <span className={`px-2 py-0.5 rounded font-semibold uppercase ${
                        item.validation_status === "passed" ? "bg-emerald-950/40 text-emerald-400 border border-emerald-800/50" : "bg-zinc-800 text-zinc-400"
                      }`}>
                        {item.validation_status}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      <span className={`px-2 py-0.5 rounded font-semibold uppercase ${
                        item.approval_status === "approved" ? "bg-emerald-950/40 text-emerald-400 border border-emerald-800/50" : "bg-zinc-800 text-zinc-400"
                      }`}>
                        {item.approval_status}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      {item.pr_url ? (
                        <a
                          href={item.pr_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline font-mono flex items-center gap-1"
                        >
                          PR #{item.pr_number || "link"}
                          <span className="material-symbols-outlined text-xs">open_in_new</span>
                        </a>
                      ) : (
                        getPrStatusBadge(item.pr_status)
                      )}
                      {item.error_message && (
                        <div className="text-[11px] text-red-400 mt-1 max-w-xs truncate">{item.error_message}</div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Rollback Plan Accordion */}
          {plan.cross_repo_rollback_plan && (
            <div className="mt-5 p-3.5 bg-zinc-950 border border-zinc-800 rounded-lg">
              <h4 className="text-xs font-bold text-zinc-300 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                <span className="material-symbols-outlined text-sm text-amber-400">undo</span>
                Coordinated Rollback Strategy
              </h4>
              <pre className="text-xs text-zinc-400 font-mono whitespace-pre-wrap">
                {plan.cross_repo_rollback_plan}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Break-Order Override Modal */}
      {showOverrideModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 max-w-lg w-full">
            <h3 className="text-lg font-bold text-zinc-100 mb-2">Override Dependency Merge Order</h3>
            <p className="text-xs text-zinc-400 mb-4">
              Specify comma-separated repository IDs in the exact order they should be merged and deployed.
            </p>
            <input
              type="text"
              value={overrideOrderInput}
              onChange={(e) => setOverrideOrderInput(e.target.value)}
              placeholder="repo-id-1, repo-id-2"
              className="w-full bg-zinc-950 border border-zinc-700 rounded-lg p-2.5 text-xs text-zinc-200 font-mono mb-4 focus:outline-none focus:border-primary"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowOverrideModal(false)}
                className="px-3.5 py-1.5 text-xs rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  const orders = overrideOrderInput.split(",").map((s) => s.trim()).filter(Boolean);
                  handleCreatePlan(orders);
                }}
                className="px-3.5 py-1.5 text-xs font-bold rounded bg-primary text-zinc-950 hover:bg-primary/90"
              >
                Apply Override Order
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
