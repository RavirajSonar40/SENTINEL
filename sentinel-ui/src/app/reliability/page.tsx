"use client";

import { useEffect, useState, useCallback } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import {
  reliabilityApi,
  SLOConfigItem,
  SLOBurnDownResponse,
  PredictiveAnomalyItem,
  BusinessImpactConfigItem,
} from "@/lib/reliabilityApi";

const burnStatusBadge: Record<string, { bg: string; text: string; label: string }> = {
  critical_page: { bg: "bg-red-500/20 border-red-500/40 text-red-400 font-bold animate-pulse", text: "text-red-400", label: "Critical 14.4x" },
  elevated: { bg: "bg-amber-500/20 border-amber-500/40 text-amber-400 font-semibold", text: "text-amber-400", label: "Elevated 6.0x" },
  normal: { bg: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400", text: "text-emerald-400", label: "Normal 1.0x" },
  insufficient_data: { bg: "bg-zinc-500/10 border-zinc-500/20 text-zinc-400", text: "text-zinc-400", label: "No Traffic" },
};

export default function ReliabilityHubPage() {
  const { token } = useAuth();
  const [activeTab, setActiveTab] = useState<"slos" | "predictions" | "impact">("slos");
  const [slos, setSlos] = useState<SLOConfigItem[]>([]);
  const [predictions, setPredictions] = useState<PredictiveAnomalyItem[]>([]);
  const [impactConfigs, setImpactConfigs] = useState<BusinessImpactConfigItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Burn-down Inspection Modal
  const [selectedSlo, setSelectedSlo] = useState<SLOConfigItem | null>(null);
  const [burnDownData, setBurnDownData] = useState<SLOBurnDownResponse | null>(null);
  const [loadingBurnDown, setLoadingBurnDown] = useState(false);

  // Create SLO Modal
  const [showCreateSlo, setShowCreateSlo] = useState(false);
  const [newSloServiceId, setNewSloServiceId] = useState("");
  const [newSloName, setNewSloName] = useState("");
  const [newSloTarget, setNewSloTarget] = useState(99.9);
  const [newSloType, setNewSloType] = useState("availability");
  const [newSloThreshold, setNewSloThreshold] = useState<number | undefined>(undefined);
  const [creatingSlo, setCreatingSlo] = useState(false);

  // Acknowledge Prediction
  const [ackLoading, setAckLoading] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [slosRes, predsRes, impactRes] = await Promise.all([
        reliabilityApi.getSLOs(),
        reliabilityApi.getPredictions("ALL"),
        reliabilityApi.getBusinessImpactConfigs(),
      ]);
      setSlos(slosRes);
      setPredictions(predsRes);
      setImpactConfigs(impactRes);
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load reliability data";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleInspectBurnDown = async (slo: SLOConfigItem) => {
    setSelectedSlo(slo);
    setLoadingBurnDown(true);
    try {
      const res = await reliabilityApi.getSLOBurnDown(slo.id);
      setBurnDownData(res);
    } catch (err: unknown) {
      console.error("Failed to load burn down", err);
    } finally {
      setLoadingBurnDown(false);
    }
  };

  const handleCreateSlo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSloServiceId || !newSloName) return;
    setCreatingSlo(true);
    try {
      await reliabilityApi.createSLO({
        service_id: newSloServiceId,
        name: newSloName,
        target_percent: Number(newSloTarget),
        sli_type: newSloType,
        threshold_value: newSloThreshold ? Number(newSloThreshold) : undefined,
      });
      setShowCreateSlo(false);
      setNewSloName("");
      setNewSloServiceId("");
      setFeedbackMessage("SLO target successfully configured!");
      fetchData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create SLO";
      setFeedbackMessage(`Error: ${msg}`);
    } finally {
      setCreatingSlo(false);
    }
  };

  const handleAcknowledgePrediction = async (anomalyId: string) => {
    setAckLoading(anomalyId);
    try {
      await reliabilityApi.acknowledgePrediction(anomalyId);
      setFeedbackMessage("Predictive anomaly acknowledged by operator.");
      fetchData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Action failed";
      setFeedbackMessage(`Error: ${msg}`);
    } finally {
      setAckLoading(null);
    }
  };

  const criticalBurnCount = slos.filter((s) => s.burn_rates.burn_status_1h === "critical_page").length;
  const activePredsCount = predictions.filter((p) => p.status === "ACTIVE").length;

  return (
    <>
      <TopBar
        title="SLO & Advanced Reliability Hub"
        subtitle="Multi-window error budget tracking, OLS predictive drift anomaly forecasting, and financial impact quantification"
        breadcrumbs={[{ label: "Reliability", active: true }]}
      />
      <main className="flex-1 p-6 pb-12 overflow-y-auto bg-surface text-on-surface">
        <div className="max-w-[1500px] mx-auto space-y-6">

          {/* Operational Metrics Strip */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-on-surface-variant font-mono">Configured SLOs</div>
                <div className="text-2xl font-bold text-on-surface mt-1 font-mono">{slos.length}</div>
              </div>
              <span className="material-symbols-outlined text-primary text-[28px]">speed</span>
            </div>

            <div className="bg-surface-container-low border border-emerald-500/30 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-emerald-400 font-mono">Healthy Error Budgets</div>
                <div className="text-2xl font-bold text-emerald-400 mt-1 font-mono">
                  {slos.filter((s) => s.status === "healthy").length}
                </div>
              </div>
              <span className="material-symbols-outlined text-emerald-400 text-[28px]">savings</span>
            </div>

            <div className="bg-surface-container-low border border-red-500/30 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-red-400 font-mono">Critical Burn Rate (14.4x)</div>
                <div className="text-2xl font-bold text-red-400 mt-1 font-mono">{criticalBurnCount}</div>
              </div>
              <span className="material-symbols-outlined text-red-400 text-[28px]">local_fire_department</span>
            </div>

            <div className="bg-surface-container-low border border-amber-500/30 rounded-xl p-4 flex items-center justify-between">
              <div>
                <div className="text-[11px] text-amber-400 font-mono">Predictive Anomaly Warnings</div>
                <div className="text-2xl font-bold text-amber-400 mt-1 font-mono">{activePredsCount}</div>
              </div>
              <span className="material-symbols-outlined text-amber-400 text-[28px]">radar</span>
            </div>
          </div>

          {feedbackMessage && (
            <div className="p-3 rounded-lg bg-surface-container border border-outline-variant text-[12px] font-mono text-primary flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px]">info</span>
                {feedbackMessage}
              </div>
              <button onClick={() => setFeedbackMessage(null)} className="text-on-surface-variant hover:text-on-surface">
                <span className="material-symbols-outlined text-[14px]">close</span>
              </button>
            </div>
          )}

          {error && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-[12px] flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px]">error</span>
              {error}
            </div>
          )}

          {/* Tabs Navigation */}
          <div className="flex border-b border-outline-variant/60 gap-6">
            <button
              onClick={() => setActiveTab("slos")}
              className={`pb-3 text-[13px] font-semibold flex items-center gap-2 border-b-2 transition-colors ${
                activeTab === "slos"
                  ? "border-primary text-primary"
                  : "border-transparent text-on-surface-variant hover:text-on-surface"
              }`}
            >
              <span className="material-symbols-outlined text-[18px]">query_stats</span>
              Service Level Objectives (SLOs) & Burn Rates
            </button>

            <button
              onClick={() => setActiveTab("predictions")}
              className={`pb-3 text-[13px] font-semibold flex items-center gap-2 border-b-2 transition-colors ${
                activeTab === "predictions"
                  ? "border-primary text-primary"
                  : "border-transparent text-on-surface-variant hover:text-on-surface"
              }`}
            >
              <span className="material-symbols-outlined text-[18px]">radar</span>
              Predictive Anomaly Early Warning Radar ({activePredsCount})
            </button>

            <button
              onClick={() => setActiveTab("impact")}
              className={`pb-3 text-[13px] font-semibold flex items-center gap-2 border-b-2 transition-colors ${
                activeTab === "impact"
                  ? "border-primary text-primary"
                  : "border-transparent text-on-surface-variant hover:text-on-surface"
              }`}
            >
              <span className="material-symbols-outlined text-[18px]">attach_money</span>
              Financial Baselines & Business Impact Config
            </button>
          </div>

          {/* TAB 1: SLOS & BURN RATES */}
          {activeTab === "slos" && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-[12px] text-on-surface-variant">
                  Google SRE standard multi-window burn rate monitoring (1h 14.4x emergency page, 6h 6.0x, 24h 1.0x).
                </p>
                <button
                  onClick={() => setShowCreateSlo(true)}
                  className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-on-primary text-[12px] font-semibold transition flex items-center gap-1.5 shadow-sm"
                >
                  <span className="material-symbols-outlined text-[16px]">add</span>
                  Declare Service SLO Target
                </button>
              </div>

              <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-[12px]">
                    <thead className="bg-surface-container/60 border-b border-outline-variant/60 text-on-surface-variant font-mono">
                      <tr>
                        <th className="py-3 px-4">Service & SLO Name</th>
                        <th className="py-3 px-4">SLI Type & Target</th>
                        <th className="py-3 px-4">Compliance (30d)</th>
                        <th className="py-3 px-4">Error Budget Left</th>
                        <th className="py-3 px-4">Burn Rates (1h / 6h / 24h)</th>
                        <th className="py-3 px-4">Time to Exhaustion</th>
                        <th className="py-3 px-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-outline-variant/40">
                      {loading ? (
                        <tr>
                          <td colSpan={7} className="py-12 text-center text-on-surface-variant font-mono">
                            Loading SLO compliance and burn rate snapshots...
                          </td>
                        </tr>
                      ) : slos.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="py-12 text-center text-on-surface-variant">
                            No service SLOs configured. Click &ldquo;Declare Service SLO Target&rdquo; to start tracking error budgets.
                          </td>
                        </tr>
                      ) : (
                        slos.map((s) => {
                          const badge1h = burnStatusBadge[s.burn_rates.burn_status_1h] || burnStatusBadge.normal;
                          return (
                            <tr key={s.id} className="hover:bg-surface-container-high/40 transition">
                              {/* Service & Name */}
                              <td className="py-3 px-4 space-y-0.5">
                                <div className="font-semibold text-on-surface">{s.name}</div>
                                <div className="text-[11px] text-on-surface-variant font-mono">{s.service_name}</div>
                              </td>

                              {/* SLI Type & Target */}
                              <td className="py-3 px-4 font-mono text-[11px]">
                                <span className="px-2 py-0.5 rounded bg-surface-container-high border border-outline-variant capitalize font-semibold">
                                  {s.sli_type}
                                </span>
                                <div className="text-on-surface-variant mt-0.5">Target: {s.target_percent}%</div>
                              </td>

                              {/* 30d Compliance */}
                              <td className="py-3 px-4 font-mono">
                                <span className={s.current_compliance_percent && s.current_compliance_percent < s.target_percent ? "text-red-400 font-bold" : "text-emerald-400 font-semibold"}>
                                  {s.compliance_display}
                                </span>
                                <div className="text-[10px] text-on-surface-variant">{s.total_samples_observed} samples</div>
                              </td>

                              {/* Error Budget Left */}
                              <td className="py-3 px-4 space-y-1.5 w-44">
                                <div className="flex items-center justify-between text-[11px] font-mono">
                                  <span>{s.budget_display}</span>
                                </div>
                                <div className="w-full bg-surface-container-high h-2 rounded-full overflow-hidden">
                                  <div
                                    className={`h-full ${s.budget_remaining_percent && s.budget_remaining_percent < 20 ? "bg-red-400" : "bg-emerald-400"}`}
                                    style={{ width: `${s.budget_remaining_percent ?? 0}%` }}
                                  />
                                </div>
                              </td>

                              {/* Burn Rates */}
                              <td className="py-3 px-4 font-mono text-[11px] space-y-1">
                                <div className="flex items-center gap-1.5">
                                  <span className={`px-1.5 py-0.5 rounded text-[10px] border ${badge1h.bg}`}>
                                    1h: {s.burn_rates.burn_rate_1h !== null ? `${s.burn_rates.burn_rate_1h}x` : "—"}
                                  </span>
                                  <span className="text-[10px] text-on-surface-variant">
                                    6h: {s.burn_rates.burn_rate_6h !== null ? `${s.burn_rates.burn_rate_6h}x` : "—"}
                                  </span>
                                </div>
                              </td>

                              {/* Time to Exhaustion */}
                              <td className="py-3 px-4 font-mono text-[11px]">
                                <span className={`font-semibold ${s.time_to_exhaustion.status === "critical_burn" ? "text-red-400 font-bold" : (s.time_to_exhaustion.status === "warning" ? "text-amber-400" : "text-on-surface")}`}>
                                  {s.time_to_exhaustion.display}
                                </span>
                              </td>

                              {/* Actions */}
                              <td className="py-3 px-4 text-right">
                                <button
                                  onClick={() => handleInspectBurnDown(s)}
                                  className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant text-[11px] font-medium transition"
                                >
                                  Burn-Down
                                </button>
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: PREDICTIVE ANOMALY RADAR */}
          {activeTab === "predictions" && (
            <div className="space-y-4">
              <p className="text-[12px] text-on-surface-variant">
                Ordinary Least Squares (OLS) regression analyzing metric slope and $R^2 \ge 0.70$ correlation to project resource exhaustion before threshold breaches occur.
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {predictions.length === 0 ? (
                  <div className="col-span-2 p-12 bg-surface-container-low border border-outline-variant/60 rounded-xl text-center space-y-2">
                    <span className="material-symbols-outlined text-emerald-400 text-[36px]">verified</span>
                    <p className="text-[13px] font-medium text-on-surface">No Projected Resource Exhaustion Anomalies</p>
                    <p className="text-[11px] text-on-surface-variant">All telemetry gradients (CPU, Memory, Latency, Queue Backlog) are within stable operational slopes.</p>
                  </div>
                ) : (
                  predictions.map((p) => (
                    <div key={p.id} className="p-4 bg-surface-container-low border border-outline-variant/60 rounded-xl space-y-3 shadow-sm">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold border font-mono ${p.severity === "CRITICAL_BREACH_ACTIVE" ? "bg-red-500/20 border-red-500 text-red-400 animate-pulse" : (p.severity === "CRITICAL" ? "bg-red-500/10 border-red-500/30 text-red-400" : "bg-amber-500/10 border-amber-500/30 text-amber-400")}`}>
                            {p.severity}
                          </span>
                          <span className="font-semibold text-on-surface text-[13px]">{p.service_name}</span>
                        </div>
                        <span className="text-[11px] font-mono text-primary font-bold">
                          {p.time_to_breach_minutes > 0 ? `Breach in ~${p.time_to_breach_minutes}m` : "ACTIVE BREACH"}
                        </span>
                      </div>

                      <div className="grid grid-cols-2 gap-2 p-2.5 rounded-lg bg-surface-container border border-outline-variant/40 text-[11px] font-mono">
                        <div><span className="text-on-surface-variant">Metric:</span> {p.metric_name}</div>
                        <div><span className="text-on-surface-variant">Current / Limit:</span> {p.current_value.toFixed(1)} / {p.threshold_value.toFixed(1)}</div>
                        <div><span className="text-on-surface-variant">Growth Rate:</span> +{p.growth_rate_per_minute}/min</div>
                        <div><span className="text-on-surface-variant">Confidence (R²):</span> {(p.r_squared * 100).toFixed(0)}%</div>
                      </div>

                      {p.recommendation && (
                        <p className="text-[11px] text-amber-200/90 bg-amber-500/10 p-2.5 rounded border border-amber-500/20 leading-relaxed">
                          {p.recommendation}
                        </p>
                      )}

                      <div className="flex items-center justify-between pt-1">
                        <span className="text-[10px] text-on-surface-variant font-mono">Status: {p.status}</span>
                        {p.status === "ACTIVE" && (
                          <button
                            onClick={() => handleAcknowledgePrediction(p.id)}
                            disabled={ackLoading === p.id}
                            className="px-3 py-1 rounded bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant text-[11px] font-semibold transition"
                          >
                            {ackLoading === p.id ? "Acknowledging..." : "Acknowledge"}
                          </button>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {/* TAB 3: FINANCIAL REVENUE BASELINES */}
          {activeTab === "impact" && (
            <div className="space-y-4">
              <p className="text-[12px] text-on-surface-variant">
                Configured hourly revenue loss rates and active user transaction baselines for automated financial quantification during incidents.
              </p>

              <div className="bg-surface-container-low border border-outline-variant/60 rounded-xl overflow-hidden shadow-sm">
                <table className="w-full text-left text-[12px]">
                  <thead className="bg-surface-container/60 border-b border-outline-variant/60 text-on-surface-variant font-mono">
                    <tr>
                      <th className="py-3 px-4">Service / Tier</th>
                      <th className="py-3 px-4">Scope</th>
                      <th className="py-3 px-4">Hourly Revenue Rate</th>
                      <th className="py-3 px-4">Active Users Baseline</th>
                      <th className="py-3 px-4">Currency</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-outline-variant/40">
                    {impactConfigs.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="py-8 text-center text-on-surface-variant">
                          No revenue baselines configured. System returns &ldquo;— (Unconfigured)&rdquo; without silent guesses.
                        </td>
                      </tr>
                    ) : (
                      impactConfigs.map((c) => (
                        <tr key={c.id} className="hover:bg-surface-container-high/40 transition">
                          <td className="py-3 px-4 font-semibold text-on-surface">
                            {c.service_name || (c.tier ? `Tier Default (${c.tier})` : "Organization Default")}
                          </td>
                          <td className="py-3 px-4">
                            <span className="px-2 py-0.5 rounded bg-surface-container-high border border-outline-variant text-[10px] font-mono">
                              {c.is_org_default ? "GLOBAL FALLBACK" : "SPECIFIC SERVICE"}
                            </span>
                          </td>
                          <td className="py-3 px-4 font-mono font-bold text-emerald-400">
                            ${c.hourly_revenue_rate_usd.toLocaleString()}/hr
                          </td>
                          <td className="py-3 px-4 font-mono text-on-surface">
                            {c.active_users_baseline.toLocaleString()} users
                          </td>
                          <td className="py-3 px-4 font-mono text-on-surface-variant">{c.currency}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* DECLARE SLO MODAL */}
          {showCreateSlo && (
            <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
              <form onSubmit={handleCreateSlo} className="bg-surface-container-low border border-outline-variant rounded-xl max-w-lg w-full overflow-hidden shadow-2xl space-y-4 p-5">
                <div className="flex items-center justify-between border-b border-outline-variant pb-3">
                  <h3 className="text-[14px] font-semibold text-on-surface flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-[20px]">add_chart</span>
                    Declare Service SLO Target
                  </h3>
                  <button type="button" onClick={() => setShowCreateSlo(false)} className="text-on-surface-variant hover:text-on-surface">
                    <span className="material-symbols-outlined text-[18px]">close</span>
                  </button>
                </div>

                <div className="space-y-3 text-[12px]">
                  <div>
                    <label className="block text-[11px] font-mono text-on-surface-variant mb-1">Service ID (UUID)</label>
                    <input
                      type="text"
                      required
                      placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
                      value={newSloServiceId}
                      onChange={(e) => setNewSloServiceId(e.target.value)}
                      className="w-full px-3 py-1.5 bg-surface-container border border-outline-variant rounded-lg font-mono focus:outline-none focus:border-primary"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono text-on-surface-variant mb-1">SLO Name</label>
                    <input
                      type="text"
                      required
                      placeholder="e.g. Availability 99.9% in Production"
                      value={newSloName}
                      onChange={(e) => setNewSloName(e.target.value)}
                      className="w-full px-3 py-1.5 bg-surface-container border border-outline-variant rounded-lg focus:outline-none focus:border-primary"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-[11px] font-mono text-on-surface-variant mb-1">Target %</label>
                      <input
                        type="number"
                        step="0.01"
                        min="50"
                        max="100"
                        required
                        value={newSloTarget}
                        onChange={(e) => setNewSloTarget(parseFloat(e.target.value))}
                        className="w-full px-3 py-1.5 bg-surface-container border border-outline-variant rounded-lg font-mono focus:outline-none focus:border-primary"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] font-mono text-on-surface-variant mb-1">SLI Type</label>
                      <select
                        value={newSloType}
                        onChange={(e) => setNewSloType(e.target.value)}
                        className="w-full px-3 py-1.5 bg-surface-container border border-outline-variant rounded-lg focus:outline-none focus:border-primary"
                      >
                        <option value="availability">Availability</option>
                        <option value="latency">Latency</option>
                        <option value="error_rate">Error Rate</option>
                      </select>
                    </div>
                  </div>

                  {newSloType === "latency" && (
                    <div>
                      <label className="block text-[11px] font-mono text-on-surface-variant mb-1">Latency Threshold (ms)</label>
                      <input
                        type="number"
                        placeholder="e.g. 200"
                        value={newSloThreshold || ""}
                        onChange={(e) => setNewSloThreshold(parseFloat(e.target.value))}
                        className="w-full px-3 py-1.5 bg-surface-container border border-outline-variant rounded-lg font-mono focus:outline-none focus:border-primary"
                      />
                    </div>
                  )}
                </div>

                <div className="pt-3 border-t border-outline-variant flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setShowCreateSlo(false)}
                    className="px-3 py-1.5 rounded-lg bg-surface-container border border-outline-variant text-[12px]"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={creatingSlo}
                    className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-on-primary text-[12px] font-semibold transition"
                  >
                    {creatingSlo ? "Creating..." : "Save SLO Target"}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* BURN-DOWN INSPECTOR MODAL */}
          {selectedSlo && (
            <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
              <div className="bg-surface-container-low border border-outline-variant rounded-xl max-w-2xl w-full p-5 space-y-4 shadow-2xl">
                <div className="flex items-center justify-between border-b border-outline-variant pb-3">
                  <div>
                    <h3 className="text-[14px] font-semibold text-on-surface">{selectedSlo.name}</h3>
                    <p className="text-[11px] text-on-surface-variant font-mono">{selectedSlo.service_name} • Target: {selectedSlo.target_percent}%</p>
                  </div>
                  <button onClick={() => setSelectedSlo(null)} className="text-on-surface-variant hover:text-on-surface">
                    <span className="material-symbols-outlined text-[18px]">close</span>
                  </button>
                </div>

                {loadingBurnDown ? (
                  <div className="py-12 text-center text-on-surface-variant font-mono text-[12px]">
                    Loading burn-down telemetry points...
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-3 p-3 bg-surface-container rounded-lg font-mono text-[11px]">
                      <div>Budget Remaining: <strong className="text-emerald-400">{selectedSlo.budget_display}</strong></div>
                      <div>Time to Exhaustion: <strong className="text-primary">{selectedSlo.time_to_exhaustion.display}</strong></div>
                    </div>

                    <div className="max-h-60 overflow-y-auto space-y-1.5 divide-y divide-outline-variant/30 text-[11px] font-mono">
                      {burnDownData?.points.length ? (
                        burnDownData.points.map((pt, idx) => (
                          <div key={idx} className="pt-1.5 first:pt-0 flex items-center justify-between text-on-surface">
                            <span>{new Date(pt.timestamp).toLocaleDateString()} {new Date(pt.timestamp).toLocaleTimeString()}</span>
                            <span>Budget: {pt.budget_remaining_percent.toFixed(1)}%</span>
                            <span className="text-amber-400">Burn: {pt.burn_rate.toFixed(1)}x</span>
                          </div>
                        ))
                      ) : (
                        <div className="py-6 text-center text-on-surface-variant text-[11px]">
                          No historical snapshot points recorded yet.
                        </div>
                      )}
                    </div>
                  </div>
                )}

                <div className="pt-3 border-t border-outline-variant flex justify-end">
                  <button
                    onClick={() => setSelectedSlo(null)}
                    className="px-3 py-1.5 rounded-lg bg-surface-container border border-outline-variant text-[12px]"
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>
          )}

        </div>
      </main>
    </>
  );
}
