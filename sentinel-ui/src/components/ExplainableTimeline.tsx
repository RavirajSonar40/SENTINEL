'use client';

import React, { useState, useEffect } from 'react';
import {
  fetchIncidentTimeline,
  TimelineEvent,
  TimelineMilestones,
  ExplainableTimelineResponse,
} from '@/lib/incidentMemoryApi';

interface ExplainableTimelineProps {
  incidentId: string;
}

export default function ExplainableTimeline({ incidentId }: ExplainableTimelineProps) {
  const [data, setData] = useState<ExplainableTimelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [expandedEvents, setExpandedEvents] = useState<Record<string, boolean>>({});

  const loadTimeline = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetchIncidentTimeline(incidentId);
      setData(res);
    } catch (err: any) {
      setError(err.message || 'Failed to load timeline');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (incidentId) {
      loadTimeline();
    }
  }, [incidentId]);

  const toggleExpand = (id: string) => {
    setExpandedEvents((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const formatDuration = (seconds?: number) => {
    if (seconds === undefined || seconds === null) return 'N/A';
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const remainingSecs = seconds % 60;
    if (mins < 60) return `${mins}m ${remainingSecs > 0 ? `${remainingSecs}s` : ''}`.trim();
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    return `${hours}h ${remMins > 0 ? `${remMins}m` : ''}`.trim();
  };

  const formatTime = (isoString?: string) => {
    if (!isoString) return 'Inferred / Baseline';
    try {
      const dt = new Date(isoString);
      return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
        ` (${dt.toLocaleDateString([], { month: 'short', day: 'numeric' })})`;
    } catch {
      return isoString;
    }
  };

  const categories = [
    { key: 'all', label: 'All Events' },
    { key: 'deployment', label: 'Deployments & Changes' },
    { key: 'telemetry', label: 'Telemetry & Alerts' },
    { key: 'investigation', label: 'Investigation & Tasks' },
    { key: 'evidence', label: 'Evidence Ledger' },
    { key: 'hypothesis', label: 'Hypotheses' },
    { key: 'root_cause', label: 'Root Cause' },
    { key: 'remediation', label: 'Remediation & PRs' },
    { key: 'human_action', label: 'Human Actions' },
  ];

  const filteredEvents = (data?.events || []).filter((e) => {
    if (selectedCategory === 'all') return true;
    if (selectedCategory === 'deployment') return e.category === 'deployment' || e.category === 'change';
    return e.category === selectedCategory;
  });

  const getActorBadge = (actor: string) => {
    switch (actor) {
      case 'ai':
        return (
          <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30 flex items-center gap-1">
            <span>✨</span> Autonomous AI
          </span>
        );
      case 'human':
        return (
          <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30 flex items-center gap-1">
            <span>👤</span> Human Operator
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-slate-700 text-slate-300 border border-slate-600 flex items-center gap-1">
            <span>⚙️</span> System Ingestion
          </span>
        );
    }
  };

  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'deployment':
      case 'change':
        return 'border-cyan-500/40 bg-cyan-950/20 text-cyan-400';
      case 'telemetry':
        return 'border-amber-500/40 bg-amber-950/20 text-amber-400';
      case 'incident':
        return 'border-rose-500/40 bg-rose-950/20 text-rose-400';
      case 'investigation':
        return 'border-indigo-500/40 bg-indigo-950/20 text-indigo-400';
      case 'evidence':
        return 'border-emerald-500/40 bg-emerald-950/20 text-emerald-400';
      case 'hypothesis':
        return 'border-violet-500/40 bg-violet-950/20 text-violet-400';
      case 'root_cause':
        return 'border-red-500/50 bg-red-950/30 text-red-300';
      case 'remediation':
        return 'border-teal-500/40 bg-teal-950/20 text-teal-400';
      case 'human_action':
        return 'border-blue-500/40 bg-blue-950/20 text-blue-400';
      default:
        return 'border-slate-700 bg-slate-800/40 text-slate-300';
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex flex-col items-center justify-center space-y-4 min-h-[300px]">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
        <p className="text-sm text-slate-400 font-mono">Synthesizing explainable timeline event graph...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-rose-950/20 border border-rose-500/30 rounded-xl text-center space-y-3">
        <p className="text-rose-400 font-medium">Failed to load Explainable Timeline</p>
        <p className="text-xs text-slate-400">{error}</p>
        <button
          onClick={loadTimeline}
          className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-medium transition"
        >
          Retry
        </button>
      </div>
    );
  }

  const milestones: TimelineMilestones = data?.milestones || {};

  return (
    <div className="space-y-6">
      {/* SRE Reliability Milestone Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <div className="p-3.5 bg-slate-900/60 border border-slate-800 rounded-xl backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold tracking-wide text-slate-400">MTTD</span>
            <span className="text-[10px] text-slate-500">Detect</span>
          </div>
          <p className="text-xl font-bold text-slate-100 mt-1">
            {formatDuration(milestones.mttd_seconds)}
          </p>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">
            {milestones.detected_at ? formatTime(milestones.detected_at) : 'No onset timestamp'}
          </p>
        </div>

        <div className="p-3.5 bg-slate-900/60 border border-slate-800 rounded-xl backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold tracking-wide text-slate-400">MTTA</span>
            <span className="text-[10px] text-slate-500">Acknowledge</span>
          </div>
          <p className="text-xl font-bold text-slate-100 mt-1">
            {formatDuration(milestones.mtta_seconds)}
          </p>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">
            {milestones.acknowledged_at ? formatTime(milestones.acknowledged_at) : 'Auto-queued'}
          </p>
        </div>

        <div className="p-3.5 bg-slate-900/60 border border-slate-800 rounded-xl backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold tracking-wide text-slate-400">MTTRC</span>
            <span className="text-[10px] text-slate-500">Root Cause</span>
          </div>
          <p className="text-xl font-bold text-slate-100 mt-1">
            {formatDuration(milestones.mttrc_seconds)}
          </p>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">
            {milestones.root_cause_at ? formatTime(milestones.root_cause_at) : 'Under investigation'}
          </p>
        </div>

        <div className="p-3.5 bg-slate-900/60 border border-slate-800 rounded-xl backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold tracking-wide text-slate-400">MTTM</span>
            <span className="text-[10px] text-slate-500">Mitigate</span>
          </div>
          <p className="text-xl font-bold text-slate-100 mt-1">
            {formatDuration(milestones.mttm_seconds)}
          </p>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">
            {milestones.mitigated_at ? formatTime(milestones.mitigated_at) : 'Pending fix merge'}
          </p>
        </div>

        <div className="p-3.5 bg-slate-900/60 border border-slate-800 rounded-xl backdrop-blur-sm col-span-2 sm:col-span-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold tracking-wide text-slate-400">MTTR</span>
            <span className="text-[10px] text-slate-500">Resolve</span>
          </div>
          <p className="text-xl font-bold text-slate-100 mt-1">
            {formatDuration(milestones.mttr_seconds)}
          </p>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">
            {milestones.resolved_at ? formatTime(milestones.resolved_at) : 'Active Incident'}
          </p>
        </div>
      </div>

      {/* Category Filter Chips */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-thin">
        {categories.map((c) => (
          <button
            key={c.key}
            onClick={() => setSelectedCategory(c.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition ${
              selectedCategory === c.key
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'bg-slate-900/80 text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-800'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Timeline Event Feed with Causal Tree Links */}
      <div className="relative border-l-2 border-slate-800 ml-4 pl-6 space-y-6">
        {filteredEvents.length === 0 ? (
          <div className="p-8 text-center bg-slate-900/40 border border-slate-800/80 rounded-xl text-slate-500 text-sm">
            No events match the selected category filter.
          </div>
        ) : (
          filteredEvents.map((evt, idx) => {
            const isExpanded = !!expandedEvents[evt.id];
            const catColor = getCategoryColor(evt.category);

            return (
              <div key={evt.id} className="relative group">
                {/* Node dot on the vertical branch line */}
                <div
                  className={`absolute -left-[31px] top-3.5 w-3.5 h-3.5 rounded-full border-2 bg-slate-950 transition ${
                    evt.category === 'root_cause'
                      ? 'border-red-500 shadow-lg shadow-red-500/50'
                      : evt.category === 'remediation'
                      ? 'border-teal-400'
                      : 'border-slate-500 group-hover:border-indigo-400'
                  }`}
                />

                {/* Event Card */}
                <div
                  className={`p-4 rounded-xl border backdrop-blur-sm transition ${catColor} hover:border-slate-600 bg-slate-900/70`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-slate-100">{evt.label}</span>
                        {getActorBadge(evt.actor)}
                        {evt.causal_relation && (
                          <span className="px-2 py-0.5 text-[10px] font-mono rounded bg-slate-800 text-slate-400 border border-slate-700">
                            ↳ {evt.causal_relation}
                          </span>
                        )}
                        {evt.inferred_timestamp && (
                          <span className="text-[10px] text-amber-400/80 italic">
                            (inferred timestamp)
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-300 leading-relaxed font-sans">{evt.detail}</p>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs font-mono text-slate-400">{formatTime(evt.time)}</span>
                      {evt.metadata && Object.keys(evt.metadata).length > 0 && (
                        <button
                          onClick={() => toggleExpand(evt.id)}
                          className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-[10px] text-slate-300 rounded border border-slate-700 transition"
                        >
                          {isExpanded ? 'Hide Details' : 'Details'}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Collapsible Metadata Details */}
                  {isExpanded && evt.metadata && (
                    <div className="mt-3 pt-3 border-t border-slate-800 text-xs font-mono bg-slate-950/60 p-2.5 rounded-lg text-slate-400 overflow-x-auto">
                      <pre className="text-[11px] whitespace-pre-wrap">
                        {JSON.stringify(evt.metadata, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
