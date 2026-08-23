import Link from "next/link";
import { notFound } from "next/navigation";

import { PriceChart } from "@/components/charts/PriceChart";
import { FundamentalsPanel } from "@/components/domain/FundamentalsPanel";
import { NewsPanel } from "@/components/domain/NewsPanel";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { ScorePanel } from "@/components/domain/ScorePanel";
import { TechnicalPanel } from "@/components/domain/TechnicalPanel";
import { Delta } from "@/components/terminal/Delta";
import { Panel } from "@/components/terminal/Panel";
import { cn } from "@/lib/utils";
import { compact, price, tradingDate } from "@/lib/format";
import {
  ApiError,
  getCompany,
  getCorporateActions,
  getFundamentals,
  getNews,
  getPrices,
  getScore,
  getTechnicals,
  type PriceRange,
} from "@/lib/api";

const RANGES: PriceRange[] = ["1m", "3m", "6m", "1y", "5y"];

function isPriceRange(value: string | undefined): value is PriceRange {
  return (RANGES as string[]).includes(value ?? "");
}

export default async function CompanyPage({
  params,
  searchParams,
}: {
  params: Promise<{ symbol: string }>;
  searchParams: Promise<{ range?: string }>;
}) {
  const { symbol } = await params;
  const { range: rawRange } = await searchParams;
  const range = isPriceRange(rawRange) ? rawRange : "1y";

  let company: Awaited<ReturnType<typeof getCompany>>;
  try {
    company = await getCompany(symbol);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  const [prices, technicals, corporateActions, fundamentals, news, score] = await Promise.all([
    getPrices(symbol, range),
    getTechnicals(symbol, range),
    getCorporateActions(symbol),
    getFundamentals(symbol),
    getNews(symbol),
    getScore(symbol),
  ]);

  const header = company.data;
  const changePct = header.latest_price.change_pct;
  const bars = prices.data;
  const latestBar = bars.length > 0 ? bars[bars.length - 1] : null;

  // Session stats come from the latest bar rather than the header, so they
  // stay consistent with the candle the chart is actually showing.
  const sessionStats = [
    { label: "Open", value: price(latestBar?.open) },
    { label: "High", value: price(latestBar?.high) },
    { label: "Low", value: price(latestBar?.low) },
    { label: "Volume", value: compact(latestBar?.volume) },
  ];

  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 px-4 py-4">
      {/* Quote header — the anchor for everything below it. */}
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3 rounded-md border border-border bg-surface px-4 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <h1 className="num text-xl font-semibold tracking-tight">{header.symbol}</h1>
            <span className="rounded-sm border border-border px-1.5 py-px text-[10px] text-muted-foreground">
              {header.exchange}
            </span>
            <span className="truncate text-sm text-muted-foreground">{header.name}</span>
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {/* NSE's constituent CSV classifies each company at one level,
                stored as industry. Keying the whole line off `sector` meant a
                company with a known industry still read "Sector unavailable"
                next to it. Show whichever levels we actually have. */}
            {[header.sector, header.industry].filter(Boolean).join(" · ") ||
              "Classification unavailable"}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div className="hidden items-center gap-x-5 sm:flex">
            {sessionStats.map((stat) => (
              <div key={stat.label} className="text-right">
                <div className="label-caps">{stat.label}</div>
                <div className="num text-[13px]">{stat.value}</div>
              </div>
            ))}
          </div>

          <div className="text-right">
            <div className="num text-2xl leading-tight font-semibold">
              {price(header.latest_price.close)}
            </div>
            <div className="flex items-center justify-end gap-2">
              <Delta value={changePct} className="text-[13px]" />
              <span className="text-[10px] text-muted-foreground">
                {tradingDate(header.latest_price.date)}
              </span>
            </div>
          </div>

          <ProvenanceBadge
            source={company.meta.source}
            asOf={company.meta.as_of}
            confidence={company.meta.confidence}
          />
        </div>
      </div>

      {/* Chart gets the width; score rides alongside it on wide screens. */}
      <div className="grid gap-3 xl:grid-cols-[1fr_320px]">
        <Panel
          title="Price"
          actions={
            <div className="flex gap-0.5">
              {RANGES.map((r) => (
                <Link
                  key={r}
                  href={`/company/${symbol}?range=${r}`}
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
          }
          bodyClassName="p-2"
        >
          <PriceChart
            bars={bars}
            technicals={technicals.data.series}
            corporateActions={corporateActions.data}
          />
        </Panel>

        <ScorePanel score={score.data} meta={score.meta} />
      </div>

      <TechnicalPanel snapshot={technicals.data.latest} meta={technicals.meta} />

      <div className="grid gap-3 xl:grid-cols-[1fr_420px]">
        <FundamentalsPanel fundamentals={fundamentals.data} meta={fundamentals.meta} />
        <NewsPanel articles={news.data} meta={news.meta} />
      </div>
    </main>
  );
}
