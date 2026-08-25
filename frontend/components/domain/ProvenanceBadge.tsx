import { Info } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** Raw backend `source` strings are internal identifiers
 * (`yfinance_fundamentals`, `mlai_scoring_v1`) — not copy a user should
 * see verbatim. Unmapped values fall back to the raw string rather than
 * disappearing, so a future/unrecognized source is never hidden. */
const SOURCE_LABELS: Record<string, string> = {
  cache: "Cached price",
  upstox: "Upstox",
  nse_bhavcopy: "NSE Bhavcopy",
  yfinance_actions: "Yahoo Finance (corporate actions)",
  yfinance_fundamentals: "Yahoo Finance (fundamentals)",
  yfinance_quotes: "Yahoo Finance (live)",
  google_news: "Google News",
  gemini_summary: "Gemini AI",
  mlai_scoring_v1: "MarketLens AI scoring",
  db: "Stored data",
  static: "Built-in screen definition",
};

/**
 * "source + as_of" hover affordance (architecture.md §E): every metric
 * should be able to reveal where it came from and how fresh it is, so
 * facts stay visibly distinct from interpretation.
 */
export function ProvenanceBadge({
  source,
  asOf,
  confidence,
}: {
  source: string;
  asOf: string | null;
  confidence: "high" | "low";
}) {
  const asOfLabel = asOf ? new Date(asOf).toLocaleString() : "unavailable";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-default items-center gap-1 text-xs text-muted-foreground">
          <Info className="size-3" aria-hidden />
          {confidence === "low" ? "Limited data" : "Source"}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p>Source: {SOURCE_LABELS[source] ?? source}</p>
        <p>As of: {asOfLabel}</p>
        {confidence === "low" && <p>Coverage is limited for this view.</p>}
      </TooltipContent>
    </Tooltip>
  );
}
