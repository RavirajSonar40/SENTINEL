"use client";

import React, { useState, useEffect, useMemo } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import {
  changeApi,
  ChangeEvent,
  ChangeType,
  ChangeRiskLevel,
  CreateChangeEventPayload,
} from "@/lib/changeApi";

export default function ChangesPage() {
  const { token } = useAuth();
  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedType, setSelectedType] = useState<string>("ALL");
  const [selectedRisk, setSelectedRisk] = useState<string>("ALL");
  const [selectedProvider, setSelectedProvider] = useState<string>("ALL");

  // Modals
  const [selectedChange, setSelectedChange] = useState<ChangeEvent | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState<CreateChangeEventPayload>({
    title: "",
    description: "",
    change_type: "CODE_COMMIT",
    provider: "manual",
    risk_level: "LOW",
    external_id: "",
    author: "",
    source_url: "",
  });
  const [submitting, setSubmitting] = useState(false);

  const fetchChanges = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await changeApi.getChanges({ limit: 100 }, token || undefined);
      setChanges(data);
    } catch (err: any) {
      setError(err.message || "Failed to load change ledger");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchChanges();
  }, [token]);

  const handleCreateChange = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      await changeApi.createChange(
        {
          ...createForm,
          effective_at: new Date().toISOString(),
        },
        token || undefined
      );
      setShowCreateModal(false);
      setCreateForm({
        title: "",
        description: "",
        change_type: "CODE_COMMIT",
        provider: "manual",
        risk_level: "LOW",
        external_id: "",
        author: "",
        source_url: "",
      });
      await fetchChanges();
    } catch (err: any) {
      alert(`Error recording change: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const filteredChanges = useMemo(() => {
    return changes.filter((c) => {
      if (selectedType !== "ALL" && c.change_type !== selectedType) return false;
      if (selectedRisk !== "ALL" && c.risk_level !== selectedRisk) return false;
      if (selectedProvider !== "ALL" && c.provider.toLowerCase() !== selectedProvider.toLowerCase()) return false;
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const matchesTitle = c.title.toLowerCase().includes(query);
        const matchesAuthor = c.author?.toLowerCase().includes(query);
        const matchesExtId = c.external_id.toLowerCase().includes(query);
        const matchesProvider = c.provider.toLowerCase().includes(query);
        if (!matchesTitle && !matchesAuthor && !matchesExtId && !matchesProvider) return false;
      }
      return true;
    });
  }, [changes, selectedType, selectedRisk, selectedProvider, searchQuery]);

  const stats = useMemo(() => {
    const total = changes.length;
    const flags = changes.filter((c) => c.change_type === "FEATURE_FLAG").length;
    const deploys = changes.filter((c) => c.change_type === "DEPLOYMENT").length;
    const migrations = changes.filter((c) => c.change_type === "DATABASE_MIGRATION").length;
    const highRisk = changes.filter((c) => c.risk_level === "HIGH" || c.risk_level === "CRITICAL").length;
    return { total, flags, deploys, migrations, highRisk };
  }, [changes]);

  const getRiskBadge = (risk: ChangeRiskLevel) => {
    switch (risk) {
      case "CRITICAL":
        return "bg-rose-500/20 text-rose-400 border-rose-500/30";
      case "HIGH":
        return "bg-amber-500/20 text-amber-400 border-amber-500/30";
      case "MEDIUM":
        return "bg-yellow-500/20 text-yellow-300 border-yellow-500/30";
      case "LOW":
      default:
        return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
    }
  };

  const getTypeBadge = (type: ChangeType) => {
    switch (type) {
      case "FEATURE_FLAG":
        return "bg-purple-500/20 text-purple-300 border-purple-500/30";
      case "DEPLOYMENT":
        return "bg-blue-500/20 text-blue-300 border-blue-500/30";
      case "DATABASE_MIGRATION":
        return "bg-cyan-500/20 text-cyan-300 border-cyan-500/30";
      case "CONFIGURATION":
      case "ENVIRONMENT_VARIABLE":
        return "bg-amber-500/20 text-amber-300 border-amber-500/30";
      case "INFRASTRUCTURE":
        return "bg-indigo-500/20 text-indigo-300 border-indigo-500/30";
      case "CODE_COMMIT":
      case "PULL_REQUEST":
        return "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";
      default:
        return "bg-neutral-500/20 text-neutral-300 border-neutral-500/30";
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-surface text-on-surface">
      <TopBar
        title="Change Intelligence Ledger"
        subtitle="Continuous multi-source change tracking across Git, Feature Flags, Database Migrations, and Infrastructure."
        actions={
          <div className="flex items-center gap-2 mr-4">
            <button
              onClick={fetchChanges}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-surface-container-high hover:bg-surface-container-highest transition border border-outline-variant text-on-surface"
            >
              <span className="material-symbols-outlined text-16">refresh</span>
              Refresh
            </button>
            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-primary hover:bg-primary/90 text-on-primary shadow-sm transition"
            >
              <span className="material-symbols-outlined text-16">add</span>
              Record Change
            </button>
          </div>
        }
      />

      <main className="flex-1 p-6 space-y-6 max-w-7xl mx-auto w-full">

        {/* Metrics Overview Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <div className="bg-surface-container-low border border-outline-variant/50 p-4 rounded-xl">
            <div className="flex items-center justify-between">
              <span className="text-xs text-on-surface-variant uppercase tracking-wider font-semibold">Total Changes</span>
              <span className="material-symbols-outlined text-primary text-20">history</span>
            </div>
            <p className="text-24 font-bold mt-2 text-on-surface">{stats.total}</p>
          </div>

          <div className="bg-surface-container-low border border-outline-variant/50 p-4 rounded-xl">
            <div className="flex items-center justify-between">
              <span className="text-xs text-on-surface-variant uppercase tracking-wider font-semibold">Feature Flags</span>
              <span className="material-symbols-outlined text-purple-400 text-20">toggle_on</span>
            </div>
            <p className="text-24 font-bold mt-2 text-purple-400">{stats.flags}</p>
          </div>

          <div className="bg-surface-container-low border border-outline-variant/50 p-4 rounded-xl">
            <div className="flex items-center justify-between">
              <span className="text-xs text-on-surface-variant uppercase tracking-wider font-semibold">Deployments</span>
              <span className="material-symbols-outlined text-blue-400 text-20">rocket_launch</span>
            </div>
            <p className="text-24 font-bold mt-2 text-blue-400">{stats.deploys}</p>
          </div>

          <div className="bg-surface-container-low border border-outline-variant/50 p-4 rounded-xl">
            <div className="flex items-center justify-between">
              <span className="text-xs text-on-surface-variant uppercase tracking-wider font-semibold">DB Migrations</span>
              <span className="material-symbols-outlined text-cyan-400 text-20">database</span>
            </div>
            <p className="text-24 font-bold mt-2 text-cyan-400">{stats.migrations}</p>
          </div>

          <div className="bg-surface-container-low border border-outline-variant/50 p-4 rounded-xl">
            <div className="flex items-center justify-between">
              <span className="text-xs text-on-surface-variant uppercase tracking-wider font-semibold">High / Critical Risk</span>
              <span className="material-symbols-outlined text-amber-400 text-20">warning</span>
            </div>
            <p className="text-24 font-bold mt-2 text-amber-400">{stats.highRisk}</p>
          </div>
        </div>

        {/* Filter Toolbar */}
        <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex flex-col md:flex-row gap-3 items-center justify-between">
          <div className="relative w-full md:w-80">
            <span className="material-symbols-outlined absolute left-3 top-2.5 text-18 text-on-surface-variant">search</span>
            <input
              type="text"
              placeholder="Search title, author, ID, provider..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 text-13 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary transition"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto">
            {/* Change Type Filter */}
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="px-3 py-1.5 text-13 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary transition"
            >
              <option value="ALL">All Change Types</option>
              <option value="FEATURE_FLAG">Feature Flags</option>
              <option value="DEPLOYMENT">Deployments</option>
              <option value="DATABASE_MIGRATION">DB Migrations</option>
              <option value="CONFIGURATION">Configurations</option>
              <option value="ENVIRONMENT_VARIABLE">Environment Variables</option>
              <option value="INFRASTRUCTURE">Infrastructure</option>
              <option value="CODE_COMMIT">Code Commits</option>
              <option value="PULL_REQUEST">Pull Requests</option>
              <option value="SCALING_CHANGE">Scaling Changes</option>
            </select>

            {/* Risk Level Filter */}
            <select
              value={selectedRisk}
              onChange={(e) => setSelectedRisk(e.target.value)}
              className="px-3 py-1.5 text-13 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary transition"
            >
              <option value="ALL">All Risk Levels</option>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
              <option value="CRITICAL">Critical</option>
            </select>

            {/* Provider Filter */}
            <select
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
              className="px-3 py-1.5 text-13 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary transition"
            >
              <option value="ALL">All Providers</option>
              <option value="github">GitHub</option>
              <option value="launchdarkly">LaunchDarkly</option>
              <option value="terraform">Terraform</option>
              <option value="kubernetes">Kubernetes</option>
              <option value="alembic">Alembic</option>
              <option value="manual">Manual</option>
            </select>
          </div>
        </div>

        {/* Change Events Table */}
        <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
          {loading ? (
            <div className="p-12 flex flex-col items-center justify-center gap-3">
              <span className="material-symbols-outlined text-36 animate-spin text-primary">progress_activity</span>
              <p className="text-14 text-on-surface-variant">Loading change intelligence records...</p>
            </div>
          ) : error ? (
            <div className="p-12 flex flex-col items-center justify-center gap-3 text-rose-400">
              <span className="material-symbols-outlined text-36">error</span>
              <p className="text-14 font-medium">{error}</p>
              <button
                onClick={fetchChanges}
                className="mt-2 px-4 py-1.5 text-12 font-medium bg-rose-500/20 rounded-md border border-rose-500/30"
              >
                Try Again
              </button>
            </div>
          ) : filteredChanges.length === 0 ? (
            <div className="p-12 flex flex-col items-center justify-center gap-2 text-on-surface-variant">
              <span className="material-symbols-outlined text-40 text-outline">history</span>
              <p className="text-15 font-semibold text-on-surface">No Change Events Found</p>
              <p className="text-13">Try adjusting your search queries or record an event.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-13">
                <thead className="bg-surface-container-high/60 text-xs font-semibold text-on-surface-variant uppercase tracking-wider border-b border-outline-variant/50">
                  <tr>
                    <th className="py-3 px-4">Change Event</th>
                    <th className="py-3 px-4">Type</th>
                    <th className="py-3 px-4">Risk</th>
                    <th className="py-3 px-4">Provider</th>
                    <th className="py-3 px-4">Author</th>
                    <th className="py-3 px-4">Effective At</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/30">
                  {filteredChanges.map((change) => (
                    <tr
                      key={change.id}
                      className="hover:bg-surface-container-high/40 transition cursor-pointer"
                      onClick={() => setSelectedChange(change)}
                    >
                      <td className="py-3.5 px-4 font-medium text-on-surface max-w-sm truncate">
                        <div>
                          <p className="font-semibold text-13 truncate">{change.title}</p>
                          <p className="text-xs text-on-surface-variant font-mono truncate">{change.external_id}</p>
                        </div>
                      </td>
                      <td className="py-3.5 px-4">
                        <span className={`px-2 py-0.5 text-xs font-medium rounded-md border ${getTypeBadge(change.change_type)}`}>
                          {change.change_type.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="py-3.5 px-4">
                        <span className={`px-2 py-0.5 text-xs font-medium rounded-md border ${getRiskBadge(change.risk_level)}`}>
                          {change.risk_level}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 capitalize font-mono text-xs text-on-surface-variant">
                        {change.provider}
                      </td>
                      <td className="py-3.5 px-4 text-on-surface-variant truncate max-w-xs">
                        {change.author || "system"}
                      </td>
                      <td className="py-3.5 px-4 text-xs font-mono text-on-surface-variant whitespace-nowrap">
                        {new Date(change.effective_at).toLocaleString()}
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedChange(change);
                          }}
                          className="px-2.5 py-1 text-xs font-medium rounded bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant text-on-surface transition"
                        >
                          Details
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>

      {/* Change Details Modal */}
      {selectedChange && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-surface-container-low border border-outline-variant rounded-2xl max-w-2xl w-full p-6 space-y-5 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-outline-variant/60 pb-3">
              <div>
                <h3 className="text-18 font-bold text-on-surface">{selectedChange.title}</h3>
                <p className="text-xs text-on-surface-variant font-mono mt-0.5">ID: {selectedChange.id}</p>
              </div>
              <button
                onClick={() => setSelectedChange(null)}
                className="p-1 rounded-md text-on-surface-variant hover:bg-surface-container-high"
              >
                <span className="material-symbols-outlined text-20">close</span>
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="bg-surface-container-high/60 p-3 rounded-lg border border-outline-variant/40">
                <span className="text-on-surface-variant font-medium">Type</span>
                <p className="font-semibold text-on-surface mt-1">{selectedChange.change_type}</p>
              </div>
              <div className="bg-surface-container-high/60 p-3 rounded-lg border border-outline-variant/40">
                <span className="text-on-surface-variant font-medium">Risk Level</span>
                <p className="font-semibold text-on-surface mt-1">{selectedChange.risk_level}</p>
              </div>
              <div className="bg-surface-container-high/60 p-3 rounded-lg border border-outline-variant/40">
                <span className="text-on-surface-variant font-medium">Provider</span>
                <p className="font-semibold text-on-surface mt-1 capitalize">{selectedChange.provider}</p>
              </div>
              <div className="bg-surface-container-high/60 p-3 rounded-lg border border-outline-variant/40">
                <span className="text-on-surface-variant font-medium">Author</span>
                <p className="font-semibold text-on-surface mt-1">{selectedChange.author || "system"}</p>
              </div>
            </div>

            {selectedChange.description && (
              <div>
                <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">Description</span>
                <p className="text-13 mt-1 text-on-surface bg-surface-container-high/40 p-3 rounded-lg border border-outline-variant/40">
                  {selectedChange.description}
                </p>
              </div>
            )}

            {/* Sanitized Diff Summary */}
            {selectedChange.diff_summary && Object.keys(selectedChange.diff_summary).length > 0 && (
              <div>
                <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">
                  Sanitized Diff Summary
                </span>
                <pre className="mt-1 text-xs font-mono bg-surface-container-highest p-3 rounded-lg border border-outline-variant overflow-x-auto text-emerald-400">
                  {JSON.stringify(selectedChange.diff_summary, null, 2)}
                </pre>
              </div>
            )}

            {/* Metadata JSON */}
            {selectedChange.metadata_json && Object.keys(selectedChange.metadata_json).length > 0 && (
              <div>
                <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">
                  Metadata & Parameters
                </span>
                <pre className="mt-1 text-xs font-mono bg-surface-container-highest p-3 rounded-lg border border-outline-variant overflow-x-auto text-cyan-300">
                  {JSON.stringify(selectedChange.metadata_json, null, 2)}
                </pre>
              </div>
            )}

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setSelectedChange(null)}
                className="px-4 py-2 text-13 font-medium bg-surface-container-high hover:bg-surface-container-highest rounded-lg border border-outline-variant text-on-surface transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Manual Change Ingestion Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <form
            onSubmit={handleCreateChange}
            className="bg-surface-container-low border border-outline-variant rounded-2xl max-w-xl w-full p-6 space-y-4 shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-outline-variant/60 pb-3">
              <h3 className="text-18 font-bold text-on-surface">Record New Change Event</h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="p-1 rounded-md text-on-surface-variant hover:bg-surface-container-high"
              >
                <span className="material-symbols-outlined text-20">close</span>
              </button>
            </div>

            <div className="space-y-3 text-13">
              <div>
                <label className="block font-medium text-on-surface-variant mb-1">Title *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Rolled out killswitch flag v2"
                  value={createForm.title}
                  onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-on-surface-variant mb-1">Change Type *</label>
                  <select
                    value={createForm.change_type}
                    onChange={(e) => setCreateForm({ ...createForm, change_type: e.target.value as ChangeType })}
                    className="w-full px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary"
                  >
                    <option value="CODE_COMMIT">Code Commit</option>
                    <option value="PULL_REQUEST">Pull Request</option>
                    <option value="FEATURE_FLAG">Feature Flag</option>
                    <option value="DATABASE_MIGRATION">DB Migration</option>
                    <option value="CONFIGURATION">Configuration</option>
                    <option value="ENVIRONMENT_VARIABLE">Environment Variable</option>
                    <option value="INFRASTRUCTURE">Infrastructure</option>
                    <option value="DEPLOYMENT">Deployment</option>
                    <option value="SCALING_CHANGE">Scaling Change</option>
                  </select>
                </div>

                <div>
                  <label className="block font-medium text-on-surface-variant mb-1">Risk Level *</label>
                  <select
                    value={createForm.risk_level}
                    onChange={(e) => setCreateForm({ ...createForm, risk_level: e.target.value as ChangeRiskLevel })}
                    className="w-full px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary"
                  >
                    <option value="LOW">Low</option>
                    <option value="MEDIUM">Medium</option>
                    <option value="HIGH">High</option>
                    <option value="CRITICAL">Critical</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-on-surface-variant mb-1">Provider</label>
                  <input
                    type="text"
                    placeholder="manual, github, etc."
                    value={createForm.provider}
                    onChange={(e) => setCreateForm({ ...createForm, provider: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>

                <div>
                  <label className="block font-medium text-on-surface-variant mb-1">Author</label>
                  <input
                    type="text"
                    placeholder="Operator name / email"
                    value={createForm.author}
                    onChange={(e) => setCreateForm({ ...createForm, author: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary"
                  />
                </div>
              </div>

              <div>
                <label className="block font-medium text-on-surface-variant mb-1">Description</label>
                <textarea
                  rows={2}
                  placeholder="Optional details or context regarding the change..."
                  value={createForm.description}
                  onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant text-on-surface focus:outline-none focus:border-primary"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-outline-variant/60">
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 text-13 font-medium bg-surface-container-high hover:bg-surface-container-highest rounded-lg border border-outline-variant text-on-surface transition"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 text-13 font-semibold rounded-lg bg-primary hover:bg-primary/90 text-on-primary shadow-sm transition disabled:opacity-50"
              >
                {submitting ? "Recording..." : "Record Change"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
