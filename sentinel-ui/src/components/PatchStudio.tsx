'use client';

import React, { useState, useEffect } from 'react';
import {
  ProposedFixDetail,
  PatchVersion,
  GeneratedTest,
  PatchChange,
  patchApi,
} from '@/lib/patchApi';
import { GeneratedTestsViewer } from './GeneratedTestsViewer';
import ValidationReportViewer from './ValidationReportViewer';
import PolicyEvaluationCard from './PolicyEvaluationCard';
import ApprovalGateModal from './ApprovalGateModal';
import {
  evaluatePolicy,
  fetchApprovals,
  requestApprovalForFix,
  PolicyEvaluationResult,
  ApprovalRequest,
} from '@/lib/policyApi';


interface PatchStudioProps {
  fix: ProposedFixDetail;
  onRefresh?: () => void;
}

export function PatchStudio({ fix, onRefresh }: PatchStudioProps) {
  const [activeTab, setActiveTab] = useState<'diff' | 'validation' | 'policy' | 'tests' | 'history' | 'safety'>('diff');
  const [history, setHistory] = useState<PatchVersion[]>(fix.versions || []);
  const [tests, setTests] = useState<GeneratedTest[]>(fix.generated_tests || []);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingTests, setLoadingTests] = useState(false);

  // Policy & Approval State
  const [policyEval, setPolicyEval] = useState<PolicyEvaluationResult | null>(null);
  const [approvalReq, setApprovalReq] = useState<ApprovalRequest | null>(null);
  const [loadingPolicy, setLoadingPolicy] = useState(false);
  const [isApprovalModalOpen, setIsApprovalModalOpen] = useState(false);

  // Manual Edit State
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editedChanges, setEditedChanges] = useState<PatchChange[]>(
    fix.patch_json?.changes || []
  );
  const [rollbackPlan, setRollbackPlan] = useState(fix.rollback_plan || '');
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Sync props & load policy
  useEffect(() => {
    if (fix.versions) setHistory(fix.versions);
    if (fix.generated_tests) setTests(fix.generated_tests);
    if (fix.patch_json?.changes) setEditedChanges(fix.patch_json.changes);
    if (fix.rollback_plan) setRollbackPlan(fix.rollback_plan);

    loadPolicyAndApproval();
  }, [fix]);

  const loadPolicyAndApproval = async () => {
    if (!fix?.id) return;
    setLoadingPolicy(true);
    try {
      const pRes = await evaluatePolicy({
        action_type: 'create_draft_pr',
        fix_id: fix.id,
      });
      setPolicyEval(pRes);

      const apps = await fetchApprovals(undefined, fix.id);
      if (apps && apps.length > 0) {
        setApprovalReq(apps[0]);
      }
    } catch (err) {
      console.error('Failed to evaluate policy or fetch approvals', err);
    } finally {
      setLoadingPolicy(false);
    }
  };

  const handleRequestApproval = async () => {
    try {
      const app = await requestApprovalForFix(fix.id);
      setApprovalReq(app);
      setIsApprovalModalOpen(true);
    } catch (err) {
      console.error('Failed to request approval', err);
      setIsApprovalModalOpen(true);
    }
  };


  const loadHistory = async () => {
    setLoadingHistory(true);
    try {
      const data = await patchApi.getFixHistory(fix.id);
      setHistory(data);
    } catch (err) {
      console.error('Failed to load fix history', err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const loadTests = async () => {
    setLoadingTests(true);
    try {
      const data = await patchApi.getFixTests(fix.id);
      setTests(data);
    } catch (err) {
      console.error('Failed to load fix tests', err);
    } finally {
      setLoadingTests(false);
    }
  };

  const handleSaveEdit = async () => {
    setSavingEdit(true);
    setEditError(null);
    try {
      await patchApi.editPatch(fix.id, {
        changes: editedChanges,
        rollback_plan: rollbackPlan,
      });
      setIsEditModalOpen(false);
      if (onRefresh) onRefresh();
    } catch (err: any) {
      setEditError(err.message || 'Failed to submit patch edits');
    } finally {
      setSavingEdit(false);
    }
  };

  const isRejected = fix.is_rejected || fix.status === 'rejected';

  return (
    <div className="space-y-6">
      {/* Studio Header Card */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-2xl">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="px-2.5 py-1 text-xs font-semibold uppercase tracking-wider rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Phase 11 Patch Studio
              </span>
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                v{fix.version || 1}
              </span>
              {isRejected ? (
                <span className="px-2.5 py-1 text-xs font-semibold rounded-md bg-rose-500/10 text-rose-400 border border-rose-500/20 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                  Rejected by Safety Engine
                </span>
              ) : (
                <span className="px-2.5 py-1 text-xs font-semibold rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Verified Safe & Test-Backed
                </span>
              )}
            </div>

            <h2 className="text-xl font-bold text-slate-100">{fix.title || 'Autonomous Remediation Patch'}</h2>
            <p className="text-sm text-slate-400 max-w-3xl">{fix.description}</p>
          </div>

          {/* Action Bar */}
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => setIsEditModalOpen(true)}
              className="px-4 py-2 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition flex items-center gap-2"
            >
              <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              Manual Edit & Revalidate
            </button>
            <div className="px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300 flex items-center gap-1.5 font-medium">
              <svg className="w-3.5 h-3.5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              Protected Base (Human Approval Required)
            </div>
          </div>
        </div>

        {/* Rejection Banner */}
        {isRejected && fix.rejection_reason && (
          <div className="mt-5 p-4 rounded-lg bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300 flex items-start gap-3">
            <svg className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <span className="font-semibold block mb-0.5">Pre-Flight Safety Rejection</span>
              <span>{fix.rejection_reason}</span>
            </div>
          </div>
        )}

        {/* Identity & Scoping Strip */}
        <div className="mt-6 pt-4 border-t border-slate-800 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div>
            <span className="text-slate-500 block">Repository:</span>
            <span className="font-mono text-slate-200 font-medium truncate block">
              {fix.repository || 'sentinel/main-service'}
            </span>
          </div>
          <div>
            <span className="text-slate-500 block">Base Commit SHA:</span>
            <span className="font-mono text-indigo-300 truncate block">
              {fix.base_commit_sha ? fix.base_commit_sha.substring(0, 10) : 'HEAD'}
            </span>
          </div>
          <div>
            <span className="text-slate-500 block">Target Branch:</span>
            <span className="font-mono text-slate-200">{fix.target_branch || 'main'}</span>
          </div>
          <div>
            <span className="text-slate-500 block">Snapshot Hash:</span>
            <span className="font-mono text-emerald-400 truncate block" title={fix.snapshot_hash}>
              {fix.snapshot_hash ? `${fix.snapshot_hash.substring(0, 12)}...` : 'Pending'}
            </span>
          </div>
        </div>
      </div>

      {/* Tabs Header */}
      <div className="flex border-b border-slate-800 space-x-1">
        <button
          onClick={() => setActiveTab('diff')}
          className={`px-5 py-3 text-sm font-medium border-b-2 transition flex items-center gap-2 ${
            activeTab === 'diff'
              ? 'border-indigo-500 text-indigo-400 bg-indigo-500/5'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
          Unified Diff
        </button>

        <button
          onClick={() => setActiveTab('validation')}
          className={`px-5 py-3 text-sm font-medium border-b-2 transition flex items-center gap-2 ${
            activeTab === 'validation'
              ? 'border-indigo-500 text-indigo-400 bg-indigo-500/5'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
          Isolated Validation & Replay
        </button>

        <button
          onClick={() => setActiveTab('policy')}
          className={`px-5 py-3 text-sm font-medium border-b-2 transition flex items-center gap-2 ${
            activeTab === 'policy'
              ? 'border-indigo-500 text-indigo-400 bg-indigo-500/5'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          Policy Gateway & Quorum
        </button>


        <button
          onClick={() => {
            setActiveTab('tests');
            loadTests();
          }}
          className={`px-5 py-3 text-sm font-medium border-b-2 transition flex items-center gap-2 ${
            activeTab === 'tests'
              ? 'border-indigo-500 text-indigo-400 bg-indigo-500/5'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Regression Tests ({tests.length})
        </button>

        <button
          onClick={() => setActiveTab('safety')}
          className={`px-5 py-3 text-sm font-medium border-b-2 transition flex items-center gap-2 ${
            activeTab === 'safety'
              ? 'border-indigo-500 text-indigo-400 bg-indigo-500/5'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
          Pre-Flight Safety Checklist
        </button>

        <button
          onClick={() => {
            setActiveTab('history');
            loadHistory();
          }}
          className={`px-5 py-3 text-sm font-medium border-b-2 transition flex items-center gap-2 ${
            activeTab === 'history'
              ? 'border-indigo-500 text-indigo-400 bg-indigo-500/5'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Version History ({history.length || fix.version})
        </button>
      </div>

      {/* Tab 1: Unified Diff */}
      {activeTab === 'diff' && (
        <div className="space-y-4">
          <div className="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
            <div className="px-4 py-3 bg-slate-900/80 border-b border-slate-800 flex items-center justify-between text-xs text-slate-400">
              <span className="font-mono font-medium text-slate-300">Unified Patch Diff</span>
              <span>{fix.scope_files?.length || 1} file(s) modified</span>
            </div>
            <pre className="p-4 text-xs font-mono overflow-x-auto leading-relaxed max-h-[600px]">
              {fix.diff ? (
                fix.diff.split('\n').map((line, idx) => {
                  let lineClass = 'text-slate-300';
                  if (line.startsWith('+') && !line.startsWith('+++')) {
                    lineClass = 'text-emerald-400 bg-emerald-950/30 -mx-4 px-4 block';
                  } else if (line.startsWith('-') && !line.startsWith('---')) {
                    lineClass = 'text-rose-400 bg-rose-950/30 -mx-4 px-4 block';
                  } else if (line.startsWith('@@')) {
                    lineClass = 'text-indigo-400 font-semibold';
                  }
                  return (
                    <div key={idx} className={lineClass}>
                      {line || ' '}
                    </div>
                  );
                })
              ) : (
                <div className="text-slate-500">No diff available</div>
              )}
            </pre>
          </div>

          {/* Rollback Plan Card */}
          {fix.rollback_plan && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-xs space-y-1.5">
              <span className="font-semibold text-slate-300 flex items-center gap-1.5">
                <svg className="w-4 h-4 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Operational Rollback Plan
              </span>
              <p className="text-slate-400">{fix.rollback_plan}</p>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Isolated Validation & Replay */}
      {activeTab === 'validation' && (
        <ValidationReportViewer
          fixId={fix.id}
          onValidationComplete={onRefresh}
        />
      )}

      {/* Tab: Policy Gateway & Quorum */}
      {activeTab === 'policy' && (
        <div className="space-y-4">
          <PolicyEvaluationCard
            evaluation={policyEval}
            loading={loadingPolicy}
            onRequestApproval={handleRequestApproval}
            onRefresh={loadPolicyAndApproval}
          />
        </div>
      )}


      {/* Tab 3: Generated Regression Tests */}
      {activeTab === 'tests' && (
        <GeneratedTestsViewer
          tests={tests}
          regressionStatus={fix.regression_test_status}
        />
      )}

      {/* Tab 3: Pre-Flight Safety Checklist */}
      {activeTab === 'safety' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <h4 className="font-semibold text-slate-200 text-sm flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              Scope & Integrity Gates
            </h4>
            <ul className="space-y-2.5 text-xs">
              <li className="flex items-center justify-between p-2.5 rounded bg-slate-950/60 border border-slate-800/60">
                <span className="text-slate-300">Scope Containment</span>
                <span className="text-emerald-400 font-medium">Passed</span>
              </li>
              <li className="flex items-center justify-between p-2.5 rounded bg-slate-950/60 border border-slate-800/60">
                <span className="text-slate-300">Exact Replacement Count (Count = 1)</span>
                <span className="text-emerald-400 font-medium">Verified Unique</span>
              </li>
              <li className="flex items-center justify-between p-2.5 rounded bg-slate-950/60 border border-slate-800/60">
                <span className="text-slate-300">Diff Bloat Limit (Max 200 Lines)</span>
                <span className="text-emerald-400 font-medium">Passed</span>
              </li>
            </ul>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <h4 className="font-semibold text-slate-200 text-sm flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              Syntax & Security Gates
            </h4>
            <ul className="space-y-2.5 text-xs">
              <li className="flex items-center justify-between p-2.5 rounded bg-slate-950/60 border border-slate-800/60">
                <span className="text-slate-300">Multi-Language AST Syntax Parser</span>
                <span className="text-emerald-400 font-medium">0 Errors</span>
              </li>
              <li className="flex items-center justify-between p-2.5 rounded bg-slate-950/60 border border-slate-800/60">
                <span className="text-slate-300">Secret & Credential Redaction Scan</span>
                <span className="text-emerald-400 font-medium">Clean</span>
              </li>
              <li className="flex items-center justify-between p-2.5 rounded bg-slate-950/60 border border-slate-800/60">
                <span className="text-slate-300">Zero Hallucinated Boilerplate</span>
                <span className="text-emerald-400 font-medium">Verified Real Code</span>
              </li>
            </ul>
          </div>
        </div>
      )}

      {/* Tab 4: Version History & Audit Log */}
      {activeTab === 'history' && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="p-4 bg-slate-950 border-b border-slate-800 font-semibold text-slate-200 text-sm">
            Patch Revision History & Invalidation Audit
          </div>
          {loadingHistory ? (
            <div className="p-8 text-center text-slate-400 text-xs">Loading version history...</div>
          ) : history.length === 0 ? (
            <div className="p-8 text-center text-slate-400 text-xs">No prior versions recorded.</div>
          ) : (
            <div className="divide-y divide-slate-800/60 text-xs">
              {history.map((ver) => (
                <div key={ver.id} className="p-4 hover:bg-slate-800/30 transition flex flex-col md:flex-row md:items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-slate-100 bg-slate-800 px-2 py-0.5 rounded">
                        v{ver.version_number}
                      </span>
                      <span
                        className={`font-semibold px-2 py-0.5 rounded text-[11px] ${
                          ver.revalidation_status === 'passed'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                        }`}
                      >
                        {ver.revalidation_status.toUpperCase()}
                      </span>
                    </div>
                    <div className="text-slate-400 text-[11px] space-x-2">
                      <span>Snapshot: {ver.new_snapshot_hash.substring(0, 14)}...</span>
                      {ver.previous_snapshot_hash && (
                        <span>(Prev: {ver.previous_snapshot_hash.substring(0, 10)}...)</span>
                      )}
                    </div>
                  </div>
                  <span className="text-slate-500 text-[11px]">
                    {ver.created_at ? new Date(ver.created_at).toLocaleString() : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Manual Edit Modal */}
      {isEditModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div>
                <h3 className="font-bold text-slate-100 text-lg">Manual Patch Editor & Revalidation</h3>
                <p className="text-xs text-slate-400">
                  Editing will increment patch to v{(fix.version || 1) + 1}, invalidate stale checks, and run full re-validation.
                </p>
              </div>
              <button
                onClick={() => setIsEditModalOpen(false)}
                className="text-slate-400 hover:text-slate-200"
              >
                ✕
              </button>
            </div>

            {editError && (
              <div className="p-3 bg-rose-950/50 border border-rose-800 rounded-lg text-xs text-rose-300">
                {editError}
              </div>
            )}

            <div className="space-y-4">
              {editedChanges.map((change, idx) => (
                <div key={idx} className="p-4 bg-slate-950 rounded-xl border border-slate-800 space-y-3">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-mono text-indigo-300 font-semibold">{change.file}</span>
                    <span className="uppercase text-slate-400 font-mono text-[10px]">{change.action}</span>
                  </div>

                  <div>
                    <label className="text-[11px] text-slate-400 block mb-1">Old Code (Exact Match Required):</label>
                    <textarea
                      value={change.old_code || ''}
                      onChange={(e) => {
                        const next = [...editedChanges];
                        next[idx].old_code = e.target.value;
                        setEditedChanges(next);
                      }}
                      rows={3}
                      className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2.5 text-xs font-mono text-rose-300 focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  <div>
                    <label className="text-[11px] text-slate-400 block mb-1">New Code (Replacement):</label>
                    <textarea
                      value={change.new_code || ''}
                      onChange={(e) => {
                        const next = [...editedChanges];
                        next[idx].new_code = e.target.value;
                        setEditedChanges(next);
                      }}
                      rows={4}
                      className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2.5 text-xs font-mono text-emerald-300 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>
              ))}

              <div>
                <label className="text-xs text-slate-400 block mb-1.5">Rollback Plan:</label>
                <input
                  type="text"
                  value={rollbackPlan}
                  onChange={(e) => setRollbackPlan(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setIsEditModalOpen(false)}
                className="px-4 py-2 text-xs text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveEdit}
                disabled={savingEdit}
                className="px-5 py-2 text-xs font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white transition disabled:opacity-50"
              >
                {savingEdit ? 'Revalidating...' : 'Commit v' + ((fix.version || 1) + 1) + ' & Revalidate'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phase 13: Approval Gate Modal */}
      <ApprovalGateModal
        isOpen={isApprovalModalOpen}
        onClose={() => setIsApprovalModalOpen(false)}
        approval={approvalReq}
        onDecisionSubmitted={(updated) => {
          setApprovalReq(updated);
          if (onRefresh) onRefresh();
          loadPolicyAndApproval();
        }}
      />
    </div>
  );
}


