'use client';

import React, { useState, useEffect } from 'react';
import {
  ValidationReport,
  ValidationCheckRun,
  validateFixIsolated,
  getValidationReport,
  replayScenario,
} from '@/lib/validationApi';

interface ValidationReportViewerProps {
  fixId: string;
  onValidationComplete?: (report: ValidationReport) => void;
}

const PIPELINE_STAGES = [
  '1. Base SHA Verification',
  '2. Sandbox Provisioning',
  '3. AST Syntax Check',
  '4. Pre-Patch Reproduction',
  '5. Strict Patch Application',
  '6. Post-Patch Regression',
  '7. Offline Scenario Replay',
  '8. Report Aggregation',
];

export default function ValidationReportViewer({ fixId, onValidationComplete }: ValidationReportViewerProps) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [expandedCheck, setExpandedCheck] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replayResult, setReplayResult] = useState<any | null>(null);

  useEffect(() => {
    if (fixId) {
      loadReport();
    }
  }, [fixId]);

  const loadReport = async () => {
    try {
      setError(null);
      const data = await getValidationReport(fixId);
      setReport(data);
    } catch {
      // It's normal to not have a report yet before running validation
    }
  };

  const handleRunValidation = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await validateFixIsolated(fixId);
      setReport(data);
      if (onValidationComplete) onValidationComplete(data);
    } catch (err: any) {
      setError(err.message || 'Validation pipeline execution failed');
    } finally {
      setLoading(false);
    }
  };

  const handleReplayScenario = async () => {
    setReplaying(true);
    setError(null);
    try {
      const res = await replayScenario(fixId);
      setReplayResult(res);
    } catch (err: any) {
      setError(err.message || 'Scenario replay failed');
    } finally {
      setReplaying(false);
    }
  };

  const matrix = report?.summary_report?.matrix || {
    compilation: report?.compilation_status || 'pending',
    tests: report?.tests_status || 'pending',
    original_failure_reproduced: report?.original_failure_reproduced || 'n/a',
    failure_absent_after_patch: report?.failure_absent_after_patch || 'n/a',
    scenario_replay: report?.scenario_replay_status || 'n/a',
    production_outcome: report?.production_outcome || 'unknown until deployed',
  };

  const getStatusBadge = (val: string) => {
    const v = (val || '').toLowerCase();
    if (v === 'passed' || v === 'yes') {
      return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">PASSED</span>;
    }
    if (v === 'failed' || v === 'no') {
      return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">FAILED</span>;
    }
    if (v.includes('unknown') || v === 'n/a') {
      return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">{val.toUpperCase()}</span>;
    }
    return <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">{val.toUpperCase()}</span>;
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-xl font-bold text-slate-100 flex items-center gap-2">
              🛡️ Isolated Validation & Replay Studio
            </span>
            {report && (
              <span
                className={`px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider ${
                  report.overall_status === 'passed'
                    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                    : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                }`}
              >
                {report.overall_status}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-1">
            8-Stage isolated sandbox execution against exact base commit with offline scenario replay.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleReplayScenario}
            disabled={replaying || loading}
            className="px-3.5 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg border border-slate-700 transition disabled:opacity-50 flex items-center gap-1.5"
          >
            {replaying ? '⏳ Replaying...' : '🔄 Replay Scenario'}
          </button>
          <button
            onClick={handleRunValidation}
            disabled={loading}
            className="px-4 py-2 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg shadow-lg shadow-indigo-500/20 transition disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Running 8-Stage Pipeline...
              </>
            ) : (
              '▶ Run Isolated Validation'
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
          <span>⚠️</span> {error}
        </div>
      )}

      {/* 8-Stage Pipeline Tracker */}
      <div className="bg-slate-950/60 rounded-lg border border-slate-800/80 p-4">
        <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
          8-Stage Validation Pipeline Flow
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {PIPELINE_STAGES.map((stage, idx) => {
            const isComplete = Boolean(report);
            return (
              <div
                key={idx}
                className={`p-2.5 rounded border text-xs flex items-center justify-between ${
                  isComplete
                    ? 'bg-slate-900/80 border-slate-800 text-slate-300'
                    : 'bg-slate-950 border-slate-900 text-slate-500'
                }`}
              >
                <span className="truncate">{stage}</span>
                {isComplete && <span className="text-emerald-400 font-bold text-xs">✓</span>}
              </div>
            );
          })}
        </div>
      </div>

      {/* 5-Point Outcome Badge Matrix */}
      <div>
        <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
          Incident Validation Outcome Matrix
        </h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          <div className="p-3.5 rounded-lg bg-slate-950/80 border border-slate-800">
            <div className="text-[11px] text-slate-400 uppercase font-medium">Compilation</div>
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-200 capitalize">{matrix.compilation}</span>
              {getStatusBadge(matrix.compilation)}
            </div>
          </div>

          <div className="p-3.5 rounded-lg bg-slate-950/80 border border-slate-800">
            <div className="text-[11px] text-slate-400 uppercase font-medium">Regression Tests</div>
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-200 capitalize">{matrix.tests}</span>
              {getStatusBadge(matrix.tests)}
            </div>
          </div>

          <div className="p-3.5 rounded-lg bg-slate-950/80 border border-slate-800">
            <div className="text-[11px] text-slate-400 uppercase font-medium">Original Defect Reproduced</div>
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-200 capitalize">{matrix.original_failure_reproduced}</span>
              {getStatusBadge(matrix.original_failure_reproduced)}
            </div>
          </div>

          <div className="p-3.5 rounded-lg bg-slate-950/80 border border-slate-800">
            <div className="text-[11px] text-slate-400 uppercase font-medium">Defect Absent Post-Patch</div>
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-200 capitalize">{matrix.failure_absent_after_patch}</span>
              {getStatusBadge(matrix.failure_absent_after_patch)}
            </div>
          </div>

          <div className="p-3.5 rounded-lg bg-slate-950/80 border border-slate-800 relative group">
            <div className="text-[11px] text-amber-400/90 uppercase font-medium flex items-center gap-1">
              <span>🔒 Production Outcome</span>
            </div>
            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-400 truncate">Unknown until deployed</span>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30">
                LOCKED
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Replay Scenario Output */}
      {replayResult && (
        <div className="p-4 rounded-lg bg-slate-950 border border-indigo-500/30">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-indigo-300">
              ⚡ Sanitized Scenario Replay Output (Mock Harness)
            </span>
            <span className="text-xs text-slate-400">Duration: {replayResult.duration_ms}ms</span>
          </div>
          <pre className="text-xs bg-slate-900/90 text-slate-300 p-3 rounded overflow-x-auto font-mono max-h-40">
            {replayResult.stdout || replayResult.stderr || 'Replay executed with zero errors.'}
          </pre>
        </div>
      )}

      {/* Granular Check Runs Accordion */}
      {report && report.check_runs && report.check_runs.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
            Execution Check Steps ({report.passed_checks}/{report.total_checks} Passed)
          </h4>
          <div className="space-y-2">
            {report.check_runs.map((cr: ValidationCheckRun) => {
              const isExpanded = expandedCheck === cr.id;
              return (
                <div
                  key={cr.id}
                  className="rounded-lg bg-slate-950/80 border border-slate-800 overflow-hidden transition"
                >
                  <div
                    onClick={() => setExpandedCheck(isExpanded ? null : cr.id)}
                    className="p-3.5 flex items-center justify-between cursor-pointer hover:bg-slate-800/40"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-semibold text-slate-200">{cr.name}</span>
                      <span className="text-[11px] text-slate-500 font-mono">[{cr.check_type}]</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-slate-400 font-mono">{cr.duration_ms}ms</span>
                      {getStatusBadge(cr.status)}
                      <span className="text-slate-500 text-xs">{isExpanded ? '▲' : '▼'}</span>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="p-4 bg-slate-950 border-t border-slate-800/80 space-y-3">
                      {cr.command && (
                        <div>
                          <span className="text-[10px] text-slate-500 uppercase font-semibold">Command</span>
                          <p className="text-xs text-indigo-400 font-mono mt-0.5">
                            {Array.isArray(cr.command) ? cr.command.join(' ') : String(cr.command)}
                          </p>
                        </div>
                      )}
                      <div>
                        <span className="text-[10px] text-slate-500 uppercase font-semibold">Console Output (Redacted)</span>
                        <pre className="mt-1 text-xs bg-slate-900 text-slate-300 p-3 rounded font-mono overflow-x-auto max-h-60 whitespace-pre-wrap">
                          {cr.stdout || cr.stderr || 'No stdout/stderr captured.'}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
