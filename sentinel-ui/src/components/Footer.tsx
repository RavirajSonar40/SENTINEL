"use client";

import { useEffect, useState } from "react";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface SystemStatus {
  postgres: string;
  qdrant: string;
  aiModel: string;
  uptime: string;
}

export default function Footer() {
  const [status, setStatus] = useState<SystemStatus>({
    postgres: "Unknown",
    qdrant: "Unknown",
    aiModel: "mock",
    uptime: "—",
  });

  useEffect(() => {
    const token = localStorage.getItem("sentinel_token");
    if (!token) return;

    fetch(`${API_BASE}/health`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((data) => {
        setStatus({
          postgres: data.database === "connected" ? "Connected" : "Disconnected",
          qdrant: data.vector_store === "connected" ? "Connected" : "Unavailable",
          aiModel: data.llm_provider || "mock",
          uptime: data.uptime_seconds
            ? `${Math.floor(data.uptime_seconds / 3600)}h ${Math.floor((data.uptime_seconds % 3600) / 60)}m`
            : "—",
        });
      })
      .catch(() => {});
  }, []);

  return (
    <footer className="h-7 w-full flex items-center bg-surface-container-lowest border-t border-outline-variant px-4 text-[10px] text-on-surface-variant font-mono justify-between shrink-0">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          Sentinel v0.1.0
        </span>
        <span className="text-outline-variant">|</span>
        <span>PostgreSQL: {status.postgres}</span>
        <span className="text-outline-variant">|</span>
        <span>Qdrant: {status.qdrant}</span>
      </div>
      <div className="flex items-center gap-3">
        <span>AI Model: {status.aiModel}</span>
        <span className="text-outline-variant">|</span>
        <span>Uptime: {status.uptime}</span>
      </div>
    </footer>
  );
}
