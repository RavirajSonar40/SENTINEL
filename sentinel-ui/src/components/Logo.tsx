"use client";

import React from "react";
import Link from "next/link";

interface LogoProps {
  size?: "sm" | "md" | "lg" | "xl";
  showWordmark?: boolean;
  subtitle?: string;
  href?: string;
  className?: string;
}

const sizeConfig = {
  sm: {
    container: "w-7 h-7 rounded-md",
    icon: "w-4 h-4",
    title: "text-sm font-bold tracking-tight",
    subtitle: "text-[10px]",
    gap: "gap-2",
  },
  md: {
    container: "w-8 h-8 rounded-lg",
    icon: "w-5 h-5",
    title: "text-[15px] font-bold tracking-tight",
    subtitle: "text-[11px]",
    gap: "gap-2.5",
  },
  lg: {
    container: "w-12 h-12 rounded-xl",
    icon: "w-7 h-7",
    title: "text-xl font-semibold",
    subtitle: "text-[12px]",
    gap: "gap-3",
  },
  xl: {
    container: "w-16 h-16 rounded-2xl",
    icon: "w-10 h-10",
    title: "text-2xl font-bold tracking-tight",
    subtitle: "text-[13px]",
    gap: "gap-4",
  },
};

export default function Logo({
  size = "md",
  showWordmark = true,
  subtitle,
  href,
  className = "",
}: LogoProps) {
  const cfg = sizeConfig[size] || sizeConfig.md;

  const content = (
    <div className={`flex items-center ${cfg.gap} ${className}`}>
      <div
        className={`${cfg.container} bg-primary-container/80 border border-primary/20 flex items-center justify-center flex-shrink-0 shadow-sm`}
      >
        <img
          src="/sentinel_logo.png"
          alt="Sentinel"
          className={`${cfg.icon} object-contain select-none`}
        />
      </div>

      {showWordmark && (
        <div className="flex flex-col">
          <span className={`${cfg.title} text-on-surface leading-tight`}>
            RAVIRAJ SENTINEL
          </span>
          {subtitle && (
            <span className={`${cfg.subtitle} text-on-surface-variant leading-tight`}>
              {subtitle}
            </span>
          )}
        </div>
      )}
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="inline-flex items-center hover:opacity-90 transition-opacity">
        {content}
      </Link>
    );
  }

  return content;
}
