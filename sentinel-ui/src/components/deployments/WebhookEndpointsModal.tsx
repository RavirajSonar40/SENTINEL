"use client";

import React, { useState, useEffect } from "react";
import { deploymentsApi, WebhookEndpoint } from "@/lib/deploymentsApi";

interface WebhookEndpointsModalProps {
  token?: string;
  onClose: () => void;
}

export default function WebhookEndpointsModal({
  token,
  onClose,
}: WebhookEndpointsModalProps) {
  const [endpoints, setEndpoints] = useState<WebhookEndpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [newEndpointName, setNewEndpointName] = useState("");
  const [newEndpointProvider, setNewEndpointProvider] = useState("generic");
  const [creating, setCreating] = useState(false);
  const [createdSecretData, setCreatedSecretData] = useState<{ key_id: string; raw_secret: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = React.useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    deploymentsApi.getWebhookEndpoints(token)
      .then((list) => {
        setEndpoints(list);
      })
      .catch((err: unknown) => {
        setError((err as Error).message || "Failed to load webhook endpoints");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [token, refreshKey]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newEndpointName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const ep = await deploymentsApi.createWebhookEndpoint(newEndpointName.trim(), newEndpointProvider, token);
      if (ep.raw_secret) {
        setCreatedSecretData({
          key_id: ep.key_id,
          raw_secret: ep.raw_secret,
        });
      }
      setNewEndpointName("");
      reload();
    } catch (err: unknown) {
      setError((err as Error).message || "Failed to create webhook endpoint");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to deactivate and delete this webhook endpoint?")) return;
    try {
      await deploymentsApi.deleteWebhookEndpoint(id, token);
      reload();
    } catch (err: unknown) {
      setError((err as Error).message || "Failed to delete webhook endpoint");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-neutral-900 border border-neutral-800 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        <div className="px-6 py-5 border-b border-neutral-800 flex items-center justify-between bg-neutral-950/40">
          <div className="flex items-center gap-2.5">
            <span className="material-symbols-outlined text-purple-400">key</span>
            <div>
              <h3 className="text-base font-semibold text-neutral-100">CI/CD Webhook Endpoints & Secrets</h3>
              <p className="text-xs text-neutral-400">Generate signed HMAC-SHA256 credentials for GitHub, GitLab, Jenkins, ArgoCD & generic pipelines</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 transition"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="p-6 overflow-y-auto space-y-6 flex-1">
          {error && (
            <div className="p-3 rounded-xl bg-rose-950/50 border border-rose-800/60 text-rose-300 text-xs flex items-center gap-2">
              <span className="material-symbols-outlined text-sm">error</span>
              <span>{error}</span>
            </div>
          )}

          {/* One-time Secret Reveal Banner */}
          {createdSecretData && (
            <div className="p-4 rounded-xl bg-emerald-950/60 border border-emerald-800/80 space-y-3 animate-in fade-in duration-200">
              <div className="flex items-center gap-2 text-emerald-400 font-semibold text-sm">
                <span className="material-symbols-outlined text-base">verified_user</span>
                <span>Webhook Key & Secret Generated Successfully</span>
              </div>
              <p className="text-xs text-emerald-200/80">
                Please copy the secret key now. For your security, this raw secret will <strong>never be shown again</strong>.
              </p>
              <div className="space-y-2 font-mono text-xs">
                <div className="flex items-center justify-between p-2 rounded bg-neutral-950/80 border border-neutral-800">
                  <span className="text-neutral-400">X-Sentinel-Key-ID:</span>
                  <div className="flex items-center gap-2">
                    <span className="text-neutral-200 font-bold">{createdSecretData.key_id}</span>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(createdSecretData.key_id);
                        setCopiedKey(true);
                        setTimeout(() => setCopiedKey(false), 2000);
                      }}
                      className="text-xs text-blue-400 hover:underline"
                    >
                      {copiedKey ? "Copied!" : "Copy"}
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between p-2 rounded bg-neutral-950/80 border border-neutral-800">
                  <span className="text-neutral-400">HMAC Secret:</span>
                  <div className="flex items-center gap-2">
                    <span className="text-emerald-300 font-bold">{createdSecretData.raw_secret}</span>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(createdSecretData.raw_secret);
                        setCopiedSecret(true);
                        setTimeout(() => setCopiedSecret(false), 2000);
                      }}
                      className="text-xs text-emerald-400 hover:underline"
                    >
                      {copiedSecret ? "Copied!" : "Copy"}
                    </button>
                  </div>
                </div>
              </div>
              <button
                onClick={() => setCreatedSecretData(null)}
                className="text-xs text-neutral-400 hover:text-neutral-200 underline mt-1"
              >
                Dismiss
              </button>
            </div>
          )}

          {/* Create Form */}
          <form onSubmit={handleCreate} className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              value={newEndpointName}
              onChange={(e) => setNewEndpointName(e.target.value)}
              placeholder="Endpoint Name (e.g. Production GitHub Webhook)"
              required
              className="flex-1 px-3.5 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-purple-500"
            />
            <select
              value={newEndpointProvider}
              onChange={(e) => setNewEndpointProvider(e.target.value)}
              className="px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-xs text-neutral-300 focus:outline-none focus:border-purple-500"
            >
              <option value="generic">Generic CI/CD</option>
              <option value="github">GitHub</option>
              <option value="gitlab">GitLab</option>
              <option value="argocd">ArgoCD</option>
              <option value="jenkins">Jenkins</option>
            </select>
            <button
              type="submit"
              disabled={creating}
              className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-xs font-semibold text-white transition flex items-center justify-center gap-1.5 whitespace-nowrap"
            >
              <span className="material-symbols-outlined text-sm">add</span>
              <span>{creating ? "Generating..." : "Generate Key"}</span>
            </button>
          </form>

          {/* Active Webhook Endpoints List */}
          <div className="space-y-3">
            <h4 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider">
              Configured Webhook Endpoints ({endpoints.length})
            </h4>

            {loading ? (
              <div className="py-8 text-center text-xs text-neutral-500 animate-pulse">
                Loading webhook endpoints...
              </div>
            ) : endpoints.length === 0 ? (
              <div className="p-6 rounded-xl bg-neutral-950/40 border border-neutral-800 text-center text-xs text-neutral-500">
                No webhook endpoints registered yet. Create one above to ingest deployments from your CI/CD runner.
              </div>
            ) : (
              <div className="divide-y divide-neutral-800/80 rounded-xl bg-neutral-950/40 border border-neutral-800 overflow-hidden">
                {endpoints.map((ep) => (
                  <div key={ep.id} className="p-3.5 flex items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-neutral-200">{ep.name}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-neutral-800 text-purple-300 border border-neutral-700 capitalize">
                          {ep.provider || "generic"}
                        </span>
                      </div>
                      <div className="text-xs font-mono text-neutral-500 mt-1 flex items-center gap-2">
                        <span>Key ID: <strong className="text-neutral-400">{ep.key_id}</strong></span>
                        <span>•</span>
                        <span>Secret: <span className="text-neutral-600">••••••••••••••••</span></span>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDelete(ep.id)}
                      className="p-1.5 rounded-lg text-neutral-500 hover:text-rose-400 hover:bg-rose-950/30 transition"
                      title="Deactivate / Delete"
                    >
                      <span className="material-symbols-outlined text-sm">delete</span>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Ingestion Documentation Snippet */}
          <div className="p-4 rounded-xl bg-neutral-950 border border-neutral-800 space-y-2">
            <div className="text-xs font-semibold text-neutral-300">Quick Integration Guide</div>
            <p className="text-xs text-neutral-400">
              Send deployment JSON payloads to <code>POST /webhooks/deployments/generic</code> with headers <code>X-Sentinel-Key-ID</code> and <code>X-Sentinel-Signature</code> (computed as <code>HMAC-SHA256(payload, secret)</code>).
            </p>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-neutral-800 bg-neutral-950/40 flex items-center justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-neutral-800 hover:bg-neutral-700 text-xs font-semibold text-neutral-200 transition"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
