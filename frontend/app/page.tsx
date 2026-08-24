import Link from "next/link";

import { MoversBoard } from "@/components/domain/MoversBoard";
import { WatchlistPanel } from "@/components/domain/WatchlistPanel";
import { Panel } from "@/components/terminal/Panel";
import { getOpportunities } from "@/lib/api";
import { tradingDate } from "@/lib/format";
import type { OpportunityHit } from "@/lib/api";

// Reads live screener output, so it must not be frozen into the build (the
// backend isn't reachable during `next build`) — same reasoning as
// /opportunities.
export const dynamic = "force-dynamic";

const BOARDS = [
  { screen: "down_5d", title: "Sharpest 5-day declines" },
  { screen: "down_30d", title: "Sharpest 30-day declines" },
  { screen: "unusual_volume", title: "Unusual volume" },
  { screen: "below_dma200", title: "Below 200-day average" },
];

async function safeScreen(screen: string): Promise<{ hits: OpportunityHit[]; asOf: string | null }> {
  // One screen failing (or the whole backend being down) should degrade that
  // board to an empty state, not blank the entire dashboard.
  try {
    const result = await getOpportunities(screen);
    return { hits: result.data, asOf: result.meta.as_of };
  } catch {
    return { hits: [], asOf: null };
  }
}

export default async function Home() {
  const boards = await Promise.all(
    BOARDS.map(async (board) => ({ ...board, ...(await safeScreen(board.screen)) })),
  );

  const asOf = boards.find((b) => b.asOf)?.asOf ?? null;
  const totalHits = boards.reduce((sum, b) => sum + b.hits.length, 0);

  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 px-4 py-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Market overview</h1>
          <p className="text-xs text-muted-foreground">
            Where price action is unusual across NSE equities — a starting point for research,
            not a list of recommendations.
          </p>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
          <span>
            <span className="label-caps mr-1.5">Screens</span>
            <span className="num text-foreground">{BOARDS.length}</span>
          </span>
          <span>
            <span className="label-caps mr-1.5">Hits</span>
            <span className="num text-foreground">{totalHits}</span>
          </span>
          <span>
            <span className="label-caps mr-1.5">As of</span>
            <span className="num text-foreground">{tradingDate(asOf)}</span>
          </span>
        </div>
      </div>

      <WatchlistPanel />

      {totalHits === 0 ? (
        <Panel>
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <p className="text-sm font-medium">No screener data yet</p>
            <p className="max-w-md text-xs text-muted-foreground">
              Either no stock currently meets any screen&apos;s threshold, or the universe
              hasn&apos;t been ingested yet. Run the daily ingestion job, then reload.
            </p>
          </div>
        </Panel>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {boards.map((board) => (
            <MoversBoard
              key={board.screen}
              title={board.title}
              href={`/opportunities?screen=${board.screen}`}
              hits={board.hits}
            />
          ))}
        </div>
      )}

      <Panel bodyClassName="px-3 py-2.5">
        <p className="text-xs text-muted-foreground">
          Looking for something specific? Press{" "}
          <kbd className="rounded-sm border border-border px-1 font-mono text-[10px]">/</kbd> to
          search any NSE symbol, or open the{" "}
          <Link href="/opportunities" className="text-primary hover:underline">
            full screener
          </Link>{" "}
          to rank candidates by Opportunity Score.
        </p>
      </Panel>
    </main>
  );
}
