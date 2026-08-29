'use client';

import React, { useState } from 'react';
import { ApprovalRequest, submitApprovalDecision } from '@/lib/policyApi';

interface ApprovalGateModalProps {
  isOpen: boolean;
  onClose: () => void;
  approval: ApprovalRequest | null;
  onDecisionSubmitted?: (updated: ApprovalRequest) => void;
}

export default function ApprovalGateModal({
  isOpen,
  onClose,
  approval,
  onDecisionSubmitted,
}: ApprovalGateModalProps) {
  const [decisionNotes, setDecisionNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen || !approval) return null;

  const handleDecision = async (decisionType: 'approved' | 'rejected' | 'changes_requested') => {
    try {
      setSubmitting(true);
      setErrorMsg(null);
      const updated = await submitApprovalDecision(approval.id, decisionType, decisionNotes);
      if (onDecisionSubmitted) {
        onDecisionSubmitted(updated);
      }
      onClose();
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to submit approval decision');
    } finally {
      setSubmitting(false);
    }
  };

  const checklist = approval.compliance_checklist;
  const isApproved = approval.status === 'approved';
  const isPending = approval.status === 'pending';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md animate-fadeIn">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-2xl w-full shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                Human Approval Gate
              </h2>
              <p className="text-xs text-slate-400">
                Patch Version {approval.patch_version} • Risk Tier: <span className="font-semibold uppercase text-slate-200">{approval.risk_level}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-5 overflow-y-auto flex-1">
          {errorMsg && (
            <div className="p-3 bg-rose-950/40 border border-rose-800/60 rounded-xl text-xs text-rose-300">
              {errorMsg}
            </div>
          )}

          {/* Quorum Tracker */}
          <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center space-x-2 text-xs font-semibold text-slate-300">
                <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                </svg>
                <span>Multi-Approver Quorum Progress</span>
              </div>
              <span className="text-xs font-mono font-semibold text-indigo-400">
                {approval.approvals_received} of {approval.required_approvals} Required
              </span>
            </div>
            <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${
                  isApproved ? 'bg-emerald-500' : 'bg-gradient-to-r from-cyan-500 to-indigo-500'
                }`}
                style={{
                  width: `${Math.min(100, (approval.approvals_received / Math.max(1, approval.required_approvals)) * 100)}%`,
                }}
              />
            </div>
          </div>

          {/* Compliance Checklist */}
          {checklist && (
            <div className="space-y-2">
              <div className="flex items-center space-x-2 text-xs font-semibold text-slate-300">
                <svg className="w-4 h-4 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                <span>Automated Compliance Verification</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div className="flex items-center space-x-2 p-2.5 rounded-lg bg-slate-950/40 border border-slate-800 text-xs">
                  {checklist.scope_contained ? (
                    <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-rose-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  )}
                  <span className="text-slate-300">Scope Contained ({checklist.details?.files_count || 1} files)</span>
                </div>
                <div className="flex items-center space-x-2 p-2.5 rounded-lg bg-slate-950/40 border border-slate-800 text-xs">
                  {checklist.ast_syntax_valid ? (
                    <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-rose-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  )}
                  <span className="text-slate-300">AST Syntax Validated</span>
                </div>
                <div className="flex items-center space-x-2 p-2.5 rounded-lg bg-slate-950/40 border border-slate-800 text-xs">
                  {checklist.secrets_clean ? (
                    <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-rose-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  )}
                  <span className="text-slate-300">Secrets Clean (No Keys Detected)</span>
                </div>
                <div className="flex items-center space-x-2 p-2.5 rounded-lg bg-slate-950/40 border border-slate-800 text-xs">
                  {checklist.base_sha_verified ? (
                    <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-rose-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  )}
                  <span className="text-slate-300">Exact Git Base SHA Verified</span>
                </div>
                <div className="flex items-center space-x-2 p-2.5 rounded-lg bg-slate-950/40 border border-slate-800 text-xs">
                  {checklist.pre_patch_reproduced ? (
                    <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                  )}
                  <span className="text-slate-300">Pre-Patch Reproduction Verified</span>
                </div>
                <div className="flex items-center space-x-2 p-2.5 rounded-lg bg-slate-950/40 border border-slate-800 text-xs">
                  {checklist.post_patch_regressions_passed ? (
                    <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                  )}
                  <span className="text-slate-300">Post-Patch Regressions Passed</span>
                </div>
              </div>
            </div>
          )}

          {/* Decision History */}
          {approval.decisions && approval.decisions.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-slate-300">Recorded Operator Decisions</div>
              <div className="space-y-1.5">
                {approval.decisions.map((d) => (
                  <div
                    key={d.id}
                    className="flex items-center justify-between p-2.5 rounded-lg bg-slate-950/40 border border-slate-800/80 text-xs"
                  >
                    <div>
                      <span className="font-semibold text-slate-200">{d.approver_name || 'Operator'}</span>
                      <span className="text-slate-400 ml-2">({d.role || 'operator'})</span>
                      {d.notes && <p className="text-slate-400 text-[11px] mt-0.5">{d.notes}</p>}
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
                        d.decision === 'approved'
                          ? 'bg-emerald-500/10 text-emerald-400'
                          : d.decision === 'rejected'
                          ? 'bg-rose-500/10 text-rose-400'
                          : 'bg-amber-500/10 text-amber-400'
                      }`}
                    >
                      {d.decision}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Review Notes Input */}
          {isPending && (
            <div className="space-y-2">
              <label className="text-xs font-semibold text-slate-300 flex items-center space-x-1.5">
                <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <span>Reviewer Decision Rationale / Comments</span>
              </label>
              <textarea
                value={decisionNotes}
                onChange={(e) => setDecisionNotes(e.target.value)}
                placeholder="Add audit notes, verification feedback, or required code modifications..."
                rows={3}
                className="w-full bg-slate-950/80 border border-slate-800 rounded-xl p-3 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500/80 focus:ring-1 focus:ring-indigo-500/50 transition-all resize-none"
              />
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors"
          >
            Cancel
          </button>

          {isPending ? (
            <div className="flex items-center space-x-2">
              <button
                disabled={submitting}
                onClick={() => handleDecision('rejected')}
                className="px-4 py-2 rounded-xl bg-rose-600/20 border border-rose-500/30 text-rose-300 hover:bg-rose-600/30 text-xs font-semibold transition-all disabled:opacity-50"
              >
                Reject Fix
              </button>
              <button
                disabled={submitting}
                onClick={() => handleDecision('changes_requested')}
                className="px-4 py-2 rounded-xl bg-amber-600/20 border border-amber-500/30 text-amber-300 hover:bg-amber-600/30 text-xs font-semibold transition-all disabled:opacity-50"
              >
                Request Changes
              </button>
              <button
                disabled={submitting}
                onClick={() => handleDecision('approved')}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white text-xs font-semibold shadow-lg shadow-emerald-500/20 transition-all flex items-center space-x-1.5 disabled:opacity-50"
              >
                {submitting ? (
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                )}
                <span>Approve Fix</span>
              </button>
            </div>
          ) : (
            <div className="text-xs font-semibold text-slate-400">
              Approval Status: <span className="uppercase text-slate-200">{approval.status}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
