"use client";

import { useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { getSettings, updateSettings, Settings } from "@/lib/api";

export default function SettingsPage() {
  const { token } = useAuth();
  const [settings, setSettings] = useState<Settings>({
    llm_provider: "mock",
    llm_model: "gpt-4",
    auto_investigate: true,
    auto_merge: false,
    notification_email: "",
  });
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    getSettings(token)
      .then(setSettings)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [token]);

  const handleSave = async () => {
    if (!token) return;
    await updateSettings(token, settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <>
      <TopBar
        title="Settings"
        subtitle="System configuration and preferences"
        breadcrumbs={[{ label: "Settings", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[900px] mx-auto space-y-4">
          {/* LLM Configuration */}
          <div className="bg-surface-container-low border border-outline-variant rounded p-4">
            <h2 className="text-[13px] font-semibold text-on-surface mb-4">LLM Configuration</h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[11px] text-on-surface-variant block mb-1">Provider</label>
                <select
                  value={settings.llm_provider}
                  onChange={(e) => setSettings({ ...settings, llm_provider: e.target.value })}
                  className="w-full bg-surface-container border border-outline-variant rounded px-3 py-2 text-[12px] text-on-surface"
                >
                  <option value="mock">Mock (Development)</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="kimi">Kimi</option>
                  <option value="ollama">Ollama (Local)</option>
                </select>
              </div>
              <div>
                <label className="text-[11px] text-on-surface-variant block mb-1">Model</label>
                <input
                  type="text"
                  value={settings.llm_model}
                  onChange={(e) => setSettings({ ...settings, llm_model: e.target.value })}
                  placeholder="gpt-4, claude-3, etc."
                  className="w-full bg-surface-container border border-outline-variant rounded px-3 py-2 text-[12px] text-on-surface placeholder:text-on-surface-variant/50"
                />
              </div>
            </div>
          </div>

          {/* Investigation Settings */}
          <div className="bg-surface-container-low border border-outline-variant rounded p-4">
            <h2 className="text-[13px] font-semibold text-on-surface mb-4">Investigation</h2>
            <div className="space-y-3">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.auto_investigate}
                  onChange={(e) => setSettings({ ...settings, auto_investigate: e.target.checked })}
                  className="w-4 h-4 accent-primary"
                />
                <div>
                  <div className="text-[12px] text-on-surface">Auto-investigate SEV-1 & SEV-2 incidents</div>
                  <div className="text-[10px] text-on-surface-variant">Automatically run AI investigation when high-severity incidents are detected</div>
                </div>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.auto_merge}
                  onChange={(e) => setSettings({ ...settings, auto_merge: e.target.checked })}
                  className="w-4 h-4 accent-primary"
                />
                <div>
                  <div className="text-[12px] text-on-surface">Auto-merge approved fixes</div>
                  <div className="text-[10px] text-on-surface-variant">Automatically merge PRs after human approval</div>
                </div>
              </label>
            </div>
          </div>

          {/* Notifications */}
          <div className="bg-surface-container-low border border-outline-variant rounded p-4">
            <h2 className="text-[13px] font-semibold text-on-surface mb-4">Notifications</h2>
            <div>
              <label className="text-[11px] text-on-surface-variant block mb-1">Notification Email</label>
              <input
                type="email"
                value={settings.notification_email}
                onChange={(e) => setSettings({ ...settings, notification_email: e.target.value })}
                placeholder="ops@example.com"
                className="w-full bg-surface-container border border-outline-variant rounded px-3 py-2 text-[12px] text-on-surface placeholder:text-on-surface-variant/50"
              />
            </div>
          </div>

          {/* Save */}
          <div className="flex justify-end">
            <button
              onClick={handleSave}
              className="px-6 py-2 bg-primary text-on-primary rounded text-[12px] font-medium hover:bg-primary/90 transition-colors"
            >
              {saved ? "Saved!" : "Save Settings"}
            </button>
          </div>
        </div>
      </main>
    </>
  );
}
