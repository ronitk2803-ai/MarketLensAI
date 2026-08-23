"use client";

import { AlertTriangle } from "lucide-react";

/**
 * Every page here is backed by the API, so the overwhelmingly likely cause
 * of an unhandled error is the backend being unreachable or misconfigured
 * (wrong API_BASE_URL, cold database, migrations not run). Say that plainly
 * instead of showing a stack trace — this is the first thing a fresh deploy
 * hits when something in the runbook was missed.
 */
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center gap-3 px-4 py-20 text-center">
      <AlertTriangle className="size-6 text-muted-foreground" aria-hidden />
      <h1 className="text-base font-semibold">Couldn&apos;t load market data</h1>
      <p className="text-[13px] text-muted-foreground">
        The API didn&apos;t respond. If this is a fresh deployment, check that the backend is
        running, that <code className="num">API_BASE_URL</code> points at it, and that the
        database has been migrated and seeded.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-1 rounded-sm border border-border px-3 py-1.5 text-[13px] hover:bg-accent"
      >
        Try again
      </button>
    </main>
  );
}
