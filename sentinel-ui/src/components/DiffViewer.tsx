'use client';

import React, { useState } from 'react';

interface DiffViewerProps {
  diff?: string | null;
  patch?: {
    diffs?: string[];
    changes?: Array<{
      file?: string;
      action?: string;
      description?: string;
      old_code?: string;
      new_code?: string;
      diff?: string;
    }>;
    summary?: string;
    commit_message?: string;
    risk?: string;
    risk_explanation?: string;
  } | Record<string, unknown> | null;
}

interface ParsedFileDiff {
  filename: string;
  action: 'modify' | 'create' | 'delete';
  additions: number;
  deletions: number;
  lines: Array<{
    type: 'add' | 'del' | 'context' | 'header';
    oldLine?: number;
    newLine?: number;
    content: string;
  }>;
}

function parseRawDiff(raw: string): ParsedFileDiff[] {
  if (!raw) return [];
  const files: ParsedFileDiff[] = [];
  const chunks = raw.split(/^diff --git |^--- a\//m);

  for (const chunk of chunks) {
    if (!chunk.trim()) continue;
    const lines = chunk.split('\n');
    let filename = 'file';
    let action: 'modify' | 'create' | 'delete' = 'modify';
    
    // Extract filename
    const fileHeader = lines[0] || '';
    const fnMatch = fileHeader.match(/a\/(.+?)\s+b\/(.+)/) || fileHeader.match(/([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)/);
    if (fnMatch) {
      filename = fnMatch[1] || fnMatch[2] || fileHeader;
    }

    if (chunk.includes('new file mode') || (chunk.includes('+++ b/') && chunk.includes('--- /dev/null'))) {
      action = 'create';
    } else if (chunk.includes('deleted file mode')) {
      action = 'delete';
    }

    let oldLineNum = 1;
    let newLineNum = 1;
    let additions = 0;
    let deletions = 0;
    const parsedLines: ParsedFileDiff['lines'] = [];

    for (const line of lines) {
      if (line.startsWith('@@')) {
        const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
        if (match) {
          oldLineNum = parseInt(match[1], 10);
          newLineNum = parseInt(match[2], 10);
        }
        parsedLines.push({ type: 'header', content: line });
      } else if (line.startsWith('+') && !line.startsWith('+++')) {
        additions++;
        parsedLines.push({
          type: 'add',
          newLine: newLineNum++,
          content: line.substring(1),
        });
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        deletions++;
        parsedLines.push({
          type: 'del',
          oldLine: oldLineNum++,
          content: line.substring(1),
        });
      } else if (!line.startsWith('diff --git') && !line.startsWith('index ') && !line.startsWith('--- ') && !line.startsWith('+++ ')) {
        parsedLines.push({
          type: 'context',
          oldLine: oldLineNum++,
          newLine: newLineNum++,
          content: line.startsWith(' ') ? line.substring(1) : line,
        });
      }
    }

    if (parsedLines.length > 0) {
      files.push({ filename, action, additions, deletions, lines: parsedLines });
    }
  }

  return files;
}

export default function DiffViewer({ diff, patch }: DiffViewerProps) {
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<'unified' | 'raw'>('unified');

  const patchObj = (patch && typeof patch === 'object' ? patch : {}) as Record<string, unknown>;
  const diffsArr = Array.isArray(patchObj.diffs) ? (patchObj.diffs as string[]) : [];
  const rawDiffText = diff || diffsArr.join('\n\n') || '';
  const parsedFiles = parseRawDiff(rawDiffText);
  const fallbackChanges = Array.isArray(patchObj.changes) ? (patchObj.changes as Array<Record<string, unknown>>) : [];
  const riskStr = typeof patchObj.risk === 'string' ? patchObj.risk : undefined;

  const handleCopy = () => {
    if (rawDiffText) {
      navigator.clipboard.writeText(rawDiffText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="mt-3 rounded-lg border border-outline-variant/60 bg-[#0d1117] overflow-hidden text-on-surface shadow-md">
      {/* Top action bar */}
      <div className="flex items-center justify-between px-3.5 py-2 bg-[#161b22] border-b border-[#30363d] text-[11px] font-mono">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-[15px] text-primary">difference</span>
          <span className="font-semibold text-on-surface">Code Diff Preview</span>
          {riskStr && (
            <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
              riskStr === 'low'
                ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                : riskStr === 'high'
                ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
            }`}>
              {riskStr} Risk
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div className="flex bg-[#0d1117] rounded border border-[#30363d] p-0.5">
            <button
              onClick={() => setViewMode('unified')}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                viewMode === 'unified' ? 'bg-[#21262d] text-white font-medium' : 'text-on-surface-variant hover:text-white'
              }`}
            >
              Visual
            </button>
            <button
              onClick={() => setViewMode('raw')}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                viewMode === 'raw' ? 'bg-[#21262d] text-white font-medium' : 'text-on-surface-variant hover:text-white'
              }`}
            >
              Raw
            </button>
          </div>

          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-2 py-1 bg-[#21262d] hover:bg-[#30363d] text-on-surface-variant hover:text-white rounded border border-[#30363d] transition-colors text-[10px]"
          >
            <span className="material-symbols-outlined text-[13px]">{copied ? 'check' : 'content_copy'}</span>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>

      {/* Raw View */}
      {viewMode === 'raw' && (
        <pre className="p-3 text-[10px] font-mono leading-5 text-[#c9d1d9] bg-[#0d1117] overflow-x-auto max-h-96 whitespace-pre-wrap">
          {rawDiffText || 'No diff text available.'}
        </pre>
      )}

      {/* Visual Unified View */}
      {viewMode === 'unified' && (
        <div className="divide-y divide-[#30363d]">
          {parsedFiles.length > 0 ? (
            parsedFiles.map((file, fIdx) => (
              <div key={fIdx} className="bg-[#0d1117]">
                {/* File Header */}
                <div className="flex items-center justify-between px-3.5 py-1.5 bg-[#161b22] text-[11px] font-mono border-b border-[#30363d]/60">
                  <div className="flex items-center gap-2 text-on-surface truncate">
                    <span className="material-symbols-outlined text-[14px] text-on-surface-variant">
                      {file.action === 'create' ? 'note_add' : file.action === 'delete' ? 'delete' : 'edit_note'}
                    </span>
                    <span className="font-semibold">{file.filename}</span>
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#21262d] text-on-surface-variant uppercase">
                      {file.action}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-green-400 font-mono text-[10px]">+{file.additions}</span>
                    <span className="text-red-400 font-mono text-[10px]">-{file.deletions}</span>
                  </div>
                </div>

                {/* Diff Lines Table */}
                <div className="overflow-x-auto max-h-96 font-mono text-[11px] leading-5 divide-y divide-[#30363d]/20">
                  {file.lines.map((line, lIdx) => {
                    if (line.type === 'header') {
                      return (
                        <div key={lIdx} className="px-3 py-1 bg-[#1f242c] text-[#8b949e] text-[10px] italic">
                          {line.content}
                        </div>
                      );
                    }

                    const isAdd = line.type === 'add';
                    const isDel = line.type === 'del';

                    return (
                      <div
                        key={lIdx}
                        className={`flex items-stretch hover:bg-[#161b22]/50 ${
                          isAdd
                            ? 'bg-[#1a4023]/25 text-[#7ee787] border-l-2 border-[#3fb950]'
                            : isDel
                            ? 'bg-[#4d1f24]/25 text-[#ffa198] border-l-2 border-[#f85149]'
                            : 'text-[#c9d1d9] pl-[2px]'
                        }`}
                      >
                        {/* Old Line Number */}
                        <div className="w-10 shrink-0 text-right pr-2 text-[#484f58] select-none text-[10px] py-0.5 border-r border-[#30363d]/40">
                          {line.oldLine || ''}
                        </div>

                        {/* New Line Number */}
                        <div className="w-10 shrink-0 text-right pr-2 text-[#484f58] select-none text-[10px] py-0.5 border-r border-[#30363d]/40">
                          {line.newLine || ''}
                        </div>

                        {/* Symbol Indicator (+ / - / space) */}
                        <div className="w-5 shrink-0 text-center select-none py-0.5 font-bold">
                          {isAdd ? '+' : isDel ? '-' : ' '}
                        </div>

                        {/* Line Code Content */}
                        <div className="flex-1 px-2 py-0.5 whitespace-pre-wrap break-all font-mono">
                          {line.content || ' '}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))
          ) : fallbackChanges.length > 0 ? (
            fallbackChanges.map((change, cIdx) => {
              const fName = String(change.file || 'file');
              const fAction = String(change.action || 'create');
              const fDesc = change.description ? String(change.description) : null;
              const fCode = change.new_code ? String(change.new_code) : null;

              return (
                <div key={cIdx} className="p-3 bg-[#0d1117]">
                  <div className="flex items-center gap-2 mb-2 text-[11px] font-mono font-semibold text-primary">
                    <span className="material-symbols-outlined text-[14px]">note_add</span>
                    <span>{fName} ({fAction})</span>
                  </div>
                  {fDesc && (
                    <p className="text-[11px] text-on-surface-variant mb-2">{fDesc}</p>
                  )}
                  {fCode && (
                    <pre className="p-3 rounded bg-[#161b22] text-[#7ee787] text-[10px] font-mono leading-4 overflow-x-auto whitespace-pre-wrap border border-green-500/20">
                      {fCode}
                    </pre>
                  )}
                </div>
              );
            })
          ) : (
            <div className="p-4 text-center text-[11px] text-on-surface-variant">
              No code diff generated yet.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
