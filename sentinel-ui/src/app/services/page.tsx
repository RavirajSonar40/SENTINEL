"use client";

import { useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { getServiceHealth } from "@/lib/api";

interface ServiceHealth {
  service: string;
  health_score: number;
  status: string;
  incidents_24h: number;
  open_incidents: number;
  severity_breakdown: { "SEV-1": number; "SEV-2": number; "SEV-3": number; "SEV-4": number };
  last_incident: string | null;
}

const statusColors: Record<string, string> = {
  healthy: "bg-green-500/10 text-green-400 border-green-500/20",
  degraded: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  unhealthy: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  critical: "bg-red-500/10 text-red-400 border-red-500/20",
};

const statusDots: Record<string, string> = {
  healthy: "bg-green-400",
  degraded: "bg-yellow-400",
  unhealthy: "bg-orange-400",
  critical: "bg-red-400",
};

export default function ServicesPage() {
  const { token } = useAuth();
  const [health, setHealth] = useState<{overall_health_score: number; services: ServiceHealth[]} | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    getServiceHealth(token)
      .then((data) => setHealth(data as typeof health))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <>
      <TopBar
        title="Services"
        subtitle="Service health monitoring and dependency tracking"
        breadcrumbs={[{ label: "Services", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto">
          {/* Overall Health */}
          <div className="grid grid-cols-4 gap-3 mb-6">
            <div className="bg-surface-container-low border border-outline-variant rounded p-4">
              <div className="text-[11px] text-on-surface-variant mb-1">Overall Health</div>
              <div className="flex items-center gap-2">
                <div className="text-[32px] font-semibold text-on-surface">
                  {health?.overall_health_score ?? "—"}
                </div>
                <div className="text-[11px] text-on-surface-variant">/ 100</div>
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-4">
              <div className="text-[11px] text-on-surface-variant mb-1">Healthy</div>
              <div className="text-[32px] font-semibold text-green-400">
                {health?.services.filter((s: ServiceHealth) => s.status === "healthy").length ?? 0}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-4">
              <div className="text-[11px] text-on-surface-variant mb-1">Degraded</div>
              <div className="text-[32px] font-semibold text-yellow-400">
                {health?.services.filter((s: ServiceHealth) => s.status === "degraded").length ?? 0}
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded p-4">
              <div className="text-[11px] text-on-surface-variant mb-1">Unhealthy / Critical</div>
              <div className="text-[32px] font-semibold text-red-400">
                {health?.services.filter((s: ServiceHealth) => s.status === "unhealthy" || s.status === "critical").length ?? 0}
              </div>
            </div>
          </div>

          {/* Service List */}
          <div className="bg-surface-container-low border border-outline-variant rounded">
            <div className="p-4 border-b border-outline-variant">
              <h2 className="text-[13px] font-semibold text-on-surface">Service Health</h2>
            </div>
            {loading ? (
              <div className="p-8 text-center text-on-surface-variant font-mono text-[12px]">Loading...</div>
            ) : !health || health.services.length === 0 ? (
              <div className="p-8 text-center">
                <span className="material-symbols-outlined text-[48px] text-on-surface-variant/20 block mb-2">settings_input_component</span>
                <div className="text-[13px] text-on-surface-variant">No services configured</div>
              </div>
            ) : (
              <div className="divide-y divide-outline-variant">
                {health.services.map((svc: ServiceHealth) => (
                  <div key={svc.service} className="p-4 flex items-center gap-4 hover:bg-surface-container-high/50">
                    <div className={`w-2.5 h-2.5 rounded-full ${statusDots[svc.status]}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-medium text-on-surface">{svc.service}</span>
                        <span className={`px-2 py-0.5 rounded text-[11px] font-mono border ${
                          statusColors[svc.status] || ""
                        }`}>
                          {svc.status}
                        </span>
                      </div>
                      <div className="flex gap-4 mt-1 font-mono text-[11px] text-on-surface-variant">
                        <span>Score: {svc.health_score}</span>
                        <span>Incidents (24h): {svc.incidents_24h}</span>
                        <span>Open: {svc.open_incidents}</span>
                        {svc.last_incident && (
                          <span>Last: {new Date(svc.last_incident).toLocaleString()}</span>
                        )}
                      </div>
                    </div>
                    <div className="flex gap-1">
                      {Object.entries(svc.severity_breakdown).map(([sev, count]) =>
                        (count as number) > 0 ? (
                          <span
                            key={sev}
                            className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
                              sev === "SEV-1"
                                ? "bg-red-500/10 text-red-400"
                                : sev === "SEV-2"
                                ? "bg-orange-500/10 text-orange-400"
                                : "bg-surface-container-high text-on-surface-variant"
                            }`}
                          >
                            {sev}: {String(count)}
                          </span>
                        ) : null
                      )}
                    </div>
                    {/* Health Score Bar */}
                    <div className="w-24">
                      <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            svc.health_score >= 90
                              ? "bg-green-400"
                              : svc.health_score >= 70
                              ? "bg-yellow-400"
                              : svc.health_score >= 50
                              ? "bg-orange-400"
                              : "bg-red-400"
                          }`}
                          style={{ width: `${svc.health_score}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
