"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Posts to app/api/alerts/read/route.ts — the one BFF route this feature
 * needs, since the page itself reads server-side. Marking read never
 * deletes: an alert row is also the record that it was already generated,
 * so removing it would let the next night's job recreate it. */
export function MarkAlertsRead({ unreadCount }: { unreadCount: number }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  if (unreadCount === 0) return null;

  async function handleClick() {
    setLoading(true);
    try {
      await fetch("/api/alerts/read", { method: "POST" });
      router.refresh();
    } finally {
      setLoading(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className="rounded-sm border border-border px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground disabled:opacity-50"
    >
      {loading ? "Marking…" : `Mark all read (${unreadCount})`}
    </button>
  );
}
