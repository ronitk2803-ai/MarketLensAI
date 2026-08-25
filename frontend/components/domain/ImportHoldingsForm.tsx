"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Panel } from "@/components/terminal/Panel";
import type { PortfolioImportSummary } from "@/lib/api";

/** Zerodha holdings-CSV import — posts to app/api/portfolio/import/route.ts
 * (the first multipart BFF route in the app). The backend's tolerant
 * header-matching parser is the mitigation for not having a fully
 * confirmed exact column format (Build_plan.md's own "format variance"
 * risk flag) — this form surfaces the resulting per-row summary so a
 * mismatch is visible rather than a silent wrong import. */
export function ImportHoldingsForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<PortfolioImportSummary | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSummary(null);

    const file = inputRef.current?.files?.[0];
    if (!file) {
      setError("Choose a .csv file first.");
      return;
    }

    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
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

  const skippedRows = summary?.rows.filter((r) => r.status === "skipped") ?? [];
  const takeoverRows =
    summary?.rows.filter((r) => r.status === "imported" && r.reason) ?? [];

  return (
    <Panel title="Import from Zerodha">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-3 py-3">
        <p className="text-xs text-muted-foreground">
          Upload your Console holdings export (.csv). This replaces whatever you last imported —
          holdings you added manually are left alone unless the file has the same symbol.
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          className="text-xs file:mr-2 file:rounded-sm file:border file:border-input file:bg-surface file:px-2 file:py-1 file:text-xs file:text-foreground"
        />

        {error && <p className="text-xs text-down">{error}</p>}

        {summary && (
          <div className="rounded-sm border border-border p-2 text-xs">
            <p className="font-medium">
              Imported {summary.imported}, skipped {summary.skipped}.
            </p>
            {takeoverRows.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-muted-foreground">
                {takeoverRows.map((r) => (
                  <li key={`${r.row_number}-${r.symbol}`}>
                    {r.symbol}: {r.reason}
                  </li>
                ))}
              </ul>
            )}
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
          {loading ? "Importing…" : "Import CSV"}
        </button>
      </form>
    </Panel>
  );
}
