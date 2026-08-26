"use client";

import { useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listAlertRules, toggleAlertRule, AlertRule } from "@/lib/api";

const severityStyles: Record<string, string> = {
  "SEV-1": "bg-error/10 text-error border-error/20",
  "SEV-2": "bg-orange-500/10 text-orange-400 border-orange-500/20",
  "SEV-3": "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  "SEV-4": "bg-surface-container-high text-on-surface-variant border-outline-variant",
};

export default function AlertsPage() {
  const { token } = useAuth();
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    listAlertRules(token)
      .then((data) => setRules(Array.isArray(data) ? data : (data as { rules?: AlertRule[] })?.rules || []))
      .catch(() => setRules([]))
      .finally(() => setLoading(false));
  }, [token]);

  const handleToggle = async (id: string) => {
    if (!token) return;
    // Optimistic update
    setRules((prev) => prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)));
    try {
      await toggleAlertRule(token, id);
    } catch {
      // Revert on failure
      setRules((prev) => prev.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)));
    }
  };

  const activeCount = rules.filter((r) => r.enabled).length;

  return (
    <>
      <TopBar
        title="Alerts"
        subtitle="Manage alert rules and view recent alerts"
        breadcrumbs={[{ label: "Alerts", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto">
          {/* Stats */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <div className="text-[11px] text-on-surface-variant uppercase tracking-wider mb-1">Total Rules</div>
              <div className="text-[24px] font-bold text-on-surface">{rules.length}</div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <div className="text-[11px] text-on-surface-variant uppercase tracking-wider mb-1">Active Rules</div>
              <div className="text-[24px] font-bold text-primary">{activeCount}</div>
            </div>
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <div className="text-[11px] text-on-surface-variant uppercase tracking-wider mb-1">Disabled Rules</div>
              <div className="text-[24px] font-bold text-on-surface-variant">{rules.length - activeCount}</div>
            </div>
          </div>

          {/* Rules Table */}
          <div className="bg-surface-container-low border border-outline-variant rounded">
            <div className="p-4 border-b border-outline-variant">
              <h2 className="text-[13px] font-semibold text-on-surface">Detection Rules</h2>
            </div>
            {loading ? (
              <div className="p-8 text-center text-on-surface-variant text-[12px] font-mono">Loading...</div>
            ) : rules.length === 0 ? (
              <div className="p-8 text-center text-on-surface-variant text-[12px]">No alert rules configured</div>
            ) : (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-outline-variant bg-surface-container">
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Rule</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Type</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Threshold</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Severity</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Services</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Status</th>
                  </tr>
                </thead>
                <tbody className="font-mono text-[11px]">
                  {rules.map((rule) => (
                    <tr key={rule.id} className="border-b border-outline-variant/50 hover:bg-surface-container-high/50 transition-colors">
                      <td className="py-2.5 px-4 text-on-surface font-medium">{rule.name}</td>
                      <td className="py-2.5 px-4 text-on-surface-variant">{rule.type}</td>
                      <td className="py-2.5 px-4 text-on-surface-variant">{rule.threshold}</td>
                      <td className="py-2.5 px-4">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${severityStyles[rule.severity] || ""}`}>
                          {rule.severity}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-on-surface-variant">{rule.services.join(", ")}</td>
                      <td className="py-2.5 px-4">
                        <button
                          onClick={() => handleToggle(rule.id)}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                            rule.enabled ? "bg-primary" : "bg-outline"
                          }`}
                        >
                          <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                            rule.enabled ? "translate-x-4.5" : "translate-x-0.5"
                          }`} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
