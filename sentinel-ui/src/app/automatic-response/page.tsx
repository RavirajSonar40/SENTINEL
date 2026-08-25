"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listIncidents, listAlertRules, Incident, AlertRule } from "@/lib/api";

export default function AutomaticResponsePage() {
  const { token } = useAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      listIncidents(token).catch(() => []),
      listAlertRules(token).catch(() => []),
    ]).then(([inc, rls]) => {
      setIncidents(inc);
      setRules(Array.isArray(rls) ? rls : (rls as any)?.rules || []);
    }).finally(() => setLoading(false));
  }, [token]);

  const activeRules = rules.filter((r) => r.enabled);
  const recentIncidents = incidents.filter((i) => {
    const created = new Date(i.created_at);
    const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
    return created > dayAgo;
  });
  const autoDetected = incidents.filter((i) => i.source === "webhook");

  return (
    <>
      <TopBar
        title="Automatic Response"
        subtitle="Monitor and manage automatic incident detection and response."
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto">
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="material-symbols-outlined text-[20px] text-primary">bolt</span>
                <h3 className="text-[13px] font-semibold text-on-surface">Detection Engine</h3>
              </div>
              <div className="flex items-center gap-2 text-[12px]">
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                <span className="text-primary">Active</span>
                <span className="text-on-surface-variant ml-auto">Monitoring {rules.length} rules</span>
              </div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="material-symbols-outlined text-[20px] text-tertiary">notifications</span>
                <h3 className="text-[13px] font-semibold text-on-surface">Alert Rules</h3>
              </div>
              <div className="text-[12px] text-on-surface-variant">{activeRules.length} active rules</div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="material-symbols-outlined text-[20px] text-primary">psychology</span>
                <h3 className="text-[13px] font-semibold text-on-surface">Auto-Investigate</h3>
              </div>
              <div className="text-[12px] text-on-surface-variant">{recentIncidents.length} incidents in 24h</div>
            </div>
          </div>

          {/* Recent Auto-Detected */}
          <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[13px] font-semibold text-on-surface">Recently Auto-Detected Incidents</h2>
              <Link href="/incidents" className="text-[11px] text-primary hover:underline">View all</Link>
            </div>
            {loading ? (
              <div className="text-[12px] text-on-surface-variant">Loading...</div>
            ) : autoDetected.length === 0 ? (
              <div className="text-[12px] text-on-surface-variant">No auto-detected incidents yet. Configure webhooks in Integrations to start.</div>
            ) : (
              <div className="space-y-2">
                {autoDetected.slice(0, 5).map((inc) => (
                  <Link
                    key={inc.id}
                    href={`/incidents/${inc.id}`}
                    className="flex items-center gap-3 p-3 bg-surface-container rounded border border-outline-variant hover:border-primary/30 transition-colors"
                  >
                    <span className={`w-2 h-2 rounded-full ${
                      inc.severity === "SEV-1" ? "bg-error" :
                      inc.severity === "SEV-2" ? "bg-tertiary" : "bg-primary"
                    }`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-[12px] font-medium text-on-surface truncate">{inc.title}</div>
                      <div className="text-[10px] text-on-surface-variant">{inc.service || "—"} &bull; {inc.status.replace(/_/g, " ")}</div>
                    </div>
                    <span className="text-[10px] text-on-surface-variant font-mono">
                      {new Date(inc.created_at).toLocaleTimeString("en-US", { hour12: false })}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Active Rules */}
          <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[13px] font-semibold text-on-surface">Active Detection Rules</h2>
              <Link href="/alerts" className="text-[11px] text-primary hover:underline">Manage rules</Link>
            </div>
            <div className="space-y-2">
              {activeRules.map((rule) => (
                <div key={rule.id} className="flex items-center gap-3 p-3 bg-surface-container rounded">
                  <span className={`w-2 h-2 rounded-full ${
                    rule.severity === "SEV-1" ? "bg-error" :
                    rule.severity === "SEV-2" ? "bg-tertiary" : "bg-primary"
                  }`} />
                  <div className="flex-1">
                    <div className="text-[12px] font-medium text-on-surface">{rule.name}</div>
                    <div className="text-[10px] text-on-surface-variant">{rule.threshold}</div>
                  </div>
                  <span className="text-[10px] text-on-surface-variant">{rule.type}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
