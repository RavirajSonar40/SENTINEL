"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { login as apiLogin, register as apiRegister } from "@/lib/api";

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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    token: null,
    userId: null,
    username: null,
    isLoading: true,
  });

  useEffect(() => {
    const token = localStorage.getItem("sentinel_token");
    const userId = localStorage.getItem("sentinel_user_id");
    const username = localStorage.getItem("sentinel_username");
    if (token && userId && username) {
      setState({ token, userId, username, isLoading: false });
    } else {
      setState((s) => ({ ...s, isLoading: false }));
    }
  }, []);

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
    localStorage.removeItem("sentinel_token");
    localStorage.removeItem("sentinel_user_id");
    localStorage.removeItem("sentinel_username");
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
