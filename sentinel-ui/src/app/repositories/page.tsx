"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listRepositories, Repository } from "@/lib/api";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

const syncStatusStyles: Record<string, string> = {
  synced: "bg-primary/10 text-primary border-primary/20",
  pending: "bg-tertiary/10 text-tertiary border-tertiary/20",
  running: "bg-primary/10 text-primary border-primary/20 animate-pulse",
  failed: "bg-error/10 text-error border-error/20",
  not_connected: "bg-outline/10 text-outline border-outline-variant",
};

export default function RepositoriesPage() {
  const { token } = useAuth();
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncAllLoading, setSyncAllLoading] = useState(false);
  const [syncError, setSyncError] = useState("");

  useEffect(() => {
    if (!token) return;
    listRepositories(token)
      .then(setRepos)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token]);

  const handleSync = async (repoId: string) => {
    if (!token || syncingId) return;
    setSyncingId(repoId);
    setSyncError("");
    try {
      const res = await fetch(`${API_BASE}/github/sync-token`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
      if (res.ok) {
        const updated = await listRepositories(token);
        setRepos(updated);
      } else {
        const data = await res.json().catch(() => ({}));
        setSyncError(data.detail || "Sync failed");
      }
    } catch {
      setSyncError("Network error - is the backend running?");
    } finally {
      setSyncingId(null);
    }
  };

  const handleSyncAll = async () => {
    if (!token || syncAllLoading) return;
    setSyncAllLoading(true);
    setSyncError("");
    try {
      const res = await fetch(`${API_BASE}/github/sync-token`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
      if (res.ok) {
        const updated = await listRepositories(token);
        setRepos(updated);
      } else {
        const data = await res.json().catch(() => ({}));
        setSyncError(data.detail || "Sync failed");
      }
    } catch {
      setSyncError("Network error - is the backend running?");
    } finally {
      setSyncAllLoading(false);
    }
  };

  const filtered = repos.filter((r) =>
    r.name.toLowerCase().includes(search.toLowerCase()) ||
    r.full_name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <>
      <TopBar
        title="Repositories"
        subtitle="Manage connected repositories and sync status."
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={handleSyncAll}
              disabled={syncAllLoading || repos.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-container-high border border-outline-variant text-on-surface text-[11px] font-semibold uppercase tracking-wider rounded-md hover:bg-surface-bright transition-colors disabled:opacity-50"
            >
              <span className={`material-symbols-outlined text-[14px] ${syncAllLoading ? "animate-spin" : ""}`}>sync</span>
              {syncAllLoading ? "Syncing..." : "Sync All"}
            </button>
            <Link
              href="/integrations"
              className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-container-high border border-outline-variant text-on-surface text-[11px] font-semibold uppercase tracking-wider rounded-md hover:bg-surface-bright transition-colors"
            >
              <span className="material-symbols-outlined text-[14px]">hub</span>
              Integrations
            </Link>
          </div>
        }
      />
      <main className="flex-1 p-6 overflow-x-auto pb-10">
        <div className="max-w-[1400px] mx-auto">

          {/* Search */}
          <div className="flex items-center gap-3 mb-4">
            <div className="relative flex-1 max-w-md">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[16px] text-on-surface-variant">search</span>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search repositories..."
                className="w-full px-10 py-2 pr-4 font-mono text-[12px] text-on-surface bg-surface-container-high border border-outline-variant rounded-md focus:border-primary focus:outline-none"
              />
            </div>
            {syncError && (
              <div className="text-[12px] text-error bg-error/10 border border-error/20 rounded px-3 py-1.5">
                {syncError}
              </div>
            )}
          </div>

          {loading ? (
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-8 text-center">
              <div className="text-on-surface-variant font-mono text-[12px]">Loading repositories...</div>
            </div>
          ) : filtered.length === 0 ? (
            <div className="bg-surface-container-low border border-outline-variant rounded-lg p-8 text-center">
              <span className="material-symbols-outlined text-[48px] text-on-surface-variant/30 mb-4 block">folder_off</span>
              <h3 className="text-[14px] font-semibold text-on-surface mb-1">No repositories found</h3>
              <p className="text-[12px] text-on-surface-variant">Connect GitHub in Integrations to sync repositories.</p>
              <Link href="/integrations" className="inline-flex items-center gap-1.5 mt-4 px-4 py-2 bg-primary-container text-on-primary-container text-[12px] font-semibold uppercase tracking-wider rounded-md border border-primary hover:bg-primary hover:text-on-primary-fixed transition-colors">
                <span className="material-symbols-outlined text-[14px]">add</span>
                Go to Integrations
              </Link>
            </div>
          ) : (
            <div className="bg-surface-container-low border border-outline-variant rounded-lg overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-outline-variant bg-surface-container">
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4 w-10"></th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4">REPOSITORY</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4 w-28">SYNC STATUS</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4 w-24">BRANCH</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4 w-32">SERVICE</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4 w-36">LAST SYNC</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2.5 px-4 w-24 text-right">ACTIONS</th>
                  </tr>
                </thead>
                <tbody className="font-mono text-[11px]">
                  {filtered.map((repo) => (
                    <tr key={repo.id} className="border-b border-outline-variant/50 hover:bg-surface-container-high/50 transition-colors">
                      <td className="py-3 px-4">
                        <span className="material-symbols-outlined text-[20px] text-on-surface-variant">folder</span>
                      </td>
                      <td className="py-3 px-4">
                        <a href={repo.github_url || "#"} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline font-medium">
                          {repo.name}
                        </a>
                        <div className="text-[10px] text-on-surface-variant">{repo.full_name}</div>
                      </td>
                      <td className="py-3 px-4">
                        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold border ${syncStatusStyles[repo.sync_status] || syncStatusStyles.not_connected}`}>
                          {repo.sync_status === "synced" ? "Synced" : repo.sync_status === "running" ? "Syncing..." : repo.sync_status === "failed" ? "Failed" : "Not Connected"}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-on-surface-variant">{repo.default_branch}</td>
                      <td className="py-3 px-4 text-on-surface-variant">{repo.service_id ? "Linked" : "—"}</td>
                      <td className="py-3 px-4 text-on-surface-variant">{repo.last_synced_at ? new Date(repo.last_synced_at).toLocaleString() : "Never"}</td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={() => handleSync(repo.id)}
                          disabled={syncingId === repo.id}
                          className="text-on-surface-variant hover:text-primary transition-colors disabled:opacity-30"
                          title="Sync repository"
                        >
                          <span className={`material-symbols-outlined text-[16px] ${syncingId === repo.id ? "animate-spin" : ""}`}>sync</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </>
  );
}