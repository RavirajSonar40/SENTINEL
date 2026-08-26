"use client";

import { useState, useRef, useEffect, useCallback } from "react";
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

  const [position, setPosition] = useState(() => ({
    x: typeof window !== "undefined" ? window.innerWidth - 420 : 800,
    y: typeof window !== "undefined" ? window.innerHeight - 620 : 400,
  }));
  const [size, setSize] = useState({ w: 400, h: 560 });
  const [isMaximized, setIsMaximized] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);

  const dragOffset = useRef({ x: 0, y: 0 });
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0 });
  const windowRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  // Drag handlers
  const onDragStart = useCallback((e: React.MouseEvent) => {
    if (isMaximized) return;
    e.preventDefault();
    setIsDragging(true);
    dragOffset.current = {
      x: e.clientX - position.x,
      y: e.clientY - position.y,
    };
  }, [position, isMaximized]);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      setPosition({
        x: Math.max(0, Math.min(window.innerWidth - 100, e.clientX - dragOffset.current.x)),
        y: Math.max(0, Math.min(window.innerHeight - 60, e.clientY - dragOffset.current.y)),
      });
    };
    const onUp = () => setIsDragging(false);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [isDragging]);

  // Resize handlers
  const onResizeStart = useCallback((e: React.MouseEvent) => {
    if (isMaximized) return;
    e.preventDefault();
    e.stopPropagation();
    setIsResizing(true);
    resizeStart.current = { x: e.clientX, y: e.clientY, w: size.w, h: size.h };
  }, [size, isMaximized]);

  useEffect(() => {
    if (!isResizing) return;
    const onMove = (e: MouseEvent) => {
      setSize({
        w: Math.max(320, Math.min(window.innerWidth - 20, resizeStart.current.w + (e.clientX - resizeStart.current.x))),
        h: Math.max(300, Math.min(window.innerHeight - 20, resizeStart.current.h + (e.clientY - resizeStart.current.y))),
      });
    };
    const onUp = () => setIsResizing(false);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [isResizing]);

  const toggleMaximize = () => {
    if (isMaximized) {
      setIsMaximized(false);
      setPosition({ x: window.innerWidth - 420, y: window.innerHeight - 620 });
      setSize({ w: 400, h: 560 });
    } else {
      setIsMaximized(true);
      setPosition({ x: 0, y: 0 });
      setSize({ w: window.innerWidth, h: window.innerHeight });
    }
  };

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
    { label: "Change the header color to blue", icon: "palette" },
  ];

  const handleQuickAction = (message: string) => {
    setMessages((prev) => [...prev, { role: "user", content: message }]);
    setLoading(true);
    fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message,
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
  };

  return (
    <>
      {/* Floating Button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-6 right-6 z-[9999] w-14 h-14 rounded-full bg-primary hover:bg-primary/90 shadow-lg flex items-center justify-center transition-all"
        >
          <span className="material-symbols-outlined text-[24px] text-on-primary">smart_toy</span>
        </button>
      )}

      {/* Chat Window */}
      {isOpen && (
        <div
          ref={windowRef}
          className={`fixed z-[9999] bg-surface-container-lowest border border-outline-variant rounded-lg shadow-2xl flex flex-col overflow-hidden ${
            isMaximized ? "" : "rounded-lg"
          } ${isDragging || isResizing ? "select-none" : ""}`}
          style={{
            left: position.x,
            top: position.y,
            width: size.w,
            height: size.h,
          }}
        >
          {/* Header — draggable */}
          <div
            onMouseDown={onDragStart}
            onDoubleClick={toggleMaximize}
            className="flex items-center gap-3 px-4 py-3 bg-surface-container-low border-b border-outline-variant cursor-move shrink-0"
          >
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center">
              <span className="material-symbols-outlined text-[16px] text-on-primary">smart_toy</span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-semibold text-on-surface">Sentinel AI</div>
              <div className="text-[10px] text-on-surface-variant">Drag to move · Double-click to maximize</div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={toggleMaximize}
                className="w-7 h-7 flex items-center justify-center rounded hover:bg-surface-container-high transition-colors"
                title={isMaximized ? "Restore" : "Maximize"}
              >
                <span className="material-symbols-outlined text-[16px] text-on-surface-variant">
                  {isMaximized ? "fullscreen_exit" : "fullscreen"}
                </span>
              </button>
              <button
                onClick={() => setIsOpen(false)}
                className="w-7 h-7 flex items-center justify-center rounded hover:bg-surface-container-high transition-colors"
                title="Close"
              >
                <span className="material-symbols-outlined text-[16px] text-on-surface-variant">close</span>
              </button>
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

          {/* Quick Actions */}
          {messages.length <= 1 && (
            <div className="px-4 pb-2 flex flex-wrap gap-1.5 shrink-0">
              {quickActions.map((action) => (
                <button
                  key={action.label}
                  onClick={() => handleQuickAction(action.label)}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-container border border-outline-variant rounded text-[10px] text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
                >
                  <span className="material-symbols-outlined text-[12px]">{action.icon}</span>
                  {action.label}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <div className="px-4 py-3 border-t border-outline-variant bg-surface-container-low shrink-0">
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

          {/* Resize handle — bottom-right corner */}
          {!isMaximized && (
            <div
              onMouseDown={onResizeStart}
              className="absolute bottom-0 right-0 w-5 h-5 cursor-nwse-resize flex items-end justify-end p-0.5 group"
              title="Resize"
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                className="text-on-surface-variant group-hover:text-primary transition-colors"
              >
                <path d="M11 1L1 11M11 5L5 11M11 9L9 11" stroke="currentColor" strokeWidth="1.5" fill="none" />
              </svg>
            </div>
          )}

          {/* Resize handles — edges */}
          {!isMaximized && (
            <>
              <div onMouseDown={(e) => { e.preventDefault(); setIsResizing(true); resizeStart.current = { x: e.clientX, y: e.clientY, w: size.w, h: size.h }; const onMove = (ev: MouseEvent) => { setSize(s => ({ ...s, w: Math.max(320, s.w + (ev.clientX - resizeStart.current.x)) })); resizeStart.current.x = ev.clientX; }; const onUp = () => { setIsResizing(false); document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); }; document.addEventListener("mousemove", onMove); document.addEventListener("mouseup", onUp); }} className="absolute top-12 right-0 w-1 h-full cursor-ew-resize" />
              <div onMouseDown={(e) => { e.preventDefault(); setIsResizing(true); resizeStart.current = { x: e.clientX, y: e.clientY, w: size.w, h: size.h }; const onMove = (ev: MouseEvent) => { setSize(s => ({ ...s, h: Math.max(300, s.h + (ev.clientY - resizeStart.current.y)) })); resizeStart.current.y = ev.clientY; }; const onUp = () => { setIsResizing(false); document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); }; document.addEventListener("mousemove", onMove); document.addEventListener("mouseup", onUp); }} className="absolute bottom-0 left-0 w-full h-1 cursor-ns-resize" />
            </>
          )}
        </div>
      )}
    </>
  );
}
