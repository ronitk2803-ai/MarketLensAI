"use client";

import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";

import { Panel } from "@/components/terminal/Panel";
import { relativeTime } from "@/lib/format";
import type { AiSummary } from "@/lib/api";

/**
 * AI narrative summary — deliberately click-triggered, not auto-loaded.
 *
 * The GET that hydrates `initial` is cache-only and free (it just reads
 * whatever's already stored for this asset); a click is the only thing
 * that can spend a (free-tier, rate-limited) LLM call, and even then only
 * when the backend decides the cached summary is actually stale — see
 * app/services/company_summary.py. Most viewers never click, and repeat
 * clicks on an unchanged company are free re-reads, which is what keeps
 * this feature both free-to-run and free-to-use regardless of traffic.
 */
export function AiSummaryPanel({ symbol, initial }: { symbol: string; initial: AiSummary | null }) {
  const [summary, setSummary] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/ai-summary?symbol=${encodeURIComponent(symbol)}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error();
      setSummary((await res.json()) as AiSummary);
    } catch {
      setError("Couldn't generate a summary right now — try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Panel
      title="AI summary"
      actions={
        summary && (
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
            title="Regenerate — free unless something about the company changed"
          >
            <RefreshCw className={loading ? "size-3 animate-spin" : "size-3"} aria-hidden />
            Regenerate
          </button>
        )
      }
      footnote="AI-generated interpretation, not verified data or investment advice."
    >
      {!summary ? (
        <div className="flex flex-col items-center gap-3 px-3 py-8 text-center">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-md border border-border bg-surface-raised px-3 py-1.5 text-xs font-medium hover:bg-surface-raised/70 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="size-3.5" aria-hidden />
            )}
            {loading ? "Generating…" : "Generate AI summary"}
          </button>
          {error && <p className="text-xs text-down">{error}</p>}
        </div>
      ) : (
        <div className="flex flex-col gap-2 px-3 py-3">
          <p className="text-sm leading-relaxed">{summary.summary}</p>
          <p className="text-[11px] text-muted-foreground">
            Generated {relativeTime(summary.generated_at)}
          </p>
          {error && <p className="text-xs text-down">{error}</p>}
        </div>
      )}
    </Panel>
  );
}
