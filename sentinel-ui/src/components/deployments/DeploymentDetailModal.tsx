"use client";

import React, { useState, useEffect } from "react";
import {
  Deployment,
  DeploymentCommitComparison,
  deploymentsApi,
} from "@/lib/deploymentsApi";

interface DeploymentDetailModalProps {
  deployment: Deployment;
  token?: string;
  onClose: () => void;
  onStatusUpdated?: () => void;
}

export default function DeploymentDetailModal({
  deployment,
  token,
  onClose,
  onStatusUpdated,
}: DeploymentDetailModalProps) {
  const [activeTab, setActiveTab] = useState<"overview" | "commits" | "metadata">("overview");
  const [previousStable, setPreviousStable] = useState<Deployment | null>(null);
  const [commitComparison, setCommitComparison] = useState<DeploymentCommitComparison | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [rollingBack, setRollingBack] = useState(false);
  const [rollbackError, setRollbackError] = useState<string | null>(null);
  const [copiedSha, setCopiedSha] = useState(false);

  useEffect(() => {
    let isMounted = true;
    const fetchDiff = async () => {
      setLoadingDiff(true);
      try {
        const [prev, diff] = await Promise.all([
          deploymentsApi.getPreviousStableDeployment(deployment.id, token),
          deploymentsApi.getDeploymentCommitsBetween(deployment.id, token),
        ]);
        if (isMounted) {
          setPreviousStable(prev);
          setCommitComparison(diff);
        }
      } catch (err) {
        console.error("Failed to load commit diff", err);
      } finally {
        if (isMounted) setLoadingDiff(false);
      }
    };
    fetchDiff();
    return () => {
      isMounted = false;
    };
  }, [deployment.id, token]);

  const handleRollback = async () => {
    if (!confirm(`Are you sure you want to mark deployment ${deployment.version || deployment.commit_sha.slice(0, 7)} as ROLLED BACK?`)) {
      return;
    }
    setRollingBack(true);
    setRollbackError(null);
    try {
      await deploymentsApi.updateDeploymentStatus(
        deployment.id,
        {
          status: "rolled_back",
          error_message: "Manual rollback triggered from Sentinel UI",
        },
        token
      );
      if (onStatusUpdated) onStatusUpdated();
      onClose();
    } catch (err: unknown) {
      setRollbackError((err as Error).message || "Failed to trigger rollback");
    } finally {
      setRollingBack(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSha(true);
    setTimeout(() => setCopiedSha(false), 2000);
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "succeeded":
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950/70 text-emerald-400 border border-emerald-800/60">Succeeded</span>;
      case "in_progress":
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-cyan-950/70 text-cyan-400 border border-cyan-800/60 animate-pulse">In Progress</span>;
      case "failed":
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-950/70 text-rose-400 border border-rose-800/60">Failed</span>;
      case "rolled_back":
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-950/70 text-amber-400 border border-amber-800/60">Rolled Back</span>;
      case "cancelled":
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-neutral-800 text-neutral-400 border border-neutral-700">Cancelled</span>;
      default:
        return <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-neutral-800 text-neutral-400 border border-neutral-700">Pending</span>;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-neutral-900 border border-neutral-800 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-5 border-b border-neutral-800 flex items-center justify-between bg-neutral-950/40">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <span className="material-symbols-outlined">rocket_launch</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-semibold text-neutral-100">
                  {deployment.service_name || "Service Release"}
                </h3>
                {deployment.version && (
                  <span className="text-xs px-2 py-0.5 rounded bg-neutral-800 text-neutral-300 font-mono">
                    {deployment.version}
                  </span>
                )}
                {deployment.is_current && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-950/80 text-blue-400 border border-blue-800/60">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-ping"></span>
                    Active Live Release
                  </span>
                )}
              </div>
              <p className="text-xs text-neutral-400 flex items-center gap-2 mt-0.5">
                <span>Env: <strong className="text-neutral-200">{deployment.environment_name || "production"}</strong></span>
                {deployment.region_code && (
                  <>
                    <span>•</span>
                    <span>Region: <strong className="text-neutral-200">{deployment.region_code}</strong></span>
                  </>
                )}
                <span>•</span>
                <span>Provider: <strong className="text-neutral-200">{deployment.provider}</strong></span>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {getStatusBadge(deployment.status)}
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 transition"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="px-6 border-b border-neutral-800 flex items-center gap-6 bg-neutral-900">
          <button
            onClick={() => setActiveTab("overview")}
            className={`py-3 text-sm font-medium border-b-2 transition ${
              activeTab === "overview"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-neutral-400 hover:text-neutral-200"
            }`}
          >
            Overview & Metrics
          </button>
          <button
            onClick={() => setActiveTab("commits")}
            className={`py-3 text-sm font-medium border-b-2 transition flex items-center gap-1.5 ${
              activeTab === "commits"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-neutral-400 hover:text-neutral-200"
            }`}
          >
            <span>Commit Delta</span>
            {commitComparison && commitComparison.status === "available" && (
              <span className="text-xs px-1.5 py-0.2 rounded bg-neutral-800 text-neutral-300 font-mono">
                {commitComparison.total_commits}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("metadata")}
            className={`py-3 text-sm font-medium border-b-2 transition ${
              activeTab === "metadata"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-neutral-400 hover:text-neutral-200"
            }`}
          >
            Raw Metadata & Payload
          </button>
        </div>

        {/* Modal Content */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1">
          {rollbackError && (
            <div className="p-3.5 rounded-xl bg-rose-950/50 border border-rose-800/60 text-rose-300 text-sm flex items-center gap-2">
              <span className="material-symbols-outlined text-rose-400">error</span>
              <span>{rollbackError}</span>
            </div>
          )}

          {activeTab === "overview" && (
            <div className="space-y-6">
              {/* Timing Grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 rounded-xl bg-neutral-950/60 border border-neutral-800">
                  <div className="text-xs text-neutral-500 font-medium">Triggered / Deployed At</div>
                  <div className="text-sm font-semibold text-neutral-200 mt-1">
                    {new Date(deployment.deployed_at).toLocaleString()}
                  </div>
                </div>
                <div className="p-4 rounded-xl bg-neutral-950/60 border border-neutral-800">
                  <div className="text-xs text-neutral-500 font-medium">Started At</div>
                  <div className="text-sm font-semibold text-neutral-200 mt-1">
                    {deployment.started_at ? new Date(deployment.started_at).toLocaleTimeString() : "—"}
                  </div>
                </div>
                <div className="p-4 rounded-xl bg-neutral-950/60 border border-neutral-800">
                  <div className="text-xs text-neutral-500 font-medium">Finished At</div>
                  <div className="text-sm font-semibold text-neutral-200 mt-1">
                    {deployment.finished_at ? new Date(deployment.finished_at).toLocaleTimeString() : "—"}
                  </div>
                </div>
                <div className="p-4 rounded-xl bg-neutral-950/60 border border-neutral-800">
                  <div className="text-xs text-neutral-500 font-medium">Duration</div>
                  <div className="text-sm font-semibold text-emerald-400 mt-1">
                    {deployment.duration_seconds !== null && deployment.duration_seconds !== undefined
                      ? `${deployment.duration_seconds.toFixed(1)}s`
                      : "—"}
                  </div>
                </div>
              </div>

              {/* Commit & Origin Box */}
              <div className="p-4 rounded-xl bg-neutral-950/40 border border-neutral-800 space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-neutral-200 flex items-center gap-2">
                    <span className="material-symbols-outlined text-blue-400 text-base">commit</span>
                    Release Commit Details
                  </h4>
                  <button
                    onClick={() => copyToClipboard(deployment.commit_sha)}
                    className="text-xs text-neutral-400 hover:text-neutral-200 flex items-center gap-1 transition"
                  >
                    <span className="material-symbols-outlined text-sm">content_copy</span>
                    <span>{copiedSha ? "Copied!" : "Copy SHA"}</span>
                  </button>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm px-2.5 py-1 rounded bg-neutral-800 text-blue-300 font-bold">
                    {deployment.commit_sha.slice(0, 10)}
                  </span>
                  <span className="text-sm text-neutral-300 font-medium truncate">
                    {deployment.commit_message || "No commit message provided"}
                  </span>
                </div>
                <div className="text-xs text-neutral-400 flex items-center gap-4 pt-1 border-t border-neutral-800/80">
                  <span>Author / Trigger: <strong className="text-neutral-300">{deployment.deployed_by || "Automated Pipeline"}</strong></span>
                  {deployment.repository_full_name && (
                    <span>Repo: <strong className="text-neutral-300">{deployment.repository_full_name}</strong></span>
                  )}
                  {deployment.url && (
                    <a
                      href={deployment.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-400 hover:underline flex items-center gap-1"
                    >
                      <span>Build URL</span>
                      <span className="material-symbols-outlined text-xs">open_in_new</span>
                    </a>
                  )}
                </div>
              </div>

              {/* Previous Stable Release Comparison Link */}
              <div className="p-4 rounded-xl bg-neutral-950/40 border border-neutral-800 flex items-center justify-between">
                <div>
                  <div className="text-xs text-neutral-500 font-medium">Previous Stable Release</div>
                  <div className="text-sm font-medium text-neutral-300 mt-0.5">
                    {previousStable ? (
                      <span className="flex items-center gap-2">
                        <span className="font-mono text-xs px-2 py-0.5 rounded bg-neutral-800 text-neutral-300">
                          {previousStable.commit_sha.slice(0, 7)}
                        </span>
                        <span>{previousStable.version || "Previous Release"}</span>
                        <span className="text-xs text-neutral-500">
                          ({new Date(previousStable.deployed_at).toLocaleDateString()})
                        </span>
                      </span>
                    ) : (
                      <span className="text-neutral-500 italic">No prior stable deployment found on this target</span>
                    )}
                  </div>
                </div>
                {previousStable && (
                  <button
                    onClick={() => setActiveTab("commits")}
                    className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-xs font-semibold text-neutral-200 transition"
                  >
                    View Diff
                  </button>
                )}
              </div>
            </div>
          )}

          {activeTab === "commits" && (
            <div className="space-y-4">
              {loadingDiff ? (
                <div className="py-12 text-center text-neutral-500 text-sm animate-pulse">
                  Computing commit difference with Git provider...
                </div>
              ) : commitComparison ? (
                commitComparison.status === "available" ? (
                  <div className="space-y-3">
                    <div className="p-3 rounded-lg bg-neutral-950/60 border border-neutral-800 text-xs text-neutral-400 flex items-center justify-between">
                      <span>Comparing <code>{commitComparison.base_commit_sha?.slice(0, 7)}</code> ... <code>{commitComparison.head_commit_sha?.slice(0, 7)}</code></span>
                      <span className="text-neutral-300 font-medium">{commitComparison.total_commits} commit(s)</span>
                    </div>
                    <div className="divide-y divide-neutral-800/80 rounded-xl bg-neutral-950/40 border border-neutral-800 overflow-hidden">
                      {commitComparison.commits.map((c, i) => (
                        <div key={i} className="p-3.5 flex items-start justify-between gap-4">
                          <div>
                            <div className="text-sm font-medium text-neutral-200">{c.message}</div>
                            <div className="text-xs text-neutral-500 mt-1 flex items-center gap-2">
                              <span>{c.author || "Unknown author"}</span>
                              {c.timestamp && <span>• {new Date(c.timestamp).toLocaleString()}</span>}
                            </div>
                          </div>
                          <span className="font-mono text-xs px-2 py-0.5 rounded bg-neutral-800 text-blue-300">
                            {c.sha.slice(0, 7)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="p-6 rounded-xl bg-neutral-950/40 border border-neutral-800 text-center space-y-2">
                    <span className="material-symbols-outlined text-neutral-500 text-3xl">info</span>
                    <div className="text-sm font-medium text-neutral-300">Commit Comparison Unavailable</div>
                    <div className="text-xs text-neutral-500 max-w-md mx-auto">
                      {commitComparison.reason || "Git provider is not configured or both deployments belong to different repositories."}
                    </div>
                  </div>
                )
              ) : null}
            </div>
          )}

          {activeTab === "metadata" && (
            <div className="space-y-3">
              <pre className="p-4 rounded-xl bg-neutral-950 border border-neutral-800 text-xs text-neutral-300 font-mono overflow-x-auto max-h-[350px]">
                {JSON.stringify(deployment.metadata || {}, null, 2)}
              </pre>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 border-t border-neutral-800 bg-neutral-950/40 flex items-center justify-between">
          <div className="text-xs text-neutral-500">
            ID: <span className="font-mono text-neutral-400">{deployment.id}</span>
          </div>
          <div className="flex items-center gap-3">
            {deployment.status === "succeeded" && (
              <button
                onClick={handleRollback}
                disabled={rollingBack}
                className="px-3.5 py-2 rounded-xl bg-amber-950/60 hover:bg-amber-900/80 border border-amber-800/80 text-amber-300 text-xs font-semibold transition flex items-center gap-1.5"
              >
                <span className="material-symbols-outlined text-sm">undo</span>
                <span>{rollingBack ? "Marking Rolled Back..." : "Mark as Rolled Back"}</span>
              </button>
            )}
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-neutral-800 hover:bg-neutral-700 text-xs font-semibold text-neutral-200 transition"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
