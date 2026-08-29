"use client";

import React, { useState } from "react";
import { Repository, ServiceRepositoryRole } from "@/lib/catalogApi";

interface ServiceRepoModalProps {
  isOpen: boolean;
  serviceId: string;
  repositories: Repository[];
  onClose: () => void;
  onSave: (data: {
    service_id: string;
    repository_id: string;
    role: ServiceRepositoryRole;
    is_primary: boolean;
    confidence: number;
    selection_reason: string;
  }) => Promise<void>;
}

export const ServiceRepoModal: React.FC<ServiceRepoModalProps> = ({
  isOpen,
  serviceId,
  repositories,
  onClose,
  onSave,
}) => {
  const [repositoryId, setRepositoryId] = useState(repositories[0]?.id || "");
  const [role, setRole] = useState<ServiceRepositoryRole>("application");
  const [isPrimary, setIsPrimary] = useState(false);
  const [confidence] = useState(1.0);
  const [selectionReason, setSelectionReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!repositoryId) {
      setError("Please select a repository.");
      return;
    }
    if (!selectionReason.trim() || selectionReason.trim().length < 3) {
      setError("Please provide a valid selection reason (minimum 3 characters).");
      return;
    }

    try {
      setLoading(true);
      setError(null);
      await onSave({
        service_id: serviceId,
        repository_id: repositoryId,
        role,
        is_primary: role === "application" ? isPrimary : false,
        confidence,
        selection_reason: selectionReason.trim(),
      });
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to link repository.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-lg w-full p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
          <h3 className="text-lg font-semibold text-white">Link Repository to Service</h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-lg font-bold"
          >
            ✕
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-950/50 border border-red-800/60 rounded-lg text-red-300 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">
              Select Repository
            </label>
            <select
              value={repositoryId}
              onChange={(e) => setRepositoryId(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              {repositories.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.full_name} ({r.language || "code"})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">
              Repository Role
            </label>
            <select
              value={role}
              onChange={(e) => {
                const newRole = e.target.value as ServiceRepositoryRole;
                setRole(newRole);
                if (newRole !== "application") {
                  setIsPrimary(false);
                }
              }}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="application">Application (Source Code)</option>
              <option value="configuration">Configuration (Helm/K8s/Env)</option>
              <option value="infrastructure">Infrastructure (Terraform/IaC)</option>
              <option value="dependency">Dependency (Shared Library/SDK)</option>
            </select>
          </div>

          {role === "application" && (
            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="is_primary"
                checked={isPrimary}
                onChange={(e) => setIsPrimary(e.target.checked)}
                className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-indigo-500"
              />
              <label htmlFor="is_primary" className="text-xs text-slate-300">
                Mark as Primary Application Repository
              </label>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">
              Selection Reason <span className="text-red-400">*</span>
            </label>
            <textarea
              value={selectionReason}
              onChange={(e) => setSelectionReason(e.target.value)}
              placeholder="e.g. Core microservice codebase housing API handlers..."
              rows={3}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="px-4 py-2 text-sm font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg transition-colors shadow-lg shadow-indigo-600/20"
            >
              {loading ? "Linking..." : "Link Repository"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
