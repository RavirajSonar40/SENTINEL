"use client";

import { useEffect, useState } from "react";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface SystemStatus {
  postgres: string;
  vectorStore: string;
  aiModel: string;
  uptime: string;
}

export default function Footer() {
  const [status, setStatus] = useState<SystemStatus>({
    postgres: "Unknown",
    vectorStore: "Unknown",
    aiModel: "Unknown",
    uptime: "—",
  });

  useEffect(() => {
    const token = localStorage.getItem("sentinel_token");
    if (!token) return;

    fetch(`${API_BASE}/system/health`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((data) => {
        const checks = data.checks || {};
        setStatus({
          postgres: checks.postgres?.status === "operational" ? "Connected" : "Disconnected",
          vectorStore: (checks.vector_store || checks.qdrant)?.status === "operational"
            ? "Connected"
            : "Unavailable",
          aiModel: checks.llm?.model || checks.llm?.provider || "Unknown",
          uptime: "—",
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
        <span>Vector DB: {status.vectorStore}</span>
      </div>
      <div className="flex items-center gap-3">
        <span>AI Model: {status.aiModel}</span>
        <span className="text-outline-variant">|</span>
        <span>Uptime: {status.uptime}</span>
      </div>
    </footer>
  );
}
