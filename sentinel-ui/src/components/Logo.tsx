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

export default function Logo({
  size = "md",
  showWordmark = true,
  subtitle,
  href,
  className = "",
}: LogoProps) {
  const content = (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <div className="w-8 h-8 rounded-lg bg-primary-container/80 flex items-center justify-center shadow-sm">
        <img
          src="/sentinel_logo.png"
          alt="Sentinel"
          className="w-5 h-5 object-contain"
        />
      </div>
      {showWordmark && (
        <div className="flex flex-col">
          <span className="text-[15px] font-bold text-on-surface">SENTINEL</span>
          {subtitle && (
            <span className="text-[11px] text-on-surface-variant">{subtitle}</span>
          )}
        </div>
      )}
    </div>
  );

  return href ? <Link href={href}>{content}</Link> : content;
}
