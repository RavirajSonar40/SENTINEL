"use client";

import { useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { getSystemHealth, SystemHealth, getMetrics } from "@/lib/api";

export default function HealthPage() {
  const { token } = useAuth();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      getSystemHealth(token).catch(() => null),
      getMetrics(token).catch(() => null),
    ]).then(([h, m]) => {
      setHealth(h);
      setMetrics(m);
    }).finally(() => setLoading(false));
  }, [token]);

  const checks = health?.checks || {};

  return (
    <>
      <TopBar
        title="System Health"
        subtitle="Infrastructure status and metrics"
        breadcrumbs={[{ label: "Health", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto space-y-6">
          {/* Overall Status */}
          <div className={`p-4 rounded-lg border ${
            health?.status === "healthy"
              ? "bg-primary/10 border-primary/20"
              : "bg-tertiary/10 border-tertiary/20"
          }`}>
            <div className="flex items-center gap-3">
              <span className={`w-3 h-3 rounded-full ${health?.status === "healthy" ? "bg-primary" : "bg-tertiary"}`} />
              <span className="text-[14px] font-semibold text-on-surface">
                System {health?.status === "healthy" ? "Operational" : "Degraded"}
              </span>
            </div>
          </div>

          {/* Service Checks */}
          <div className="grid grid-cols-2 gap-4">
            {Object.entries(checks).map(([name, check]) => (
              <div key={name} className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-[13px] font-semibold text-on-surface capitalize">{name}</h3>
                  <span className={`flex items-center gap-1.5 text-[12px] ${
                    check.status === "operational" || check.status === "configured" ? "text-primary" : "text-error"
                  }`}>
                    <span className={`w-2 h-2 rounded-full ${
                      check.status === "operational" || check.status === "configured" ? "bg-primary" : "bg-error"
                    }`} />
                    {check.status}
                  </span>
                </div>
                {check.error && (
                  <div className="text-[11px] text-error font-mono mt-1">{check.error}</div>
                )}
                {check.latency_ms !== undefined && (
                  <div className="text-[11px] text-on-surface-variant mt-1">Latency: {check.latency_ms}ms</div>
                )}
                {check.provider && (
                  <div className="text-[11px] text-on-surface-variant mt-1">Provider: {check.provider} / {check.model}</div>
                )}
              </div>
            ))}
          </div>

          {/* Metrics */}
          {metrics && (
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <h2 className="text-[13px] font-semibold text-on-surface mb-4">System Metrics</h2>
              <div className="grid grid-cols-4 gap-4">
                <div>
                  <div className="text-[10px] text-on-surface-variant uppercase">Requests</div>
                  <div className="text-[18px] font-bold text-on-surface">{metrics.requests?.total || 0}</div>
                </div>
                <div>
                  <div className="text-[10px] text-on-surface-variant uppercase">LLM Calls</div>
                  <div className="text-[18px] font-bold text-on-surface">{metrics.llm?.total_calls || 0}</div>
                </div>
                <div>
                  <div className="text-[10px] text-on-surface-variant uppercase">Tool Calls</div>
                  <div className="text-[18px] font-bold text-on-surface">{metrics.tools?.total_calls || 0}</div>
                </div>
                <div>
                  <div className="text-[10px] text-on-surface-variant uppercase">Total Cost</div>
                  <div className="text-[18px] font-bold text-on-surface">${metrics.llm?.total_cost_usd || 0}</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
