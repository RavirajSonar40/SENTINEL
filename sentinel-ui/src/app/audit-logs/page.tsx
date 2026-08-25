"use client";

import { useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listAuditLogs, AuditLog } from "@/lib/api";

const actionIcons: Record<string, string> = {
  "incident.created": "add_circle",
  "incident.updated": "edit",
  "incident.resolved": "check_circle",
  "investigation.started": "psychology",
  "investigation.completed": "task_alt",
  "fix.approved": "thumb_up",
  "fix.rejected": "thumb_down",
  "fix.generated": "code",
  "feedback.approve": "thumb_up",
  "feedback.reject": "thumb_down",
  "user.login": "login",
};

const actionColors: Record<string, string> = {
  "incident.created": "text-error",
  "incident.resolved": "text-green-400",
  "investigation.started": "text-primary",
  "investigation.completed": "text-tertiary",
  "fix.approved": "text-green-400",
  "fix.rejected": "text-error",
  "feedback.approve": "text-green-400",
  "feedback.reject": "text-error",
};

export default function AuditLogsPage() {
  const { token } = useAuth();
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    if (!token) return;
    listAuditLogs(token)
      .then(setLogs)
      .catch(() => setLogs([]))
      .finally(() => setLoading(false));
  }, [token]);

  const filtered = filter === "all" ? logs : logs.filter((l) => l.action.startsWith(filter));

  return (
    <>
      <TopBar
        title="Audit Logs"
        subtitle="System activity and compliance audit trail"
        breadcrumbs={[{ label: "Audit Logs", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto">
          <div className="bg-surface-container-low border border-outline-variant rounded">
            <div className="p-4 border-b border-outline-variant flex items-center justify-between">
              <h2 className="text-[13px] font-semibold text-on-surface">Activity Log</h2>
              <div className="flex gap-2">
                <select
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="bg-surface-container border border-outline-variant rounded px-2 py-1 text-[11px] text-on-surface"
                >
                  <option value="all">All Events</option>
                  <option value="incident">Incidents</option>
                  <option value="investigation">Investigations</option>
                  <option value="fix">Fixes</option>
                  <option value="feedback">Feedback</option>
                </select>
              </div>
            </div>
            {loading ? (
              <div className="p-8 text-center text-on-surface-variant text-[12px] font-mono">Loading...</div>
            ) : filtered.length === 0 ? (
              <div className="p-8 text-center text-on-surface-variant text-[12px]">No audit logs found</div>
            ) : (
              <div className="divide-y divide-outline-variant/50">
                {filtered.map((log) => (
                  <div key={log.id} className="px-4 py-3 flex items-center gap-3 hover:bg-surface-container-high/30 transition-colors">
                    <span className={`material-symbols-outlined text-[16px] ${actionColors[log.action] || "text-on-surface-variant"}`}>
                      {actionIcons[log.action] || "circle"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-[12px] text-on-surface truncate">{log.action}</div>
                      {log.details && Object.keys(log.details).length > 0 && (
                        <div className="text-[10px] text-on-surface-variant font-mono truncate">
                          {JSON.stringify(log.details).slice(0, 80)}
                        </div>
                      )}
                    </div>
                    <span className="text-[10px] text-on-surface-variant font-mono whitespace-nowrap">
                      {log.created_at ? new Date(log.created_at).toLocaleString() : "—"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
