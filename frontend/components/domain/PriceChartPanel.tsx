"use client";

import Link from "next/link";

import { PriceChart } from "@/components/charts/PriceChart";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import type { CorporateAction, Meta, PriceBar, TechnicalSeries } from "@/lib/api";
import { cn } from "@/lib/utils";

const RANGES = ["1m", "3m", "6m", "1y", "5y"] as const;

/**
 * Client wrapper around Panel + PriceChart, split out of the (server)
 * company page specifically so `fullscreenable`'s render-prop children can
 * be used here. A plain function isn't serializable across the server/
 * client boundary — passed from the server page straight into Panel (now a
 * client component) it crashed every request with "Functions cannot be
 * passed directly to Client Components." Isolating the render-prop inside
 * an already-client component, fed only serializable data (bars, a plain
 * string range) from its server parent, is the fix.
 */
export function PriceChartPanel({
  symbol,
  range,
  bars,
  technicals,
  corporateActions,
  meta,
}: {
  symbol: string;
  range: string;
  bars: PriceBar[];
  technicals: TechnicalSeries | null;
  corporateActions: CorporateAction[];
  meta: Meta;
}) {
  return (
    <Panel
      title="Price"
      actions={
        <div className="flex items-center gap-2">
          <div className="flex gap-0.5">
            {RANGES.map((r) => (
              <Link
                key={r}
                href={`/company/${encodeURIComponent(symbol)}?range=${r}`}
                className={cn(
                  "num rounded-sm px-2 py-0.5 text-[11px] transition-colors",
                  r === range
                    ? "bg-primary/20 font-medium text-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                {r.toUpperCase()}
              </Link>
            ))}
          </div>
          <ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />
        </div>
      }
      bodyClassName="p-2"
      fullscreenable
    >
      {(expanded) => (
        <PriceChart
          symbol={symbol}
          bars={bars}
          technicals={technicals}
          corporateActions={corporateActions}
          heightClassName={expanded ? "h-full" : "h-[420px]"}
        />
      )}
    </Panel>
  );
}
