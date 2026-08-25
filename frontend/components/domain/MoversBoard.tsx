"use client";

import Link from "next/link";

import { Delta } from "@/components/terminal/Delta";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { Sparkline } from "@/components/terminal/Sparkline";
import { compact, num, price, scoreTone } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Meta, OpportunityHit } from "@/lib/api";

/**
 * Compact leaderboard of one screen's top hits — the home dashboard's unit.
 * Screens carry different metric sets (the decline screens have
 * close/change_pct; unusual_volume has volume/relative_volume and no price
 * at all), so each row picks the two most meaningful figures it actually
 * has rather than rendering dashes for columns that were never going to
 * exist.
 */
function primaryFigures(hit: OpportunityHit) {
  const m = hit.metrics;
  if (typeof m.close === "number") {
    return {
      left: price(m.close),
      right:
        typeof m.change_pct === "number" ? (
          <Delta value={m.change_pct} digits={1} />
        ) : typeof m.pct_below === "number" ? (
          <Delta value={-m.pct_below} digits={1} />
        ) : null,
    };
  }
  if (typeof m.relative_volume === "number") {
    return {
      left: compact(m.volume),
      right: <span className="num text-foreground">{num(m.relative_volume, 1)}x</span>,
    };
  }
  return { left: "", right: null };
}
export function MoversBoard({
  title,
  href,
  hits,
  meta,
  limit = 6,
}: {
  title: string;
  href: string;
  hits: OpportunityHit[];
  meta: Meta | null;
  limit?: number;
}) {
  return (
    <Panel
      title={title}
      actions={
        <div className="flex items-center gap-3">
          {meta && (
            <ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />
          )}
          <Link href={href} className="text-[11px] text-primary hover:underline">
            View all
          </Link>
        </div>
      }
      bodyClassName="p-0"
      fullscreenable
    >
      {/* Expanded, the panel has real vertical room, so cap at a much
          higher count rather than the 6 that fits a homepage tile — the
          fullscreen button is pointless if it doesn't also surface more of
          what the screen actually found. */}
      {(expanded) => {
        const rows = hits.slice(0, expanded ? 40 : limit);
        return (
      <>
      {/* Flex rows rather than a table: `table-auto` sizes columns to their
          content, so the company name refuses to truncate and pushes the
          figures out of the panel instead. A flex row with `min-w-0` on the
          label lets the numbers keep their intrinsic width and the name
          absorb — and truncate into — whatever is left. */}
      {rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-muted-foreground">
          No matches right now.
        </p>
      ) : (
        <ul className={expanded ? "text-sm" : "text-[13px]"}>
          {rows.map((hit) => {
            const figures = primaryFigures(hit);
            return (
              <li key={hit.symbol} className="border-b border-border/60 last:border-0">
                <Link
                  href={`/company/${hit.symbol}`}
                  className={cn(
                    "flex items-center gap-2 px-3 hover:bg-accent/40",
                    expanded ? "py-2.5" : "py-1.5",
                  )}
                >
                  {/* The ticker is the row's identifier, so it must never be
                      the thing that gives way — at the 4-up xl layout the
                      panel is only ~300px and a shared truncate turned
                      GMRAIRPORT into "GMRAIR…". The symbol now sets the
                      column's floor and the company name absorbs instead. */}
                  <span className="min-w-0 flex-1">
                    <span className="num block font-medium whitespace-nowrap">{hit.symbol}</span>
                    <span
                      className={cn(
                        "block text-muted-foreground",
                        expanded ? "text-xs" : "truncate text-[11px]",
                      )}
                    >
                      {hit.name}
                    </span>
                  </span>
                  <Sparkline
                    values={hit.spark}
                    width={expanded ? 72 : 40}
                    className="hidden sm:block"
                  />
                  <span className="num shrink-0 text-right whitespace-nowrap text-muted-foreground">
                    {figures.left}
                  </span>
                  <span className="shrink-0 text-right whitespace-nowrap">{figures.right}</span>
                  <span
                    className={`num w-5 shrink-0 text-right text-[11px] ${scoreTone(hit.opportunity_score)}`}
                    title="Opportunity Score (0-100, research attractiveness — not a return prediction)"
                  >
                    {typeof hit.opportunity_score === "number"
                      ? hit.opportunity_score.toFixed(0)
                      : "—"}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      </>
        );
      }}
    </Panel>
  );
}
