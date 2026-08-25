"use client";

import { useState, useRef, useEffect } from "react";
import { useAuth } from "@/lib/AuthContext";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function ChatBot() {
  const { token } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "Hi! I'm Sentinel AI Assistant. I can help you understand incidents, investigations, code fixes, and more. What would you like to know?",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  const sendMessage = async () => {
    if (!input.trim() || loading || !token) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);

    try {
      const history = messages.map((m) => ({ role: m.role, content: m.content }));
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message: userMsg, history }),
      });

      if (!res.ok) throw new Error("Failed to get response");
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.response }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Sorry, I couldn't process that. Please try again." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const quickActions = [
    { label: "What incidents are open?", icon: "warning" },
    { label: "Show recent fixes", icon: "build" },
    { label: "How does Sentinel work?", icon: "help" },
    { label: "What repos are connected?", icon: "folder" },
  ];

  return (
    <>
      {/* Floating Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full shadow-lg flex items-center justify-center transition-all ${
          isOpen
            ? "bg-surface-container-high border border-outline-variant rotate-0"
            : "bg-primary hover:bg-primary/90"
        }`}
      >
        <span className="material-symbols-outlined text-[24px] text-on-primary">
          {isOpen ? "close" : "smart_toy"}
        </span>
      </button>

      {/* Chat Window */}
      {isOpen && (
        <div className="fixed bottom-24 right-6 z-50 w-[380px] h-[520px] bg-surface-container-lowest border border-outline-variant rounded-lg shadow-2xl flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-3 px-4 py-3 bg-surface-container-low border-b border-outline-variant">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center">
              <span className="material-symbols-outlined text-[16px] text-on-primary">smart_toy</span>
            </div>
            <div className="flex-1">
              <div className="text-[13px] font-semibold text-on-surface">Sentinel AI</div>
              <div className="text-[10px] text-on-surface-variant">Ask anything about incidents & fixes</div>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] px-3 py-2 rounded-lg text-[12px] leading-relaxed ${
                    msg.role === "user"
                      ? "bg-primary text-on-primary rounded-br-sm"
                      : "bg-surface-container border border-outline-variant text-on-surface rounded-bl-sm"
                  }`}
                >
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-surface-container border border-outline-variant rounded-lg rounded-bl-sm px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick Actions (only show at start) */}
          {messages.length <= 1 && (
            <div className="px-4 pb-2 flex flex-wrap gap-1.5">
              {quickActions.map((action) => (
                <button
                  key={action.label}
                  onClick={() => {
                    setInput(action.label);
                    setTimeout(() => {
                      setInput(action.label);
                      const fakeEvent = { preventDefault: () => {} };
                      // Trigger send
                      setMessages((prev) => [...prev, { role: "user", content: action.label }]);
                      setLoading(true);
                      fetch(`${API_BASE}/chat`, {
                        method: "POST",
                        headers: {
                          Authorization: `Bearer ${token}`,
                          "Content-Type": "application/json",
                        },
                        body: JSON.stringify({
                          message: action.label,
                          history: messages.map((m) => ({ role: m.role, content: m.content })),
                        }),
                      })
                        .then((r) => r.json())
                        .then((data) => {
                          setMessages((prev) => [...prev, { role: "assistant", content: data.response }]);
                        })
                        .catch(() => {
                          setMessages((prev) => [
                            ...prev,
                            { role: "assistant", content: "Sorry, couldn't process that." },
                          ]);
                        })
                        .finally(() => setLoading(false));
                    }, 100);
                    setInput("");
                  }}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-container border border-outline-variant rounded text-[10px] text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
                >
                  <span className="material-symbols-outlined text-[12px]">{action.icon}</span>
                  {action.label}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <div className="px-4 py-3 border-t border-outline-variant bg-surface-container-low">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                sendMessage();
              }}
              className="flex items-center gap-2"
            >
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about incidents, fixes, repos..."
                className="flex-1 px-3 py-2 bg-surface-container border border-outline-variant rounded-md text-[12px] text-on-surface placeholder:text-on-surface-variant/50 focus:border-primary focus:outline-none"
              />
              <button
                type="submit"
                disabled={!input.trim() || loading}
                className="w-8 h-8 flex items-center justify-center rounded-md bg-primary text-on-primary hover:bg-primary/90 transition-colors disabled:opacity-30"
              >
                <span className="material-symbols-outlined text-[16px]">send</span>
              </button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
