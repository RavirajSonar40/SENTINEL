"use client";

import React from "react";
import { ServiceGraphResponse } from "@/lib/catalogApi";

interface DependencyGraphViewProps {
  graph: ServiceGraphResponse;
  onSelectService?: (serviceId: string) => void;
}

export const DependencyGraphView: React.FC<DependencyGraphViewProps> = ({
  graph,
  onSelectService,
}) => {
  const { service_id, service_name, upstream_dependencies, downstream_dependents, nodes } = graph;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-800">
        <div>
          <h3 className="text-lg font-semibold text-white">Service Dependency Topology</h3>
          <p className="text-xs text-slate-400">
            Visualizing blast radius & upstream/downstream connections for <span className="text-indigo-400 font-medium">{service_name}</span>
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs text-slate-400">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
            <span>Healthy</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500"></span>
            <span>Hard Criticality</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
            <span>Soft Criticality</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
        {/* Downstream Dependents (Callers) */}
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-400 uppercase tracking-wider px-1">
            <span>Downstream Callers ({downstream_dependents.length})</span>
            <span className="text-[10px] text-slate-500">Depends on this service</span>
          </div>
          {downstream_dependents.length === 0 ? (
            <div className="p-4 rounded-lg border border-dashed border-slate-800 text-center text-xs text-slate-500">
              No downstream callers
            </div>
          ) : (
            downstream_dependents.map((dep) => (
              <div
                key={dep.service_id}
                onClick={() => onSelectService && onSelectService(dep.service_id)}
                className="p-3 bg-slate-950/70 border border-slate-800 hover:border-indigo-500/50 rounded-lg cursor-pointer transition-all hover:translate-x-1"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-slate-200">{dep.name}</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                      dep.criticality === "hard"
                        ? "bg-rose-950/60 text-rose-300 border border-rose-800/40"
                        : "bg-amber-950/60 text-amber-300 border border-amber-800/40"
                    }`}
                  >
                    {dep.criticality}
                  </span>
                </div>
                <div className="text-[11px] text-slate-400 flex items-center gap-2">
                  <span className="capitalize">{dep.tier} tier</span>
                  <span>•</span>
                  <span>{dep.dependency_type}</span>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Root Service Node (Center) */}
        <div className="flex flex-col items-center justify-center p-6 bg-indigo-950/30 border-2 border-indigo-500/40 rounded-xl shadow-lg shadow-indigo-950/20 text-center relative my-auto">
          <div className="absolute -top-3 px-2 py-0.5 bg-indigo-600 text-white rounded text-[10px] font-semibold tracking-wide uppercase">
            Current Service
          </div>
          <div className="w-12 h-12 rounded-xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400 mb-3 text-xl font-bold">
            ⚡
          </div>
          <h4 className="text-base font-bold text-white mb-1">{service_name}</h4>
          <p className="text-xs text-indigo-300/80 mb-3 font-mono">{service_id.slice(0, 8)}...</p>
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2 py-0.5 bg-slate-800 text-slate-300 rounded font-medium">
              {nodes.length} Nodes in Blast Radius
            </span>
          </div>
        </div>

        {/* Upstream Dependencies (Providers) */}
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-400 uppercase tracking-wider px-1">
            <span>Upstream Dependencies ({upstream_dependencies.length})</span>
            <span className="text-[10px] text-slate-500">Called by this service</span>
          </div>
          {upstream_dependencies.length === 0 ? (
            <div className="p-4 rounded-lg border border-dashed border-slate-800 text-center text-xs text-slate-500">
              No upstream dependencies
            </div>
          ) : (
            upstream_dependencies.map((dep) => (
              <div
                key={dep.service_id}
                onClick={() => onSelectService && onSelectService(dep.service_id)}
                className="p-3 bg-slate-950/70 border border-slate-800 hover:border-indigo-500/50 rounded-lg cursor-pointer transition-all hover:-translate-x-1"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-slate-200">{dep.name}</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                      dep.criticality === "hard"
                        ? "bg-rose-950/60 text-rose-300 border border-rose-800/40"
                        : "bg-amber-950/60 text-amber-300 border border-amber-800/40"
                    }`}
                  >
                    {dep.criticality}
                  </span>
                </div>
                <div className="text-[11px] text-slate-400 flex items-center gap-2">
                  <span className="capitalize">{dep.tier} tier</span>
                  <span>•</span>
                  <span>{dep.dependency_type}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
