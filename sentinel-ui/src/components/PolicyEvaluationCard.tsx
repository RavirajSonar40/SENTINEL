'use client';

import React, { useState } from 'react';
import { PolicyEvaluationResult, PolicyStepCheck } from '@/lib/policyApi';

interface PolicyEvaluationCardProps {
  evaluation: PolicyEvaluationResult | null;
  loading?: boolean;
  onRequestApproval?: () => void;
  onRefresh?: () => void;
}

export default function PolicyEvaluationCard({
  evaluation,
  loading = false,
  onRequestApproval,
  onRefresh,
}: PolicyEvaluationCardProps) {
  const [expanded, setExpanded] = useState(false);

  if (loading) {
    return (
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 backdrop-blur animate-pulse">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 bg-indigo-500/20 rounded-lg" />
          <div className="space-y-2 flex-1">
            <div className="h-4 bg-slate-800 rounded w-1/3" />
            <div className="h-3 bg-slate-800/60 rounded w-1/2" />
          </div>
        </div>
      </div>
    );
  }

  if (!evaluation) {
    return null;
  }

  const getDecisionBadge = (decision: string) => {
    switch (decision) {
      case 'allow':
        return {
          bg: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
          label: 'Allowed (Automated)',
        };
      case 'block':
        return {
          bg: 'bg-rose-500/10 border-rose-500/30 text-rose-400',
          label: 'Blocked by Policy',
        };
      case 'multi_approval':
        return {
          bg: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
          label: `Multi-Approval Required (${evaluation.required_approvals_count} approvers)`,
        };
      case 'security_approval':
        return {
          bg: 'bg-purple-500/10 border-purple-500/30 text-purple-400',
          label: 'Security Officer Approval Required',
        };
      case 'require_human':
      default:
        return {
          bg: 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400',
          label: 'Human Operator Approval Required',
        };
    }
  };

  const getRiskBadge = (risk: string) => {
    switch (risk) {
      case 'critical':
        return 'bg-rose-950/60 border-rose-600/40 text-rose-300';
      case 'high':
        return 'bg-amber-950/60 border-amber-600/40 text-amber-300';
      case 'medium':
        return 'bg-yellow-950/60 border-yellow-600/40 text-yellow-300';
      case 'low':
      default:
        return 'bg-emerald-950/60 border-emerald-600/40 text-emerald-300';
    }
  };

  const badge = getDecisionBadge(evaluation.decision);
  const passedSteps = evaluation.steps.filter((s) => s.status === 'passed').length;
  const totalSteps = evaluation.steps.length;

  return (
    <div className="bg-gradient-to-b from-slate-900/90 to-slate-950/90 border border-slate-800/80 rounded-xl p-5 shadow-2xl backdrop-blur-md transition-all">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/60 pb-4">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 shadow-inner">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h3 className="text-base font-semibold text-slate-100 tracking-wide">
                Policy Gateway Verification
              </h3>
              <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider border ${getRiskBadge(evaluation.risk_level)}`}>
                {evaluation.risk_level} Risk
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Deterministic 9-step safety evaluation for <span className="font-mono text-slate-300">{evaluation.action_type}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          <div className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-medium ${badge.bg}`}>
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
            <span>{badge.label}</span>
          </div>

          {onRequestApproval && evaluation.requires_approval && (
            <button
              onClick={onRequestApproval}
              className="px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-lg shadow-indigo-500/20 transition-all flex items-center space-x-1.5"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              <span>Review & Approve</span>
            </button>
          )}
        </div>
      </div>

      {/* Summary Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 my-4">
        <div className="bg-slate-900/50 border border-slate-800/60 rounded-lg p-3">
          <div className="text-xs text-slate-400 font-medium">Policy Checks</div>
          <div className="text-sm font-semibold text-slate-200 mt-0.5">
            {passedSteps} / {totalSteps} Passed
          </div>
        </div>
        <div className="bg-slate-900/50 border border-slate-800/60 rounded-lg p-3">
          <div className="text-xs text-slate-400 font-medium">Quorum Requirement</div>
          <div className="text-sm font-semibold text-indigo-300 mt-0.5">
            {evaluation.required_approvals_count} Approver{evaluation.required_approvals_count > 1 ? 's' : ''}
          </div>
        </div>
        <div className="bg-slate-900/50 border border-slate-800/60 rounded-lg p-3">
          <div className="text-xs text-slate-400 font-medium">Authorized Roles</div>
          <div className="text-sm font-semibold text-slate-200 mt-0.5 truncate">
            {evaluation.required_roles.join(', ') || 'operator'}
          </div>
        </div>
        <div className="bg-slate-900/50 border border-slate-800/60 rounded-lg p-3">
          <div className="text-xs text-slate-400 font-medium">Matched Gate</div>
          <div className="text-sm font-semibold text-cyan-300 mt-0.5 truncate">
            {evaluation.matched_rule || 'Standard Gate'}
          </div>
        </div>
      </div>

      {/* Blocked Reasons Alert */}
      {evaluation.reasons && evaluation.reasons.length > 0 && (
        <div className="bg-rose-950/40 border border-rose-800/50 rounded-lg p-3.5 mb-4 text-xs text-rose-300 space-y-1">
          <div className="font-semibold flex items-center space-x-1.5 text-rose-200">
            <svg className="w-4 h-4 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>Policy Violations / Blockers Detected</span>
          </div>
          <ul className="list-disc list-inside space-y-0.5 pl-1">
            {evaluation.reasons.map((r, idx) => (
              <li key={idx}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Expandable 9-Step Details */}
      <div className="mt-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between text-xs font-semibold text-slate-400 hover:text-slate-200 py-1.5 transition-colors"
        >
          <span>9-Step Safety Pipeline Breakdown</span>
          <svg className={`w-4 h-4 transform transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {expanded && (
          <div className="mt-3 space-y-2 border-t border-slate-800/60 pt-3">
            {evaluation.steps.map((step) => {
              const isPassed = step.status === 'passed';
              const isWarning = step.status === 'warning';
              return (
                <div
                  key={step.step_number}
                  className={`flex items-start justify-between p-2.5 rounded-lg border text-xs ${
                    isPassed
                      ? 'bg-slate-900/40 border-slate-800/50 text-slate-300'
                      : isWarning
                      ? 'bg-amber-950/20 border-amber-800/40 text-amber-300'
                      : 'bg-rose-950/20 border-rose-800/40 text-rose-300'
                  }`}
                >
                  <div className="flex items-start space-x-2.5 flex-1">
                    {isPassed ? (
                      <svg className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : isWarning ? (
                      <svg className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                      </svg>
                    ) : (
                      <svg className="w-4 h-4 text-rose-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    )}
                    <div>
                      <div className="font-semibold text-slate-200">
                        Step {step.step_number}: {step.name}
                      </div>
                      <div className="text-slate-400 mt-0.5">{step.message}</div>
                    </div>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
                      isPassed
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : isWarning
                        ? 'bg-amber-500/10 text-amber-400'
                        : 'bg-rose-500/10 text-rose-400'
                    }`}
                  >
                    {step.status}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
