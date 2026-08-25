"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listRepositories, createIncident, Repository } from "@/lib/api";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

const sources = [
  { value: "manual", label: "Manual" },
  { value: "alert", label: "Alert" },
  { value: "prometheus", label: "Prometheus" },
  { value: "sentry", label: "Sentry" },
  { value: "webhook", label: "Webhook" },
  { value: "deployment_regression", label: "Deployment Regression" },
];

const severities = [
  { value: "SEV-1", label: "SEV-1", desc: "Critical outage, broad impact.", color: "error" },
  { value: "SEV-2", label: "SEV-2", desc: "Severe degradation.", color: "tertiary" },
  { value: "SEV-3", label: "SEV-3", desc: "Partial degradation.", color: "primary" },
  { value: "SEV-4", label: "SEV-4", desc: "Minor issue, monitoring.", color: "secondary" },
];

export default function NewIncident() {
  const { token } = useAuth();
  const router = useRouter();
  const [repos, setRepos] = useState<Repository[]>([]);
  const [services, setServices] = useState<{value: string; label: string}[]>([]);
  const [title, setTitle] = useState("");
  const [errorLog, setErrorLog] = useState("");
  const [service, setService] = useState("");
  const [source, setSource] = useState("manual");
  const [severity, setSeverity] = useState("SEV-1");
  const [selectedRepos, setSelectedRepos] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [autoDetect, setAutoDetect] = useState(true);
  const [additionalContext, setAdditionalContext] = useState("");
  const [incidentTime, setIncidentTime] = useState("");

  useEffect(() => {
    if (!token) return;
    listRepositories(token).then(setRepos).catch(console.error);
    fetch(`${API_BASE}/services/health`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((data) => {
        const svcs = (data.services || []).map((s: { service_name: string }) => ({
          value: s.service_name,
          label: s.service_name,
        }));
        setServices(svcs);
      })
      .catch(() => {});
  }, [token]);

  const toggleRepo = (id: string) => {
    setSelectedRepos((prev) =>
      prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setError("");
    setLoading(true);
    try {
      const incident = await createIncident(token, {
        title,
        description: errorLog + (additionalContext ? "\n\nAdditional context: " + additionalContext : ""),
        severity,
        service,
        source,
        repository_ids: autoDetect ? [] : selectedRepos,
      });
      router.push(`/incidents/${incident.id}`);
    } catch (err: any) {
      setError(err.message || "Failed to create incident");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <TopBar
        breadcrumbs={[
          { label: "Incidents", href: "/incidents" },
          { label: "Create Manual Incident", active: true },
        ]}
      />
      <main className="flex-1 p-6 overflow-y-auto pb-12">
        <div className="max-w-[1200px] mx-auto flex gap-6">
          {/* Main Form */}
          <div className="flex-1">
            <h1 className="text-[22px] font-semibold text-on-surface mb-1">Create Manual Incident</h1>
            <p className="text-[13px] text-on-surface-variant mb-6">
              Provide details about the issue you are facing. Sentinel will investigate and find the root cause.
            </p>

            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Step 1 - Describe the Issue */}
              <div className="bg-surface-container-low border border-outline-variant rounded-lg p-5">
                <div className="flex items-center gap-3 mb-4">
                  <span className="w-7 h-7 rounded-full bg-primary flex items-center justify-center text-[13px] font-bold text-on-primary">1</span>
                  <h2 className="text-[15px] font-semibold text-on-surface">Describe the Issue</h2>
                </div>
                <p className="text-[12px] text-on-surface-variant mb-4">
                  Paste error logs, stack traces, or any relevant details
                </p>
                <div className="relative">
                  <div className="absolute top-2 right-2 flex items-center gap-2">
                    <button type="button" className="text-[11px] text-on-surface-variant hover:text-primary flex items-center gap-1 transition-colors">
                      <span className="material-symbols-outlined text-[14px]">upload</span>
                      Import from file
                    </button>
                  </div>
                  <textarea
                    value={errorLog}
                    onChange={(e) => setErrorLog(e.target.value)}
                    className="w-full px-4 py-3 font-mono text-[13px] text-on-surface resize-y bg-surface-container border border-outline-variant rounded-md focus:border-primary focus:outline-none"
                    placeholder={"Paste error logs, stack traces, or alert messages here...\n\nExample:\n2026-08-25T10:30:00.000Z  ERROR  [service-name]\nConnection refused\n    at ..."}
                    rows={10}
                    required
                  />
                  <div className="text-right text-[11px] text-on-surface-variant mt-1">
                    {errorLog.length.toLocaleString()} / 50,000
                  </div>
                </div>
                <div className="mt-3">
                  <label className="text-[12px] text-on-surface-variant mb-1 block">Short summary (optional)</label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full px-3 py-2 text-[13px] text-on-surface bg-surface-container border border-outline-variant rounded-md focus:border-primary focus:outline-none"
                    placeholder="e.g., Database connection pool exhausted causing request failures"
                  />
                </div>
              </div>

              {/* Step 2 - Additional Context */}
              <div className="bg-surface-container-low border border-outline-variant rounded-lg p-5">
                <div className="flex items-center gap-3 mb-4">
                  <span className="w-7 h-7 rounded-full bg-primary flex items-center justify-center text-[13px] font-bold text-on-primary">2</span>
                  <h2 className="text-[15px] font-semibold text-on-surface">Additional Context</h2>
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="text-[12px] text-on-surface-variant mb-1 block">Incident Time (optional)</label>
                    <input
                      type="datetime-local"
                      value={incidentTime}
                      onChange={(e) => setIncidentTime(e.target.value)}
                      className="w-full px-3 py-2 text-[13px] text-on-surface bg-surface-container border border-outline-variant rounded-md focus:border-primary focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-[12px] text-on-surface-variant mb-1 block">Affected Service (optional)</label>
                    <div className="relative">
                      <select
                        value={service}
                        onChange={(e) => setService(e.target.value)}
                        className="w-full px-3 py-2 font-mono text-[13px] text-on-surface bg-surface-container border border-outline-variant rounded-md appearance-none pr-8 focus:border-primary focus:outline-none"
                      >
                        <option value="">Auto-detect from logs</option>
                        {services.map((s) => (
                          <option key={s.value} value={s.value}>{s.label}</option>
                        ))}
                      </select>
                      <span className="material-symbols-outlined absolute right-2 top-2.5 text-on-surface-variant pointer-events-none text-[16px]">
                        expand_more
                      </span>
                    </div>
                    <p className="text-[11px] text-on-surface-variant mt-1">Sentinel will identify the affected service automatically</p>
                  </div>
                </div>
                <div>
                  <label className="text-[12px] text-on-surface-variant mb-1 block">Anything else we should know? (optional)</label>
                  <input
                    type="text"
                    value={additionalContext}
                    onChange={(e) => setAdditionalContext(e.target.value)}
                    className="w-full px-3 py-2 text-[13px] text-on-surface bg-surface-container border border-outline-variant rounded-md focus:border-primary focus:outline-none"
                    placeholder="e.g., Issue started right after the deployment of v2.8.1"
                  />
                </div>
              </div>

              {/* Step 3 - Investigation Scope */}
              <div className="bg-surface-container-low border border-outline-variant rounded-lg p-5">
                <div className="flex items-center gap-3 mb-4">
                  <span className="w-7 h-7 rounded-full bg-primary flex items-center justify-center text-[13px] font-bold text-on-primary">3</span>
                  <h2 className="text-[15px] font-semibold text-on-surface">Investigation Scope</h2>
                </div>

                <div className="bg-surface-container rounded-md border border-outline-variant p-4 mb-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-medium text-on-surface">Repository & Service Discovery</span>
                        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">Recommended</span>
                      </div>
                      <p className="text-[12px] text-on-surface-variant mt-0.5">
                        Sentinel will automatically detect relevant services and repositories based on the error logs
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setAutoDetect(!autoDetect)}
                      className={`w-11 h-6 rounded-full transition-colors relative ${autoDetect ? "bg-primary" : "bg-surface-container-highest"}`}
                    >
                      <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${autoDetect ? "left-[22px]" : "left-0.5"}`} />
                    </button>
                  </div>
                  {!autoDetect && (
                    <div className="mt-3 pt-3 border-t border-outline-variant">
                      <p className="text-[12px] text-on-surface-variant mb-2">Select repositories:</p>
                      <div className="grid grid-cols-2 gap-2">
                        {repos.map((repo) => (
                          <label key={repo.id} className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={selectedRepos.includes(repo.id)}
                              onChange={() => toggleRepo(repo.id)}
                              className="w-4 h-4 rounded"
                            />
                            <span className="font-mono text-[12px] text-on-surface">{repo.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <button type="button" className="flex items-center gap-2 text-[12px] text-on-surface-variant hover:text-primary transition-colors">
                  <span className="material-symbols-outlined text-[16px]">expand_more</span>
                  Advanced Options (Narrow down repositories, branches, tags, etc.)
                </button>
              </div>

              {error && (
                <div className="text-[12px] text-error bg-error/10 border border-error/20 rounded-md p-3">
                  {error}
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-end gap-3">
                <Link
                  href="/incidents"
                  className="px-5 py-2.5 text-[12px] font-semibold uppercase tracking-wider text-on-surface-variant hover:text-on-surface border border-outline-variant rounded-md hover:bg-surface-container-high transition-colors"
                >
                  Cancel
                </Link>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-6 py-2.5 bg-primary-container text-on-primary-container text-[12px] font-semibold uppercase tracking-wider rounded-md border border-primary hover:bg-primary hover:text-on-primary-fixed transition-colors flex items-center gap-2 disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]">rocket_launch</span>
                  {loading ? "Investigating..." : "Start Investigation"}
                </button>
              </div>
            </form>
          </div>

          {/* Right Sidebar */}
          <div className="w-[300px] flex-shrink-0 space-y-4">
            {/* How Sentinel Helps */}
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <div className="flex items-center gap-2 mb-4">
                <span className="material-symbols-outlined text-[18px] text-primary">auto_awesome</span>
                <h3 className="text-[13px] font-semibold text-on-surface">How Sentinel Helps</h3>
              </div>
              <div className="space-y-4">
                {[
                  { icon: "settings_input_component", title: "Auto Discovers Impacted Services", desc: "We'll identify which services are affected and analyze their health and dependencies." },
                  { icon: "code", title: "Finds Relevant Code Changes", desc: "Sentinel reviews recent deployments, commits, and pull requests to find suspicious changes." },
                  { icon: "analytics", title: "Analyzes Logs, Metrics & Traces", desc: "We correlate logs, metrics, and traces to pinpoint the exact failure point." },
                  { icon: "psychology", title: "Generates Root Cause Hypothesis", desc: "Multiple hypotheses are evaluated with evidence to find the most likely root cause." },
                  { icon: "build", title: "Proposes & Validates Fix", desc: "A fix is generated, tested, and presented for your review as a draft PR." },
                ].map((item) => (
                  <div key={item.title} className="flex gap-3">
                    <span className="material-symbols-outlined text-[18px] text-primary/60 mt-0.5">{item.icon}</span>
                    <div>
                      <div className="text-[12px] font-medium text-on-surface">{item.title}</div>
                      <div className="text-[11px] text-on-surface-variant leading-relaxed">{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* What happens next */}
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
              <h3 className="text-[13px] font-semibold text-on-surface mb-4">What happens next?</h3>
              <div className="space-y-4">
                {[
                  { step: 1, title: "Investigation will begin immediately", desc: "You'll be able to track progress in real-time." },
                  { step: 2, title: "We'll notify you when root cause is identified", desc: "You'll receive a notification and can review the findings." },
                  { step: 3, title: "Review & approve the proposed fix", desc: "Approve to create a draft pull request." },
                ].map((item) => (
                  <div key={item.step} className="flex gap-3">
                    <span className="w-6 h-6 rounded-full bg-surface-container-highest flex items-center justify-center text-[11px] font-bold text-on-surface-variant flex-shrink-0">
                      {item.step}
                    </span>
                    <div>
                      <div className="text-[12px] font-medium text-on-surface">{item.title}</div>
                      <div className="text-[11px] text-on-surface-variant">{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
              <Link href="/automatic-response" className="block mt-4 text-[12px] text-primary hover:underline">
                View sample investigation →
              </Link>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
