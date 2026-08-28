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
  const [error, setError] = useState<string | null>(null);

  /** Both actions used to ignore the response entirely, which was fine
   *  while they could only succeed. The verified-email gate can now refuse
   *  them with a 403, and an unexplained no-op reads as a broken button. */
  async function failureMessage(res: Response): Promise<string | null> {
    if (res.ok) return null;
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    return body.error ?? "That didn't save. Try again.";
  }

  async function setStatus(next: ThesisStatus) {
    setLoading(next);
    setError(null);
    try {
      const res = await fetch(`/api/theses/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: next }),
      });
      const message = await failureMessage(res);
      if (message) {
        setError(message);
        return;
      }
      router.refresh();
    } finally {
      setLoading(null);
    }
  }

  async function handleDelete() {
    if (!confirm("Delete this thesis and its whole history? This can't be undone.")) return;
    setLoading("delete");
    setError(null);
    try {
      const res = await fetch(`/api/theses/${id}`, { method: "DELETE" });
      const message = await failureMessage(res);
      if (message) {
        setError(message);
        return;
      }
      router.push("/theses");
    } finally {
      setLoading(null);
    }
  }

  const buttonClass =
    "rounded-sm border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground disabled:opacity-50";

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {error && <p className="w-full text-[11px] text-down">{error}</p>}
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
