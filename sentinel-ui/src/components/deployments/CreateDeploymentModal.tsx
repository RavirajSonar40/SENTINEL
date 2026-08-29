"use client";

import React, { useState } from "react";
import { deploymentsApi, DeploymentCreateInput } from "@/lib/deploymentsApi";
import { Service, Environment, Region, Repository } from "@/lib/catalogApi";

interface CreateDeploymentModalProps {
  services: Service[];
  environments: Environment[];
  regions: Region[];
  repositories: Repository[];
  token?: string;
  onClose: () => void;
  onCreated: () => void;
}

export default function CreateDeploymentModal({
  services,
  environments,
  regions,
  repositories,
  token,
  onClose,
  onCreated,
}: CreateDeploymentModalProps) {
  const [serviceId, setServiceId] = useState(services[0]?.id || "");
  const [environmentId, setEnvironmentId] = useState(environments[0]?.id || "");
  const [regionId, setRegionId] = useState("");
  const [repositoryId, setRepositoryId] = useState("");
  const [commitSha, setCommitSha] = useState("");
  const [commitMessage, setCommitMessage] = useState("");
  const [version, setVersion] = useState("");
  const [status, setStatus] = useState("succeeded");
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!serviceId || !environmentId || !commitSha.trim()) {
      setError("Please fill in all required fields (Service, Environment, Commit SHA).");
      return;
    }
    if (commitSha.trim().length < 7) {
      setError("Commit SHA must be at least 7 characters.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const payload: DeploymentCreateInput = {
        service_id: serviceId,
        environment_id: environmentId,
        region_id: regionId || null,
        repository_id: repositoryId || null,
        commit_sha: commitSha.trim(),
        commit_message: commitMessage.trim() || undefined,
        version: version.trim() || undefined,
        provider: "manual",
        status,
        url: url.trim() || undefined,
      };
      await deploymentsApi.createDeployment(payload, token);
      onCreated();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || "Failed to register deployment");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-neutral-900 border border-neutral-800 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden">
        <div className="px-6 py-5 border-b border-neutral-800 flex items-center justify-between bg-neutral-950/40">
          <div className="flex items-center gap-2.5">
            <span className="material-symbols-outlined text-blue-400">rocket_launch</span>
            <h3 className="text-base font-semibold text-neutral-100">Register New Deployment</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 transition"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-rose-950/50 border border-rose-800/60 text-rose-300 text-xs flex items-center gap-2">
              <span className="material-symbols-outlined text-sm">error</span>
              <span>{error}</span>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Target Service *</label>
              <select
                value={serviceId}
                onChange={(e) => setServiceId(e.target.value)}
                required
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-blue-500"
              >
                {services.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Environment *</label>
              <select
                value={environmentId}
                onChange={(e) => setEnvironmentId(e.target.value)}
                required
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-blue-500"
              >
                {environments.map((e) => (
                  <option key={e.id} value={e.id}>{e.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Region (Optional)</label>
              <select
                value={regionId}
                onChange={(e) => setRegionId(e.target.value)}
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-blue-500"
              >
                <option value="">Global / Unspecified</option>
                {regions.map((r) => (
                  <option key={r.id} value={r.id}>{r.name} ({r.code})</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Repository (Optional)</label>
              <select
                value={repositoryId}
                onChange={(e) => setRepositoryId(e.target.value)}
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-blue-500"
              >
                <option value="">Select linked repository</option>
                {repositories.map((r) => (
                  <option key={r.id} value={r.id}>{r.full_name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Commit SHA *</label>
              <input
                type="text"
                value={commitSha}
                onChange={(e) => setCommitSha(e.target.value)}
                placeholder="e.g. 7a1b2c3..."
                required
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 font-mono focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Release Version</label>
              <input
                type="text"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="e.g. v2.1.0"
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-neutral-400 mb-1">Commit Message</label>
            <input
              type="text"
              value={commitMessage}
              onChange={(e) => setCommitMessage(e.target.value)}
              placeholder="e.g. chore(auth): update token expiration logic"
              className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Initial Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-blue-500"
              >
                <option value="succeeded">Succeeded (Active Live)</option>
                <option value="in_progress">In Progress</option>
                <option value="pending">Pending</option>
                <option value="failed">Failed</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Build / Release URL</label>
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://ci.acme.com/job/42"
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm text-neutral-200 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div className="pt-4 border-t border-neutral-800 flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-neutral-800 hover:bg-neutral-700 text-xs font-semibold text-neutral-200 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white transition flex items-center gap-1.5"
            >
              {loading ? "Registering..." : "Register Release"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
