"use client";

import { useState } from "react";
import { useAuth } from "@/lib/AuthContext";
import Link from "next/link";

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    console.log("Attempting login to http://localhost:8000/auth/login...");
    try {
      await login(username, password);
      console.log("Login successful, redirecting...");
      window.location.href = "/";
    } catch (err: any) {
      console.error("Login error:", err);
      setError(err.message || "Login failed — is the backend running on port 8000?");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface-container-lowest flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="flex flex-col items-center mb-8">
          <img
            src="/sentinel_logo.png"
            alt="Sentinel"
            className="w-16 h-16 mb-4"

          />
          <h1 className="text-2xl font-semibold text-on-surface">SENTINEL</h1>
          <p className="text-[12px] text-on-surface-variant mt-1">
            Incident Response Platform
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-surface border border-outline-variant rounded p-6 space-y-6"
        >
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 text-[14px] text-on-surface"
              placeholder="admin"
              required
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 text-[14px] text-on-surface"
              placeholder="••••••••"
              required
            />
          </div>

          {error && (
            <div className="text-[12px] text-error bg-error/10 border border-error/20 rounded p-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full px-6 py-2 bg-primary-container text-on-primary-container text-[11px] font-semibold uppercase tracking-wider rounded border border-primary hover:bg-primary hover:text-on-primary-fixed transition-colors disabled:opacity-50"
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>

          <p className="text-[11px] text-on-surface-variant text-center">
            Don&apos;t have an account?{" "}
            <Link href="/register" className="text-primary hover:underline">
              Create one
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
