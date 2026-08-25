"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listRepositories, getGithubStatus, Repository } from "@/lib/api";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

const integrations = [
  {
    id: "github",
    name: "GitHub",
    description: "Sync repositories, commits, PRs, and branches. Enable automatic investigation on push/deployment.",
    icon: "folder",
    color: "text-primary",
    features: ["Repository sync", "Commit history", "Pull requests", "Branch management", "Webhook events"],
    oauthPath: "/github/login",
  },
  {
    id: "webhooks",
    name: "Webhook Receivers",
    description: "Receive alerts from PagerDuty, Datadog, Sentry, Slack, and custom sources.",
    icon: "webhook",
    color: "text-tertiary",
    features: ["PagerDuty", "Datadog", "Sentry", "Slack", "Generic webhooks"],
    configPath: "/webhooks/config",
  },
  {
    id: "prometheus",
    name: "Prometheus",
    description: "Ingest metrics and alerts for automatic incident detection.",
    icon: "monitoring",
    color: "text-tertiary",
    features: ["Metric queries", "Alert rules", "Recording rules"],
  },
  {
    id: "sentry",
    name: "Sentry",
    description: "Track errors and exceptions for incident context.",
    icon: "bug_report",
    color: "text-error",
    features: ["Error tracking", "Stack traces", "Release tracking"],
  },
];

function IntegrationsContent() {
  const { token } = useAuth();
  const searchParams = useSearchParams();
  const justConnected = searchParams.get("connected") === "github";
  const [repos, setRepos] = useState<Repository[]>([]);
  const [githubConnected, setGithubConnected] = useState(false);
  const [githubConfigured, setGithubConfigured] = useState(false);

  useEffect(() => {
    if (!token) return;
    listRepositories(token)
      .then((r) => {
        setRepos(r);
        if (r.length > 0) setGithubConnected(true);
      })
      .catch(() => {});
    getGithubStatus(token)
      .then((s) => {
        setGithubConfigured(s.configured);
        if (s.connected) setGithubConnected(true);
      })
      .catch(() => {});
  }, [token]);

  return (
    <>
      <TopBar
        title="Integrations"
        subtitle="Connect external services and data sources"
        breadcrumbs={[{ label: "Integrations", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto space-y-6">
          {/* Success banner */}
          {justConnected && (
            <div className="bg-primary/10 border border-primary/20 rounded-lg p-4 flex items-center gap-3">
              <span className="material-symbols-outlined text-primary">check_circle</span>
              <div>
                <div className="text-[13px] font-semibold text-primary">GitHub Connected Successfully</div>
                <div className="text-[12px] text-on-surface-variant">Your GitHub account is now linked. Sync repos to start investigating.</div>
              </div>
            </div>
          )}

          {integrations.map((intg) => {
            const isConnected = intg.id === "github" ? githubConnected : intg.id === "webhooks" ? true : false;
            return (
              <div key={intg.id} className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
                <div className="flex items-start gap-4">
                  <div className={`w-10 h-10 rounded-lg bg-surface-container flex items-center justify-center`}>
                    <span className={`material-symbols-outlined text-[20px] ${intg.color}`}>{intg.icon}</span>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-1">
                      <h3 className="text-[13px] font-semibold text-on-surface">{intg.name}</h3>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                        isConnected ? "bg-primary/10 text-primary" : "bg-outline/10 text-outline"
                      }`}>
                        {isConnected ? "Connected" : "Not Connected"}
                      </span>
                    </div>
                    <p className="text-[12px] text-on-surface-variant mb-3">{intg.description}</p>
                    <div className="flex flex-wrap gap-2 mb-3">
                      {intg.features.map((f) => (
                        <span key={f} className="px-2 py-0.5 bg-surface-container rounded text-[10px] text-on-surface-variant">
                          {f}
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-2 flex-wrap">
                      {intg.id === "github" && !githubConnected && (
                        <button
                          onClick={() => { window.location.href = `${API_BASE}/github/login`; }}
                          className="px-4 py-1.5 bg-primary text-on-primary rounded text-[12px] font-medium hover:bg-primary/90 transition-colors"
                        >
                          Connect GitHub
                        </button>
                      )}
                      {intg.id === "github" && githubConnected && (
                        <>
                          <Link
                            href="/repositories"
                            className="px-4 py-1.5 bg-surface-container border border-outline-variant text-on-surface rounded text-[12px] font-medium hover:bg-surface-container-high transition-colors"
                          >
                            View Repos ({repos.length})
                          </Link>
                          <button
                            onClick={() => { window.location.href = `${API_BASE}/github/login`; }}
                            className="px-4 py-1.5 bg-surface-container border border-outline-variant text-on-surface-variant rounded text-[12px] font-medium hover:bg-surface-container-high transition-colors"
                          >
                            Re-authenticate
                          </button>
                        </>
                      )}
                      {intg.id === "webhooks" && (
                        <Link
                          href="/webhooks/config"
                          className="px-4 py-1.5 bg-surface-container border border-outline-variant text-on-surface rounded text-[12px] font-medium hover:bg-surface-container-high transition-colors"
                        >
                          View Endpoints
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}

          {/* Webhook Endpoints */}
          <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
            <h3 className="text-[13px] font-semibold text-on-surface mb-3">Webhook Endpoints</h3>
            <p className="text-[12px] text-on-surface-variant mb-3">
              POST JSON payloads to these endpoints. Sentinel auto-detects the source format.
            </p>
            <div className="space-y-2 font-mono text-[11px]">
              {["pagerduty", "datadog", "sentry", "slack", "generic"].map((source) => (
                <div key={source} className="flex items-center gap-3 p-2 bg-surface-container rounded">
                  <span className="text-on-surface-variant w-20">{source}</span>
                  <span className="text-primary">{API_BASE}/webhooks/{source}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

export default function IntegrationsPage() {
  return (
    <Suspense fallback={<div className="flex-1 p-6"><div className="text-on-surface-variant text-[13px]">Loading...</div></div>}>
      <IntegrationsContent />
    </Suspense>
  );
}
