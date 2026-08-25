"use client";

import { useState } from "react";
import { useAuth } from "@/lib/AuthContext";
import Link from "next/link";

export default function RegisterPage() {
  const { register } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    setLoading(true);
    try {
      await register(username, email, password);
      window.location.href = "/";
    } catch (err: any) {
      setError(err.message || "Registration failed");
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
            style={{ filter: "invert(80%) sepia(40%) saturate(500%) hue-rotate(200deg) brightness(1.1)" }}
          />
          <h1 className="text-2xl font-semibold text-on-surface">Create Account</h1>
          <p className="text-[12px] text-on-surface-variant mt-1">
            Join Sentinel Incident Response Platform
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-surface border border-outline-variant rounded p-6 space-y-5"
        >
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 text-[14px] text-on-surface bg-surface-container border border-outline-variant rounded focus:border-primary focus:outline-none"
              placeholder="Choose a username"
              required
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 text-[14px] text-on-surface bg-surface-container border border-outline-variant rounded focus:border-primary focus:outline-none"
              placeholder="you@company.com"
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
              className="w-full px-3 py-2 text-[14px] text-on-surface bg-surface-container border border-outline-variant rounded focus:border-primary focus:outline-none"
              placeholder="At least 6 characters"
              required
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">
              Confirm Password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-3 py-2 text-[14px] text-on-surface bg-surface-container border border-outline-variant rounded focus:border-primary focus:outline-none"
              placeholder="Repeat password"
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
            {loading ? "Creating account..." : "Create Account"}
          </button>

          <p className="text-[11px] text-on-surface-variant text-center">
            Already have an account?{" "}
            <Link href="/login" className="text-primary hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
