"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  monitoringApi,
  TelemetrySignal,
  HealthCheckStatus,
  AlertRuleConfigDTO,
  CorrelationSummary,
} from "@/lib/monitoringApi";

export default function MonitoringPage() {
  const [activeTab, setActiveTab] = useState<"signals" | "health" | "rules">("signals");
  const [signals, setSignals] = useState<TelemetrySignal[]>([]);
  const [healthChecks, setHealthChecks] = useState<HealthCheckStatus[]>([]);
  const [rules, setRules] = useState<AlertRuleConfigDTO[]>([]);
  const [summary, setSummary] = useState<CorrelationSummary | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [probingConfigId, setProbingConfigId] = useState<string | null>(null);
  const [editingRule, setEditingRule] = useState<AlertRuleConfigDTO | null>(null);
  const [newThreshold, setNewThreshold] = useState<string>("");
  const [saveRuleLoading, setSaveRuleLoading] = useState(false);
  const [expandedSignalId, setExpandedSignalId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Filters
  const [providerFilter, setProviderFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const loadData = useCallback(async (isSilent = false) => {
    try {
      if (!isSilent) setRefreshing(true);
      setErrorMsg(null);

      const [sigData, hcData, rulesData, sumData] = await Promise.all([
        monitoringApi.fetchTelemetrySignals(undefined, {
          provider: providerFilter || undefined,
          status: statusFilter || undefined,
          limit: 50,
        }),
        monitoringApi.fetchHealthCheckStatuses(),
        monitoringApi.fetchAlertRules(),
        monitoringApi.fetchCorrelationSummary(),
      ]);

      setSignals(sigData);
      setHealthChecks(hcData);
      setRules(rulesData);
      setSummary(sumData);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to load monitoring data");
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [providerFilter, statusFilter]);

  useEffect(() => {
    let ignore = false;
    const execute = async () => {
      try {
        const [sigData, hcData, rulesData, sumData] = await Promise.all([
          monitoringApi.fetchTelemetrySignals(undefined, {
            provider: providerFilter || undefined,
            status: statusFilter || undefined,
            limit: 50,
          }),
          monitoringApi.fetchHealthCheckStatuses(),
          monitoringApi.fetchAlertRules(),
          monitoringApi.fetchCorrelationSummary(),
        ]);
        if (!ignore) {
          setSignals(sigData);
          setHealthChecks(hcData);
          setRules(rulesData);
          setSummary(sumData);
        }
      } catch (err: unknown) {
        if (!ignore) {
          setErrorMsg(err instanceof Error ? err.message : "Failed to load monitoring data");
        }
      } finally {
        if (!ignore) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    };
    execute();
    return () => {
      ignore = true;
    };
  }, [providerFilter, statusFilter]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(() => {
      loadData(true);
    }, 10000);
    return () => clearInterval(timer);
  }, [autoRefresh, loadData]);

  const handleProbeNow = async (configId: string) => {
    try {
      setProbingConfigId(configId);
      const res = await monitoringApi.probeHealthCheckNow(configId);
      // Update item in local list
      setHealthChecks((prev) =>
        prev.map((hc) =>
          hc.id === configId
            ? {
                ...hc,
                is_healthy: res.is_healthy,
                last_probe_status_code: res.status_code,
                last_probe_latency_ms: res.latency_ms,
                last_probe_error: res.error_message,
                last_probed_at: res.probed_at,
                consecutive_failures: res.is_healthy ? 0 : hc.consecutive_failures + 1,
              }
            : hc
        )
      );
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Probe failed");
    } finally {
      setProbingConfigId(null);
    }
  };

  const handleToggleRule = async (rule: AlertRuleConfigDTO) => {
    try {
      const updated = await monitoringApi.updateAlertRule(rule.rule_name, {
        is_enabled: !rule.is_enabled,
      });
      setRules((prev) => prev.map((r) => (r.rule_name === rule.rule_name ? updated : r)));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to toggle rule");
    }
  };

  const handleSaveThreshold = async () => {
    if (!editingRule) return;
    try {
      setSaveRuleLoading(true);
      const val = parseFloat(newThreshold);
      const updated = await monitoringApi.updateAlertRule(editingRule.rule_name, {
        threshold_value: isNaN(val) ? undefined : val,
      });
      setRules((prev) => prev.map((r) => (r.rule_name === editingRule.rule_name ? updated : r)));
      setEditingRule(null);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to save threshold");
    } finally {
      setSaveRuleLoading(false);
    }
  };

  const filteredSignals = signals.filter((s) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      s.title.toLowerCase().includes(q) ||
      (s.service_name && s.service_name.toLowerCase().includes(q)) ||
      (s.environment_name && s.environment_name.toLowerCase().includes(q)) ||
      s.rule_name.toLowerCase().includes(q) ||
      s.correlation_key.toLowerCase().includes(q)
    );
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-3xl">sensors</span>
            <h1 className="text-2xl font-bold text-on-surface tracking-tight">
              Autonomous Monitoring & Production Detection
            </h1>
          </div>
          <p className="text-sm text-on-surface-variant mt-1">
            Real-time anomaly ingestion, 12 production detection rules, distributed health probes, and automated incident correlation.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors flex items-center gap-1.5 ${
              autoRefresh
                ? "bg-primary/10 border-primary text-primary"
                : "bg-surface-container border-outline text-on-surface-variant"
            }`}
          >
            <span className="material-symbols-outlined text-sm">
              {autoRefresh ? "sync" : "sync_disabled"}
            </span>
            {autoRefresh ? "Auto-refresh: 10s" : "Auto-refresh: Off"}
          </button>

          <button
            onClick={() => loadData()}
            disabled={refreshing}
            className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-surface-container hover:bg-surface-container-high border border-outline text-on-surface transition-all flex items-center gap-1.5 disabled:opacity-50"
          >
            <span className={`material-symbols-outlined text-sm ${refreshing ? "animate-spin" : ""}`}>
              refresh
            </span>
            Refresh
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 rounded-xl bg-error-container/20 border border-error/30 text-error flex items-center gap-3">
          <span className="material-symbols-outlined">error</span>
          <span className="text-sm">{errorMsg}</span>
        </div>
      )}

      {/* Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant shadow-sm flex items-center justify-between">
          <div>
            <div className="text-xs font-medium uppercase tracking-wider text-on-surface-variant">
              Telemetry Signals (24h)
            </div>
            <div className="text-2xl font-bold text-on-surface mt-1">
              {summary?.total_signals_24h ?? "—"}
            </div>
          </div>
          <div className="p-2.5 rounded-lg bg-primary/10 text-primary">
            <span className="material-symbols-outlined">stacked_line_chart</span>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant shadow-sm flex items-center justify-between">
          <div>
            <div className="text-xs font-medium uppercase tracking-wider text-on-surface-variant">
              Auto-Detected Incidents
            </div>
            <div className="text-2xl font-bold text-error mt-1">
              {summary?.auto_incidents_24h ?? "—"}
            </div>
          </div>
          <div className="p-2.5 rounded-lg bg-error/10 text-error">
            <span className="material-symbols-outlined">auto_fix_high</span>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant shadow-sm flex items-center justify-between">
          <div>
            <div className="text-xs font-medium uppercase tracking-wider text-on-surface-variant">
              Active Fleet Probes
            </div>
            <div className="text-2xl font-bold text-on-surface mt-1">
              {summary ? summary.healthy_probes + summary.failing_probes : "—"}
            </div>
          </div>
          <div className="p-2.5 rounded-lg bg-secondary/10 text-secondary">
            <span className="material-symbols-outlined">monitor_heart</span>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant shadow-sm flex items-center justify-between">
          <div>
            <div className="text-xs font-medium uppercase tracking-wider text-on-surface-variant">
              Fleet Probe Health
            </div>
            <div className="text-2xl font-bold text-tertiary mt-1">
              {summary?.failing_probes === 0 ? (
                <span className="text-tertiary">100% Healthy</span>
              ) : (
                <span className="text-error">{summary?.failing_probes} Failing</span>
              )}
            </div>
          </div>
          <div className="p-2.5 rounded-lg bg-tertiary/10 text-tertiary">
            <span className="material-symbols-outlined">verified_user</span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-outline-variant">
        <button
          onClick={() => setActiveTab("signals")}
          className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === "signals"
              ? "border-primary text-primary"
              : "border-transparent text-on-surface-variant hover:text-on-surface"
          }`}
        >
          <span className="material-symbols-outlined text-sm">hub</span>
          Telemetry Signals ({signals.length})
        </button>

        <button
          onClick={() => setActiveTab("health")}
          className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === "health"
              ? "border-primary text-primary"
              : "border-transparent text-on-surface-variant hover:text-on-surface"
          }`}
        >
          <span className="material-symbols-outlined text-sm">health_and_safety</span>
          Fleet Health Checks ({healthChecks.length})
        </button>

        <button
          onClick={() => setActiveTab("rules")}
          className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === "rules"
              ? "border-primary text-primary"
              : "border-transparent text-on-surface-variant hover:text-on-surface"
          }`}
        >
          <span className="material-symbols-outlined text-sm">tune</span>
          12 Detection Rules & Thresholds ({rules.length})
        </button>
      </div>

      {/* Tab 1: Telemetry Signals Feed */}
      {activeTab === "signals" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
            <div className="relative w-full sm:w-80">
              <span className="material-symbols-outlined absolute left-3 top-2.5 text-on-surface-variant text-sm">
                search
              </span>
              <input
                type="text"
                placeholder="Search signals, rules, keys..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 bg-surface-container rounded-lg text-sm border border-outline focus:outline-none focus:border-primary text-on-surface"
              />
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto">
              <select
                value={providerFilter}
                onChange={(e) => setProviderFilter(e.target.value)}
                className="px-3 py-1.5 bg-surface-container rounded-lg text-xs border border-outline text-on-surface focus:outline-none"
              >
                <option value="">All Providers</option>
                <option value="prometheus">Prometheus</option>
                <option value="sentry">Sentry</option>
                <option value="health_check">Health Check</option>
                <option value="generic">Generic APM</option>
              </select>

              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-3 py-1.5 bg-surface-container rounded-lg text-xs border border-outline text-on-surface focus:outline-none"
              >
                <option value="">All Statuses</option>
                <option value="ingested">Ingested</option>
                <option value="triggered_incident">Triggered Incident</option>
                <option value="correlated">Correlated</option>
                <option value="suppressed_non_prod">Suppressed Non-Prod</option>
                <option value="resolved">Resolved</option>
              </select>
            </div>
          </div>

          {loading ? (
            <div className="py-12 text-center text-on-surface-variant">Loading signals...</div>
          ) : filteredSignals.length === 0 ? (
            <div className="py-12 text-center text-on-surface-variant border border-dashed border-outline-variant rounded-xl">
              <span className="material-symbols-outlined text-4xl mb-2">inbox</span>
              <p>No telemetry signals matching the criteria</p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredSignals.map((signal) => {
                const isExpanded = expandedSignalId === signal.id;
                return (
                  <div
                    key={signal.id}
                    className="p-4 rounded-xl bg-surface-container-low border border-outline-variant hover:border-outline transition-all"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                              signal.provider === "prometheus"
                                ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                : signal.provider === "sentry"
                                ? "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                                : signal.provider === "health_check"
                                ? "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                                : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                            }`}
                          >
                            {signal.provider}
                          </span>

                          <span className="font-mono text-xs text-primary font-semibold">
                            {signal.rule_name}
                          </span>

                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                              signal.status === "triggered_incident"
                                ? "bg-error/20 text-error border border-error/30"
                                : signal.status === "correlated"
                                ? "bg-secondary/20 text-secondary"
                                : signal.status === "suppressed_non_prod"
                                ? "bg-on-surface-variant/20 text-on-surface-variant"
                                : "bg-surface-container text-on-surface"
                            }`}
                          >
                            {signal.status}
                          </span>

                          {signal.environment_name && (
                            <span className="text-xs text-on-surface-variant">
                              env: <strong className="text-on-surface">{signal.environment_name}</strong>
                            </span>
                          )}

                          {signal.service_name && (
                            <span className="text-xs text-on-surface-variant">
                              svc: <strong className="text-on-surface">{signal.service_name}</strong>
                            </span>
                          )}
                        </div>

                        <div className="text-sm font-medium text-on-surface">
                          {signal.title}
                        </div>
                      </div>

                      <div className="flex items-center gap-3 text-xs text-on-surface-variant">
                        <span>{new Date(signal.observed_at).toLocaleTimeString()}</span>
                        {signal.incident_id && (
                          <Link
                            href={`/incidents/${signal.incident_id}`}
                            className="px-2.5 py-1 rounded bg-error/15 text-error hover:bg-error/25 font-semibold flex items-center gap-1 border border-error/30"
                          >
                            <span className="material-symbols-outlined text-xs">emergency</span>
                            INC-{signal.incident_number || signal.incident_id.slice(0, 8)}
                          </Link>
                        )}
                        <button
                          onClick={() => setExpandedSignalId(isExpanded ? null : signal.id)}
                          className="p-1 rounded hover:bg-surface-container text-on-surface-variant"
                        >
                          <span className="material-symbols-outlined text-sm">
                            {isExpanded ? "expand_less" : "expand_more"}
                          </span>
                        </button>
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="mt-3 pt-3 border-t border-outline-variant space-y-2 text-xs font-mono">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-on-surface-variant">
                          <div>
                            <strong>Fingerprint:</strong> {signal.fingerprint}
                          </div>
                          <div>
                            <strong>Correlation Key:</strong> {signal.correlation_key}
                          </div>
                          {signal.error_signature && (
                            <div>
                              <strong>Error Signature:</strong> {signal.error_signature}
                            </div>
                          )}
                          {signal.metric_value !== undefined && (
                            <div>
                              <strong>Metric Value:</strong> {signal.metric_value} (threshold: {signal.threshold_value ?? "default"})
                            </div>
                          )}
                        </div>

                        {signal.raw_payload && (
                          <div>
                            <div className="text-on-surface-variant font-bold mb-1">Sanitized Raw Payload:</div>
                            <pre className="p-2.5 rounded bg-surface-container text-[11px] overflow-x-auto text-on-surface">
                              {JSON.stringify(signal.raw_payload, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Fleet Health Checks */}
      {activeTab === "health" && (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border border-outline-variant bg-surface-container-low">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-outline-variant bg-surface-container text-on-surface-variant uppercase tracking-wider font-semibold">
                <tr>
                  <th className="p-3">Service</th>
                  <th className="p-3">Environment</th>
                  <th className="p-3">Health URL</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Latency</th>
                  <th className="p-3">Failures</th>
                  <th className="p-3">Last Probed</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant">
                {healthChecks.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="p-6 text-center text-on-surface-variant">
                      No service deployment configs with health check endpoints registered.
                    </td>
                  </tr>
                ) : (
                  healthChecks.map((hc) => (
                    <tr key={hc.id} className="hover:bg-surface-container/50 transition-colors">
                      <td className="p-3 font-medium text-on-surface">{hc.service_name}</td>
                      <td className="p-3 text-on-surface-variant">{hc.environment_name}</td>
                      <td className="p-3 font-mono text-[11px] text-on-surface-variant max-w-[200px] truncate">
                        {hc.health_check_url}
                      </td>
                      <td className="p-3">
                        {hc.is_healthy === true ? (
                          <span className="px-2 py-0.5 rounded bg-tertiary/20 text-tertiary font-semibold flex items-center gap-1 w-max">
                            <span className="w-1.5 h-1.5 rounded-full bg-tertiary animate-pulse" />
                            Healthy ({hc.last_probe_status_code || 200})
                          </span>
                        ) : hc.is_healthy === false ? (
                          <span className="px-2 py-0.5 rounded bg-error/20 text-error font-semibold flex items-center gap-1 w-max">
                            <span className="w-1.5 h-1.5 rounded-full bg-error" />
                            Failing ({hc.last_probe_status_code || hc.last_probe_error || "ERR"})
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant">
                            Pending Probe
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-on-surface font-mono">
                        {hc.last_probe_latency_ms ? `${hc.last_probe_latency_ms.toFixed(1)} ms` : "—"}
                      </td>
                      <td className="p-3">
                        <span
                          className={`font-semibold ${
                            hc.consecutive_failures > 0 ? "text-error" : "text-on-surface-variant"
                          }`}
                        >
                          {hc.consecutive_failures}
                        </span>
                      </td>
                      <td className="p-3 text-on-surface-variant">
                        {hc.last_probed_at ? new Date(hc.last_probed_at).toLocaleTimeString() : "Never"}
                      </td>
                      <td className="p-3 text-right">
                        <button
                          onClick={() => handleProbeNow(hc.id)}
                          disabled={probingConfigId === hc.id}
                          className="px-2.5 py-1 rounded bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 font-medium transition-all disabled:opacity-50 flex items-center gap-1 ml-auto"
                        >
                          <span
                            className={`material-symbols-outlined text-xs ${
                              probingConfigId === hc.id ? "animate-spin" : ""
                            }`}
                          >
                            network_ping
                          </span>
                          {probingConfigId === hc.id ? "Probing..." : "Probe Now"}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 3: 12 Detection Rules & Thresholds */}
      {activeTab === "rules" && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {rules.map((rule) => (
              <div
                key={rule.rule_name}
                className={`p-4 rounded-xl border transition-all ${
                  rule.is_enabled
                    ? "bg-surface-container-low border-outline-variant hover:border-primary/50"
                    : "bg-surface-container-lowest/50 border-outline-variant opacity-60"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-mono text-sm font-semibold text-primary">
                      {rule.rule_name}
                    </div>
                    <div className="text-xs text-on-surface-variant mt-0.5">
                      Severity: <strong className="text-on-surface">{rule.severity_override || "Default"}</strong>
                    </div>
                  </div>

                  <button
                    onClick={() => handleToggleRule(rule)}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                      rule.is_enabled ? "bg-primary" : "bg-outline"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                        rule.is_enabled ? "translate-x-4" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>

                <div className="mt-4 pt-3 border-t border-outline-variant flex items-center justify-between text-xs">
                  <div>
                    <span className="text-on-surface-variant">Threshold: </span>
                    <strong className="text-on-surface">
                      {rule.threshold_value !== undefined && rule.threshold_value !== null
                        ? rule.threshold_value
                        : "Default"}
                    </strong>
                  </div>

                  <button
                    onClick={() => {
                      setEditingRule(rule);
                      setNewThreshold(rule.threshold_value ? String(rule.threshold_value) : "");
                    }}
                    className="px-2 py-1 rounded bg-surface-container hover:bg-surface-container-high text-primary border border-outline text-[11px] font-medium"
                  >
                    Edit Threshold
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Threshold Edit Modal */}
      {editingRule && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-container-low border border-outline p-6 rounded-2xl max-w-md w-full space-y-4 shadow-2xl">
            <h3 className="text-lg font-bold text-on-surface">
              Edit Threshold: {editingRule.rule_name}
            </h3>
            <p className="text-xs text-on-surface-variant">
              Adjust numerical trigger threshold or clear input to revert to built-in rule defaults.
            </p>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-1">
                Threshold Value
              </label>
              <input
                type="number"
                step="any"
                value={newThreshold}
                onChange={(e) => setNewThreshold(e.target.value)}
                placeholder="Enter threshold (e.g. 85.0)"
                className="w-full px-3 py-2 bg-surface-container rounded-lg border border-outline text-sm text-on-surface focus:outline-none focus:border-primary"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setEditingRule(null)}
                className="px-4 py-2 rounded-lg text-xs font-medium bg-surface-container text-on-surface hover:bg-surface-container-high border border-outline"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveThreshold}
                disabled={saveRuleLoading}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-primary text-on-primary hover:bg-primary/90 transition-all disabled:opacity-50 flex items-center gap-1.5"
              >
                {saveRuleLoading && (
                  <span className="material-symbols-outlined text-sm animate-spin">refresh</span>
                )}
                Save Configuration
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
