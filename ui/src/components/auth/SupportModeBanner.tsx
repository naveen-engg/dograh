"use client";

import { AlertOctagon, LogOut, ShieldAlert } from "lucide-react";
import React, { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

export function SupportModeBanner() {
  const { user } = useAuth();
  const [isImpersonating, setIsImpersonating] = useState(false);
  const isSupportEngineer = (user as { role?: string })?.role === "support_engineer";

  useEffect(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("dograh_impersonating");
      setIsImpersonating(stored === "true" || isSupportEngineer);
    }
  }, [isSupportEngineer]);

  const handleExitImpersonation = async () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("dograh_impersonating");
      // Call logout/session reset and redirect back to admin portal
      try {
        await fetch("/api/auth/logout", { method: "POST" });
      } catch (err) {
        console.error("Failed to clear impersonation session", err);
      }
      window.location.href = "/auth/login";
    }
  };

  if (!isImpersonating && !isSupportEngineer) {
    return null;
  }

  return (
    <aside
      aria-label="Support impersonation mode active"
      className="sticky top-0 z-[60] flex w-full flex-wrap items-center justify-between border-b border-amber-500/40 bg-amber-950/80 px-4 py-2 text-xs font-medium text-amber-200 shadow-sm backdrop-blur-md"
    >
      <div className="flex items-center gap-2.5">
        <ShieldAlert className="h-4 w-4 text-amber-400 shrink-0 animate-pulse" />
        <span className="font-semibold text-amber-100">
          SUPPORT IMPERSONATION ACTIVE
        </span>
        <Badge
          variant="outline"
          className="border-amber-400/50 bg-amber-900/60 text-[10px] uppercase text-amber-300"
        >
          Read-Only Enforcement
        </Badge>
        <span className="hidden sm:inline text-amber-300/80">
          All mutations (create/update/delete) are blocked and security-audited.
        </span>
      </div>

      <div className="flex items-center gap-2 mt-1 sm:mt-0">
        <span className="text-[11px] text-amber-300/70">
          Actor: {user?.email || "Support"}
        </span>
        <Button
          size="sm"
          variant="outline"
          onClick={handleExitImpersonation}
          className="h-6 gap-1 border-amber-400/60 bg-amber-900/40 px-2 text-xs text-amber-200 hover:bg-amber-800/60 hover:text-amber-100"
        >
          <LogOut className="h-3 w-3" />
          Exit Impersonation
        </Button>
      </div>
    </aside>
  );
}
