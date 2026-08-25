"use client";

import { useEffect, useState } from "react";
import TopBar from "@/components/TopBar";
import { useAuth } from "@/lib/AuthContext";
import { listUsers, User } from "@/lib/api";

const roleColors: Record<string, string> = {
  admin: "bg-primary/10 text-primary border-primary/20",
  investigator: "bg-tertiary/10 text-tertiary border-tertiary/20",
  viewer: "bg-surface-container-high text-on-surface-variant border-outline-variant",
};

export default function UsersPage() {
  const { token } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    listUsers(token)
      .then(setUsers)
      .catch(() => setUsers([]))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <>
      <TopBar
        title="Users"
        subtitle="User management and access control"
        breadcrumbs={[{ label: "Users", active: true }]}
      />
      <main className="flex-1 p-6 pb-10">
        <div className="max-w-[1400px] mx-auto">
          <div className="bg-surface-container-low border border-outline-variant rounded">
            <div className="p-4 border-b border-outline-variant flex items-center justify-between">
              <h2 className="text-[13px] font-semibold text-on-surface">Users ({users.length})</h2>
            </div>
            {loading ? (
              <div className="p-8 text-center text-on-surface-variant text-[12px] font-mono">Loading...</div>
            ) : users.length === 0 ? (
              <div className="p-8 text-center text-on-surface-variant text-[12px]">No users found</div>
            ) : (
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-outline-variant bg-surface-container">
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Username</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Email</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Role</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Status</th>
                    <th className="text-[10px] font-semibold uppercase tracking-wider text-on-surface-variant py-2 px-4">Created</th>
                  </tr>
                </thead>
                <tbody className="font-mono text-[11px]">
                  {users.map((user) => (
                    <tr key={user.id} className="border-b border-outline-variant/50 hover:bg-surface-container-high/50 transition-colors">
                      <td className="py-2.5 px-4 text-on-surface font-medium">{user.username}</td>
                      <td className="py-2.5 px-4 text-on-surface-variant">{user.email}</td>
                      <td className="py-2.5 px-4">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${roleColors[user.role] || roleColors.viewer}`}>
                          {user.role}
                        </span>
                      </td>
                      <td className="py-2.5 px-4">
                        <span className={`flex items-center gap-1.5 ${user.is_active ? "text-primary" : "text-on-surface-variant"}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${user.is_active ? "bg-primary" : "bg-outline"}`} />
                          {user.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-on-surface-variant">
                        {user.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
