"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { getMe, UserProfile, listIncidents, Incident } from "@/lib/api";

export default function ProfilePage() {
  const { token, userId, username, logout } = useAuth();
  const router = useRouter();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [stats, setStats] = useState({ incidents: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      getMe(token).catch(() => null),
      listIncidents(token).catch(() => []),
    ]).then(([p, inc]) => {
      setProfile(p);
      setStats({ incidents: inc.length });
    }).finally(() => setLoading(false));
  }, [token]);

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  return (
    <>
      <TopBar
        title="Profile"
        subtitle="Your account information"
        breadcrumbs={[{ label: "Profile", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[600px] mx-auto space-y-6">
          {/* Avatar + Name */}
          <div className="bg-surface-container-low border border-outline-variant rounded-lg p-6 flex items-center gap-5">
            <div className="w-16 h-16 rounded-full bg-primary-container flex items-center justify-center text-[28px] font-bold text-on-primary-container">
              {username?.charAt(0).toUpperCase() || "A"}
            </div>
            <div>
              <h2 className="text-[18px] font-semibold text-on-surface">{profile?.username || username || "Admin"}</h2>
              <p className="text-[13px] text-on-surface-variant">{profile?.email || "No email set"}</p>
              <span className="inline-block mt-1 px-2 py-0.5 bg-primary/10 text-primary text-[10px] font-semibold rounded border border-primary/20">
                {loading ? "..." : (profile?.role || "Admin")}
              </span>
            </div>
          </div>

          {/* Account Details */}
          <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
            <h3 className="text-[13px] font-semibold text-on-surface mb-4">Account Details</h3>
            <div className="space-y-3">
              <div className="flex justify-between items-center py-2 border-b border-outline-variant/50">
                <span className="text-[12px] text-on-surface-variant">User ID</span>
                <span className="text-[12px] text-on-surface font-mono">{userId || "—"}</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-outline-variant/50">
                <span className="text-[12px] text-on-surface-variant">Username</span>
                <span className="text-[12px] text-on-surface">{profile?.username || username || "—"}</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-outline-variant/50">
                <span className="text-[12px] text-on-surface-variant">Email</span>
                <span className="text-[12px] text-on-surface">{profile?.email || "—"}</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-outline-variant/50">
                <span className="text-[12px] text-on-surface-variant">Role</span>
                <span className="text-[12px] text-on-surface">{profile?.role || "Admin"}</span>
              </div>
              <div className="flex justify-between items-center py-2">
                <span className="text-[12px] text-on-surface-variant">Session Status</span>
                <span className="flex items-center gap-1.5 text-[12px] text-primary">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                  Active
                </span>
              </div>
            </div>
          </div>

          {/* Activity Summary */}
          <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
            <h3 className="text-[13px] font-semibold text-on-surface mb-4">Activity Summary</h3>
            <div className="grid grid-cols-1 gap-4">
              <div className="bg-surface-container rounded p-3 text-center">
                <div className="text-[24px] font-bold text-on-surface">{stats.incidents}</div>
                <div className="text-[11px] text-on-surface-variant">Total Incidents</div>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="bg-surface-container-low border border-outline-variant rounded-lg p-4">
            <h3 className="text-[13px] font-semibold text-on-surface mb-4">Actions</h3>
            <div className="space-y-2">
              <button
                onClick={() => router.push("/settings")}
                className="w-full flex items-center gap-3 p-3 bg-surface-container border border-outline-variant rounded text-[12px] text-on-surface hover:bg-surface-container-high transition-colors"
              >
                <span className="material-symbols-outlined text-[18px] text-on-surface-variant">settings</span>
                Settings
              </button>
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-3 p-3 bg-error/10 border border-error/20 rounded text-[12px] text-error hover:bg-error/20 transition-colors"
              >
                <span className="material-symbols-outlined text-[18px]">logout</span>
                Log Out
              </button>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
