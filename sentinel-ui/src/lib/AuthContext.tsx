"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { login as apiLogin, register as apiRegister } from "@/lib/api";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface AuthState {
  token: string | null;
  userId: string | null;
  username: string | null;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

function clearAuth() {
  localStorage.removeItem("sentinel_token");
  localStorage.removeItem("sentinel_user_id");
  localStorage.removeItem("sentinel_username");
}

function getInitialAuth(): AuthState {
  // Keep the first render identical on the server and client. Auth storage is
  // read after hydration so protected pages never trigger a React mismatch.
  if (typeof window === "undefined") return { token: null, userId: null, username: null, isLoading: true };
  const token = localStorage.getItem("sentinel_token");
  const userId = localStorage.getItem("sentinel_user_id");
  const username = localStorage.getItem("sentinel_username");
  // The token is the source of truth. Profile fields are cacheable metadata
  // and may be absent after a browser cleanup or an older deployment.
  if (!token) return { token: null, userId: null, username: null, isLoading: true };
  return { token, userId, username, isLoading: true };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(getInitialAuth);

  useEffect(() => {
    const { token } = state;
    if (!token) {
      setState((current) => current.isLoading ? { ...current, isLoading: false } : current);
      return;
    }

    fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (res.status === 401) {
          throw new Error("invalid");
        }
        if (!res.ok) {
          throw new Error("temporary");
        }
        return res.json();
      })
      .then((data) => {
        localStorage.setItem("sentinel_user_id", data.id);
        localStorage.setItem("sentinel_username", data.username);
        setState({ token, userId: data.id, username: data.username, isLoading: false });
      })
      .catch((error) => {
        // Do not log a user out because Render is waking up or temporarily
        // unavailable. Only an explicit 401 invalidates the session.
        if (error instanceof Error && error.message === "invalid") {
          clearAuth();
          setState({ token: null, userId: null, username: null, isLoading: false });
          return;
        }
        setState((current) => ({ ...current, isLoading: false }));
      });
  }, [state.token]); // eslint-disable-line react-hooks/exhaustive-deps

  const login = async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    localStorage.setItem("sentinel_token", res.access_token);
    localStorage.setItem("sentinel_user_id", res.user_id);
    localStorage.setItem("sentinel_username", res.username);
    setState({ token: res.access_token, userId: res.user_id, username: res.username, isLoading: false });
  };

  const register = async (username: string, email: string, password: string) => {
    const res = await apiRegister(username, email, password);
    localStorage.setItem("sentinel_token", res.access_token);
    localStorage.setItem("sentinel_user_id", res.user_id);
    localStorage.setItem("sentinel_username", res.username);
    setState({ token: res.access_token, userId: res.user_id, username: res.username, isLoading: false });
  };

  const logout = () => {
    clearAuth();
    setState({ token: null, userId: null, username: null, isLoading: false });
  };

  return (
    <AuthContext.Provider value={{ ...state, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
