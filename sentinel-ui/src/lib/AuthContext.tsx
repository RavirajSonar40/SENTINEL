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
  if (typeof window === "undefined") return { token: null, userId: null, username: null, isLoading: true };
  const token = localStorage.getItem("sentinel_token");
  const userId = localStorage.getItem("sentinel_user_id");
  const username = localStorage.getItem("sentinel_username");
  if (!token || !userId || !username) return { token: null, userId: null, username: null, isLoading: false };
  return { token, userId, username, isLoading: true };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(getInitialAuth);

  useEffect(() => {
    const { token } = state;
    if (!token) return;

    fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("invalid");
        return res.json();
      })
      .then((data) => {
        localStorage.setItem("sentinel_user_id", data.id);
        localStorage.setItem("sentinel_username", data.username);
        setState({ token, userId: data.id, username: data.username, isLoading: false });
      })
      .catch(() => {
        clearAuth();
        setState({ token: null, userId: null, username: null, isLoading: false });
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
