"use client";

import { Delta } from "@/components/terminal/Delta";
import { price, tradingDate } from "@/lib/format";
import { useLiveQuotes } from "@/lib/use-live-quotes";

/**
 * The company header's price, live while the session is trading.
 *
 * Client island inside an otherwise server-rendered page: the stored close
 * arrives as props and renders immediately (so there is no blank flash and
 * the page still works with JS disabled), and the live tick replaces it
 * once polling starts.
 *
 * Deliberately stricter than the watchlist row, which shows the provider's
 * quote whenever it has one. This price sits directly above session OHLC
 * and a chart that both come from stored bars, so outside live trading it
 * falls back to the stored close rather than showing the provider's
 * closing price — those are the same number on a normal day, but on any
 * day the daily ingestion hasn't run yet they are a day apart, and a
 * header disagreeing with the candle beneath it is worse than a header
 * that is simply end-of-day.
 */
export function LivePrice({
  symbol,
  storedClose,
  storedChangePct,
  storedDate,
}: {
  symbol: string;
  storedClose: number | null;
  storedChangePct: number | null;
  storedDate: string | null;
}) {
  const live = useLiveQuotes([symbol]);
  const quote = live.isLive ? live.bySymbol[symbol] : undefined;

  return (
    <div className="text-right">
      <div className="num text-2xl leading-tight font-semibold">
        {price(quote ? quote.ltp : storedClose)}
      </div>
      <div className="flex items-center justify-end gap-2">
        <Delta
          value={quote ? quote.change_pct : storedChangePct}
          className="text-[13px]"
        />
        {quote ? (
          <span
            className="flex items-center gap-1 text-[10px] text-up"
            title="Market is open — price updates every 15s"
          >
            <span className="size-1.5 animate-pulse rounded-full bg-up" />
            LIVE
          </span>
        ) : (
          <span className="text-[10px] text-muted-foreground">{tradingDate(storedDate)}</span>
        )}
      </div>
    </div>
  );
}
