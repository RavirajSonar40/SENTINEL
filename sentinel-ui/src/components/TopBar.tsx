"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { listAuditLogs, AuditLog } from "@/lib/api";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface TopBarProps {
  breadcrumbs?: { label: string; href?: string; active?: boolean }[];
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export default function TopBar({ breadcrumbs = [], title, subtitle, actions }: TopBarProps) {
  const { username, token } = useAuth();
  const router = useRouter();
  const [notifications, setNotifications] = useState<AuditLog[]>([]);
  const [showNotifs, setShowNotifs] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<{ title: string; href: string; type: string }[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const notifRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!token) return;
    listAuditLogs(token, 20)
      .then((logs) => {
        const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
        setNotifications(
          logs.filter((l) => l.created_at && new Date(l.created_at) > dayAgo)
        );
      })
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setShowNotifs(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setShowSearch(true);
      }
      if (e.key === "Escape") {
        setShowSearch(false);
        setSearchQuery("");
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  useEffect(() => {
    if (showSearch && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [showSearch]);

  useEffect(() => {
    if (!showSearch || !searchQuery.trim() || !token) {
      setSearchResults([]);
      return;
    }
    setSearchLoading(true);
    const timeout = setTimeout(() => {
      Promise.all([
        fetch(`${API_BASE}/incidents?search=${encodeURIComponent(searchQuery)}`, {
          headers: { Authorization: `Bearer ${token}` },
        }).then((r) => r.json()).catch(() => []),
        fetch(`${API_BASE}/services/health`, {
          headers: { Authorization: `Bearer ${token}` },
        }).then((r) => r.json()).catch(() => ({ services: [] })),
      ]).then(([incidents, healthData]) => {
        const results: { title: string; href: string; type: string }[] = [];
        const incList = Array.isArray(incidents) ? incidents : (incidents.incidents || []);
        incList.slice(0, 5).forEach((inc: { id: string; title: string }) => {
          results.push({ title: inc.title || `Incident ${inc.id.slice(0, 8)}`, href: `/incidents/${inc.id}`, type: "Incident" });
        });
        const svcs = healthData.services || [];
        svcs.filter((s: { service_name: string }) =>
          s.service_name.toLowerCase().includes(searchQuery.toLowerCase())
        ).slice(0, 3).forEach((s: { service_name: string }) => {
          results.push({ title: s.service_name, href: `/health`, type: "Service" });
        });
        setSearchResults(results);
        setSearchLoading(false);
      });
    }, 300);
    return () => clearTimeout(timeout);
  }, [searchQuery, token, showSearch]);

  return (
    <>
      <header className="h-14 w-full flex items-center bg-surface-container-lowest sticky top-0 z-40 justify-between px-6 border-b border-outline-variant">
        <div className="flex items-center gap-4">
          {title ? (
            <div>
              <h1 className="text-[18px] font-semibold text-on-surface">{title}</h1>
              {subtitle && (
                <p className="text-[12px] text-on-surface-variant mt-0.5">{subtitle}</p>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-3">
              {breadcrumbs.map((crumb, i) => (
                <span key={i} className="flex items-center gap-3">
                  {i > 0 && <span className="text-outline-variant">/</span>}
                  {crumb.href ? (
                    <a
                      href={crumb.href}
                      className="text-[13px] text-on-surface-variant hover:text-primary cursor-pointer transition-colors"
                    >
                      {crumb.label}
                    </a>
                  ) : (
                    <span
                      className={`text-[13px] cursor-pointer transition-colors ${
                        crumb.active
                          ? "text-on-surface font-medium"
                          : "text-on-surface-variant"
                      }`}
                    >
                      {crumb.label}
                    </span>
                  )}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          {actions}

          {/* Search */}
          <button
            onClick={() => setShowSearch(true)}
            className="flex items-center gap-2 bg-surface-container-high border border-outline-variant rounded-md px-3 py-1.5 mr-2 hover:bg-surface-container-highest transition-colors"
          >
            <span className="material-symbols-outlined text-[16px] text-on-surface-variant">search</span>
            <span className="text-[12px] text-on-surface-variant">Search (Ctrl+K)</span>
            <kbd className="ml-4 text-[10px] text-on-surface-variant bg-surface-container-highest px-1.5 py-0.5 rounded border border-outline-variant font-mono">
              ⌘K
            </kbd>
          </button>

          {/* Notifications */}
          <div className="relative" ref={notifRef}>
            <button
              onClick={() => setShowNotifs(!showNotifs)}
              className="relative hover:bg-surface-container-high w-8 h-8 flex items-center justify-center rounded-md transition-colors"
            >
              <span className="material-symbols-outlined text-[18px] text-on-surface-variant">
                notifications
              </span>
              {notifications.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-primary text-on-primary text-[9px] font-bold rounded-full flex items-center justify-center">
                  {notifications.length}
                </span>
              )}
            </button>
            {showNotifs && (
              <div className="absolute right-0 top-full mt-1 w-72 bg-surface-container-lowest border border-outline-variant rounded-lg shadow-lg z-50 overflow-hidden">
                <div className="px-3 py-2 border-b border-outline-variant flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-on-surface-variant uppercase tracking-wider">Notifications</span>
                  {notifications.length > 0 && (
                    <button
                      onClick={() => setNotifications([])}
                      className="text-[10px] text-primary hover:underline"
                    >
                      Clear all
                    </button>
                  )}
                </div>
                <div className="max-h-64 overflow-y-auto">
                  {notifications.length === 0 ? (
                    <div className="p-4 text-center text-[12px] text-on-surface-variant">
                      No notifications
                    </div>
                  ) : (
                    notifications.map((log) => (
                      <div key={log.id} className="px-3 py-2 border-b border-outline-variant/50 hover:bg-surface-container-high/50">
                        <div className="text-[11px] text-on-surface font-medium">{log.action}</div>
                        <div className="text-[10px] text-on-surface-variant mt-0.5">
                          {log.entity_type}{log.entity_id ? ` • ${log.entity_id.slice(0, 8)}` : ""}
                        </div>
                        {log.created_at && (
                          <div className="text-[10px] text-on-surface-variant/60 mt-0.5">
                            {new Date(log.created_at).toLocaleString()}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Help */}
          <button
            onClick={() => window.open("https://github.com/RavirajSonar40/SENTINEL#readme", "_blank")}
            className="hover:bg-surface-container-high w-8 h-8 flex items-center justify-center rounded-md transition-colors"
            title="Help & Documentation"
          >
            <span className="material-symbols-outlined text-[18px] text-on-surface-variant">
              help
            </span>
          </button>

          {/* User */}
          <a href="/profile" className="flex items-center gap-2 ml-2 pl-2 border-l border-outline-variant hover:opacity-80 transition-opacity cursor-pointer">
            <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center text-[12px] font-bold text-on-primary-container">
              {username?.charAt(0).toUpperCase() || "A"}
            </div>
            <div className="flex flex-col">
              <span className="text-[12px] font-medium text-on-surface leading-tight">{username || "Admin"}</span>
              <span className="text-[10px] text-on-surface-variant leading-tight">Admin</span>
            </div>
          </a>
        </div>
      </header>

      {/* Search Modal */}
      {showSearch && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]" onClick={() => { setShowSearch(false); setSearchQuery(""); }}>
          <div className="absolute inset-0 bg-black/50" />
          <div
            className="relative w-full max-w-lg bg-surface-container-lowest border border-outline-variant rounded-lg shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 px-4 py-3 border-b border-outline-variant">
              <span className="material-symbols-outlined text-[18px] text-on-surface-variant">search</span>
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search incidents, services..."
                className="flex-1 text-[14px] text-on-surface bg-transparent outline-none placeholder:text-on-surface-variant/50"
              />
              <kbd className="text-[10px] text-on-surface-variant bg-surface-container-highest px-1.5 py-0.5 rounded border border-outline-variant font-mono">
                ESC
              </kbd>
            </div>
            <div className="max-h-64 overflow-y-auto">
              {searchLoading ? (
                <div className="p-4 text-center text-[12px] text-on-surface-variant">Searching...</div>
              ) : searchResults.length > 0 ? (
                searchResults.map((result, i) => (
                  <button
                    key={i}
                    onClick={() => { router.push(result.href); setShowSearch(false); setSearchQuery(""); }}
                    className="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-surface-container-high transition-colors text-left"
                  >
                    <span className="material-symbols-outlined text-[16px] text-on-surface-variant">
                      {result.type === "Incident" ? "warning" : "dns"}
                    </span>
                    <div>
                      <div className="text-[12px] text-on-surface font-medium">{result.title}</div>
                      <div className="text-[10px] text-on-surface-variant">{result.type}</div>
                    </div>
                  </button>
                ))
              ) : searchQuery.length > 0 ? (
                <div className="p-4 text-center text-[12px] text-on-surface-variant">No results found</div>
              ) : (
                <div className="p-4 text-center text-[12px] text-on-surface-variant">Type to search incidents and services</div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
