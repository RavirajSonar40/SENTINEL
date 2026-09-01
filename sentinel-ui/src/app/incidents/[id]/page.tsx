"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import DiffViewer from "@/components/DiffViewer";
import { useAuth } from "@/lib/AuthContext";
import {
  getIncident, updateIncident, deleteIncident, getInvestigation, listEvidence, listHypotheses,
  Incident, Investigation, Evidence, Hypothesis,
  listRepositories, Repository,
  triggerInvestigationStream, InvestigationStep,
  getRootCause, listFixes, RootCause, ProposedFix,
  generateDraftPR,
  getInvestigationTimeline, TimelineEvent,
  getRepoCommits, getRepoPRs, getRepoBranches,
} from "@/lib/api";
import { graphApi, IncidentBlastRadiusReport } from "@/lib/graphApi";
import {
  changeApi,
  ChangeCorrelationReport,
  IncidentChangeCorrelation,
  CorrelationStatus,
} from "@/lib/changeApi";
import {
  getIncidentEvidence,
  submitManualEvidence,
  verifyEvidence,
  submitEvidenceCorrection,
  getIncidentHypotheses,
  evaluateHypotheses,
  triageHypothesis,
  getIncidentRootCause,
  overrideRootCause,
  EvidenceItem,
  EvidenceListResponse,
  HypothesisItem,
  RootCauseReport,
} from "@/lib/evidenceApi";
import ExplainableTimeline from "@/components/ExplainableTimeline";
import PostMortemStudio from "@/components/PostMortemStudio";
import { PatchStudio } from "@/components/PatchStudio";
import { MultiRepoRemediationStudio } from "@/components/MultiRepoRemediationStudio";
import { patchApi, ProposedFixDetail } from "@/lib/patchApi";
import { reliabilityApi, IncidentBusinessImpactItem } from "@/lib/reliabilityApi";


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
  const router = useRouter();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [investigating, setInvestigating] = useState(false);
  const [engineResult, setEngineResult] = useState<{
    status?: string;
    tasks_completed?: number;
    tasks_failed?: number;
    evidence_count?: number;
    hypotheses_count?: number;
    confidence?: string;
    root_cause_found?: boolean;
    message?: string;
  } | null>(null);
  const [rootCause, setRootCause] = useState<RootCause | null>(null);
  const [fixes, setFixes] = useState<ProposedFix[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [githubData, setGithubData] = useState<{commits: Array<{sha?: string; commit?: {message?: string}}>; prs: Array<{number?: number; title?: string}>; branches: Array<{name?: string}>}>({commits: [], prs: [], branches: []});
  const [githubLoading, setGithubLoading] = useState<string | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<string>("");
  const [streamSteps, setStreamSteps] = useState<InvestigationStep[]>([]);
  const [streamingActive, setStreamingActive] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [prLoading, setPrLoading] = useState<string | null>(null);
  const [prError, setPrError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editService, setEditService] = useState("");
  const [editSeverity, setEditSeverity] = useState("");
  const [editDescription, setEditDescription] = useState("");

  const [blastRadius, setBlastRadius] = useState<IncidentBlastRadiusReport | null>(null);
  const [blastLoading, setBlastLoading] = useState(false);
  const [recalculatingBlast, setRecalculatingBlast] = useState(false);

  const [changeReport, setChangeReport] = useState<ChangeCorrelationReport | null>(null);
  const [changeLoading, setChangeLoading] = useState(false);
  const [correlatingChanges, setCorrelatingChanges] = useState(false);
  const [triagingId, setTriagingId] = useState<string | null>(null);

  // Phase 9 States
  const [phase9Evidence, setPhase9Evidence] = useState<EvidenceItem[]>([]);
  const [phase9Families, setPhase9Families] = useState<string[]>([]);
  const [phase9Hypotheses, setPhase9Hypotheses] = useState<HypothesisItem[]>([]);
  const [phase9RootCause, setPhase9RootCause] = useState<RootCauseReport | null>(null);
  const [evidenceCategoryFilter, setEvidenceCategoryFilter] = useState<string>("all");
  const [evidenceFamilyFilter, setEvidenceFamilyFilter] = useState<string>("all");
  const [evaluatingHypotheses, setEvaluatingHypotheses] = useState(false);

  // Tab Navigation State
  const [mainTab, setMainTab] = useState<"investigation" | "timeline" | "postmortem" | "patch_studio" | "multi_repo">("investigation");
  const [patchDetail, setPatchDetail] = useState<ProposedFixDetail | null>(null);

  const [patchLoading, setPatchLoading] = useState(false);
  const [generatingPatch, setGeneratingPatch] = useState(false);
  const [patchError, setPatchError] = useState<string | null>(null);

  // Phase 16 Business Impact State
  const [businessImpact, setBusinessImpact] = useState<IncidentBusinessImpactItem | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);


  // Phase 9 Modals
  const [manualModalOpen, setManualModalOpen] = useState(false);
  const [manualTitle, setManualTitle] = useState("");
  const [manualCategory, setManualCategory] = useState<string>("fact");
  const [manualContent, setManualContent] = useState("");
  const [manualService, setManualService] = useState("");
  const [manualSubmitting, setManualSubmitting] = useState(false);

  const [correctionModalEvidence, setCorrectionModalEvidence] = useState<EvidenceItem | null>(null);
  const [correctionTitle, setCorrectionTitle] = useState("");
  const [correctionContent, setCorrectionContent] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [correctionSubmitting, setCorrectionSubmitting] = useState(false);

  const [triageModalHypothesis, setTriageModalHypothesis] = useState<HypothesisItem | null>(null);
  const [triageStatus, setTriageStatus] = useState<string>("supported");
  const [triageNotes, setTriageNotes] = useState("");
  const [triageSubmitting, setTriageSubmitting] = useState(false);

  const [overrideModalOpen, setOverrideModalOpen] = useState(false);
  const [overrideSummary, setOverrideSummary] = useState("");
  const [overrideExplanation, setOverrideExplanation] = useState("");
  const [overrideNotes, setOverrideNotes] = useState("");
  const [overrideSubmitting, setOverrideSubmitting] = useState(false);

  const loadBlastRadius = async () => {
    if (!params.id) return;
    setBlastLoading(true);
    try {
      const report = await graphApi.getIncidentBlastRadius(params.id as string);
      setBlastRadius(report);
    } catch (e) {
      console.error("Blast radius load error:", e);
    } finally {
      setBlastLoading(false);
    }
  };

  const handleRecalculateBlastRadius = async () => {
    if (!params.id) return;
    setRecalculatingBlast(true);
    try {
      const report = await graphApi.recalculateIncidentBlastRadius(params.id as string);
      setBlastRadius(report);
    } catch (e) {
      console.error("Recalculate blast radius error:", e);
    } finally {
      setRecalculatingBlast(false);
    }
  };

  const loadChangeCorrelations = async () => {
    if (!params.id) return;
    setChangeLoading(true);
    try {
      const rep = await changeApi.getIncidentChanges(params.id as string, 120);
      setChangeReport(rep);
    } catch (e) {
      console.error("Change correlations load error:", e);
    } finally {
      setChangeLoading(false);
    }
  };

  const handleForceCorrelateChanges = async () => {
    if (!params.id) return;
    setCorrelatingChanges(true);
    try {
      const rep = await changeApi.correlateIncidentChanges(params.id as string, 120);
      setChangeReport(rep);
    } catch (e) {
      console.error("Force correlate error:", e);
    } finally {
      setCorrelatingChanges(false);
    }
  };

  const handleTriageCorrelation = async (correlationId: string, triage_status: CorrelationStatus) => {
    if (!params.id) return;
    const reason = window.prompt(`Enter operator triage rationale for '${triage_status}':`) || undefined;
    setTriagingId(correlationId);
    try {
      await changeApi.triageCorrelation(params.id as string, correlationId, {
        triage_status,
        reason,
      });
      await loadChangeCorrelations();
    } catch (e) {
      console.error("Triage correlation error:", e);
    } finally {
      setTriagingId(null);
    }
  };

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

  const loadPhase9Data = async () => {
    if (!params.id) return;
    const id = params.id as string;
    try {
      const [evRes, hypRes, rcRes] = await Promise.allSettled([
        getIncidentEvidence(id),
        getIncidentHypotheses(id),
        getIncidentRootCause(id),
      ]);
      if (evRes.status === "fulfilled") {
        setPhase9Evidence(evRes.value.items || []);
        setPhase9Families(evRes.value.distinct_families || []);
      }
      if (hypRes.status === "fulfilled") {
        setPhase9Hypotheses(hypRes.value || []);
      }
      if (rcRes.status === "fulfilled") {
        setPhase9RootCause(rcRes.value || null);
      }
    } catch (e) {
      console.error("Phase 9 data load error:", e);
    }
  };

  const loadPatchDetail = async () => {
    if (!params.id) return;
    setPatchLoading(true);
    try {
      const fixList = await listFixes(token || "", params.id as string);
      if (fixList && fixList.length > 0) {
        const detail = await patchApi.getPatchDetail(fixList[0].id);
        setPatchDetail(detail);
      } else {
        setPatchDetail(null);
      }
    } catch (e) {
      console.error("Failed to load patch detail:", e);
    } finally {
      setPatchLoading(false);
    }
  };

  const loadBusinessImpact = async () => {
    if (!params.id) return;
    setImpactLoading(true);
    try {
      const imp = await reliabilityApi.getIncidentBusinessImpact(params.id as string);
      setBusinessImpact(imp);
    } catch (e) {
      console.error("Failed to load business impact:", e);
    } finally {
      setImpactLoading(false);
    }
  };

  const handleGeneratePatch = async () => {

    if (!incident) return;
    setGeneratingPatch(true);
    setPatchError(null);
    try {
      const detail = await patchApi.generatePatch({
        incident_id: incident.id,
        instructions: incident.description || incident.title,
      });
      setPatchDetail(detail);
      setMainTab("patch_studio");
    } catch (err: any) {
      setPatchError(err.message || "Failed to generate remediation patch");
    } finally {
      setGeneratingPatch(false);
    }
  };

  const handleManualEvidenceSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!params.id || !manualTitle) return;
    setManualSubmitting(true);
    try {
      await submitManualEvidence(params.id as string, {
        title: manualTitle,
        category_type: manualCategory,
        content: manualContent,
        service: manualService || (incident?.service ?? undefined),
      });
      setManualTitle("");
      setManualContent("");
      setManualModalOpen(false);
      await loadPhase9Data();
    } catch (err) {
      console.error("Submit manual evidence error:", err);
    } finally {
      setManualSubmitting(false);
    }
  };

  const handleVerifyEvidence = async (evId: string, status: "verified" | "rejected") => {
    if (!params.id) return;
    try {
      await verifyEvidence(params.id as string, evId, status);
      await loadPhase9Data();
    } catch (err) {
      console.error("Verify evidence error:", err);
    }
  };

  const handleCorrectionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!params.id || !correctionModalEvidence || !correctionTitle || !correctionReason) return;
    setCorrectionSubmitting(true);
    try {
      await submitEvidenceCorrection(params.id as string, {
        supersedes_evidence_id: correctionModalEvidence.id,
        title: correctionTitle,
        content: correctionContent,
        correction_reason: correctionReason,
      });
      setCorrectionModalEvidence(null);
      await loadPhase9Data();
    } catch (err) {
      console.error("Submit correction error:", err);
    } finally {
      setCorrectionSubmitting(false);
    }
  };

  const handleRunHypothesisCompetition = async () => {
    if (!params.id) return;
    setEvaluatingHypotheses(true);
    try {
      await evaluateHypotheses(params.id as string);
      await loadPhase9Data();
    } catch (err) {
      console.error("Evaluate hypotheses error:", err);
    } finally {
      setEvaluatingHypotheses(false);
    }
  };

  const handleTriageHypothesisSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!params.id || !triageModalHypothesis || !triageNotes) return;
    setTriageSubmitting(true);
    try {
      await triageHypothesis(params.id as string, triageModalHypothesis.id, triageStatus, triageNotes);
      setTriageModalHypothesis(null);
      await loadPhase9Data();
    } catch (err) {
      console.error("Triage hypothesis error:", err);
    } finally {
      setTriageSubmitting(false);
    }
  };

  const handleOverrideRootCauseSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!params.id || !overrideSummary || !overrideExplanation || !overrideNotes) return;
    setOverrideSubmitting(true);
    try {
      await overrideRootCause(params.id as string, {
        summary: overrideSummary,
        affected_component: incident?.service ?? undefined,
        causal_explanation: overrideExplanation,
        override_notes: overrideNotes,
      });
      setOverrideModalOpen(false);
      await loadPhase9Data();
    } catch (err) {
      console.error("Override root cause error:", err);
    } finally {
      setOverrideSubmitting(false);
    }
  };

  const handleRunInvestigation = async () => {
    if (!token || !incident) return;
    setInvestigating(true);
    setEngineResult(null);
    setStreamSteps([]);
    setStreamError(null);
    setStreamingActive(true);

    triggerInvestigationStream(
      token,
      incident.id,
      (step) => {
        setStreamSteps((prev) => {
          const existing = prev.findIndex((s) => s.step === step.step);
          if (existing >= 0) {
            const next = [...prev];
            next[existing] = step;
            return next;
          }
          return [...prev, step];
        });
      },
      async (data) => {
        setEngineResult(data as typeof engineResult);
        setStreamingActive(false);
        try {
          // Refresh all data
          const inc = await getIncident(token, incident.id);
          setIncident(inc);
          if (inc.investigation) {
            const inv = await getInvestigation(token, inc.investigation.id).catch(() => null);
            if (inv) setInvestigation(inv);
            const ev = await listEvidence(token, inc.investigation.id).catch(() => []);
            setEvidence(ev);
            const hyp = await listHypotheses(token, inc.investigation.id).catch(() => []);
            setHypotheses(hyp);
            const rc = await getRootCause(token, inc.investigation.id).catch(() => null);
            setRootCause(rc);
            const fx = await listFixes(token, inc.investigation.id).catch(() => []);
            setFixes(fx);
          }
        } catch (e) {
          console.error("Failed to refresh data after investigation:", e);
        }
        setInvestigating(false);
      },
      (errMsg) => {
        setStreamError(errMsg);
        setStreamingActive(false);
        setInvestigating(false);
      },
      selectedRepo || undefined,
    );
  };

  const handleCreateDraftPR = async (fix: ProposedFix) => {
    if (!token || !investigation) return;
    setPrLoading(fix.id);
    setPrError(null);
    try {
      await generateDraftPR(token, investigation.id, fix.id);
      const refreshed = await listFixes(token, investigation.id);
      setFixes(refreshed);
    } catch (error) {
      setPrError(error instanceof Error ? error.message : "Could not create draft PR");
    } finally {
      setPrLoading(null);
    }
  };

  useEffect(() => {
    if (!token || !params.id) return;
    const id = params.id as string;

    getIncident(token, id)
      .then((inc) => {
        setIncident(inc);
        setEditTitle(inc.title);
        setEditService(inc.service || "");
        setEditSeverity(inc.severity);
        setEditDescription(inc.description || "");
        if (inc.investigation) {
          getInvestigation(token, inc.investigation.id).then(setInvestigation).catch(() => {});
          listEvidence(token, inc.investigation.id).then(setEvidence).catch(() => {});
          listHypotheses(token, inc.investigation.id).then(setHypotheses).catch(() => {});
          getRootCause(token, inc.investigation.id).then(setRootCause).catch(() => {});
          listFixes(token, inc.investigation.id).then(setFixes).catch(() => {});
          getInvestigationTimeline(token, inc.investigation.id).then(setTimeline).catch(() => {});
        }
        // Load repositories for GitHub evidence
        listRepositories(token).then(setRepos).catch(() => {});
        loadBlastRadius();
        loadChangeCorrelations();
        loadPhase9Data();
        loadBusinessImpact();
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token, params.id]);


  const handleSaveIncident = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token || !incident) return;
    setEditSaving(true);
    setEditError(null);
    try {
      const updated = await updateIncident(token, incident.id, {
        title: editTitle,
        service: editService,
        severity: editSeverity,
        description: editDescription,
      });
      setIncident(updated);
      setEditing(false);
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "Could not update incident");
    } finally {
      setEditSaving(false);
    }
  };

  const handleDeleteIncident = async () => {
    if (!token || !incident) return;
    if (!window.confirm(`Delete INC-${incident.number}? This cannot be undone.`)) return;
    try {
      await deleteIncident(token, incident.id);
      router.push("/incidents");
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "Could not delete incident");
    }
  };

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
                <div className="flex items-center gap-2">
                  <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
                    Incident Summary
                  </h2>
                  <button type="button" title="Edit incident" onClick={() => setEditing(true)} className="text-on-surface-variant hover:text-primary">
                    <span className="material-symbols-outlined text-[15px]">edit</span>
                  </button>
                  <button type="button" title="Delete incident" onClick={handleDeleteIncident} className="text-on-surface-variant hover:text-error">
                    <span className="material-symbols-outlined text-[15px]">delete</span>
                  </button>
                </div>
                <span className={`px-1.5 py-0.5 rounded font-mono text-[11px] border ${
                  severityStyles[incident.severity] || ""
                }`}>
                  {incident.severity}
                </span>
              </div>

              {editing && (
                <form onSubmit={handleSaveIncident} className="mt-3 bg-surface-container border border-outline-variant rounded p-3 space-y-2">
                  <input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} placeholder="Title" required className="w-full bg-surface-container-high border border-outline-variant rounded px-2 py-1.5 text-[11px] text-on-surface" />
                  <input value={editService} onChange={(event) => setEditService(event.target.value)} placeholder="Service" required className="w-full bg-surface-container-high border border-outline-variant rounded px-2 py-1.5 text-[11px] text-on-surface" />
                  <select value={editSeverity} onChange={(event) => setEditSeverity(event.target.value)} className="w-full bg-surface-container-high border border-outline-variant rounded px-2 py-1.5 text-[11px] text-on-surface">
                    {['SEV-1', 'SEV-2', 'SEV-3', 'SEV-4'].map((severity) => <option key={severity}>{severity}</option>)}
                  </select>
                  <textarea value={editDescription} onChange={(event) => setEditDescription(event.target.value)} rows={4} placeholder="Description" className="w-full bg-surface-container-high border border-outline-variant rounded px-2 py-1.5 text-[11px] text-on-surface" />
                  {editError && <div className="text-[11px] text-error">{editError}</div>}
                  <div className="flex gap-2 justify-end">
                    <button type="button" onClick={() => setEditing(false)} className="px-2 py-1 text-[11px] text-on-surface-variant">Cancel</button>
                    <button type="submit" disabled={editSaving} className="px-2 py-1 rounded bg-primary text-on-primary text-[11px] disabled:opacity-50">{editSaving ? "Saving..." : "Save"}</button>
                  </div>
                </form>
              )}
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

              {(incident.repositories || []).length > 0 && (
                <div className="mt-4 pt-3 border-t border-outline-variant/50">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-2">
                    Repository Scope
                  </h3>
                  <div className="font-mono text-[11px] space-y-1">
                    {(incident.repositories || []).map((repo) => (
                      <div key={repo.id} className="text-primary">{repo.full_name}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Phase 16: Executive Financial & User Impact Card */}
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 space-y-3 shadow-sm">
              <div className="flex items-center justify-between">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[16px] text-emerald-400">payments</span>
                  Business Impact
                </h3>
                {businessImpact && (
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${businessImpact.sla_breach_detected ? "bg-red-500/20 text-red-400 border border-red-500/30" : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"}`}>
                    {businessImpact.sla_breach_detected ? "SLA BREACH" : "SLA COMPLIANT"}
                  </span>
                )}
              </div>

              {impactLoading ? (
                <div className="text-[11px] text-on-surface-variant font-mono py-2 text-center">
                  Calculating impact...
                </div>
              ) : businessImpact ? (
                <div className="space-y-2 text-[11px] font-mono">
                  <div className="p-2.5 rounded bg-surface-container border border-outline-variant/40 space-y-1">
                    <div className="text-[10px] text-on-surface-variant">Estimated Financial Loss</div>
                    <div className="text-[15px] font-bold text-emerald-400">
                      {businessImpact.financial_loss_display}
                    </div>
                    {businessImpact.is_estimated_default && (
                      <div className="text-[9px] text-on-surface-variant">(Org Baseline Estimate)</div>
                    )}
                  </div>

                  <div className="flex justify-between text-on-surface-variant">
                    <span>Duration:</span>
                    <span className="text-on-surface font-semibold">{businessImpact.outage_duration_minutes} mins</span>
                  </div>

                  <div className="flex justify-between text-on-surface-variant">
                    <span>Affected Users:</span>
                    <span className="text-on-surface font-semibold">{businessImpact.affected_user_count.toLocaleString()}</span>
                  </div>

                  <div className="flex justify-between text-on-surface-variant">
                    <span>Degradation:</span>
                    <span className="text-on-surface font-semibold">{(businessImpact.degradation_factor * 100).toFixed(0)}%</span>
                  </div>

                  {businessImpact.hourly_revenue_rate_usd && (
                    <div className="flex justify-between text-on-surface-variant pt-1 border-t border-outline-variant/30">
                      <span>Rate Base:</span>
                      <span className="text-on-surface">${businessImpact.hourly_revenue_rate_usd.toLocaleString()}/hr</span>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-[11px] text-on-surface-variant font-mono py-2 text-center">
                  No revenue baseline configured.
                </div>
              )}
            </div>
          </div>


          {/* Right Column - Investigation Details */}
          <div className="flex-1 flex flex-col gap-4 min-w-0">
            {/* Phase 10 Navigation Bar */}
            <div className="flex items-center gap-1.5 bg-surface-container-low border border-outline-variant p-1.5 rounded-xl shadow-sm overflow-x-auto">
              <button
                onClick={() => setMainTab("investigation")}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition ${
                  mainTab === "investigation"
                    ? "bg-primary text-on-primary shadow-sm"
                    : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container"
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">troubleshoot</span>
                Live Investigation &amp; Analysis
              </button>
              <button
                onClick={() => setMainTab("timeline")}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition ${
                  mainTab === "timeline"
                    ? "bg-primary text-on-primary shadow-sm"
                    : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container"
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">timeline</span>
                Explainable Timeline
              </button>
              <button
                onClick={() => setMainTab("postmortem")}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition ${
                  mainTab === "postmortem"
                    ? "bg-primary text-on-primary shadow-sm"
                    : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container"
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">description</span>
                Post-Mortem Studio
              </button>
              <button
                onClick={() => {
                  setMainTab("patch_studio");
                  loadPatchDetail();
                }}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition ${
                  mainTab === "patch_studio"
                    ? "bg-primary text-on-primary shadow-sm"
                    : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container"
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">code</span>
                Patch Studio &amp; Test Suite
              </button>
              <button
                onClick={() => setMainTab("multi_repo")}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition ${
                  mainTab === "multi_repo"
                    ? "bg-primary text-on-primary shadow-sm"
                    : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container"
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">account_tree</span>
                Multi-Repo Remediation
              </button>
            </div>

            {/* Multi-Repo Remediation View */}
            {mainTab === "multi_repo" && token && (
              <MultiRepoRemediationStudio
                incidentId={incident.id}
                token={token}
                onRefreshParent={() => {
                  if (token && params.id) {
                    getIncident(token, params.id as string).then(setIncident).catch(() => {});
                  }
                }}
              />
            )}


            {/* Patch Studio View */}
            {mainTab === "patch_studio" && (
              <div className="space-y-4">
                {patchLoading ? (
                  <div className="bg-surface-container-low border border-outline-variant rounded-xl p-8 text-center text-xs text-on-surface-variant font-mono">
                    Loading Patch Studio...
                  </div>
                ) : patchDetail ? (
                  <PatchStudio fix={patchDetail} onRefresh={loadPatchDetail} />
                ) : (
                  <div className="bg-surface-container-low border border-outline-variant rounded-xl p-8 text-center space-y-4 shadow-sm">
                    <div className="w-12 h-12 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mx-auto text-primary">
                      <span className="material-symbols-outlined text-2xl">auto_fix_high</span>
                    </div>
                    <div className="max-w-md mx-auto space-y-1">
                      <h3 className="font-bold text-on-surface text-base">No Remediation Patch Generated Yet</h3>
                      <p className="text-xs text-on-surface-variant">
                        Sentinel can autonomously synthesize a minimal git patch, pre-flight safety checklist, and two-phase regression test suite based on the verified root cause.
                      </p>
                    </div>
                    {patchError && (
                      <div className="max-w-md mx-auto p-3 rounded-lg bg-rose-950/40 border border-rose-800 text-xs text-rose-300">
                        {patchError}
                      </div>
                    )}
                    <button
                      onClick={handleGeneratePatch}
                      disabled={generatingPatch}
                      className="px-5 py-2.5 bg-primary text-on-primary text-xs font-semibold rounded-lg shadow-lg hover:opacity-90 transition disabled:opacity-50 inline-flex items-center gap-2"
                    >
                      <span className="material-symbols-outlined text-[16px]">play_arrow</span>
                      {generatingPatch ? "Synthesizing Patch & Regression Tests..." : "Generate Safe Remediation Patch"}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Timeline View */}
            {mainTab === "timeline" && (
              <ExplainableTimeline incidentId={incident.id} />
            )}

            {/* Post-Mortem View */}
            {mainTab === "postmortem" && (
              <PostMortemStudio incidentId={incident.id} />
            )}


            {/* Live Investigation View */}
            {mainTab === "investigation" && (
              <>
            {/* Phase 6 Blast Radius & Impact Card */}
            <div className="bg-surface-container-low border border-outline-variant rounded-xl p-5 shadow-sm space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-outline-variant/60 pb-3">
                <div className="flex items-center gap-2.5">
                  <span className="material-symbols-outlined text-rose-400 text-[22px]">radar</span>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-bold text-on-surface">Service Graph Blast Radius</h2>
                      {blastRadius && (
                        <span className="px-2 py-0.2 rounded text-[10px] font-mono bg-surface-container-highest text-on-surface-variant">
                          v{blastRadius.version} &bull; {blastRadius.engine_version}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-on-surface-variant">
                      Multi-hop dependency traversal, live telemetry correlation &amp; repository action classification.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={handleRecalculateBlastRadius}
                    disabled={recalculatingBlast || blastLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-container-highest text-[11px] font-medium border border-outline-variant transition-colors disabled:opacity-50"
                  >
                    <span className={`material-symbols-outlined text-[14px] ${recalculatingBlast ? "animate-spin" : ""}`}>
                      refresh
                    </span>
                    {recalculatingBlast ? "Recalculating..." : "Recalculate"}
                  </button>
                  <Link
                    href="/topology"
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary text-[11px] font-medium transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">schema</span>
                    View Graph
                  </Link>
                </div>
              </div>

              {blastLoading ? (
                <div className="p-4 text-center text-xs text-on-surface-variant">
                  <span className="material-symbols-outlined animate-spin text-[20px] mb-1">progress_activity</span>
                  <div>Evaluating system dependency graph...</div>
                </div>
              ) : blastRadius ? (
                <div className="space-y-4">
                  {/* Customer Impact Summary Banner */}
                  <div className="bg-gradient-to-r from-rose-950/30 via-surface-container-lowest to-surface-container-lowest p-4 rounded-xl border border-rose-500/20">
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                            blastRadius.customer_impact.traffic_impact_mode === "measured"
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                              : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                          }`}>
                            {blastRadius.customer_impact.traffic_impact_mode.toUpperCase()} IMPACT
                          </span>
                          <span className="text-[11px] text-on-surface-variant">
                            Confidence: <strong className="text-on-surface">{blastRadius.customer_impact.traffic_confidence?.toUpperCase()}</strong>
                          </span>
                        </div>
                        <div className="text-xs text-on-surface-variant mt-1">
                          {blastRadius.customer_impact.calculation_basis || "Calculated using graph topology heuristics."}
                        </div>
                      </div>

                      <div className="flex items-center gap-3 bg-surface-container-low px-4 py-2 rounded-lg border border-outline-variant">
                        <div className="text-center">
                          <div className="text-[10px] uppercase text-on-surface-variant font-semibold">Traffic Risk</div>
                          <div className="text-xl font-black text-rose-400">
                            {blastRadius.customer_impact.traffic_percent || 0}%
                          </div>
                        </div>
                        <div className="h-6 w-px bg-outline-variant" />
                        <div className="text-center">
                          <div className="text-[10px] uppercase text-on-surface-variant font-semibold">Users Risk</div>
                          <div className="text-xl font-black text-amber-400">
                            {blastRadius.customer_impact.user_percent || 0}%
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Impacted Entities Columns */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                    {/* Indirect Downstream Services */}
                    <div className="p-3 bg-surface-container-lowest rounded-lg border border-outline-variant space-y-2">
                      <div className="font-semibold text-[11px] text-on-surface-variant uppercase tracking-wider flex items-center justify-between">
                        <span>Downstream Callers ({blastRadius.indirect_services.length})</span>
                      </div>
                      {blastRadius.indirect_services.length === 0 ? (
                        <div className="text-on-surface-variant/60 italic py-1">No downstream callers impacted.</div>
                      ) : (
                        <div className="space-y-1.5 max-h-[160px] overflow-y-auto pr-1">
                          {blastRadius.indirect_services.map((svc, idx) => (
                            <div key={idx} className="flex items-center justify-between p-2 rounded bg-surface-container-low border border-outline-variant/60">
                              <div>
                                <div className="font-medium text-on-surface flex items-center gap-1.5">
                                  <span>{svc.name}</span>
                                  <span className={`px-1 py-0.2 rounded text-[9px] font-bold ${svc.impact_type === "observed" ? "bg-rose-500/20 text-rose-300" : "bg-sky-500/20 text-sky-300"}`}>
                                    {svc.impact_type.toUpperCase()}
                                  </span>
                                </div>
                                <div className="text-[10px] text-on-surface-variant">
                                  Hop {svc.distance} &bull; {svc.impact_level}
                                </div>
                              </div>
                              <span className={`text-[10px] font-mono font-bold ${svc.criticality === "hard" ? "text-rose-400" : "text-amber-400"}`}>
                                {svc.criticality.toUpperCase()}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Affected Repositories with Remediation Target vs Evidence Only */}
                    <div className="p-3 bg-surface-container-lowest rounded-lg border border-outline-variant space-y-2">
                      <div className="font-semibold text-[11px] text-on-surface-variant uppercase tracking-wider">
                        Repository Scopes ({blastRadius.affected_repositories.length})
                      </div>
                      {blastRadius.affected_repositories.length === 0 ? (
                        <div className="text-on-surface-variant/60 italic py-1">No linked repositories.</div>
                      ) : (
                        <div className="space-y-1.5 max-h-[160px] overflow-y-auto pr-1">
                          {blastRadius.affected_repositories.map((repo, idx) => (
                            <div key={idx} className="flex items-center justify-between p-2 rounded bg-surface-container-low border border-outline-variant/60">
                              <div className="truncate mr-2">
                                <div className="font-medium text-on-surface truncate">{repo.name}</div>
                                <div className="text-[10px] text-on-surface-variant">{repo.role}</div>
                              </div>
                              <div>
                                {repo.remediation_target ? (
                                  <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 whitespace-nowrap">
                                    Remediation Target
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 rounded-full text-[9px] font-bold bg-surface-container-highest text-on-surface-variant border border-outline-variant whitespace-nowrap">
                                    Evidence Only
                                  </span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="p-3 bg-surface-container-lowest rounded-lg border border-outline-variant text-xs text-on-surface-variant flex items-center justify-between">
                  <span>Blast radius analysis is not yet generated for this incident.</span>
                  <button
                    onClick={handleRecalculateBlastRadius}
                    className="px-3 py-1 bg-primary text-on-primary rounded text-xs font-medium"
                  >
                    Calculate Now
                  </button>
                </div>
              )}
            </div>

            {/* Phase 7 Change Intelligence & Temporal Correlation Card */}
            <div className="bg-surface-container-low border border-outline-variant/80 rounded-xl p-4 space-y-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-20">history_toggle_off</span>
                  <h3 className="font-bold text-14 text-on-surface">Change Intelligence & Temporal Correlation</h3>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-primary/20 text-primary border border-primary/30">
                    P7 {changeReport ? `v${changeReport.version}` : ""}
                  </span>
                  {changeReport && changeReport.snapshot_hash && (
                    <span className="hidden sm:inline-block px-1.5 py-0.5 rounded text-[10px] font-mono text-on-surface-variant bg-surface-container-high border border-outline-variant" title={`Snapshot SHA-256: ${changeReport.snapshot_hash}`}>
                      {changeReport.snapshot_hash.slice(0, 8)}
                    </span>
                  )}
                  {changeReport && changeReport.causal_candidates_count > 0 && (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse">
                      {changeReport.causal_candidates_count} Causal Candidate{changeReport.causal_candidates_count > 1 ? "s" : ""}
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={handleForceCorrelateChanges}
                    disabled={correlatingChanges || changeLoading}
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant text-on-surface transition disabled:opacity-50"
                  >
                    <span className={`material-symbols-outlined text-14 ${correlatingChanges ? "animate-spin" : ""}`}>
                      autorenew
                    </span>
                    {correlatingChanges ? "Correlating..." : "Correlate Changes"}
                  </button>
                </div>
              </div>

              {changeLoading && !changeReport ? (
                <div className="p-6 flex flex-col items-center justify-center gap-2">
                  <span className="material-symbols-outlined text-24 animate-spin text-primary">progress_activity</span>
                  <p className="text-xs text-on-surface-variant">Scanning recent multi-source changes...</p>
                </div>
              ) : changeReport && changeReport.correlations.length > 0 ? (
                <div className="space-y-3">
                  <div className="p-2.5 bg-surface-container-lowest rounded-lg border border-outline-variant/60 flex items-center justify-between text-xs text-on-surface-variant">
                    <span>{changeReport.summary}</span>
                    <span className="font-mono text-[11px] text-on-surface-variant/80">Window: {changeReport.lookback_window_minutes}m</span>
                  </div>

                  <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
                    {changeReport.correlations.map((corr) => {
                      const deltaMin = Math.round(corr.time_delta_seconds / 60);
                      const isBefore = corr.time_delta_seconds <= 0;
                      const timingStr = isBefore ? `${Math.abs(deltaMin)}m before onset` : `${deltaMin}m after onset`;

                      return (
                        <div
                          key={corr.id}
                          className={`p-3 rounded-lg border transition space-y-2 ${
                            corr.is_causal_candidate
                              ? "bg-amber-500/5 border-amber-500/30 hover:border-amber-500/50"
                              : "bg-surface-container-lowest border-outline-variant/60 hover:border-outline-variant"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-semibold text-13 text-on-surface truncate">
                                  {corr.change_event?.title || `Change Event #${corr.rank}`}
                                </span>
                                {corr.is_causal_candidate && (
                                  <span className="px-2 py-0.2 rounded text-[9px] font-bold uppercase bg-amber-500/20 text-amber-300 border border-amber-500/40">
                                    Causal Candidate
                                  </span>
                                )}
                                <span className="px-1.5 py-0.2 rounded text-[9px] font-medium bg-surface-container-high text-on-surface-variant border border-outline-variant">
                                  {corr.change_event?.change_type.replace(/_/g, " ") || "CHANGE"}
                                </span>
                              </div>
                              <div className="text-[11px] text-on-surface-variant font-mono mt-0.5">
                                {corr.change_event?.provider} &bull; {timingStr} &bull; {corr.topological_distance === 0 ? "Root Service" : `${corr.topological_distance} hop(s) away`}
                              </div>
                            </div>

                            {/* Correlation Score Tag */}
                            <div className="text-right whitespace-nowrap">
                              <div className="text-12 font-bold font-mono text-primary">
                                {(corr.correlation_score * 100).toFixed(1)}%
                              </div>
                              <span className="text-[10px] text-on-surface-variant">Rank #{corr.rank}</span>
                            </div>
                          </div>

                          {/* Reasoning string */}
                          {corr.reasoning && (
                            <p className="text-[11px] text-on-surface-variant/90 bg-surface-container-high/40 p-2 rounded border border-outline-variant/40">
                              {corr.reasoning}
                            </p>
                          )}

                          {/* Human Operator Triage Row */}
                          <div className="flex items-center justify-between pt-1 border-t border-outline-variant/40 text-[11px]">
                            <div className="flex items-center gap-1.5 text-on-surface-variant">
                              <span>Triage:</span>
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                  corr.triage_status === "SUSPECTED_ROOT_CAUSE"
                                    ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                                    : corr.triage_status === "CONTRIBUTING_FACTOR"
                                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                                    : corr.triage_status === "DISMISSED"
                                    ? "bg-neutral-500/20 text-neutral-400 border border-neutral-500/40"
                                    : "bg-surface-container text-on-surface-variant border border-outline-variant"
                                }`}
                              >
                                {corr.triage_status.replace(/_/g, " ")}
                              </span>
                              {corr.triage_reason && (
                                <span className="italic text-[10px] text-on-surface-variant truncate max-w-xs">
                                  — "{corr.triage_reason}"
                                </span>
                              )}
                            </div>

                            {/* Triage Action Buttons */}
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => handleTriageCorrelation(corr.id, "SUSPECTED_ROOT_CAUSE")}
                                disabled={triagingId === corr.id}
                                title="Mark as Suspected Root Cause"
                                className="px-2 py-0.5 rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-[10px] font-medium transition"
                              >
                                Root Cause
                              </button>
                              <button
                                onClick={() => handleTriageCorrelation(corr.id, "CONTRIBUTING_FACTOR")}
                                disabled={triagingId === corr.id}
                                title="Mark as Contributing Factor"
                                className="px-2 py-0.5 rounded bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px] font-medium transition"
                              >
                                Factor
                              </button>
                              <button
                                onClick={() => handleTriageCorrelation(corr.id, "DISMISSED")}
                                disabled={triagingId === corr.id}
                                title="Dismiss Correlation"
                                className="px-2 py-0.5 rounded bg-surface-container-high hover:bg-surface-container-highest text-on-surface-variant border border-outline-variant text-[10px] font-medium transition"
                              >
                                Dismiss
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="p-3 bg-surface-container-lowest rounded-lg border border-outline-variant text-xs text-on-surface-variant flex items-center justify-between">
                  <span>No recent changes correlated within the incident window.</span>
                  <button
                    onClick={handleForceCorrelateChanges}
                    disabled={correlatingChanges}
                    className="px-3 py-1 bg-primary text-on-primary rounded text-xs font-medium"
                  >
                    Scan Changes
                  </button>
                </div>
              )}
            </div>

            {/* Run AI Investigation Button */}
            {(!investigation || ["created", "planning", "investigating", "failed"].includes(investigation.status)) && (
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
                {streamError && (
                  <div className="mt-3 p-3 rounded border bg-error/10 border-error/20 text-[11px] text-error">
                    Investigation failed: {streamError}
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
                          <span className="material-symbols-outlined text-[14px]">{event.icon}</span>
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
                      Tokens: {(investigation.total_tokens ?? 0).toLocaleString()}
                    </span>
                    <span className="text-on-surface-variant">
                      Cost: ${(investigation.total_cost_usd ?? 0).toFixed(4)}
                    </span>
                  </div>
                </div>

                <div className="mb-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] text-on-surface-variant">
                      {streamSteps.length > 0
                        ? streamSteps[streamSteps.length - 1].message
                        : investigation.completed_at
                        ? "Investigation complete"
                        : investigation.current_step || "Starting..."}
                    </span>
                    <span className="text-[11px] font-mono text-on-surface">
                      {streamSteps.length > 0
                        ? Math.round((streamSteps.filter(s => s.status === "completed").length / Math.max(streamSteps.length, 1)) * 100)
                        : investigation.completed_at
                        ? 100
                        : investigation.progress_percent || 0}%
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all duration-500"
                      style={{ width: `${streamSteps.length > 0
                        ? Math.round((streamSteps.filter(s => s.status === "completed").length / Math.max(streamSteps.length, 1)) * 100)
                        : investigation.completed_at
                        ? 100
                        : investigation.progress_percent || 0}%` }}
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

                {/* Live streaming steps */}
                {streamSteps.length > 0 && (
                  <div className="mt-3 space-y-1 border-t border-surface-container-highest pt-3">
                    {streamSteps.map((s, i) => (
                      <div key={`${s.step}-${i}`} className="flex items-start gap-2 py-1">
                        <div className="mt-0.5 shrink-0">
                          {s.status === "completed" ? (
                            <span className="material-symbols-outlined text-[13px] text-green-400">check_circle</span>
                          ) : s.status === "active" ? (
                            <span className="material-symbols-outlined animate-spin text-[13px] text-primary">progress_activity</span>
                          ) : (
                            <span className="material-symbols-outlined text-[13px] text-on-surface-variant">radio_button_unchecked</span>
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-[11px] text-on-surface">{s.message}</div>
                          {s.detail && (
                            <div className="text-[10px] text-on-surface-variant mt-0.5 font-mono truncate">
                              {typeof s.detail === "string" ? s.detail : Array.isArray(s.detail) ? s.detail.map((d: unknown) => String(typeof d === "string" ? d : typeof d === "object" && d !== null ? ((d as Record<string, unknown>).label || (d as Record<string, unknown>).title || JSON.stringify(d)) : d)).join(", ") : typeof s.detail === "object" && s.detail !== null ? Object.entries(s.detail as Record<string, unknown>).map(([k, v]) => `${k}: ${typeof v === "string" ? v : String(v ?? "")}`).join(" | ") : ""}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {/* Phase 9 Root Cause & Safe Abstention Card */}
            <div className="bg-surface-container-low border border-outline-variant/80 rounded-xl p-4 space-y-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[18px]">psychology_alt</span>
                  <h2 className="text-[12px] font-semibold text-on-surface">
                    Root Cause Analysis & Safe Abstention (Phase 9)
                  </h2>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleRunHypothesisCompetition}
                    disabled={evaluatingHypotheses}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-high hover:bg-surface-container-highest text-[11px] font-medium border border-outline-variant transition-colors disabled:opacity-50"
                  >
                    <span className={`material-symbols-outlined text-[14px] ${evaluatingHypotheses ? "animate-spin" : ""}`}>
                      cycle
                    </span>
                    {evaluatingHypotheses ? "Evaluating..." : "Run Competition"}
                  </button>
                  <button
                    onClick={() => {
                      setOverrideSummary(phase9RootCause?.summary || "");
                      setOverrideExplanation(phase9RootCause?.causal_explanation || "");
                      setOverrideModalOpen(true);
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary text-[11px] font-medium border border-primary/30 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">tune</span>
                    Human Override
                  </button>
                </div>
              </div>

              {phase9RootCause ? (
                phase9RootCause.abstained ? (
                  <div className="p-4 rounded-xl bg-gradient-to-r from-amber-950/30 via-surface-container-lowest to-surface-container-lowest border border-amber-500/30 space-y-3">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-amber-400 text-[20px]">shield_with_heart</span>
                      <span className="text-[13px] font-bold text-amber-300">
                        Root Cause Inconclusive — Safe Abstention Triggered
                      </span>
                      <span className="ml-auto px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/20 text-amber-300 border border-amber-500/30">
                        v{phase9RootCause.evaluation_version} &bull; {phase9RootCause.snapshot_hash || "hash"}
                      </span>
                    </div>
                    <p className="text-xs text-on-surface-variant leading-relaxed">
                      {phase9RootCause.abstention_reason || "Evidence was insufficient across orthogonal families to declare a single deterministic root cause without risking hallucination."}
                    </p>
                    {phase9RootCause.missing_evidence_json && phase9RootCause.missing_evidence_json.length > 0 && (
                      <div className="bg-surface-container-low p-3 rounded-lg border border-outline-variant space-y-1.5">
                        <div className="text-[11px] font-semibold text-on-surface uppercase tracking-wider flex items-center gap-1">
                          <span className="material-symbols-outlined text-amber-400 text-[14px]">checklist</span>
                          Missing Evidence Required to Disambiguate:
                        </div>
                        <ul className="list-disc list-inside text-xs text-on-surface-variant space-y-1 pl-1">
                          {phase9RootCause.missing_evidence_json.map((m, idx) => (
                            <li key={idx}><span className="text-on-surface font-medium">{m}</span></li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="p-4 rounded-xl bg-gradient-to-r from-emerald-950/30 via-surface-container-lowest to-surface-container-lowest border border-emerald-500/30 space-y-3">
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="material-symbols-outlined text-emerald-400 text-[20px]">verified</span>
                          <span className="text-[13px] font-bold text-emerald-300">
                            Accepted Root Cause
                          </span>
                          {phase9RootCause.human_overridden && (
                            <span className="px-2 py-0.5 rounded text-[9px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                              OPERATOR OVERRIDDEN
                            </span>
                          )}
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                            CONFIDENCE: {phase9RootCause.confidence.toUpperCase()}
                          </span>
                        </div>
                        <h3 className="text-sm font-semibold text-on-surface mt-1.5">{phase9RootCause.summary}</h3>
                      </div>
                      <div className="text-[10px] font-mono text-on-surface-variant bg-surface-container-low px-3 py-1.5 rounded border border-outline-variant shrink-0">
                        v{phase9RootCause.evaluation_version} &bull; {phase9RootCause.distinct_families_count} families &bull; {phase9RootCause.snapshot_hash || "hash"}
                      </div>
                    </div>
                    <div className="text-xs text-on-surface-variant bg-surface-container-low p-3 rounded-lg border border-outline-variant">
                      <span className="font-semibold text-on-surface">Causal Explanation: </span>
                      {phase9RootCause.causal_explanation}
                    </div>
                    {phase9RootCause.disproof_summary && (
                      <div className="text-[11px] text-on-surface-variant font-mono flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[13px] text-emerald-400">check_circle</span>
                        <span>Adversarial Disproof: {phase9RootCause.disproof_summary}</span>
                      </div>
                    )}
                  </div>
                )
              ) : (
                <div className="p-3 bg-surface-container-lowest rounded-lg border border-outline-variant text-xs text-on-surface-variant flex items-center justify-between">
                  <span>No automated root-cause competition run yet.</span>
                  <button
                    onClick={handleRunHypothesisCompetition}
                    disabled={evaluatingHypotheses}
                    className="px-3 py-1 bg-primary text-on-primary rounded text-xs font-medium"
                  >
                    Evaluate Hypotheses
                  </button>
                </div>
              )}
            </div>

            {/* Phase 9 Competing Hypotheses Matrix */}
            <div className="bg-surface-container-low border border-surface-container-highest rounded-xl p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[18px]">balance</span>
                  <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
                    Competing Hypotheses Matrix ({phase9Hypotheses.length || hypotheses.length})
                  </h2>
                </div>
                <button
                  onClick={handleRunHypothesisCompetition}
                  disabled={evaluatingHypotheses}
                  className="text-xs text-primary hover:underline font-medium"
                >
                  Re-evaluate Matrix
                </button>
              </div>

              <div className="space-y-2.5">
                {(phase9Hypotheses.length > 0 ? phase9Hypotheses : hypotheses).map((hyp: any) => (
                  <div
                    key={hyp.id}
                    className={`p-3.5 rounded-xl border transition-all ${
                      hyp.status === "accepted"
                        ? "border-emerald-500/40 bg-emerald-950/20 shadow-sm"
                        : hyp.status === "supported"
                        ? "border-primary/30 bg-primary/5"
                        : hyp.status === "disproven" || hyp.status === "contradicted" || hyp.status === "rejected"
                        ? "border-outline-variant bg-surface-container/50 opacity-80"
                        : "border-outline-variant bg-surface-container"
                    }`}
                  >
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-surface-container-high text-on-surface border border-outline-variant">
                          {hyp.label}
                        </span>
                        <span className="text-xs font-semibold text-on-surface">{hyp.description}</span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded uppercase ${
                          hyp.status === "accepted"
                            ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                            : hyp.status === "supported"
                            ? "bg-sky-500/20 text-sky-300 border border-sky-500/40"
                            : hyp.status === "disproven"
                            ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                            : "bg-surface-container-high text-on-surface-variant border border-outline-variant"
                        }`}>
                          {hyp.status}
                        </span>
                        {hyp.human_triaged && (
                          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/40">
                            TRIAGED
                          </span>
                        )}
                        <button
                          onClick={() => {
                            setTriageModalHypothesis(hyp);
                            setTriageStatus(hyp.status || "supported");
                            setTriageNotes(hyp.human_triage_notes || "");
                          }}
                          className="px-2 py-0.5 text-[10px] font-medium rounded bg-surface-container hover:bg-surface-container-highest border border-outline-variant text-on-surface"
                        >
                          Triage
                        </button>
                      </div>
                    </div>

                    {/* Tri-Factor Fit Badges */}
                    <div className="flex flex-wrap gap-2 text-[10px] font-mono pt-1">
                      <span className={`px-2 py-0.5 rounded border ${
                        hyp.temporal_fit ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30" : "bg-rose-500/10 text-rose-300 border-rose-500/30"
                      }`}>
                        Temporal Fit: {hyp.temporal_fit_score != null ? (hyp.temporal_fit_score * 100).toFixed(0) : "100"}%
                      </span>
                      <span className={`px-2 py-0.5 rounded border ${
                        hyp.code_path_fit ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30" : "bg-amber-500/10 text-amber-300 border-amber-500/30"
                      }`}>
                        Code-Path Fit: {hyp.code_path_fit_score != null ? (hyp.code_path_fit_score * 100).toFixed(0) : "100"}%
                      </span>
                      <span className={`px-2 py-0.5 rounded border ${
                        hyp.operational_fit ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30" : "bg-amber-500/10 text-amber-300 border-amber-500/30"
                      }`}>
                        Operational Fit: {hyp.operational_fit_score != null ? (hyp.operational_fit_score * 100).toFixed(0) : "100"}%
                      </span>
                      <span className="px-2 py-0.5 rounded bg-surface-container-high border border-outline-variant text-on-surface-variant">
                        Evidence Families: {hyp.distinct_families_count || 1}
                      </span>
                    </div>

                    {hyp.disproof_attempt_notes && (
                      <div className="text-[11px] text-rose-300/90 font-mono mt-2 bg-rose-950/20 p-2 rounded border border-rose-500/20">
                        {hyp.disproof_attempt_notes}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Phase 9 Multi-Family Immutable Evidence Ledger */}
            <div className="bg-surface-container-low border border-surface-container-highest rounded-xl p-4 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[18px]">fact_check</span>
                  <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
                    Evidence Ledger & Audit Trail ({phase9Evidence.length || evidence.length})
                  </h2>
                </div>
                <button
                  onClick={() => setManualModalOpen(true)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary text-on-primary text-[11px] font-medium hover:bg-primary/90 transition-colors shadow-sm self-start sm:self-auto"
                >
                  <span className="material-symbols-outlined text-[14px]">add_circle</span>
                  Add Manual Evidence
                </button>
              </div>

              {/* Filter Chips */}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <div className="flex items-center gap-1 bg-surface-container p-1 rounded-lg border border-outline-variant">
                  {["all", "fact", "inference", "conclusion"].map((cat) => (
                    <button
                      key={cat}
                      onClick={() => setEvidenceCategoryFilter(cat)}
                      className={`px-2.5 py-1 rounded text-[10px] font-medium uppercase tracking-wider transition-colors ${
                        evidenceCategoryFilter === cat
                          ? "bg-primary text-on-primary shadow-sm"
                          : "text-on-surface-variant hover:text-on-surface"
                      }`}
                    >
                      {cat}
                    </button>
                  ))}
                </div>

                <div className="flex items-center gap-1 bg-surface-container p-1 rounded-lg border border-outline-variant">
                  {["all", "runtime_telemetry", "code_change", "topology_graph", "workspace_static", "verified_human"].map((fam) => (
                    <button
                      key={fam}
                      onClick={() => setEvidenceFamilyFilter(fam)}
                      className={`px-2 py-1 rounded text-[10px] font-medium transition-colors ${
                        evidenceFamilyFilter === fam
                          ? "bg-secondary text-on-secondary shadow-sm"
                          : "text-on-surface-variant hover:text-on-surface"
                      }`}
                    >
                      {fam.replace("_", " ")}
                    </button>
                  ))}
                </div>
              </div>

              {/* Evidence Items List */}
              <div className="space-y-2.5">
                {(phase9Evidence.length > 0 ? phase9Evidence : (evidence as unknown as EvidenceItem[]))
                  .filter((ev) => evidenceCategoryFilter === "all" || ev.category_type === evidenceCategoryFilter)
                  .filter((ev) => evidenceFamilyFilter === "all" || ev.evidence_family === evidenceFamilyFilter)
                  .map((ev) => (
                    <div
                      key={ev.id}
                      className="p-3 rounded-xl border border-outline-variant bg-surface-container hover:bg-surface-container-high transition-colors space-y-2"
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5">
                        <div className="flex items-center gap-2">
                          <span className="material-symbols-outlined text-[16px] text-primary">
                            {evidenceSourceIcons[ev.source_type] || "description"}
                          </span>
                          <span className="text-xs font-semibold text-on-surface">{ev.title}</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-primary/10 text-primary border border-primary/20 uppercase">
                            {ev.category_type}
                          </span>
                          {ev.evidence_family && (
                            <span className="px-2 py-0.5 rounded text-[9px] font-mono bg-surface-container-highest text-on-surface-variant border border-outline-variant">
                              {ev.evidence_family}
                            </span>
                          )}
                          {ev.is_redacted && (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-rose-500/20 text-rose-300 border border-rose-500/30">
                              REDACTED
                            </span>
                          )}
                          {ev.version && ev.version > 1 && (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-purple-500/20 text-purple-300 border border-purple-500/30">
                              v{ev.version}
                            </span>
                          )}
                          <span className="text-[10px] font-mono text-on-surface-variant">
                            hash:{ev.content_hash?.slice(0, 8) || "canonical"}
                          </span>
                        </div>
                      </div>

                      {ev.content && (
                        <pre className="text-[11px] font-mono text-on-surface-variant bg-surface-container-lowest p-2.5 rounded-lg border border-outline-variant/60 max-h-36 overflow-y-auto whitespace-pre-wrap">
                          {ev.content}
                        </pre>
                      )}

                      <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-on-surface-variant font-mono pt-1">
                        <div className="flex gap-3">
                          {ev.service && <span>Service: {ev.service}</span>}
                          {ev.commit_sha && <span>Commit: {ev.commit_sha.slice(0, 7)}</span>}
                          {ev.file_path && <span>Path: {ev.file_path}</span>}
                        </div>

                        <div className="flex items-center gap-2">
                          {ev.source_type === "manual" && ev.verification_status !== "verified" && (
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => handleVerifyEvidence(ev.id, "verified")}
                                className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500/30"
                              >
                                Verify
                              </button>
                              <button
                                onClick={() => handleVerifyEvidence(ev.id, "rejected")}
                                className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 hover:bg-rose-500/30"
                              >
                                Reject
                              </button>
                            </div>
                          )}
                          <button
                            onClick={() => {
                              setCorrectionModalEvidence(ev);
                              setCorrectionTitle(ev.title);
                              setCorrectionContent(ev.content || "");
                            }}
                            className="px-2 py-0.5 rounded bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant text-on-surface"
                          >
                            Correct (Append-Only)
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            </div>

            {/* Proposed Fixes */}
            {fixes.length > 0 && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
                    Proposed Fixes ({fixes.length})
                  </h2>
                  <span className="text-[10px] text-on-surface-variant italic">
                    Human Review Gate: Sentinel creates Draft PRs on GitHub — merging is manual
                  </span>
                </div>
                <div className="space-y-4">
                  {fixes.map((fix) => (
                    <div
                      key={fix.id}
                      className={`p-4 rounded-lg border ${
                        fix.pr_url
                          ? "border-primary/30 bg-primary/5"
                          : fix.status === "approved"
                          ? "border-green-500/30 bg-green-500/5"
                          : fix.status === "rejected"
                          ? "border-error/30 bg-error/5"
                          : "border-outline-variant bg-surface-container"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="material-symbols-outlined text-[16px] text-primary">
                            {fix.fix_type === "rollback" ? "replay" : fix.fix_type === "dependency_update" ? "system_update" : "code"}
                          </span>
                          <span className="text-[13px] font-semibold text-on-surface">{fix.title}</span>
                        </div>
                        <span className={`px-2.5 py-0.5 rounded text-[10px] font-mono font-semibold ${
                          fix.pr_url
                            ? "bg-primary/20 text-primary border border-primary/30"
                            : fix.status === "approved"
                            ? "bg-green-500/10 text-green-400 border border-green-500/20"
                            : fix.status === "rejected"
                            ? "bg-error/10 text-error"
                            : "bg-surface-container-high text-on-surface-variant border border-outline-variant"
                        }`}>
                          {fix.pr_url ? "DRAFT PR ON GITHUB" : fix.status === "approved" ? "READY TO PUBLISH" : "PROPOSED"}
                        </span>
                      </div>
                      <p className="text-[11px] text-on-surface-variant ml-6">{fix.description}</p>
                      <div className="flex gap-3 mt-2 ml-6 font-mono text-[10px] text-on-surface-variant">
                        <span>Type: {fix.fix_type}</span>
                        {fix.repository && <span>Repository: {fix.repository}</span>}
                        {fix.approach && <span>Approach: {fix.approach}</span>}
                      </div>

                      {/* Rich GitHub-Style Diff Viewer */}
                      {(fix.diff || fix.patch) && (
                        <div className="mt-3 ml-6">
                          <DiffViewer diff={fix.diff || undefined} patch={fix.patch || undefined} />
                        </div>
                      )}

                      <div className="mt-3 ml-6 flex items-center gap-3">
                        {fix.pr_url ? (
                          <a
                            href={fix.pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-primary text-on-primary text-[11px] font-medium rounded hover:bg-primary/90 transition-colors shadow-sm"
                          >
                            <span className="material-symbols-outlined text-[14px]">open_in_new</span>
                            Review Draft PR on GitHub #{fix.pr_number}
                          </a>
                        ) : (
                          <button
                            onClick={() => handleCreateDraftPR(fix)}
                            disabled={prLoading === fix.id}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-primary text-on-primary text-[11px] font-medium rounded hover:bg-primary/90 disabled:opacity-50 transition-colors shadow-sm"
                          >
                            <span className="material-symbols-outlined text-[14px]">
                              {prLoading === fix.id ? "progress_activity" : "call_split"}
                            </span>
                            {prLoading === fix.id ? "Creating Draft PR..." : "Publish Draft PR to GitHub"}
                          </button>
                        )}
                      </div>

                      {prError && prLoading === null && (
                        <div className="mt-2 ml-6 text-[11px] text-error flex items-center gap-1">
                          <span className="material-symbols-outlined text-[13px]">error</span>
                          <span>{prError}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Investigation Status / Streaming Progress */}
            {!investigation && evidence.length === 0 && hypotheses.length === 0 && (
              <div className="bg-surface-container-low border border-surface-container-highest rounded p-4">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant mb-4">
                  Investigation Status
                </h2>

                {/* Streaming progress panel */}
                {streamingActive && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-primary text-[13px] font-medium">
                      <span className="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>
                      Investigating...
                    </div>
                    <div className="space-y-1">
                      {streamSteps.map((s, i) => (
                        <div key={`${s.step}-${i}`} className="flex items-start gap-3 py-1.5">
                          <div className="mt-0.5">
                            {s.status === "completed" ? (
                              <span className="material-symbols-outlined text-[14px] text-green-400">check_circle</span>
                            ) : (
                              <span className="material-symbols-outlined animate-spin text-[14px] text-primary">progress_activity</span>
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-[12px] text-on-surface">{s.message}</div>
                            {s.detail && (
                              <div className="text-[11px] text-on-surface-variant mt-0.5 font-mono">
                                {typeof s.detail === "string" ? s.detail : Array.isArray(s.detail) ? (
                                  <div className="flex flex-wrap gap-1 mt-1">
                                    {s.detail.map((d: unknown, j: number) => (
                                      <span key={j} className="px-1.5 py-0.5 bg-surface-container-high rounded text-[10px]">
                                        {String(typeof d === "string" ? d : typeof d === "object" && d !== null ? ((d as Record<string, unknown>).label || (d as Record<string, unknown>).title || JSON.stringify(d)) : d)}
                                      </span>
                                    ))}
                                  </div>
                                ) : typeof s.detail === "object" && s.detail !== null ? (
                                  <div className="mt-1 space-y-0.5">
                                    {Object.entries(s.detail as Record<string, unknown>).map(([k, v]) => (
                                      <div key={k}><span className="text-on-surface-variant">{k}:</span> {typeof v === "string" ? v : typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}</div>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Error display */}
                {streamError && (
                  <div className="mt-3 p-3 bg-error/10 border border-error/20 rounded text-[12px] text-error">
                    {streamError}
                  </div>
                )}

                {/* Complete display */}
                {engineResult && !streamingActive && (
                  <div className="mt-3 p-3 bg-green-500/10 border border-green-500/20 rounded text-[12px] text-green-400">
                    Investigation complete — {engineResult.evidence_count} evidence items, {engineResult.hypotheses_count} hypotheses
                    {engineResult.root_cause_found ? " (root cause found)" : " (no definitive root cause)"}
                  </div>
                )}

                {/* Idle state */}
                {!streamingActive && !engineResult && (
                  <>
                    <div className="flex items-center gap-2 text-on-surface text-[12px]">
                      <span className="w-2 h-2 rounded-full bg-tertiary" />
                      {incident.status === "created" && "Awaiting investigation start"}
                      {incident.status === "investigating" && "Investigation in progress..."}
                      {incident.status === "resolved" && "Investigation complete"}
                    </div>
                    <p className="text-[12px] text-on-surface-variant mt-4">
                      Click below to start the AI investigation. You will see real-time progress as Sentinel analyzes your codebase.
                    </p>
                  </>
                )}

                {incident.status === "created" && !streamingActive && (
                  <button
                    onClick={handleRunInvestigation}
                    disabled={investigating}
                    className="mt-4 px-4 py-2 bg-primary-container text-on-primary-container text-[12px] font-semibold uppercase tracking-wider rounded-md border border-primary hover:bg-primary hover:text-on-primary-fixed transition-colors flex items-center gap-2 disabled:opacity-50"
                  >
                    <span className="material-symbols-outlined text-[16px]">play_arrow</span>
                    Start Investigation
                  </button>
                )}
              </div>
            )}
            </>
            )}
          </div>
        </div>

        {/* Phase 9 Manual Evidence Submission Modal */}
        {manualModalOpen && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-surface-container-low border border-outline-variant rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[20px]">add_circle</span>
                  <h3 className="text-sm font-bold text-on-surface">Submit Manual Evidence</h3>
                </div>
                <button
                  onClick={() => setManualModalOpen(false)}
                  className="text-on-surface-variant hover:text-on-surface"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
              </div>

              <form onSubmit={handleManualEvidenceSubmit} className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Title *</label>
                  <input
                    type="text"
                    required
                    value={manualTitle}
                    onChange={(e) => setManualTitle(e.target.value)}
                    placeholder="e.g. SRE observed thread dump pool exhaustion"
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-on-surface-variant mb-1">Category Type</label>
                    <select
                      value={manualCategory}
                      onChange={(e) => setManualCategory(e.target.value)}
                      className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                    >
                      <option value="fact">Fact (Observed truth)</option>
                      <option value="inference">Inference (Derived belief)</option>
                      <option value="conclusion">Conclusion (Synthesized claim)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-on-surface-variant mb-1">Component / Service</label>
                    <input
                      type="text"
                      value={manualService}
                      onChange={(e) => setManualService(e.target.value)}
                      placeholder={incident?.service || "payment-service"}
                      className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Content / Logs / Notes</label>
                  <textarea
                    rows={4}
                    value={manualContent}
                    onChange={(e) => setManualContent(e.target.value)}
                    placeholder="Paste logs, stack traces, or operational observations here..."
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs font-mono text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setManualModalOpen(false)}
                    className="px-4 py-2 rounded-lg bg-surface-container hover:bg-surface-container-highest text-xs text-on-surface font-medium border border-outline-variant"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={manualSubmitting}
                    className="px-4 py-2 rounded-lg bg-primary text-on-primary text-xs font-bold hover:bg-primary/90 disabled:opacity-50 shadow-md"
                  >
                    {manualSubmitting ? "Submitting..." : "Submit Evidence"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Phase 9 Append-Only Evidence Correction Modal */}
        {correctionModalEvidence && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-surface-container-low border border-outline-variant rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-purple-400 text-[20px]">edit_note</span>
                  <h3 className="text-sm font-bold text-on-surface">Submit Append-Only Correction</h3>
                </div>
                <button
                  onClick={() => setCorrectionModalEvidence(null)}
                  className="text-on-surface-variant hover:text-on-surface"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
              </div>

              <div className="p-2.5 rounded-lg bg-surface-container-high/60 border border-outline-variant text-[11px] text-on-surface-variant">
                Creating an immutable versioned record that supersedes <strong>{correctionModalEvidence.title}</strong> (v{correctionModalEvidence.version || 1}).
              </div>

              <form onSubmit={handleCorrectionSubmit} className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Corrected Title *</label>
                  <input
                    type="text"
                    required
                    value={correctionTitle}
                    onChange={(e) => setCorrectionTitle(e.target.value)}
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Correction Reason *</label>
                  <input
                    type="text"
                    required
                    value={correctionReason}
                    onChange={(e) => setCorrectionReason(e.target.value)}
                    placeholder="e.g. Revised after analyzing database pool flame graphs"
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Corrected Content</label>
                  <textarea
                    rows={4}
                    value={correctionContent}
                    onChange={(e) => setCorrectionContent(e.target.value)}
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs font-mono text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setCorrectionModalEvidence(null)}
                    className="px-4 py-2 rounded-lg bg-surface-container hover:bg-surface-container-highest text-xs text-on-surface font-medium border border-outline-variant"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={correctionSubmitting}
                    className="px-4 py-2 rounded-lg bg-purple-600 text-white text-xs font-bold hover:bg-purple-500 disabled:opacity-50 shadow-md"
                  >
                    {correctionSubmitting ? "Saving..." : "Save Correction (v" + ((correctionModalEvidence.version || 1) + 1) + ")"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Phase 9 Hypothesis Triage Modal */}
        {triageModalHypothesis && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-surface-container-low border border-outline-variant rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-purple-400 text-[20px]">gavel</span>
                  <h3 className="text-sm font-bold text-on-surface">Operator Hypothesis Triage</h3>
                </div>
                <button
                  onClick={() => setTriageModalHypothesis(null)}
                  className="text-on-surface-variant hover:text-on-surface"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
              </div>

              <div className="p-3 rounded-lg bg-surface-container border border-outline-variant space-y-1">
                <div className="font-mono text-xs font-bold text-primary">{triageModalHypothesis.label}</div>
                <div className="text-xs text-on-surface">{triageModalHypothesis.description}</div>
              </div>

              <form onSubmit={handleTriageHypothesisSubmit} className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Triage Status *</label>
                  <select
                    value={triageStatus}
                    onChange={(e) => setTriageStatus(e.target.value)}
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                  >
                    <option value="supported">Supported (Consistent with facts)</option>
                    <option value="accepted">Accepted (Declared definitive root-cause)</option>
                    <option value="contradicted">Contradicted (Questioned by data)</option>
                    <option value="disproven">Disproven (Falsified by facts)</option>
                    <option value="rejected">Rejected (Discarded)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Triage Notes / Operator Rationale *</label>
                  <textarea
                    rows={3}
                    required
                    value={triageNotes}
                    onChange={(e) => setTriageNotes(e.target.value)}
                    placeholder="Document operator reasoning and supporting analysis..."
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setTriageModalHypothesis(null)}
                    className="px-4 py-2 rounded-lg bg-surface-container hover:bg-surface-container-highest text-xs text-on-surface font-medium border border-outline-variant"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={triageSubmitting}
                    className="px-4 py-2 rounded-lg bg-purple-600 text-white text-xs font-bold hover:bg-purple-500 disabled:opacity-50 shadow-md"
                  >
                    {triageSubmitting ? "Recording..." : "Apply Human Triage"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Phase 9 Root Cause Override Modal */}
        {overrideModalOpen && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-surface-container-low border border-outline-variant rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[20px]">tune</span>
                  <h3 className="text-sm font-bold text-on-surface">Human Root Cause Override</h3>
                </div>
                <button
                  onClick={() => setOverrideModalOpen(false)}
                  className="text-on-surface-variant hover:text-on-surface"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
              </div>

              <form onSubmit={handleOverrideRootCauseSubmit} className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Root Cause Summary *</label>
                  <input
                    type="text"
                    required
                    value={overrideSummary}
                    onChange={(e) => setOverrideSummary(e.target.value)}
                    placeholder="e.g. Memory leak in background metric scrubber"
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Causal Explanation *</label>
                  <textarea
                    rows={3}
                    required
                    value={overrideExplanation}
                    onChange={(e) => setOverrideExplanation(e.target.value)}
                    placeholder="Explain the causal mechanics of the failure..."
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-on-surface-variant mb-1">Operator Override Notes *</label>
                  <input
                    type="text"
                    required
                    value={overrideNotes}
                    onChange={(e) => setOverrideNotes(e.target.value)}
                    placeholder="e.g. Confirmed by DBA post-mortem analysis"
                    className="w-full bg-surface-container border border-outline-variant rounded-lg px-3 py-2 text-xs text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setOverrideModalOpen(false)}
                    className="px-4 py-2 rounded-lg bg-surface-container hover:bg-surface-container-highest text-xs text-on-surface font-medium border border-outline-variant"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={overrideSubmitting}
                    className="px-4 py-2 rounded-lg bg-primary text-on-primary text-xs font-bold hover:bg-primary/90 disabled:opacity-50 shadow-md"
                  >
                    {overrideSubmitting ? "Saving..." : "Save Override"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
