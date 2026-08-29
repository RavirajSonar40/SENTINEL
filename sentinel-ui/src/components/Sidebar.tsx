"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Logo from "@/components/Logo";

const navSections = [
  {
    label: null,
    items: [
      { href: "/", icon: "home", label: "Overview" },
    ],
  },
  {
    label: "INCIDENT RESPONSE",
    items: [
      { href: "/incidents", icon: "emergency", label: "Incidents" },
      { href: "/security", icon: "shield", label: "Security Command", tag: "P17" },
      { href: "/reliability", icon: "speed", label: "SLOs & Reliability", tag: "P16" },
      { href: "/monitoring", icon: "sensors", label: "Monitoring & Signals", tag: "Live" },
      { href: "/automatic-response", icon: "bolt", label: "Automatic Response", tag: "New" },
      { href: "/investigations", icon: "psychology", label: "Investigations" },
      { href: "/alerts", icon: "notifications", label: "Alerts" },
    ],

  },
  {
    label: "SYSTEM",
    items: [
      { href: "/changes", icon: "history_toggle_off", label: "Change Ledger", tag: "P7" },
      { href: "/topology", icon: "schema", label: "System Graph", tag: "P6" },
      { href: "/catalog", icon: "account_tree", label: "Catalog & Topology" },
      { href: "/deployments", icon: "rocket_launch", label: "Deployments" },
      { href: "/services", icon: "settings_input_component", label: "Services" },
      { href: "/repositories", icon: "folder", label: "Repositories" },
      { href: "/integrations", icon: "hub", label: "Integrations" },
      { href: "/health", icon: "monitor_heart", label: "Health" },
    ],
  },
  {
    label: "REMEDIATION",
    items: [
      { href: "/pull-requests", icon: "merge", label: "Pull Requests" },
    ],
  },
  {
    label: "ADMIN",
    items: [
      { href: "/settings", icon: "settings", label: "Settings" },
      { href: "/users", icon: "group", label: "Users" },
      { href: "/audit-logs", icon: "history", label: "Audit Logs" },
    ],
  },
  {
    label: null,
    items: [
      { href: "/profile", icon: "person", label: "Profile" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <nav className="w-[220px] h-screen flex flex-col bg-surface-container-lowest fixed left-0 top-0 z-50 border-r border-outline-variant">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-outline-variant">
        <Logo size="md" href="/" />
      </div>

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto py-2 px-2">
        {navSections.map((section, si) => (
          <div key={si} className="mb-3">
            {section.label && (
              <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-on-surface-variant/60">
                {section.label}
              </div>
            )}
            {section.items.map((item) => {
              const isActive =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] font-medium transition-colors mb-0.5 ${
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
                  }`}
                >
                  <span
                    className={`material-symbols-outlined text-[18px] ${
                      isActive ? "fill-1" : ""
                    }`}
                    style={
                      isActive
                        ? { fontVariationSettings: "'FILL' 1" }
                        : undefined
                    }
                  >
                    {item.icon}
                  </span>
                  <span className="flex-1">{item.label}</span>
                  {"tag" in item && (item as { tag?: string }).tag && (
                    <span className="bg-tertiary/20 text-tertiary text-[9px] font-bold px-1.5 py-0.5 rounded uppercase">
                      {(item as { tag?: string }).tag}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </div>

      {/* Report Button + Help */}
      <div className="p-2 border-t border-outline-variant">
        <Link
          href="/incidents/new"
          className="flex items-center justify-center gap-2 w-full px-3 py-2.5 bg-primary-container text-on-primary-container text-[12px] font-semibold uppercase tracking-wider rounded-md hover:bg-primary hover:text-on-primary-fixed transition-colors"
        >
          <span className="material-symbols-outlined text-[16px]">add</span>
          Report Production Error
        </Link>
        <button
          onClick={() => window.open("https://github.com/RavirajSonar40/SENTINEL#readme", "_blank")}
          className="flex items-center gap-2 w-full px-3 py-2 mt-1 text-on-surface-variant text-[12px] font-medium hover:bg-surface-container-high rounded-md transition-colors"
        >
          <span className="material-symbols-outlined text-[16px]">help</span>
          Help & Support
          <span className="material-symbols-outlined text-[14px] ml-auto">open_in_new</span>
        </button>
      </div>
    </nav>
  );
}
