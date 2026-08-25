"use client";

import { useEffect, useState, useRef } from "react";
import { useAuth } from "@/lib/AuthContext";
import { listAuditLogs, AuditLog } from "@/lib/api";

interface TopBarProps {
  breadcrumbs?: { label: string; href?: string; active?: boolean }[];
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export default function TopBar({ breadcrumbs = [], title, subtitle, actions }: TopBarProps) {
  const { username, token } = useAuth();
  const [notifications, setNotifications] = useState<AuditLog[]>([]);
  const [showNotifs, setShowNotifs] = useState(false);
  const notifRef = useRef<HTMLDivElement>(null);

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

  return (
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
        <div className="flex items-center gap-2 bg-surface-container-high border border-outline-variant rounded-md px-3 py-1.5 mr-2">
          <span className="material-symbols-outlined text-[16px] text-on-surface-variant">search</span>
          <span className="text-[12px] text-on-surface-variant">Search (Ctrl+K)</span>
          <kbd className="ml-4 text-[10px] text-on-surface-variant bg-surface-container-highest px-1.5 py-0.5 rounded border border-outline-variant font-mono">
            ⌘K
          </kbd>
        </div>

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
              <div className="px-3 py-2 border-b border-outline-variant text-[11px] font-semibold text-on-surface-variant uppercase tracking-wider">
                Notifications
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
        <button className="hover:bg-surface-container-high w-8 h-8 flex items-center justify-center rounded-md transition-colors">
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
  );
}
