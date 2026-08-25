import Link from "next/link";

import { ConditionBuilder } from "@/components/domain/ConditionBuilder";
import { OpportunityTable } from "@/components/domain/OpportunityTable";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { getOpportunityIndustries, getScreenerMetrics, runScreener } from "@/lib/api";
import { EMPTY_TREE, decodeTree } from "@/lib/screener-tree";
import { getSignedInSession } from "@/lib/session";
import type { OpportunityHit, ScreenerMeta } from "@/lib/api";

// Same reasoning as /opportunities: a static route Next would otherwise
// try to prerender against a backend that isn't running at build time.
export const dynamic = "force-dynamic";

export default async function AdvancedScreenerPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; industry?: string }>;
}) {
  const [session, metricsResult, industriesResult, params] = await Promise.all([
    getSignedInSession(),
    getScreenerMetrics(),
    getOpportunityIndustries(),
    searchParams,
  ]);
  const metrics = metricsResult.data;
  const industries = industriesResult.data;

  // A malformed or hand-truncated ?q= falls back to a starter tree rather
  // than erroring — the backend validates independently anyway.
  const tree = decodeTree(params.q) ?? EMPTY_TREE;
  const activeIndustry =
    params.industry && industries.some((i) => i.code === params.industry)
      ? params.industry
      : undefined;

  let hits: OpportunityHit[] = [];
  let meta: ScreenerMeta | null = null;
  let error: string | null = null;
  if (session && params.q) {
    try {
      const result = await runScreener(session.accessToken, tree, activeIndustry);
      hits = result.data;
      meta = result.meta;
    } catch {
      error = "Couldn't run that screen — check the conditions and try again.";
    }
  }

  // Conditions whose metric isn't available for the whole universe. Shown
  // because excluding a row for missing data is right, but silently
  // returning nothing would make "no data" look like "no match".
  const partial = (meta?.coverage ?? []).filter((c) => c.available < c.total);

  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 px-4 py-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Advanced screener</h1>
          <p className="text-xs text-muted-foreground">
            Combine conditions with AND/OR across price, technical and fundamental metrics.
          </p>
        </div>
        <Link href="/opportunities" className="text-[11px] text-primary hover:underline">
          ← Preset screens
        </Link>
      </div>

      {!session ? (
        <Panel title="Advanced screener" bodyClassName="p-0">
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            <Link href="/login" className="text-primary hover:underline">
              Sign in
            </Link>{" "}
            to build a custom screen.
          </p>
        </Panel>
      ) : (
        <>
          <Panel title="Conditions">
            <ConditionBuilder
              initialTree={tree}
              metrics={metrics}
              industries={industries}
              initialIndustry={activeIndustry}
            />
          </Panel>

          <Panel
            title={
              <div className="flex items-baseline gap-3">
                <h2 className="label-caps">Results</h2>
                {meta && (
                  <span className="num text-[11px] text-muted-foreground">
                    {hits.length} match{hits.length === 1 ? "" : "es"} of {meta.universe_size}{" "}
                    screened
                  </span>
                )}
              </div>
            }
            actions={
              meta && (
                <ProvenanceBadge
                  source={meta.source}
                  asOf={meta.as_of}
                  confidence={meta.confidence}
                />
              )
            }
            bodyClassName="p-0"
            footnote="Ranked by Opportunity Score where available — attention-worthiness, not raw decline. A condition whose metric is missing for a company excludes it rather than passing it; coverage below says how often that happened."
          >
            {error ? (
              <p className="px-3 py-10 text-center text-sm text-down">{error}</p>
            ) : !params.q ? (
              <p className="px-3 py-10 text-center text-sm text-muted-foreground">
                Build a set of conditions above, then run the screen.
              </p>
            ) : hits.length === 0 ? (
              <div className="px-3 py-10 text-center text-sm text-muted-foreground">
                <p>No matches.</p>
                {partial.length > 0 && (
                  <p className="mt-2 text-xs">
                    Note that{" "}
                    {partial
                      .map((c) => `${c.metric} is available for ${c.available} of ${c.total}`)
                      .join(", ")}{" "}
                    — companies without a figure are excluded, not counted as non-matches.
                  </p>
                )}
              </div>
            ) : (
              <OpportunityTable hits={hits} />
            )}
          </Panel>

          {partial.length > 0 && hits.length > 0 && (
            <p className="px-1 text-[11px] text-muted-foreground">
              Coverage:{" "}
              {partial
                .map((c) => `${c.metric} available for ${c.available} of ${c.total}`)
                .join(" · ")}
              . Companies without a figure were excluded rather than treated as non-matches.
            </p>
          )}
        </>
      )}
    </main>
  );
}
