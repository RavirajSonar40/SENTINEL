'use client';

import React, { useState } from 'react';
import { GeneratedTest } from '@/lib/patchApi';

interface GeneratedTestsViewerProps {
  tests: GeneratedTest[];
  regressionStatus?: string;
}

export function GeneratedTestsViewer({ tests, regressionStatus }: GeneratedTestsViewerProps) {
  const [selectedTestIndex, setSelectedTestIndex] = useState(0);
  const [copied, setCopied] = useState(false);

  if (!tests || tests.length === 0) {
    return (
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6 text-center text-slate-400">
        <p className="text-sm">No generated tests recorded for this remediation patch.</p>
      </div>
    );
  }

  const activeTest = tests[selectedTestIndex] || tests[0];

  const handleCopyCode = () => {
    if (activeTest?.test_code) {
      navigator.clipboard.writeText(activeTest.test_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
      {/* Header */}
      <div className="border-b border-slate-800 bg-slate-950/60 p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
          <h3 className="font-semibold text-slate-100 text-base">Generated Remediation Tests</h3>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-medium">
            {tests.length} {tests.length === 1 ? 'Suite' : 'Suites'}
          </span>
        </div>

        {/* Two-Phase Regression Overall Status */}
        {regressionStatus && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Regression Gate:</span>
            {regressionStatus === 'reproduced_and_fixed' ? (
              <span className="text-xs px-2.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-medium flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Reproduced & Fixed
              </span>
            ) : regressionStatus === 'failed_pre_check' ? (
              <span className="text-xs px-2.5 py-0.5 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/30 font-medium">
                Failed Pre-Check (Didn't Fail on Base)
              </span>
            ) : regressionStatus === 'failed_post_check' ? (
              <span className="text-xs px-2.5 py-0.5 rounded-md bg-rose-500/10 text-rose-400 border border-rose-500/30 font-medium">
                Failed Post-Check (Broken After Patch)
              </span>
            ) : (
              <span className="text-xs px-2.5 py-0.5 rounded-md bg-slate-800 text-slate-300 font-medium capitalize">
                {regressionStatus.replace(/_/g, ' ')}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800 bg-slate-950/30 overflow-x-auto">
        {tests.map((t, idx) => (
          <button
            key={t.id || idx}
            onClick={() => setSelectedTestIndex(idx)}
            className={`px-4 py-3 text-xs font-mono border-b-2 transition-all flex items-center gap-2 whitespace-nowrap ${
              selectedTestIndex === idx
                ? 'border-indigo-500 text-indigo-300 bg-indigo-500/5'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
            }`}
          >
            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-300 uppercase">
              {t.framework || 'pytest'}
            </span>
            <span>{t.file_path}</span>
          </button>
        ))}
      </div>

      {/* Active Test Card */}
      {activeTest && (
        <div className="p-5 space-y-4">
          {/* Metadata Row */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 bg-slate-950/40 p-3.5 rounded-lg border border-slate-800/60 text-xs">
            <div>
              <span className="text-slate-400 block mb-1">Target Symbol:</span>
              <span className="font-mono text-indigo-300 font-medium">
                {activeTest.target_symbol || 'N/A'}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block mb-1">Test Type:</span>
              <span className="uppercase font-mono text-slate-200">
                {activeTest.test_type}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block mb-1">Base SHA Check:</span>
              <span
                className={`font-semibold ${
                  activeTest.pre_patch_result === 'failed'
                    ? 'text-emerald-400'
                    : 'text-amber-400'
                }`}
              >
                {activeTest.pre_patch_result === 'failed' ? 'FAILED (Expected)' : activeTest.pre_patch_result || 'N/A'}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block mb-1">Patched SHA Check:</span>
              <span
                className={`font-semibold ${
                  activeTest.post_patch_result === 'passed'
                    ? 'text-emerald-400'
                    : 'text-rose-400'
                }`}
              >
                {activeTest.post_patch_result === 'passed' ? 'PASSED (Verified)' : activeTest.post_patch_result || 'N/A'}
              </span>
            </div>
          </div>

          {/* Test Code Box */}
          <div className="relative">
            <div className="flex items-center justify-between bg-slate-950 border border-b-0 border-slate-800 rounded-t-lg px-4 py-2 text-xs text-slate-400">
              <span className="font-mono">{activeTest.file_path}</span>
              <button
                onClick={handleCopyCode}
                className="hover:text-slate-100 text-xs flex items-center gap-1 transition-colors px-2 py-0.5 rounded bg-slate-800/60 border border-slate-700/50"
              >
                {copied ? '✓ Copied' : 'Copy Code'}
              </button>
            </div>
            <pre className="p-4 bg-slate-950 border border-slate-800 rounded-b-lg text-xs font-mono text-emerald-300 overflow-x-auto max-h-96 leading-relaxed">
              <code>{activeTest.test_code}</code>
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
