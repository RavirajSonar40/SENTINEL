"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import {
  getIncident, getInvestigation, listEvidence, listHypotheses,
  Incident, Investigation, Evidence, Hypothesis,
  listRepositories, Repository,
  triggerInvestigation, getEngineStatus,
  getRootCause, listFixes, RootCause, ProposedFix,
  getInvestigationTimeline, TimelineEvent,
  getRepoCommits, getRepoPRs, getRepoBranches,
} from "@/lib/api";

const severityStyles: Record<string, string> = {
  "SEV-1": "bg-error/10 text-error border-error/20",
  "SEV-2": "bg-tertiary-container/10 text-tertiary border-tertiary/20",
  "SEV-3": "bg-primary/10 text-primary border-primary/20",
  "SEV-4": "bg-surface-variant text-on-surface-variant border-outline-variant",
};

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
};

const evidenceSourceIcons: Record<string, string> = {
  commit: "commit",
  diff: "difference",
  file: "description",
  function: "code",
  log: "terminal",
  metric: "monitoring",
  trace: "route",
  alert: "notification_important",
  deployment: "update",
  documentation: "menu_book",
  runbook: "menu_book",
  previous_incident: "history",
  pull_request: "merge",
  issue: "issue",
};

export default function InvestigationDetail() {
  const { token } = useAuth();
  const params = useParams();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [investigating, setInvestigating] = useState(false);
  const [engineResult, setEngineResult] = useState<any>(null);
  const [rootCause, setRootCause] = useState<RootCause | null>(null);
  const [fixes, setFixes] = useState<ProposedFix[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [githubData, setGithubData] = useState<{commits: any[]; prs: any[]; branches: any[]}>({commits: [], prs: [], branches: []});
  const [githubLoading, setGithubLoading] = useState<string | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<string>("");

  const handleFetchGithub = async (type: "commits" | "prs" | "branches") => {
    if (!token || !repos.length) return;
    setGithubLoading(type);
    try {
      const repo = repos[0];
      const [owner, name] = repo.full_name.split("/");
      if (type === "commits") {
        const commits = await getRepoCommits(token, owner, name);
        setGithubData((prev) => ({ ...prev, commits: Array.isArray(commits) ? commits : [] }));
      } else if (type === "prs") {
        const prs = await getRepoPRs(token, owner, name);
        setGithubData((prev) => ({ ...prev, prs: Array.isArray(prs) ? prs : [] }));
      } else {
        const branches = await getRepoBranches(token, owner, name);
        setGithubData((prev) => ({ ...prev, branches: Array.isArray(branches) ? branches : [] }));
      }
    } catch (e) {
      console.error("GitHub fetch error:", e);
    } finally {
      setGithubLoading(null);
    }
  };

  const handleRunInvestigation = async () => {
    if (!token || !incident) return;
    setInvestigating(true);
    setEngineResult(null);
    try {
      const result = await triggerInvestigation(token, incident.id, selectedRepo || undefined);
      setEngineResult(result);
      // Refresh data
      const inc = await getIncident(token, incident.id);
      setIncident(inc);
      if (inc.investigation) {
        const inv = await getInvestigation(token, inc.investigation.id);
        setInvestigation(inv);
        const ev = await listEvidence(token, inc.investigation.id).catch(() => []);
        setEvidence(ev);
        const hyp = await listHypotheses(token, inc.investigation.id).catch(() => []);
        setHypotheses(hyp);
      }
    } catch (err) {
      console.error("Investigation failed:", err);
      setEngineResult({ status: "failed", message: String(err) });
    } finally {
      setInvestigating(false);
    }
  };

  useEffect(() => {
    if (!token || !params.id) return;
    const id = params.id as string;

    getIncident(token, id)
      .then((inc) => {
        setIncident(inc);
        if (inc.investigation) {
          getInvestigation(token, inc.investigation.id).then(setInvestigation);
          listEvidence(token, inc.investigation.id).then(setEvidence).catch(() => {});
          listHypotheses(token, inc.investigation.id).then(setHypotheses).catch(() => {});
          getRootCause(token, inc.investigation.id).then(setRootCause).catch(() => {});
          listFixes(token, inc.investigation.id).then(setFixes).catch(() => {});
          getInvestigationTimeline(token, inc.investigation.id).then(setTimeline).catch(() => {});
        }
        // Load repositories for GitHub evidence
        listRepositories(token).then(setRepos).catch(() => {});
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token, params.id]);

  if (loading) {
    return (
      <>
        <TopBar breadcrumbs={[{ label: "Loading..." }]} />
        <main className="flex-1 p-4 pb-20 flex items-center justify-center">
          <div className="text-on-surface-variant font-mono text-[12px]">Loading investigation...</div>
        </main>
      </>
    );
  }

  if (!incident) {
    return (
      <>
        <TopBar breadcrumbs={[{ label: "Not Found" }]} />
        <main className="flex-1 p-4 pb-20 flex items-center justify-center">
          <div className="text-on-surface-variant font-mono text-[12px]">Incident not found.</div>
        </main>
      </>
    );
  }

  return (
    <>
      <TopBar
        breadcrumbs={[
          { label: `INC-${incident.number}`, href: `/incidents/${incident.id}` },
          { label: incident.severity },
          { label: "Investigation", active: true },
        ]}
      />
      <main className="flex-1 p-4 pb-20">
        <div className="max-w-[1600px] mx-auto flex gap-3 h-full">
          {/* Left Column - Incident Summary */}
          <div className="w-[300px] flex-shrink-0 flex flex-col gap-1">
            <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
              <div className="flex items-center justify-between mb-4 border-b border-outline-variant pb-2">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
                  Incident Summary
                </h2>
                <span className={`px-1.5 py-0.5 rounded font-mono text-[11px] border ${
                  severityStyles[incident.severity] || ""
                }`}>
                  {incident.severity}
                </span>
              </div>
              <div className="space-y-3 font-mono text-[11px]">
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">ID</span>
                  <span className="text-on-surface">INC-{incident.number}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Service</span>
                  <span className="text-on-surface">{incident.service || "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Source</span>
                  <span className="text-on-surface">{incident.source}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Status</span>
                  <span className="text-on-surface">{statusLabels[incident.status] || incident.status}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Confidence</span>
                  <span className={`font-semibold ${
                    incident.confidence === "high" ? "text-primary" :
                    incident.confidence === "medium" ? "text-tertiary" :
                    "text-on-surface-variant"
                  }`}>
                    {incident.confidence?.toUpperCase() || "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-on-surface-variant">Created</span>
                  <span className="text-on-surface">{new Date(incident.created_at).toLocaleString()}</span>
                </div>
              </div>

              {incident.description && (
                <div className="mt-4 pt-3 border-t border-outline-variant/50">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-2">
                    Description
                  </h3>
                  <p className="text-[11px] text-on-surface-variant leading-relaxed">
                    {incident.description}
                  </p>
                </div>
              )}

              {incident.root_cause_summary && (
                <div className="mt-4 pt-3 border-t border-outline-variant/50">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-2">
                    Root Cause
                  </h3>
                  <p className="text-[11px] text-on-surface leading-relaxed">
                    {incident.root_cause_summary}
                  </p>
                </div>
              )}

              {incident.repositories.length > 0 && (
                <div className="mt-4 pt-3 border-t border-outline-variant/50">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-2">
                    Repository Scope
                  </h3>
                  <div className="font-mono text-[11px] space-y-1">
                    {incident.repositories.map((repo) => (
                      <div key={repo.id} className="text-primary">{repo.full_name}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Right Column - Investigation Details */}
          <div className="flex-1 flex flex-col gap-1 min-w-0">
            {/* Run AI Investigation Button */}
            {(!investigation || investigation.status === "created" || investigation.status === "investigating") && (
              <div className="bg-primary/5 border border-primary/20 rounded p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-[12px] font-semibold text-primary">
                      AI Investigation Engine
                    </h2>
                    <p className="text-[11px] text-on-surface-variant mt-1">
                      Run semantic code analysis, generate hypotheses, and identify root cause
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {repos.length > 0 && (
                      <select
                        value={selectedRepo}
                        onChange={(e) => setSelectedRepo(e.target.value)}
                        className="bg-surface-container border border-outline-variant rounded px-2 py-1.5 text-[11px] text-on-surface appearance-none pr-6"
                      >
                        <option value="">All repositories</option>
                        {repos.map((repo) => (
                          <option key={repo.id} value={repo.full_name}>{repo.name}</option>
                        ))}
                      </select>
                    )}
                    <button
                      onClick={handleRunInvestigation}
                      disabled={investigating}
                      className={`px-4 py-2 rounded text-[12px] font-medium transition-all ${
                        investigating
                          ? "bg-primary/20 text-primary/50 cursor-not-allowed"
                          : "bg-primary text-on-primary hover:bg-primary/90"
                      }`}
                    >
                    {investigating ? (
                      <span className="flex items-center gap-2">
                        <span className="w-3 h-3 border-2 border-on-primary/30 border-t-on-primary rounded-full animate-spin" />
                        Investigating...
                      </span>
                    ) : (
                      <span className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-[16px]">psychology</span>
                        Run AI Investigation
                      </span>
                    )}
                  </button>
                  </div>
                </div>

                {/* Engine Result */}
                {engineResult && (
                  <div className={`mt-3 p-3 rounded border ${
                    engineResult.status === "completed"
                      ? "bg-primary/10 border-primary/20"
                      : "bg-error/10 border-error/20"
                  }`}>
                    <div className="font-mono text-[11px] space-y-1">
                      <div className="flex gap-4">
                        <span>Tasks: {engineResult.tasks_completed} completed, {engineResult.tasks_failed} failed</span>
                        <span>Evidence: {engineResult.evidence_count} items</span>
                        <span>Hypotheses: {engineResult.hypotheses_count}</span>
                      </div>
                      <div className="flex gap-4">
                        <span>Confidence: {engineResult.confidence?.toUpperCase()}</span>
                        <span>Root Cause: {engineResult.root_cause_found ? "Found" : "Not identified"}</span>
                      </div>
                      <div className="text-on-surface-variant">{engineResult.message}</div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Investigation Timeline */}
            {timeline.length > 0 && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-4">
                  Investigation Timeline
                </h2>
                <div className="relative">
                  <div className="absolute left-[15px] top-0 bottom-0 w-px bg-surface-container-highest" />
                  <div className="space-y-3">
                    {timeline.map((event, i) => (
                      <div key={i} className="flex items-start gap-3 relative">
                        <div className={`w-[30px] h-[30px] rounded-full flex items-center justify-center shrink-0 z-10 ${
                          event.color === "primary" ? "bg-primary text-on-primary" :
                          event.color === "error" ? "bg-error text-on-error" :
                          "bg-surface-container-highest text-on-surface-variant"
                        }`}>
                          <span className="material-symbols-rounded text-[14px]">{event.icon}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-[13px]">{event.label}</span>
                            <span className="text-[10px] text-on-surface-variant font-mono">
                              {event.time ? new Date(event.time).toLocaleTimeString("en-US", { hour12: false }) : ""}
                            </span>
                          </div>
                          {event.detail && (
                            <div className="text-[11px] text-on-surface-variant truncate">{event.detail}</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Investigation Progress */}
            {investigation && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
                    Investigation Progress
                  </h2>
                  <div className="flex items-center gap-3 font-mono text-[11px]">
                    <span className="text-on-surface-variant">
                      Model: {investigation.llm_model || "—"}
                    </span>
                    <span className="text-on-surface-variant">
                      Tokens: {investigation.total_tokens.toLocaleString()}
                    </span>
                    <span className="text-on-surface-variant">
                      Cost: ${investigation.total_cost_usd.toFixed(4)}
                    </span>
                  </div>
                </div>

                <div className="mb-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] text-on-surface-variant">
                      {investigation.current_step || "Starting..."}
                    </span>
                    <span className="text-[11px] font-mono text-on-surface">
                      {investigation.progress_percent}%
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all duration-500"
                      style={{ width: `${investigation.progress_percent}%` }}
                    />
                  </div>
                </div>

                <div className="flex gap-2 font-mono text-[11px]">
                  <span className={`px-2 py-0.5 rounded border ${
                    investigation.root_cause_found
                      ? "bg-primary/10 text-primary border-primary/20"
                      : "bg-surface-container-high text-on-surface-variant border-outline-variant"
                  }`}>
                    {investigation.root_cause_found ? "Root Cause Found" : "Investigating"}
                  </span>
                  {investigation.confidence && (
                    <span className={`px-2 py-0.5 rounded border ${
                      investigation.confidence === "high"
                        ? "bg-primary/10 text-primary border-primary/20"
                        : investigation.confidence === "medium"
                        ? "bg-tertiary/10 text-tertiary border-tertiary/20"
                        : "bg-surface-container-high text-on-surface-variant border-outline-variant"
                    }`}>
                      Confidence: {investigation.confidence.toUpperCase()}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Hypotheses */}
            {hypotheses.length > 0 && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                  Hypotheses ({hypotheses.length})
                </h2>
                <div className="space-y-2">
                  {hypotheses.map((hyp) => (
                    <div
                      key={hyp.id}
                      className={`p-3 rounded border ${
                        hyp.status === "supported"
                          ? "border-primary/30 bg-primary/5"
                          : hyp.status === "rejected"
                          ? "border-outline-variant bg-surface-container"
                          : "border-outline-variant"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[12px] font-medium text-on-surface">
                          {hyp.label} — {hyp.description}
                        </span>
                        <span className={`text-[11px] font-mono px-1.5 py-0.5 rounded ${
                          hyp.status === "supported"
                            ? "bg-primary/10 text-primary"
                            : hyp.status === "rejected"
                            ? "bg-surface-container-high text-on-surface-variant"
                            : "bg-tertiary/10 text-tertiary"
                        }`}>
                          {hyp.status}
                        </span>
                      </div>
                      <div className="flex gap-3 font-mono text-[11px] text-on-surface-variant mt-1">
                        <span>Confidence: {hyp.confidence}</span>
                        <span>Support: {hyp.supporting_evidence_count}</span>
                        <span>Contradict: {hyp.contradicting_evidence_count}</span>
                        {hyp.rejection_reason && (
                          <span className="text-error">Reason: {hyp.rejection_reason}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Evidence */}
            {evidence.length > 0 && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                  Evidence ({evidence.length})
                </h2>
                <div className="space-y-2">
                  {evidence.map((ev) => (
                    <div
                      key={ev.id}
                      className="p-3 rounded border border-outline-variant bg-surface-container"
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="material-symbols-outlined text-[14px] text-primary">
                          {evidenceSourceIcons[ev.source_type] || "help"}
                        </span>
                        <span className="text-[12px] font-medium text-on-surface">
                          {ev.title}
                        </span>
                        <span className="text-[11px] font-mono text-on-surface-variant ml-auto">
                          {ev.source_type}
                        </span>
                      </div>
                      {ev.summary && (
                        <p className="text-[11px] text-on-surface-variant ml-6">
                          {ev.summary}
                        </p>
                      )}
                      <div className="flex gap-3 font-mono text-[11px] text-on-surface-variant ml-6 mt-1">
                        {ev.repository && <span>{ev.repository}</span>}
                        {ev.file_path && <span>{ev.file_path}</span>}
                        {ev.source_id && <span>{ev.source_id.slice(0, 7)}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* GitHub Evidence */}
            {repos.length > 0 && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                  GitHub Evidence
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="bg-surface-container border border-outline-variant rounded p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined text-[16px] text-primary">commit</span>
                      <span className="text-[12px] font-medium text-on-surface">Recent Commits</span>
                    </div>
                    <p className="text-[12px] text-on-surface-variant">
                      Fetch commits from connected repositories to find suspicious changes.
                    </p>
                    <button
                      onClick={() => handleFetchGithub("commits")}
                      disabled={githubLoading === "commits"}
                      className="mt-2 text-[11px] text-primary hover:underline disabled:opacity-50"
                    >
                      {githubLoading === "commits" ? "Fetching..." : githubData.commits.length > 0 ? `View ${githubData.commits.length} Commits` : "Fetch Commits"}
                    </button>
                    {githubData.commits.length > 0 && (
                      <div className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                        {githubData.commits.slice(0, 5).map((c: any, i: number) => (
                          <div key={i} className="text-[10px] font-mono text-on-surface-variant truncate">
                            {c.sha?.slice(0, 7)} {c.commit?.message?.slice(0, 40)}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="bg-surface-container border border-outline-variant rounded p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined text-[16px] text-tertiary">merge</span>
                      <span className="text-[12px] font-medium text-on-surface">Pull Requests</span>
                    </div>
                    <p className="text-[12px] text-on-surface-variant">
                      Review recent PRs and their diffs for potential root causes.
                    </p>
                    <button
                      onClick={() => handleFetchGithub("prs")}
                      disabled={githubLoading === "prs"}
                      className="mt-2 text-[11px] text-primary hover:underline disabled:opacity-50"
                    >
                      {githubLoading === "prs" ? "Fetching..." : githubData.prs.length > 0 ? `View ${githubData.prs.length} PRs` : "View PRs"}
                    </button>
                    {githubData.prs.length > 0 && (
                      <div className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                        {githubData.prs.slice(0, 5).map((p: any, i: number) => (
                          <div key={i} className="text-[10px] font-mono text-on-surface-variant truncate">
                            #{p.number} {p.title?.slice(0, 40)}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="bg-surface-container border border-outline-variant rounded p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined text-[16px] text-secondary">hub</span>
                      <span className="text-[12px] font-medium text-on-surface">Branches</span>
                    </div>
                    <p className="text-[12px] text-on-surface-variant">
                      Compare branches and deployment tags for regression analysis.
                    </p>
                    <button
                      onClick={() => handleFetchGithub("branches")}
                      disabled={githubLoading === "branches"}
                      className="mt-2 text-[11px] text-primary hover:underline disabled:opacity-50"
                    >
                      {githubLoading === "branches" ? "Fetching..." : githubData.branches.length > 0 ? `View ${githubData.branches.length} Branches` : "Compare"}
                    </button>
                    {githubData.branches.length > 0 && (
                      <div className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                        {githubData.branches.slice(0, 5).map((b: any, i: number) => (
                          <div key={i} className="text-[10px] font-mono text-on-surface-variant truncate">
                            {b.name}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div className="mt-3 p-3 bg-surface-container-high border border-outline-variant rounded">
                  <p className="text-[11px] text-on-surface-variant">
                    Connect GitHub in <a href="/integrations" className="text-primary hover:underline">Integrations</a> to enable automatic commit/PR fetching and webhook-based real-time sync.
                  </p>
                </div>
              </div>
            )}

            {/* Root Cause */}
            {rootCause && (
              <div className="bg-primary/5 border border-primary/20 rounded p-4">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-primary mb-3">
                  Root Cause Identified
                </h2>
                <div className="space-y-3">
                  <div>
                    <div className="text-[13px] font-medium text-on-surface mb-1">{rootCause.summary}</div>
                    <div className="text-[11px] text-on-surface-variant">{rootCause.causal_explanation}</div>
                  </div>
                  <div className="flex gap-3 font-mono text-[11px]">
                    <span className={`px-2 py-0.5 rounded border ${
                      rootCause.confidence === "high"
                        ? "bg-primary/10 text-primary border-primary/20"
                        : rootCause.confidence === "medium"
                        ? "bg-tertiary/10 text-tertiary border-tertiary/20"
                        : "bg-surface-container-high text-on-surface-variant border-outline-variant"
                    }`}>
                      Confidence: {rootCause.confidence}
                    </span>
                    {rootCause.affected_component && (
                      <span className="text-on-surface-variant">Component: {rootCause.affected_component}</span>
                    )}
                  </div>
                  {rootCause.relevant_files && rootCause.relevant_files.length > 0 && (
                    <div className="mt-2">
                      <div className="text-[10px] text-on-surface-variant mb-1">Affected Files:</div>
                      <div className="flex flex-wrap gap-1">
                        {rootCause.relevant_files.map((f, i) => (
                          <span key={i} className="px-2 py-0.5 bg-surface-container rounded text-[10px] font-mono text-on-surface-variant">
                            {f}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Proposed Fixes */}
            {fixes.length > 0 && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
                  Proposed Fixes ({fixes.length})
                </h2>
                <div className="space-y-2">
                  {fixes.map((fix) => (
                    <div
                      key={fix.id}
                      className={`p-3 rounded border ${
                        fix.status === "approved"
                          ? "border-green-500/30 bg-green-500/5"
                          : fix.status === "rejected"
                          ? "border-error/30 bg-error/5"
                          : "border-outline-variant"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="material-symbols-outlined text-[14px] text-primary">
                            {fix.fix_type === "rollback" ? "replay" : fix.fix_type === "dependency_update" ? "system_update" : "code"}
                          </span>
                          <span className="text-[12px] font-medium text-on-surface">{fix.title}</span>
                        </div>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${
                          fix.status === "approved"
                            ? "bg-green-500/10 text-green-400"
                            : fix.status === "rejected"
                            ? "bg-error/10 text-error"
                            : fix.status === "in_progress"
                            ? "bg-primary/10 text-primary"
                            : "bg-surface-container-high text-on-surface-variant"
                        }`}>
                          {fix.status}
                        </span>
                      </div>
                      <p className="text-[11px] text-on-surface-variant ml-6">{fix.description}</p>
                      <div className="flex gap-3 mt-2 ml-6 font-mono text-[10px] text-on-surface-variant">
                        <span>Type: {fix.fix_type}</span>
                        <span>Approach: {fix.approach}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Placeholder when no investigation data */}
            {!investigation && evidence.length === 0 && hypotheses.length === 0 && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-4">
                  Investigation Status
                </h2>
                <div className="flex items-center gap-2 text-on-surface text-[12px]">
                  <span className="w-2 h-2 rounded-full bg-tertiary" />
                  {incident.status === "created" && "Awaiting investigation start"}
                  {incident.status === "investigating" && "Investigation in progress..."}
                  {incident.status === "resolved" && "Investigation complete"}
                </div>
                <p className="text-[12px] text-on-surface-variant mt-4">
                  Investigation details, hypotheses, evidence, and proposed fixes will appear here once the investigation engine is active.
                </p>
                {incident.status === "created" && (
                  <button
                    onClick={handleRunInvestigation}
                    className="mt-4 px-4 py-2 bg-primary-container text-on-primary-container text-[12px] font-semibold uppercase tracking-wider rounded-md border border-primary hover:bg-primary hover:text-on-primary-fixed transition-colors flex items-center gap-2"
                  >
                    <span className="material-symbols-outlined text-[16px]">play_arrow</span>
                    Start Investigation
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
