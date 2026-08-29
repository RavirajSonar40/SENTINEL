'use client';

import React, { useState, useEffect } from 'react';
import {
  fetchPostMortem,
  generatePostMortem,
  updatePostMortem,
  publishPostMortem,
  createActionItem,
  updateActionItem,
  PostMortem,
  ActionItem,
  ActionItemCreate,
} from '@/lib/incidentMemoryApi';

interface PostMortemStudioProps {
  incidentId: string;
}

export default function PostMortemStudio({ incidentId }: PostMortemStudioProps) {
  const [postMortem, setPostMortem] = useState<PostMortem | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Edit states
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editSummary, setEditSummary] = useState('');
  const [editRootCause, setEditRootCause] = useState('');
  const [editImpact, setEditImpact] = useState('');
  const [editResolution, setEditResolution] = useState('');

  // Action Item creation state
  const [showAddAction, setShowAddAction] = useState(false);
  const [actionTitle, setActionTitle] = useState('');
  const [actionDesc, setActionDesc] = useState('');
  const [actionCategory, setActionCategory] = useState('code_hardening');
  const [actionPriority, setActionPriority] = useState('P2');

  // Sign off modal
  const [showSignOffModal, setShowSignOffModal] = useState(false);
  const [signOffNotes, setSignOffNotes] = useState('');

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const pm = await fetchPostMortem(incidentId);
      setPostMortem(pm);
      setEditTitle(pm.title);
      setEditSummary(pm.summary);
      setEditRootCause(pm.root_cause_summary);
      setEditImpact(pm.impact_summary || '');
      setEditResolution(pm.resolution_summary || '');
    } catch (err: any) {
      if (err.message?.includes('404') || err.message?.includes('not found')) {
        setPostMortem(null);
      } else {
        setError(err.message || 'Failed to load post-mortem');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (incidentId) {
      loadData();
    }
  }, [incidentId]);

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);
      const pm = await generatePostMortem(incidentId);
      setPostMortem(pm);
      setEditTitle(pm.title);
      setEditSummary(pm.summary);
      setEditRootCause(pm.root_cause_summary);
      setEditImpact(pm.impact_summary || '');
      setEditResolution(pm.resolution_summary || '');
    } catch (err: any) {
      setError(err.message || 'Failed to synthesize post-mortem');
    } finally {
      setGenerating(false);
    }
  };

  const handleSaveDraft = async () => {
    if (!postMortem) return;
    try {
      setLoading(true);
      const updated = await updatePostMortem(incidentId, {
        title: editTitle,
        summary: editSummary,
        root_cause_summary: editRootCause,
        impact_summary: editImpact,
        resolution_summary: editResolution,
      });
      setPostMortem(updated);
      setIsEditing(false);
    } catch (err: any) {
      setError(err.message || 'Failed to save changes');
    } finally {
      setLoading(false);
    }
  };

  const handlePublish = async () => {
    try {
      setPublishing(true);
      const published = await publishPostMortem(incidentId, signOffNotes);
      setPostMortem(published);
      setShowSignOffModal(false);
    } catch (err: any) {
      setError(err.message || 'Failed to publish post-mortem');
    } finally {
      setPublishing(false);
    }
  };

  const handleCreateActionItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!actionTitle.trim()) return;
    try {
      const newItem = await createActionItem(incidentId, {
        title: actionTitle,
        description: actionDesc,
        category: actionCategory,
        priority: actionPriority,
      });
      if (postMortem) {
        setPostMortem({
          ...postMortem,
          action_items: [...(postMortem.action_items || []), newItem],
        });
      }
      setShowAddAction(false);
      setActionTitle('');
      setActionDesc('');
    } catch (err: any) {
      setError(err.message || 'Failed to create action item');
    }
  };

  const handleToggleActionStatus = async (item: ActionItem) => {
    try {
      const newStatus = item.status === 'completed' ? 'open' : 'completed';
      const updated = await updateActionItem(item.id, { status: newStatus });
      if (postMortem) {
        setPostMortem({
          ...postMortem,
          action_items: (postMortem.action_items || []).map((a) =>
            a.id === item.id ? updated : a
          ),
        });
      }
    } catch (err: any) {
      setError(err.message || 'Failed to update action item status');
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'published':
        return (
          <span className="px-2.5 py-1 text-xs font-bold rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400"></span> PUBLISHED
          </span>
        );
      default:
        return (
          <span className="px-2.5 py-1 text-xs font-bold rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span> DRAFT (v{postMortem?.version || 1})
          </span>
        );
    }
  };

  const getMemoryBadge = (status: string) => {
    switch (status) {
      case 'indexed':
        return (
          <span className="px-2 py-0.5 text-[11px] font-mono rounded bg-purple-950/60 text-purple-300 border border-purple-500/40">
            🧠 Pinecone: Indexed
          </span>
        );
      case 'failed':
        return (
          <span className="px-2 py-0.5 text-[11px] font-mono rounded bg-rose-950/60 text-rose-300 border border-rose-500/40">
            ⚠️ Vector Memory: Failed
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 text-[11px] font-mono rounded bg-slate-800 text-slate-400 border border-slate-700">
            ⏳ Vector Memory: Pending Publish
          </span>
        );
    }
  };

  if (loading) {
    return (
      <div className="p-12 flex flex-col items-center justify-center space-y-4">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
        <p className="text-sm text-slate-400 font-mono">Loading post-mortem studio...</p>
      </div>
    );
  }

  if (!postMortem) {
    return (
      <div className="p-10 border border-slate-800 rounded-2xl bg-slate-900/50 backdrop-blur-sm text-center space-y-4 max-w-xl mx-auto my-6">
        <div className="w-12 h-12 rounded-2xl bg-indigo-600/20 text-indigo-400 flex items-center justify-center text-2xl mx-auto border border-indigo-500/30">
          📝
        </div>
        <div className="space-y-1">
          <h3 className="text-lg font-bold text-slate-100">No Post-Mortem Generated Yet</h3>
          <p className="text-xs text-slate-400 max-w-md mx-auto">
            Synthesize an evidence-bound, blameless SRE post-mortem aggregating incident timeline, root cause causality, and preventive action items.
          </p>
        </div>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white text-xs font-semibold rounded-xl shadow-lg shadow-indigo-500/25 transition flex items-center gap-2 mx-auto disabled:opacity-50"
        >
          {generating ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
              <span>Synthesizing Post-Mortem...</span>
            </>
          ) : (
            <>
              <span>✨</span>
              <span>Generate AI Post-Mortem</span>
            </>
          )}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Safe Abstention Warning Banner */}
      {postMortem.abstained && (
        <div className="p-4 bg-amber-950/30 border border-amber-500/40 rounded-xl flex items-start gap-3 text-amber-300">
          <span className="text-xl">⚠️</span>
          <div className="space-y-1 text-xs">
            <p className="font-bold">Phase 9 Safe Abstention Enforced</p>
            <p className="text-amber-300/80 leading-relaxed">
              The automated root-cause engine safely abstained from certifying a conclusive root cause due to missing multi-family corroboration. Additional telemetry or human override is noted in this post-mortem.
            </p>
          </div>
        </div>
      )}

      {/* Header Bar */}
      <div className="p-5 bg-slate-900/80 border border-slate-800 rounded-2xl backdrop-blur-md flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1.5">
          <div className="flex items-center gap-3 flex-wrap">
            {getStatusBadge(postMortem.status)}
            {getMemoryBadge(postMortem.memory_indexing_status)}
            <span className="text-xs font-mono text-slate-400">
              Hash: {postMortem.snapshot_hash?.slice(0, 12)}...
            </span>
          </div>
          {isEditing ? (
            <input
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              className="w-full text-base font-bold bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-100 focus:outline-none focus:border-indigo-500"
            />
          ) : (
            <h2 className="text-xl font-bold text-slate-100">{postMortem.title}</h2>
          )}
        </div>

        <div className="flex items-center gap-2">
          {postMortem.status === 'draft' && (
            <>
              {isEditing ? (
                <>
                  <button
                    onClick={handleSaveDraft}
                    className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg transition"
                  >
                    Save Changes
                  </button>
                  <button
                    onClick={() => setIsEditing(false)}
                    className="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg transition"
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  onClick={() => setIsEditing(true)}
                  className="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700 transition"
                >
                  Edit Sections
                </button>
              )}
              <button
                onClick={() => setShowSignOffModal(true)}
                className="px-4 py-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-semibold rounded-lg shadow-md transition"
              >
                Sign Off & Publish
              </button>
            </>
          )}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="px-3 py-1.5 bg-slate-800/80 hover:bg-slate-800 text-slate-400 hover:text-slate-200 text-xs font-medium rounded-lg border border-slate-700 transition"
            title="Re-synthesize post-mortem from updated evidence"
          >
            {generating ? 'Regenerating...' : '🔄 Regenerate'}
          </button>
        </div>
      </div>

      {/* Main Grid: Analysis & Action Items */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Post-Mortem Narrative */}
        <div className="lg:col-span-2 space-y-4">
          {/* Executive Summary */}
          <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl space-y-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-400">1. Executive Summary</h4>
            {isEditing ? (
              <textarea
                value={editSummary}
                onChange={(e) => setEditSummary(e.target.value)}
                rows={3}
                className="w-full text-xs font-sans bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
              />
            ) : (
              <p className="text-xs text-slate-300 leading-relaxed font-sans">{postMortem.summary}</p>
            )}
          </div>

          {/* Root Cause Analysis */}
          <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl space-y-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-red-400">2. Root Cause Analysis</h4>
            {isEditing ? (
              <textarea
                value={editRootCause}
                onChange={(e) => setEditRootCause(e.target.value)}
                rows={3}
                className="w-full text-xs font-sans bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
              />
            ) : (
              <p className="text-xs text-slate-300 leading-relaxed font-sans">{postMortem.root_cause_summary}</p>
            )}
          </div>

          {/* Trigger & Impact */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl space-y-1.5">
              <h4 className="text-xs font-bold uppercase tracking-wider text-amber-400">Trigger Event</h4>
              <p className="text-xs text-slate-300 font-sans">{postMortem.trigger_event || 'Unknown'}</p>
            </div>
            <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl space-y-1.5">
              <h4 className="text-xs font-bold uppercase tracking-wider text-rose-400">Impact & Downtime</h4>
              <p className="text-xs text-slate-300 font-sans">
                {postMortem.impact_summary || `${postMortem.downtime_minutes} min estimated downtime`}
              </p>
            </div>
          </div>

          {/* Resolution & Remediation */}
          <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl space-y-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-teal-400">3. Resolution & Remediation</h4>
            {isEditing ? (
              <textarea
                value={editResolution}
                onChange={(e) => setEditResolution(e.target.value)}
                rows={2}
                className="w-full text-xs font-sans bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-slate-200 focus:outline-none focus:border-indigo-500"
              />
            ) : (
              <p className="text-xs text-slate-300 leading-relaxed font-sans">{postMortem.resolution_summary}</p>
            )}
          </div>

          {/* Lessons Learned */}
          {postMortem.lessons_learned_json && postMortem.lessons_learned_json.length > 0 && (
            <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-xl space-y-2.5">
              <h4 className="text-xs font-bold uppercase tracking-wider text-emerald-400">4. Lessons Learned</h4>
              <ul className="space-y-1.5">
                {postMortem.lessons_learned_json.map((l, i) => (
                  <li key={i} className="text-xs text-slate-300 flex items-start gap-2">
                    <span className="text-emerald-400 mt-0.5">•</span>
                    <span>{typeof l === 'object' ? l.lesson : l}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Right Column: Action Items */}
        <div className="space-y-4">
          <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-2xl space-y-4 backdrop-blur-sm">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-sm font-bold text-slate-100">Preventive Action Items</h4>
                <p className="text-[11px] text-slate-400">Track corrective engineering tasks</p>
              </div>
              <button
                onClick={() => setShowAddAction(!showAddAction)}
                className="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-lg transition"
              >
                + Add
              </button>
            </div>

            {/* Inline Action Item Creator */}
            {showAddAction && (
              <form onSubmit={handleCreateActionItem} className="p-3 bg-slate-950 border border-slate-700 rounded-xl space-y-2.5">
                <input
                  type="text"
                  placeholder="Action item title..."
                  value={actionTitle}
                  onChange={(e) => setActionTitle(e.target.value)}
                  className="w-full text-xs bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 focus:outline-none focus:border-indigo-500"
                  required
                />
                <textarea
                  placeholder="Description..."
                  value={actionDesc}
                  onChange={(e) => setActionDesc(e.target.value)}
                  rows={2}
                  className="w-full text-xs bg-slate-900 border border-slate-700 rounded-lg p-2 text-slate-200 focus:outline-none focus:border-indigo-500"
                />
                <div className="flex items-center gap-2">
                  <select
                    value={actionCategory}
                    onChange={(e) => setActionCategory(e.target.value)}
                    className="text-xs bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-slate-300"
                  >
                    <option value="code_hardening">Code Hardening</option>
                    <option value="monitoring_gap">Monitoring Gap</option>
                    <option value="architectural_debt">Architectural Debt</option>
                    <option value="runbook_improvement">Runbook Improvement</option>
                    <option value="infrastructure_resilience">Infrastructure Resilience</option>
                  </select>
                  <select
                    value={actionPriority}
                    onChange={(e) => setActionPriority(e.target.value)}
                    className="text-xs bg-slate-900 border border-slate-700 rounded-lg p-1.5 text-slate-300"
                  >
                    <option value="P0">P0 (Critical)</option>
                    <option value="P1">P1 (High)</option>
                    <option value="P2">P2 (Medium)</option>
                    <option value="P3">P3 (Low)</option>
                  </select>
                </div>
                <div className="flex justify-end gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => setShowAddAction(false)}
                    className="px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg"
                  >
                    Add Task
                  </button>
                </div>
              </form>
            )}

            {/* Action Items List */}
            <div className="space-y-2">
              {(postMortem.action_items || []).length === 0 ? (
                <p className="text-xs text-slate-500 text-center py-4">No action items recorded.</p>
              ) : (
                (postMortem.action_items || []).map((item) => (
                  <div
                    key={item.id}
                    className={`p-3 rounded-xl border transition ${
                      item.status === 'completed'
                        ? 'bg-slate-950/40 border-slate-800/80 opacity-75'
                        : 'bg-slate-900/90 border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-start gap-2.5">
                      <input
                        type="checkbox"
                        checked={item.status === 'completed'}
                        onChange={() => handleToggleActionStatus(item)}
                        className="mt-1 rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-0 cursor-pointer"
                      />
                      <div className="space-y-1 flex-1">
                        <p
                          className={`text-xs font-medium text-slate-200 ${
                            item.status === 'completed' ? 'line-through text-slate-500' : ''
                          }`}
                        >
                          {item.title}
                        </p>
                        {item.description && (
                          <p className="text-[11px] text-slate-400 leading-snug">{item.description}</p>
                        )}
                        <div className="flex items-center gap-2 pt-1">
                          <span
                            className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${
                              item.priority === 'P0'
                                ? 'bg-rose-500/20 text-rose-300'
                                : item.priority === 'P1'
                                ? 'bg-amber-500/20 text-amber-300'
                                : 'bg-slate-800 text-slate-400'
                            }`}
                          >
                            {item.priority}
                          </span>
                          <span className="text-[10px] text-slate-500 font-mono">
                            {item.category.replace('_', ' ')}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Publish Sign-Off Modal */}
      {showSignOffModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-slate-100">Sign Off & Publish Post-Mortem</h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Publishing marks this post-mortem as human-reviewed and indexes it into Sentinel&apos;s institutional Pinecone memory for semantic retrieval during future investigations.
            </p>
            <textarea
              placeholder="Optional sign-off notes or review summary..."
              value={signOffNotes}
              onChange={(e) => setSignOffNotes(e.target.value)}
              rows={3}
              className="w-full text-xs bg-slate-950 border border-slate-700 rounded-xl p-3 text-slate-200 focus:outline-none focus:border-indigo-500"
            />
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowSignOffModal(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl"
              >
                Cancel
              </button>
              <button
                onClick={handlePublish}
                disabled={publishing}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-xl shadow-lg shadow-emerald-500/25 transition disabled:opacity-50"
              >
                {publishing ? 'Publishing & Indexing...' : 'Certify & Publish'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
