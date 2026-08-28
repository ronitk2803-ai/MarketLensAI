"use client";

import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { relativeTime } from "@/lib/format";
import { parseAiSummary } from "@/lib/parse-ai-summary";
import type { AiSummary, Meta } from "@/lib/api";

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
/**
 * Renders the synthesis + supporting/risk factors if the text matches
 * that shape, otherwise the raw text as one paragraph — a parsing miss
 * degrades to plain text, never to nothing.
 *
 * Deliberately no color-coding (no green for "supporting", red for
 * "risk"): this app's up/down tokens mean "price rose/fell" everywhere
 * else, and reusing them here would visually assert a bullish/bearish
 * verdict through color even though the text itself is explicitly
 * instructed never to give one — the "no advice" rule has to hold for the
 * whole panel, not just the words.
 */
function SummaryBody({ text }: { text: string }) {
  const parsed = parseAiSummary(text);
  if (!parsed) {
    return <p className="text-sm leading-relaxed">{text}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {parsed.intro && <p className="text-sm leading-relaxed">{parsed.intro}</p>}
      {parsed.supportingFactors.length > 0 && (
        <div>
          <p className="label-caps mb-1">Supporting factors</p>
          <ul className="flex flex-col gap-1 text-sm leading-snug">
            {parsed.supportingFactors.map((f, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-muted-foreground" aria-hidden>
                  •
                </span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {parsed.riskFactors.length > 0 && (
        <div>
          <p className="label-caps mb-1">Risk factors</p>
          <ul className="flex flex-col gap-1 text-sm leading-snug">
            {parsed.riskFactors.map((f, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-muted-foreground" aria-hidden>
                  •
                </span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function AiSummaryPanel({
  symbol,
  initial,
  meta,
  canGenerate,
}: {
  symbol: string;
  initial: AiSummary | null;
  meta: Meta;
  /** Generating spends an LLM call, so the backend requires sign-in for it
   * and additionally rate-limits it per user (~5/day — app/core/
   * rate_limit.py). Reading a cached summary stays public, which is why
   * this only gates the button and not the panel. */
  canGenerate: boolean;
}) {
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
      const body = (await res.json()) as AiSummary & { error?: string };
      if (!res.ok) {
        // Show what actually went wrong. "Try again in a moment" is right
        // for a blip and actively misleading for a misconfigured key.
        setError(body.error ?? "Couldn't generate a summary right now — try again in a moment.");
        return;
      }
      setSummary(body);
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
          <div className="flex items-center gap-3">
            {/* The badge belongs to the cached summary, so it shows for
                everyone; only regenerating spends a call. */}
            <ProvenanceBadge
              source={meta.source}
              asOf={summary.generated_at}
              confidence={meta.confidence}
            />
            {canGenerate && (
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
            )}
          </div>
        )
      }
      footnote="AI-generated interpretation, produced for research and analytical purposes only — not verified data, not investment advice, and not a recommendation to buy, sell, or hold. MarketLens AI is not a SEBI-registered investment adviser or research analyst; verify independently before acting."
    >
      {!summary ? (
        <div className="flex flex-col items-center gap-3 px-3 py-8 text-center">
          {canGenerate ? (
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
          ) : (
            <p className="text-xs text-muted-foreground">
              <Link href="/login" className="text-primary hover:underline">
                Sign in
              </Link>{" "}
              to generate a summary. Summaries already generated for a company are visible to
              everyone.
            </p>
          )}
          {error && <p className="text-xs text-down">{error}</p>}
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-3 py-3">
          <SummaryBody text={summary.summary} />
          <p className="text-[11px] text-muted-foreground">
            Generated {relativeTime(summary.generated_at)}
          </p>
          {error && <p className="text-xs text-down">{error}</p>}
        </div>
      )}
    </Panel>
  );
}
