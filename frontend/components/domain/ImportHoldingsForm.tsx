"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Panel } from "@/components/terminal/Panel";
import type { PortfolioBroker, PortfolioImportSummary } from "@/lib/api";

const BROKER_OPTIONS: { value: PortfolioBroker; label: string }[] = [
  { value: "zerodha", label: "Zerodha" },
  { value: "upstox", label: "Upstox" },
];

/** Broker holdings import (Zerodha or Upstox, .csv or .xlsx) — posts to
 * app/api/portfolio/import/route.ts (the first multipart BFF route in the
 * app). The backend's tolerant header-matching parser is the mitigation
 * for not having a fully confirmed exact column format for either broker
 * (Build_plan.md's own "format variance" risk flag) — this form surfaces
 * the resulting per-row summary so a mismatch is visible rather than a
 * silent wrong import.
 *
 * `broker` is required and explicit (not auto-detected from the file) —
 * it's what scopes re-import replacement to just this broker's own
 * previously-imported holdings, so guessing wrong would silently corrupt
 * the wrong bucket. A user can import both brokers' files one after the
 * other; a stock held in both consolidates into one row rather than the
 * second import overwriting the first. */
export function ImportHoldingsForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [broker, setBroker] = useState<PortfolioBroker>("zerodha");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<PortfolioImportSummary | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSummary(null);

    const file = inputRef.current?.files?.[0];
    if (!file) {
      setError("Choose a .csv or .xlsx file first.");
      return;
    }

    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("broker", broker);
      const res = await fetch("/api/portfolio/import", { method: "POST", body: formData });
      const body = (await res.json()) as PortfolioImportSummary & { error?: string };
      if (!res.ok) {
        setError(body.error ?? "Couldn't import the file.");
        return;
      }
      setSummary(body);
      if (inputRef.current) inputRef.current.value = "";
      router.refresh();
    } catch {
      setError("Something went wrong — try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  const brokerLabel = BROKER_OPTIONS.find((b) => b.value === broker)?.label ?? broker;

  const skippedRows = summary?.rows.filter((r) => r.status === "skipped") ?? [];

  return (
    <Panel title="Import holdings">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-3 py-3">
        <label className="flex flex-col gap-1">
          <span className="label-caps">Broker</span>
          <select
            value={broker}
            onChange={(e) => setBroker(e.target.value as PortfolioBroker)}
            className="h-8 rounded-sm border border-input bg-surface px-2 text-xs"
          >
            {BROKER_OPTIONS.map((b) => (
              <option key={b.value} value={b.value}>
                {b.label}
              </option>
            ))}
          </select>
        </label>

        <p className="text-xs text-muted-foreground">
          Upload your {brokerLabel} holdings export (.csv or .xlsx). This replaces your previously
          imported {brokerLabel} holdings — other brokers and manually added holdings are left
          alone.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx"
          className="text-xs file:mr-2 file:rounded-sm file:border file:border-input file:bg-surface file:px-2 file:py-1 file:text-xs file:text-foreground"
        />

        {error && <p className="text-xs text-down">{error}</p>}

        {summary && (
          <div className="rounded-sm border border-border p-2 text-xs">
            <p className="font-medium">
              Imported {summary.imported}, skipped {summary.skipped}.
            </p>
            {skippedRows.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-down">
                {skippedRows.map((r) => (
                  <li key={`${r.row_number}-${r.symbol || "row"}`}>
                    Row {r.row_number}: {r.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="h-9 rounded-sm bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/80 disabled:opacity-50"
        >
          {loading ? "Importing…" : "Import"}
        </button>
      </form>
    </Panel>
  );
}
