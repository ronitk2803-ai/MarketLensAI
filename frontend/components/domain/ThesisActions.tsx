"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { ThesisStatus } from "@/lib/api";

/** Status changes and delete both go through app/api/theses/[id]/route.ts
 * — the mutation-only Route Handler this feature needs (reads go straight
 * from the Server Component page, same reasoning as auth's routes). */
export function ThesisActions({ id, status }: { id: number; status: ThesisStatus }) {
  const router = useRouter();
  const [loading, setLoading] = useState<string | null>(null);

  async function setStatus(next: ThesisStatus) {
    setLoading(next);
    try {
      await fetch(`/api/theses/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: next }),
      });
      router.refresh();
    } finally {
      setLoading(null);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this thesis and its whole history? This can't be undone.")) return;
    setLoading("delete");
    try {
      await fetch(`/api/theses/${id}`, { method: "DELETE" });
      router.push("/theses");
    } finally {
      setLoading(null);
    }
  }

  const buttonClass =
    "rounded-sm border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground disabled:opacity-50";

  return (
    <div className="flex flex-wrap gap-1.5">
      {status !== "invalidated" && status !== "closed" && (
        <button
          type="button"
          onClick={() => setStatus("invalidated")}
          disabled={loading !== null}
          className={buttonClass}
        >
          {loading === "invalidated" ? "Marking…" : "Mark invalidated"}
        </button>
      )}
      {status !== "closed" && (
        <button
          type="button"
          onClick={() => setStatus("closed")}
          disabled={loading !== null}
          className={buttonClass}
        >
          {loading === "closed" ? "Marking…" : "Mark closed"}
        </button>
      )}
      <button
        type="button"
        onClick={handleDelete}
        disabled={loading !== null}
        className="rounded-sm border border-border px-2.5 py-1 text-xs text-down transition-colors hover:bg-down/10 disabled:opacity-50"
      >
        {loading === "delete" ? "Deleting…" : "Delete"}
      </button>
    </div>
  );
}
