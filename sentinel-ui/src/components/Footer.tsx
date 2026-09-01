"use client";

import { useEffect, useState } from "react";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface SystemStatus {
  postgres: string;
  vectorStore: string;
  aiModel: string;
  uptime: string;
  startedAt: number;
}

const APP_START = Date.now();

function formatUptime(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days}d ${hours % 24}h`;
  if (hours > 0) return `${hours}h ${minutes % 60}m`;
  return `${minutes}m ${seconds % 60}s`;
}

export default function Footer() {
  const [status, setStatus] = useState<SystemStatus>({
    postgres: "Unknown",
    vectorStore: "Unknown",
    aiModel: "Unknown",
    uptime: "—",
    startedAt: APP_START,
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
          uptime: formatUptime(Date.now() - APP_START),
          startedAt: APP_START,
        });
      })
      .catch(() => {});
  }, []);

  // Update uptime every 10 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setStatus((prev) => ({ ...prev, uptime: formatUptime(Date.now() - APP_START) }));
    }, 10000);
    return () => clearInterval(interval);
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
