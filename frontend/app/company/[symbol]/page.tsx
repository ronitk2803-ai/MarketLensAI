import { notFound } from "next/navigation";

import { AiSummaryPanel } from "@/components/domain/AiSummaryPanel";
import { FundamentalsPanel } from "@/components/domain/FundamentalsPanel";
import { LivePrice } from "@/components/domain/LivePrice";
import { NewsPanel } from "@/components/domain/NewsPanel";
import { PriceChartPanel } from "@/components/domain/PriceChartPanel";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { ScorePanel } from "@/components/domain/ScorePanel";
import { TechnicalPanel } from "@/components/domain/TechnicalPanel";
import { compact, price, tradingDate } from "@/lib/format";
import { getSignedInUser } from "@/lib/session";
import {
  ApiError,
  getAiSummary,
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

  // Generating a summary spends an LLM call, so the backend gates it
  // behind sign-in; the page itself stays public.
  const [prices, technicals, corporateActions, fundamentals, news, score, aiSummary, user] =
    await Promise.all([
      getPrices(symbol, range),
      getTechnicals(symbol, range),
      getCorporateActions(symbol),
      getFundamentals(symbol),
      getNews(symbol),
      getScore(symbol),
      getAiSummary(symbol),
      getSignedInUser(),
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
          {/* Dated explicitly: once the price beside it goes live, this is
              the only thing saying which session the OHLC belongs to — and
              on any day before the 20:00 IST ingestion runs, that session
              is not today. */}
          <div
            className="hidden items-center gap-x-5 sm:flex"
            title={`Session of ${tradingDate(latestBar?.date ?? null)}`}
          >
            {sessionStats.map((stat) => (
              <div key={stat.label} className="text-right">
                <div className="label-caps">{stat.label}</div>
                <div className="num text-[13px]">{stat.value}</div>
              </div>
            ))}
            <div className="text-right">
              <div className="label-caps">Session</div>
              <div className="num text-[13px] text-muted-foreground">
                {tradingDate(latestBar?.date ?? null)}
              </div>
            </div>
          </div>

          <LivePrice
            symbol={header.symbol}
            storedClose={header.latest_price.close}
            storedChangePct={changePct}
            storedDate={header.latest_price.date}
          />

          <ProvenanceBadge
            source={company.meta.source}
            asOf={company.meta.as_of}
            confidence={company.meta.confidence}
          />
        </div>
      </div>

      {/* Chart gets the width; score rides alongside it on wide screens. */}
      <div className="grid gap-3 xl:grid-cols-[1fr_320px]">
        <PriceChartPanel
          symbol={header.symbol}
          range={range}
          bars={bars}
          technicals={technicals.data.series}
          corporateActions={corporateActions.data}
          meta={prices.meta}
        />

        <ScorePanel score={score.data} meta={score.meta} />
      </div>

      <TechnicalPanel snapshot={technicals.data.latest} meta={technicals.meta} />

      <AiSummaryPanel
        symbol={header.symbol}
        initial={aiSummary.data}
        meta={aiSummary.meta}
        canGenerate={user !== null}
      />

      <div className="grid gap-3 xl:grid-cols-[1fr_420px]">
        <FundamentalsPanel
          fundamentals={fundamentals.data}
          meta={fundamentals.meta}
          industry={header.industry}
        />
        <NewsPanel articles={news.data} meta={news.meta} />
      </div>
    </main>
  );
}
