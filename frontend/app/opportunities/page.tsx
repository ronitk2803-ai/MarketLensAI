import Link from "next/link";

import { OpportunityTable } from "@/components/domain/OpportunityTable";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { getOpportunities, getOpportunityIndustries, getOpportunityScreens } from "@/lib/api";
import { PRESET_TREES, encodeTree } from "@/lib/screener-tree";
import { cn } from "@/lib/utils";

// This is a static route (no [param] segment), so Next attempts to
// prerender it at build time by default — which fails when the backend
// isn't running during `next build` (verified live: ECONNREFUSED against
// API_BASE_URL). Screening results should reflect current data on each
// request anyway (the fetch-level `revalidate` above already bounds
// staleness), so force this dynamic rather than statically cached.
export const dynamic = "force-dynamic";
// See company/[symbol]/page.tsx — cold free-tier backend can exceed the
// default 10s Vercel function budget.
export const maxDuration = 60;

export default async function OpportunitiesPage({
  searchParams,
}: {
  searchParams: Promise<{ screen?: string; industry?: string }>;
}) {
  const [screensResult, industriesResult, params] = await Promise.all([
    getOpportunityScreens(),
    getOpportunityIndustries(),
    searchParams,
  ]);
  const screens = screensResult.data;
  const industries = industriesResult.data;
  const { screen: rawScreen, industry: rawIndustry } = params;
  const activeScreen =
    rawScreen && screens.some((s) => s.id === rawScreen) ? rawScreen : (screens[0]?.id ?? "");
  const activeIndustry =
    rawIndustry && industries.some((i) => i.code === rawIndustry) ? rawIndustry : undefined;

  const result = activeScreen ? await getOpportunities(activeScreen, activeIndustry) : null;
  const hits = result?.data ?? [];
  const scored = hits.filter((h) => typeof h.opportunity_score === "number");

  // Every preset is expressible as a condition tree, so "refine" hands the
  // builder the exact equivalent rather than starting from a blank slate.
  const presetTree = PRESET_TREES[activeScreen];
  const refineHref = presetTree
    ? `/opportunities/advanced?q=${encodeTree(presetTree)}${
        activeIndustry ? `&industry=${encodeURIComponent(activeIndustry)}` : ""
      }`
    : "/opportunities/advanced";

  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 px-4 py-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Screener</h1>
        <p className="text-xs text-muted-foreground">
          What deserves attention right now — screened against stored end-of-day data. Research
          candidates, not recommendations.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {screens.map((s) => (
          <Link
            key={s.id}
            href={`/opportunities?screen=${s.id}${activeIndustry ? `&industry=${encodeURIComponent(activeIndustry)}` : ""}`}
            className={cn(
              "rounded-sm border px-2.5 py-1 text-xs transition-colors",
              s.id === activeScreen
                ? "border-primary bg-primary/15 font-medium text-foreground"
                : "border-border text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )}
          >
            {s.label}
          </Link>
        ))}
      </div>

      {industries.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="label-caps mr-1 text-muted-foreground">Industry</span>
          <Link
            href={`/opportunities?screen=${activeScreen}`}
            className={cn(
              "rounded-sm border px-2.5 py-1 text-xs transition-colors",
              !activeIndustry
                ? "border-primary bg-primary/15 font-medium text-foreground"
                : "border-border text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )}
          >
            All
          </Link>
          {industries.map((i) => (
            <Link
              key={i.code}
              href={`/opportunities?screen=${activeScreen}&industry=${encodeURIComponent(i.code)}`}
              className={cn(
                "rounded-sm border px-2.5 py-1 text-xs transition-colors",
                i.code === activeIndustry
                  ? "border-primary bg-primary/15 font-medium text-foreground"
                  : "border-border text-muted-foreground hover:bg-accent/60 hover:text-foreground",
              )}
            >
              {i.name}
            </Link>
          ))}
        </div>
      )}

      <Panel
        title={
          <div className="flex items-baseline gap-3">
            <h2 className="label-caps">
              {screens.find((s) => s.id === activeScreen)?.label ?? "Results"}
            </h2>
            <span className="num text-[11px] text-muted-foreground">
              {hits.length} match{hits.length === 1 ? "" : "es"}
              {scored.length !== hits.length && ` · ${scored.length} scored`}
            </span>
          </div>
        }
        actions={
          <div className="flex items-center gap-3">
            <Link href={refineHref} className="text-[11px] text-primary hover:underline">
              Refine in advanced builder →
            </Link>
            {result && (
              <ProvenanceBadge
                source={result.meta.source}
                asOf={result.meta.as_of}
                confidence={result.meta.confidence}
              />
            )}
          </div>
        }
        bodyClassName="p-0"
        footnote="Ranked by Opportunity Score where available — attention-worthiness, not raw decline, and not a buy/sell/hold recommendation. Rows without a score yet sort after every scored row. MarketLens AI is not a SEBI-registered investment adviser or research analyst."
      >
        {hits.length === 0 ? (
          <p className="px-3 py-10 text-center text-sm text-muted-foreground">
            No matches right now — either nothing meets the threshold, or the universe
            doesn&apos;t have enough price history yet.
          </p>
        ) : (
          <OpportunityTable hits={hits} />
        )}
      </Panel>
    </main>
  );
}
