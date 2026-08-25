"use client";

import { LogOut, User } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { AuthUser } from "@/lib/api";

/**
 * Signed-out: a plain "Sign in" link. Signed-in: the account's email (only
 * this app knows it — nothing else here needs a name/avatar yet) plus a
 * sign-out icon button styled like ThemeToggle's.
 *
 * `user` comes from the server (AppHeader reads the session cookie and
 * calls getCurrentUser — see lib/api.ts), so this component itself never
 * touches cookies or tokens; signing out just calls the Route Handler that
 * clears them, then refreshes so the server re-renders as signed-out.
 */
export function AccountControl({ user }: { user: AuthUser | null }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  if (!user) {
    return (
      <Link
        href="/login"
        className="rounded-sm px-2.5 py-1 text-[13px] text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
      >
        Sign in
      </Link>
    );
  }

  async function signOut() {
    setLoading(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
      router.refresh();
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="hidden items-center gap-1 text-[11px] text-muted-foreground sm:flex">
        <User className="size-3" aria-hidden />
        <span className="max-w-[140px] truncate">{user.email}</span>
      </span>
      <button
        type="button"
        onClick={signOut}
        disabled={loading}
        aria-label="Sign out"
        title="Sign out"
        className="grid size-8 shrink-0 place-items-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
      >
        <LogOut className="size-4" />
      </button>
    </div>
  );
}
