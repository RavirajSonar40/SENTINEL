"use client";

import { useEffect, useState, useCallback } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import {
  fetchSecurityCases,
  createSecurityCase,
  fetchSecurityEvidence,
  fetchAuditChain,
  fetchContainmentActions,
  proposeContainmentAction,
  approveContainmentAction,
  executeContainmentAction,
  resolveSecurityCase,
  SecurityCaseItem,
  SecurityEvidenceSnapshot,
  SecurityContainmentAction,
  SecurityAuditChainVerification,
} from "@/lib/securityApi";

const severityColors: Record<string, { bg: string; text: string; border: string }> = {
  CRITICAL: { bg: "bg-red-500/20", text: "text-red-400 font-bold animate-pulse", border: "border-red-500/50" },
  HIGH: { bg: "bg-amber-500/20", text: "text-amber-400 font-semibold", border: "border-amber-500/40" },
  MEDIUM: { bg: "bg-yellow-500/10", text: "text-yellow-400", border: "border-yellow-500/30" },
  LOW: { bg: "bg-blue-500/10", text: "text-blue-400", border: "border-blue-500/20" },
};

const categoryLabels: Record<string, { label: string; icon: string }> = {
  CREDENTIAL_LEAK: { label: "Credential Leak", icon: "🔑" },
  SUSPICIOUS_AUTH: { label: "Suspicious Auth", icon: "🛡️" },
  PRIVILEGE_ESCALATION: { label: "Privilege Escalation", icon: "⚡" },
  UNUSUAL_DATA_ACCESS: { label: "Unusual Data Access", icon: "📊" },
  VULNERABLE_DEPENDENCY: { label: "Vulnerable CVE", icon: "📦" },
  MALWARE_SUSPECTED: { label: "Malware Suspected", icon: "☣️" },
  CUSTOM: { label: "Security Anomaly", icon: "🔒" },
};

export default function SecurityIncidentCommandPage() {
  const { token } = useAuth();
  const [cases, setCases] = useState<SecurityCaseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");

  // Modal States
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedCase, setSelectedCase] = useState<SecurityCaseItem | null>(null);

  // Evidence Modal
  const [evidenceSnapshot, setEvidenceSnapshot] = useState<SecurityEvidenceSnapshot | null>(null);
  const [loadingEvidence, setLoadingEvidence] = useState(false);

  // Containment Modal
  const [containmentActions, setContainmentActions] = useState<SecurityContainmentAction[]>([]);
  const [loadingContainment, setLoadingContainment] = useState(false);
  const [showProposeAction, setShowProposeAction] = useState(false);
  const [actionType, setActionType] = useState("REVOKE_CREDENTIAL");
  const [targetType, setTargetType] = useState("secret");
  const [targetId, setTargetId] = useState("");
  const [actionTitle, setActionTitle] = useState("");
  const [actionDescription, setActionDescription] = useState("");
  const [proposingAction, setProposingAction] = useState(false);
  const [approvingActionId, setApprovingActionId] = useState<string | null>(null);
  const [executingActionId, setExecutingActionId] = useState<string | null>(null);

  // Audit Chain Modal
  const [auditChain, setAuditChain] = useState<SecurityAuditChainVerification | null>(null);
  const [loadingAudit, setLoadingAudit] = useState(false);

  // Resolve Modal
  const [showResolveModal, setShowResolveModal] = useState(false);
  const [resolutionSummary, setResolutionSummary] = useState("");
  const [resolvingCase, setResolvingCase] = useState(false);

  // Create Form State
  const [newTitle, setNewTitle] = useState("");
  const [newCategory, setNewCategory] = useState("CREDENTIAL_LEAK");
  const [newSeverity, setNewSeverity] = useState("CRITICAL");
  const [newDescription, setNewDescription] = useState("");
  const [creatingCase, setCreatingCase] = useState(false);

  const [notification, setNotification] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const showToast = (type: "success" | "error", msg: string) => {
    setNotification({ type, msg });
    setTimeout(() => setNotification(null), 5000);
  };

  const loadCases = useCallback(async () => {
    try {
      setLoading(true);
      const data = await fetchSecurityCases(
        categoryFilter || undefined,
        severityFilter || undefined,
        statusFilter || undefined,
      );
      setCases(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load security cases");
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, severityFilter, statusFilter]);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  // Open Evidence Vault
  const handleOpenEvidence = async (secCase: SecurityCaseItem) => {
    setSelectedCase(secCase);
    try {
      setLoadingEvidence(true);
      const ev = await fetchSecurityEvidence(secCase.id);
      setEvidenceSnapshot(ev);
    } catch (err: any) {
      showToast("error", err.message || "Failed to load evidence");
    } finally {
      setLoadingEvidence(false);
    }
  };

  // Open Containment Playbook
  const handleOpenContainment = async (secCase: SecurityCaseItem) => {
    setSelectedCase(secCase);
    try {
      setLoadingContainment(true);
      const acts = await fetchContainmentActions(secCase.id);
      setContainmentActions(acts);
    } catch (err: any) {
      showToast("error", err.message || "Failed to load containment actions");
    } finally {
      setLoadingContainment(false);
    }
  };

  // Open Audit Chain
  const handleOpenAuditChain = async (secCase: SecurityCaseItem) => {
    setSelectedCase(secCase);
    try {
      setLoadingAudit(true);
      const chain = await fetchAuditChain(secCase.id);
      setAuditChain(chain);
    } catch (err: any) {
      showToast("error", err.message || "Failed to load audit chain");
    } finally {
      setLoadingAudit(false);
    }
  };

  // Create Case Handler
  const handleCreateCase = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle) return;
    try {
      setCreatingCase(true);
      await createSecurityCase({
        title: newTitle,
        category: newCategory,
        severity: newSeverity,
        description: newDescription || undefined,
      });
      showToast("success", "Security Case quarantined and evidence frozen.");
      setShowCreateModal(false);
      setNewTitle("");
      setNewDescription("");
      loadCases();
    } catch (err: any) {
      showToast("error", err.message || "Failed to create security case");
    } finally {
      setCreatingCase(false);
    }
  };

  // Propose Containment Handler
  const handleProposeAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedCase || !actionTitle || !targetId) return;
    try {
      setProposingAction(true);
      await proposeContainmentAction(selectedCase.id, {
        action_type: actionType,
        target_type: targetType,
        target_id: targetId,
        title: actionTitle,
        description: actionDescription || undefined,
      });
      showToast("success", "Containment action proposed. Awaiting Dual Sign-Off.");
      setShowProposeAction(false);
      setActionTitle("");
      setTargetId("");
      setActionDescription("");
      handleOpenContainment(selectedCase);
      loadCases();
    } catch (err: any) {
      showToast("error", err.message || "Failed to propose action");
    } finally {
      setProposingAction(false);
    }
  };

  // Approve Containment Handler
  const handleApproveAction = async (actionId: string) => {
    try {
      setApprovingActionId(actionId);
      const updated = await approveContainmentAction(actionId, "Signed off in Security Incident Command");
      showToast("success", `Approval step recorded. Current status: ${updated.status}`);
      if (selectedCase) {
        handleOpenContainment(selectedCase);
      }
      loadCases();
    } catch (err: any) {
      showToast("error", err.message || "Failed to approve action");
    } finally {
      setApprovingActionId(null);
    }
  };

  // Execute Containment Handler
  const handleExecuteAction = async (actionId: string, dryRun: boolean) => {
    try {
      setExecutingActionId(actionId);
      const res = await executeContainmentAction(actionId, dryRun);
      showToast("success", dryRun ? "Dry-run simulation completed successfully." : "Containment action executed! Case status updated.");
      if (selectedCase) {
        handleOpenContainment(selectedCase);
      }
      loadCases();
    } catch (err: any) {
      showToast("error", err.message || "Failed to execute containment");
    } finally {
      setExecutingActionId(null);
    }
  };

  // Resolve Case Handler
  const handleResolveCase = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedCase) return;
    try {
      setResolvingCase(true);
      await resolveSecurityCase(selectedCase.id, resolutionSummary || "Remediation verified and forensic review closed.");
      showToast("success", "Security Case resolved and closed.");
      setShowResolveModal(false);
      setResolutionSummary("");
      setSelectedCase(null);
      loadCases();
    } catch (err: any) {
      showToast("error", err.message || "Failed to resolve security case");
    } finally {
      setResolvingCase(false);
    }
  };

  // Stats calculation
  const totalCases = cases.length;
  const criticalCount = cases.filter((c) => c.severity === "CRITICAL" && c.status !== "RESOLVED" && c.status !== "CLOSED").length;
  const activeContainment = cases.filter((c) => c.containment_status === "PROPOSED" || c.containment_status === "APPROVED" || c.containment_status === "EXECUTING").length;
  const containedCount = cases.filter((c) => c.containment_status === "CONTAINED").length;

  return (
    <div className="min-h-screen bg-[#0a0d14] text-zinc-100 flex flex-col font-sans">
      <TopBar
        title="Security Command"
        subtitle="Forensic quarantine, dual sign-off containment, and cryptographic audit"
        breadcrumbs={[{ label: "Security", active: true }]}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-8 space-y-6">
        {/* Toast Notification */}
        {notification && (
          <div
            className={`p-4 rounded-xl border backdrop-blur-md flex items-center justify-between transition-all ${
              notification.type === "success"
                ? "bg-emerald-950/80 border-emerald-500/40 text-emerald-300"
                : "bg-red-950/80 border-red-500/40 text-red-300"
            }`}
          >
            <div className="flex items-center space-x-3">
              <span className="text-xl">{notification.type === "success" ? "🛡️" : "⚠️"}</span>
              <p className="text-sm font-medium">{notification.msg}</p>
            </div>
            <button onClick={() => setNotification(null)} className="text-zinc-400 hover:text-zinc-200">
              ✕
            </button>
          </div>
        )}

        {/* Header Deck */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-gradient-to-r from-zinc-900 via-zinc-900/90 to-red-950/30 p-6 rounded-2xl border border-zinc-800 shadow-2xl">
          <div>
            <div className="flex items-center space-x-3">
              <span className="p-2.5 bg-red-500/10 text-red-400 rounded-xl border border-red-500/20 text-2xl">
                🛡️
              </span>
              <div>
                <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
                  Security Incident Command & Forensic Vault
                  <span className="text-xs uppercase px-2.5 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30 font-mono font-semibold">
                    Dual Sign-Off Gate
                  </span>
                </h1>
                <p className="text-xs text-zinc-400 mt-0.5">
                  Zero Autonomous Mutation Policy • Cryptographic SHA-256 Forensic Snapshots • Immutable Audit Ledgers
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2.5 bg-red-600 hover:bg-red-500 text-white font-medium text-sm rounded-xl shadow-lg shadow-red-900/40 transition-all flex items-center space-x-2"
            >
              <span>+</span>
              <span>File Security Incident</span>
            </button>
            <button
              onClick={loadCases}
              className="px-3.5 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-xl border border-zinc-700 text-sm transition-all"
            >
              🔄 Refresh
            </button>
          </div>
        </div>

        {/* Security KPI Metric Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl p-5 shadow-lg relative overflow-hidden">
            <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Total Security Cases</div>
            <div className="text-3xl font-extrabold text-white mt-2">{totalCases}</div>
            <div className="text-xs text-zinc-500 mt-1">Logged & cryptographically tracked</div>
          </div>

          <div className="bg-zinc-900/80 border border-red-900/30 rounded-xl p-5 shadow-lg relative overflow-hidden">
            <div className="text-xs font-semibold text-red-400 uppercase tracking-wider flex items-center justify-between">
              <span>Active Critical Cases</span>
              <span className="h-2 w-2 rounded-full bg-red-500 animate-ping"></span>
            </div>
            <div className="text-3xl font-extrabold text-red-400 mt-2">{criticalCount}</div>
            <div className="text-xs text-zinc-500 mt-1">Requiring immediate containment</div>
          </div>

          <div className="bg-zinc-900/80 border border-amber-900/30 rounded-xl p-5 shadow-lg relative overflow-hidden">
            <div className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Under Containment</div>
            <div className="text-3xl font-extrabold text-amber-400 mt-2">{activeContainment}</div>
            <div className="text-xs text-zinc-500 mt-1">Awaiting dual officer sign-off</div>
          </div>

          <div className="bg-zinc-900/80 border border-emerald-900/30 rounded-xl p-5 shadow-lg relative overflow-hidden">
            <div className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Successfully Contained</div>
            <div className="text-3xl font-extrabold text-emerald-400 mt-2">{containedCount}</div>
            <div className="text-xs text-zinc-500 mt-1">Blast radius isolated</div>
          </div>
        </div>

        {/* Filter Controls */}
        <div className="flex flex-wrap items-center gap-3 bg-zinc-900/50 p-4 rounded-xl border border-zinc-800">
          <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Filters:</span>

          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-red-500"
          >
            <option value="">All Categories</option>
            <option value="CREDENTIAL_LEAK">🔑 Credential Leak</option>
            <option value="SUSPICIOUS_AUTH">🛡️ Suspicious Auth</option>
            <option value="PRIVILEGE_ESCALATION">⚡ Privilege Escalation</option>
            <option value="UNUSUAL_DATA_ACCESS">📊 Unusual Data Access</option>
            <option value="VULNERABLE_DEPENDENCY">📦 Vulnerable Dependency</option>
            <option value="MALWARE_SUSPECTED">☣️ Malware Suspected</option>
          </select>

          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-red-500"
          >
            <option value="">All Severities</option>
            <option value="CRITICAL">🔴 Critical</option>
            <option value="HIGH">🟠 High</option>
            <option value="MEDIUM">🟡 Medium</option>
            <option value="LOW">🔵 Low</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs rounded-lg px-3 py-2 focus:outline-none focus:border-red-500"
          >
            <option value="">All Statuses</option>
            <option value="DETECTED">DETECTED</option>
            <option value="CONTAINING">CONTAINING</option>
            <option value="CONTAINED">CONTAINED</option>
            <option value="RESOLVED">RESOLVED</option>
          </select>

          {(categoryFilter || severityFilter || statusFilter) && (
            <button
              onClick={() => {
                setCategoryFilter("");
                setSeverityFilter("");
                setStatusFilter("");
              }}
              className="text-xs text-zinc-400 hover:text-zinc-200 underline ml-auto"
            >
              Clear Filters
            </button>
          )}
        </div>

        {/* Security Case Matrix Table */}
        <div className="bg-zinc-900/80 rounded-2xl border border-zinc-800 overflow-hidden shadow-2xl">
          {loading ? (
            <div className="py-20 text-center text-zinc-500 flex flex-col items-center">
              <span className="text-3xl animate-spin mb-3">🔄</span>
              <p className="text-sm">Loading security cases and cryptographic records...</p>
            </div>
          ) : error ? (
            <div className="py-20 text-center text-red-400">
              <p className="text-sm">{error}</p>
            </div>
          ) : cases.length === 0 ? (
            <div className="py-20 text-center text-zinc-500 flex flex-col items-center">
              <span className="text-4xl mb-3">🛡️</span>
              <p className="text-sm font-semibold text-zinc-300">No Security Incidents Detected</p>
              <p className="text-xs text-zinc-500 mt-1">All monitored perimeter signals and credentials are normal.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-zinc-950/80 text-zinc-400 uppercase tracking-wider border-b border-zinc-800">
                  <tr>
                    <th className="py-3.5 px-4 font-semibold">Case #</th>
                    <th className="py-3.5 px-4 font-semibold">Severity & Category</th>
                    <th className="py-3.5 px-4 font-semibold">Incident Title</th>
                    <th className="py-3.5 px-4 font-semibold">Containment Status</th>
                    <th className="py-3.5 px-4 font-semibold">Lifecycle</th>
                    <th className="py-3.5 px-4 font-semibold">Logged At</th>
                    <th className="py-3.5 px-4 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60 font-mono">
                  {cases.map((c) => {
                    const sev = severityColors[c.severity] || severityColors.MEDIUM;
                    const cat = categoryLabels[c.category] || categoryLabels.CUSTOM;

                    return (
                      <tr key={c.id} className="hover:bg-zinc-800/40 transition-colors">
                        <td className="py-4 px-4 font-bold text-white whitespace-nowrap">
                          {c.case_number}
                        </td>

                        <td className="py-4 px-4 whitespace-nowrap">
                          <div className="flex items-center space-x-2">
                            <span className={`px-2 py-0.5 rounded text-[11px] border ${sev.bg} ${sev.text} ${sev.border}`}>
                              {c.severity}
                            </span>
                            <span className="text-zinc-300 font-sans flex items-center gap-1">
                              <span>{cat.icon}</span>
                              <span>{cat.label}</span>
                            </span>
                          </div>
                        </td>

                        <td className="py-4 px-4 max-w-xs truncate font-sans text-zinc-200">
                          <div className="font-semibold text-sm truncate">{c.title}</div>
                          {c.description && <div className="text-xs text-zinc-500 truncate">{c.description}</div>}
                        </td>

                        <td className="py-4 px-4 whitespace-nowrap">
                          <span
                            className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                              c.containment_status === "CONTAINED"
                                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                                : c.containment_status === "PROPOSED" || c.containment_status === "APPROVED"
                                ? "bg-amber-500/20 text-amber-400 border border-amber-500/30 animate-pulse"
                                : "bg-zinc-800 text-zinc-400 border border-zinc-700"
                            }`}
                          >
                            {c.containment_status}
                          </span>
                        </td>

                        <td className="py-4 px-4 whitespace-nowrap text-zinc-300 font-sans">
                          <span
                            className={`px-2 py-0.5 rounded text-xs ${
                              c.status === "RESOLVED"
                                ? "bg-zinc-800 text-zinc-400"
                                : "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                            }`}
                          >
                            {c.status}
                          </span>
                        </td>

                        <td className="py-4 px-4 whitespace-nowrap text-zinc-400 text-[11px]">
                          {new Date(c.created_at).toLocaleString()}
                        </td>

                        <td className="py-4 px-4 whitespace-nowrap text-right space-x-1.5 font-sans">
                          <button
                            onClick={() => handleOpenEvidence(c)}
                            className="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs border border-zinc-700"
                            title="Inspect Frozen Evidence Snapshot"
                          >
                            🔍 Evidence
                          </button>
                          <button
                            onClick={() => handleOpenContainment(c)}
                            className="px-2.5 py-1 bg-red-950/60 hover:bg-red-900/60 text-red-300 rounded text-xs border border-red-700/50 font-semibold"
                            title="Dual Sign-Off Containment Gate"
                          >
                            ⚡ Containment
                          </button>
                          <button
                            onClick={() => handleOpenAuditChain(c)}
                            className="px-2.5 py-1 bg-blue-950/50 hover:bg-blue-900/50 text-blue-300 rounded text-xs border border-blue-700/40"
                            title="Verify Chained SHA-256 Audit Ledger"
                          >
                            ⛓️ Audit Chain
                          </button>
                          {c.status !== "RESOLVED" && (
                            <button
                              onClick={() => {
                                setSelectedCase(c);
                                setShowResolveModal(true);
                              }}
                              className="px-2 py-1 bg-emerald-950/50 hover:bg-emerald-900/50 text-emerald-300 rounded text-xs border border-emerald-700/40"
                              title="Resolve & Close Case"
                            >
                              ✓
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>

      {/* MODAL 1: FILE SECURITY INCIDENT */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <span>🛡️</span> File Security Incident (Quarantine Mode)
              </h2>
              <button onClick={() => setShowCreateModal(false)} className="text-zinc-400 hover:text-white">✕</button>
            </div>

            <form onSubmit={handleCreateCase} className="space-y-4 text-xs font-sans">
              <div>
                <label className="block text-zinc-300 font-medium mb-1">Incident Summary Title *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. AWS Secret Access Key leaked in staging logs"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2.5 text-white focus:outline-none focus:border-red-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-zinc-300 font-medium mb-1">Threat Category</label>
                  <select
                    value={newCategory}
                    onChange={(e) => setNewCategory(e.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2.5 text-white focus:outline-none focus:border-red-500"
                  >
                    <option value="CREDENTIAL_LEAK">🔑 Credential Leak</option>
                    <option value="SUSPICIOUS_AUTH">🛡️ Suspicious Auth</option>
                    <option value="PRIVILEGE_ESCALATION">⚡ Privilege Escalation</option>
                    <option value="UNUSUAL_DATA_ACCESS">📊 Unusual Data Access</option>
                    <option value="VULNERABLE_DEPENDENCY">📦 Vulnerable Dependency</option>
                    <option value="MALWARE_SUSPECTED">☣️ Malware Suspected</option>
                    <option value="CUSTOM">🔒 Custom Security Issue</option>
                  </select>
                </div>

                <div>
                  <label className="block text-zinc-300 font-medium mb-1">Severity Level</label>
                  <select
                    value={newSeverity}
                    onChange={(e) => setNewSeverity(e.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2.5 text-white focus:outline-none focus:border-red-500"
                  >
                    <option value="CRITICAL">🔴 CRITICAL</option>
                    <option value="HIGH">🟠 HIGH</option>
                    <option value="MEDIUM">🟡 MEDIUM</option>
                    <option value="LOW">🔵 LOW</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-zinc-300 font-medium mb-1">Threat Context / Raw Log Snippet</label>
                <textarea
                  rows={4}
                  placeholder="Paste relevant telemetry logs or alert message. Sensitive credentials will be auto-redacted and cryptographically sealed."
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2.5 text-white font-mono focus:outline-none focus:border-red-500"
                />
              </div>

              <div className="bg-red-950/30 border border-red-900/40 p-3 rounded-lg text-zinc-400 text-[11px]">
                <strong className="text-red-400">Zero Autonomous Mutation Invariant:</strong> Creating this case will freeze an immutable SHA-256 evidence snapshot and enforce strict quarantine. Autonomous code patches are blocked.
              </div>

              <div className="flex justify-end space-x-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingCase}
                  className="px-4 py-2 bg-red-600 hover:bg-red-500 text-white font-semibold rounded-lg shadow-lg shadow-red-900/30"
                >
                  {creatingCase ? "Sealing Evidence..." : "Quarantine & File Case"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL 2: FORENSIC EVIDENCE VAULT */}
      {evidenceSnapshot && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-2xl w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <span>🔒</span> Forensic Evidence Snapshot Vault
                </h2>
                <p className="text-xs text-zinc-400 font-mono mt-0.5">
                  Case: {selectedCase?.case_number} • Sealed: {new Date(evidenceSnapshot.sealed_at).toLocaleString()}
                </p>
              </div>
              <button onClick={() => setEvidenceSnapshot(null)} className="text-zinc-400 hover:text-white">✕</button>
            </div>

            <div className="space-y-3 text-xs font-sans">
              <div className="bg-zinc-950 p-3 rounded-xl border border-zinc-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400 uppercase tracking-wider text-[10px] font-bold">Cryptographic Digest</span>
                  <span className="px-2 py-0.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded text-[10px] font-mono">
                    STATUS: {evidenceSnapshot.completeness_status}
                  </span>
                </div>
                <div className="font-mono text-zinc-300 text-[11px] break-all bg-zinc-900 p-2 rounded border border-zinc-800">
                  SHA256: {evidenceSnapshot.manifest_hash}
                </div>
              </div>

              <div>
                <label className="block text-zinc-400 font-semibold mb-1 text-[11px] uppercase tracking-wider">
                  Immutable Captured Manifest JSON
                </label>
                <pre className="bg-zinc-950 p-4 rounded-xl border border-zinc-800 text-zinc-300 font-mono text-[11px] overflow-auto max-h-72">
                  {JSON.stringify(evidenceSnapshot.manifest_json, null, 2)}
                </pre>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  onClick={() => setEvidenceSnapshot(null)}
                  className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg text-xs"
                >
                  Close Vault
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 3: CONTAINMENT PLAYBOOK & DUAL SIGN-OFF GATE */}
      {selectedCase && !evidenceSnapshot && !auditChain && !showResolveModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-3xl w-full p-6 space-y-4 shadow-2xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <span>⚡</span> Dual Sign-Off Containment Gate
                </h2>
                <p className="text-xs text-zinc-400 font-mono mt-0.5">
                  Case: {selectedCase.case_number} — {selectedCase.title}
                </p>
              </div>
              <button onClick={() => setSelectedCase(null)} className="text-zinc-400 hover:text-white">✕</button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-4 text-xs font-sans pr-1">
              <div className="flex items-center justify-between">
                <span className="text-zinc-400 font-semibold uppercase tracking-wider text-[11px]">
                  Configured Containment Actions ({containmentActions.length})
                </span>
                <button
                  onClick={() => setShowProposeAction(true)}
                  className="px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white rounded-lg text-xs font-medium"
                >
                  + Propose Containment Action
                </button>
              </div>

              {/* Propose Action Form */}
              {showProposeAction && (
                <form onSubmit={handleProposeAction} className="bg-zinc-950 p-4 rounded-xl border border-zinc-800 space-y-3">
                  <h3 className="font-bold text-white text-xs">New Scoped Containment Action</h3>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-zinc-400 mb-1">Playbook Action Type</label>
                      <select
                        value={actionType}
                        onChange={(e) => setActionType(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-white"
                      >
                        <option value="REVOKE_CREDENTIAL">🔑 REVOKE_CREDENTIAL</option>
                        <option value="QUARANTINE_SERVICE">🛡️ QUARANTINE_SERVICE</option>
                        <option value="BLOCK_IDENTITY">🚫 BLOCK_IDENTITY</option>
                        <option value="LOCK_DEPENDENCY">📦 LOCK_DEPENDENCY</option>
                        <option value="ROTATE_SECRET">🔄 ROTATE_SECRET</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-zinc-400 mb-1">Target Entity Type</label>
                      <select
                        value={targetType}
                        onChange={(e) => setTargetType(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-white"
                      >
                        <option value="secret">Secret / Token</option>
                        <option value="service">Service</option>
                        <option value="user">User Account</option>
                        <option value="repository">Repository</option>
                        <option value="network_ip">Network IP / CIDR</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-zinc-400 mb-1">Target ID / Resource Name *</label>
                      <input
                        type="text"
                        required
                        placeholder="e.g. checkout-api-secret-key"
                        value={targetId}
                        onChange={(e) => setTargetId(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-white"
                      />
                    </div>
                    <div>
                      <label className="block text-zinc-400 mb-1">Action Title *</label>
                      <input
                        type="text"
                        required
                        placeholder="e.g. Revoke leaked API key"
                        value={actionTitle}
                        onChange={(e) => setActionTitle(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-white"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-zinc-400 mb-1">Execution Rationale</label>
                    <input
                      type="text"
                      placeholder="Optional notes for approving officers"
                      value={actionDescription}
                      onChange={(e) => setActionDescription(e.target.value)}
                      className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2 text-white"
                    />
                  </div>

                  <div className="flex justify-end space-x-2 pt-1">
                    <button
                      type="button"
                      onClick={() => setShowProposeAction(false)}
                      className="px-3 py-1.5 bg-zinc-800 text-zinc-300 rounded-lg"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={proposingAction}
                      className="px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white font-medium rounded-lg"
                    >
                      {proposingAction ? "Submitting..." : "Submit Proposal"}
                    </button>
                  </div>
                </form>
              )}

              {/* Containment Action Cards */}
              {loadingContainment ? (
                <div className="py-12 text-center text-zinc-500">Loading containment actions...</div>
              ) : containmentActions.length === 0 ? (
                <div className="py-12 text-center text-zinc-500 bg-zinc-950/50 rounded-xl border border-zinc-800/60">
                  No containment actions proposed yet for this case.
                </div>
              ) : (
                <div className="space-y-3">
                  {containmentActions.map((act) => {
                    return (
                      <div key={act.id} className="bg-zinc-950 p-4 rounded-xl border border-zinc-800 space-y-3">
                        <div className="flex items-start justify-between">
                          <div>
                            <div className="flex items-center space-x-2">
                              <span className="font-bold text-white text-sm">{act.title}</span>
                              <span className="px-2 py-0.5 bg-zinc-800 text-zinc-400 rounded text-[10px] font-mono">
                                {act.action_type}
                              </span>
                            </div>
                            <div className="text-xs text-zinc-400 mt-0.5">
                              Target: <span className="font-mono text-zinc-300">{act.target_type}:{act.target_id}</span>
                            </div>
                          </div>

                          <span
                            className={`px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider ${
                              act.status === "EXECUTED"
                                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                                : act.status === "APPROVED"
                                ? "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                                : act.status === "PENDING_SECOND_APPROVAL"
                                ? "bg-amber-500/20 text-amber-400 border border-amber-500/30 animate-pulse"
                                : "bg-zinc-800 text-zinc-400 border border-zinc-700"
                            }`}
                          >
                            {act.status}
                          </span>
                        </div>

                        {/* Dual Sign-Off Progress Bar */}
                        <div className="bg-zinc-900/90 p-3 rounded-lg border border-zinc-800/80 space-y-2">
                          <div className="flex items-center justify-between text-[11px]">
                            <span className="text-zinc-400 font-semibold">Dual Sign-Off Gate Status</span>
                            <span className="text-zinc-500 font-mono">
                              {act.status === "EXECUTED" || act.status === "APPROVED"
                                ? "2 of 2 Approved"
                                : act.status === "PENDING_SECOND_APPROVAL"
                                ? "1 of 2 Approved (Awaiting 2nd Officer)"
                                : "0 of 2 Approved"}
                            </span>
                          </div>

                          <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
                            <div className={`p-2 rounded border ${act.approver_1_user_id ? "bg-emerald-950/40 border-emerald-700/40 text-emerald-300" : "bg-zinc-950 border-zinc-800 text-zinc-500"}`}>
                              ✓ Sign-Off 1: {act.approver_1_name || "Pending..."}
                            </div>
                            <div className={`p-2 rounded border ${act.approver_2_user_id ? "bg-emerald-950/40 border-emerald-700/40 text-emerald-300" : "bg-zinc-950 border-zinc-800 text-zinc-500"}`}>
                              ✓ Sign-Off 2: {act.approver_2_name || "Pending (Distinct Officer)..."}
                            </div>
                          </div>
                        </div>

                        {act.execution_output && (
                          <div className="bg-zinc-900 p-2.5 rounded text-[11px] font-mono text-zinc-300 border border-zinc-800">
                            <strong>Execution Log:</strong> {act.execution_output}
                          </div>
                        )}

                        {/* Action Controls */}
                        <div className="flex items-center justify-end space-x-2 pt-1">
                          {(act.status === "PROPOSED" || act.status === "PENDING_SECOND_APPROVAL") && (
                            <button
                              onClick={() => handleApproveAction(act.id)}
                              disabled={approvingActionId === act.id}
                              className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-semibold"
                            >
                              {approvingActionId === act.id ? "Signing..." : "✍️ Sign Off Approval"}
                            </button>
                          )}

                          {act.status === "APPROVED" && (
                            <>
                              <button
                                onClick={() => handleExecuteAction(act.id, true)}
                                disabled={executingActionId === act.id}
                                className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs border border-zinc-700"
                              >
                                🧪 Dry Run
                              </button>
                              <button
                                onClick={() => handleExecuteAction(act.id, false)}
                                disabled={executingActionId === act.id}
                                className="px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white rounded text-xs font-bold shadow-lg shadow-red-900/40"
                              >
                                🚀 Execute Containment
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="flex justify-end pt-3 border-t border-zinc-800">
              <button
                onClick={() => setSelectedCase(null)}
                className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg text-xs"
              >
                Close Playbook
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 4: TAMPER-EVIDENT AUDIT CHAIN */}
      {auditChain && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-3xl w-full p-6 space-y-4 shadow-2xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <span>⛓️</span> Cryptographic Forensic Audit Ledger
                </h2>
                <p className="text-xs text-zinc-400 font-mono mt-0.5">
                  Case: {selectedCase?.case_number} • Monotonic SHA-256 Chaining
                </p>
              </div>
              <button onClick={() => setAuditChain(null)} className="text-zinc-400 hover:text-white">✕</button>
            </div>

            {/* Verification Banner */}
            <div
              className={`p-3 rounded-xl border flex items-center justify-between text-xs font-sans ${
                auditChain.is_valid
                  ? "bg-emerald-950/40 border-emerald-500/40 text-emerald-300"
                  : "bg-red-950/40 border-red-500/40 text-red-300"
              }`}
            >
              <div className="flex items-center space-x-2">
                <span className="text-base">{auditChain.is_valid ? "🛡️" : "⚠️"}</span>
                <span className="font-semibold">{auditChain.message}</span>
              </div>
              <span className="font-mono text-[11px]">{auditChain.total_entries} Blocks Verified</span>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3 font-mono text-[11px] pr-1">
              {auditChain.entries.map((entry) => (
                <div key={entry.id} className="bg-zinc-950 p-3.5 rounded-xl border border-zinc-800 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-red-400">
                      Block #{entry.sequence_number}: {entry.event_type}
                    </span>
                    <span className="text-zinc-500 text-[10px]">
                      {new Date(entry.timestamp).toLocaleString()}
                    </span>
                  </div>

                  <div className="text-zinc-400 font-sans text-xs">
                    Actor: <span className="text-zinc-200 font-semibold">{entry.actor_name || "System"}</span>
                  </div>

                  <div className="text-zinc-500 text-[10px] space-y-0.5 break-all">
                    <div>Prev: {entry.previous_hash}</div>
                    <div className="text-zinc-300">Curr: {entry.current_hash}</div>
                  </div>

                  {entry.payload_json && Object.keys(entry.payload_json).length > 0 && (
                    <pre className="bg-zinc-900/80 p-2 rounded border border-zinc-800/60 text-[10px] text-zinc-400 overflow-x-auto">
                      {JSON.stringify(entry.payload_json, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
            </div>

            <div className="flex justify-end pt-2 border-t border-zinc-800">
              <button
                onClick={() => setAuditChain(null)}
                className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg text-xs font-sans"
              >
                Close Audit Chain
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL 5: RESOLVE CASE */}
      {showResolveModal && selectedCase && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <span>✓</span> Resolve Security Case
              </h2>
              <button onClick={() => setShowResolveModal(false)} className="text-zinc-400 hover:text-white">✕</button>
            </div>

            <form onSubmit={handleResolveCase} className="space-y-4 text-xs font-sans">
              <div>
                <label className="block text-zinc-300 font-medium mb-1">
                  Post-Incident Hardening & Resolution Summary *
                </label>
                <textarea
                  rows={4}
                  required
                  placeholder="Describe root cause, containment actions taken, credentials rotated, and perimeter hardening applied."
                  value={resolutionSummary}
                  onChange={(e) => setResolutionSummary(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-2.5 text-white focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div className="flex justify-end space-x-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowResolveModal(false)}
                  className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={resolvingCase}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-lg shadow-lg shadow-emerald-900/30"
                >
                  {resolvingCase ? "Resolving..." : "Confirm Resolution"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
