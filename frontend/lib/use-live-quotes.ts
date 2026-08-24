"use client";

import { useEffect, useState } from "react";

import type { LiveQuote } from "@/lib/api";

/** Polling interval while the exchange session is live. */
const LIVE_POLL_MS = 15_000;
/**
 * When the market is closed the LTP cannot move, so polling it is pure
 * waste against an endpoint whose rate limits are unpublished. One slow
 * heartbeat is enough to notice the session reopening.
 */
const CLOSED_POLL_MS = 5 * 60_000;

export interface LiveQuoteState {
  bySymbol: Record<string, LiveQuote>;
  /** True only while the provider reports an actively trading session. */
  isLive: boolean;
}

/**
 * Polls /api/quotes for `symbols`, adapting its cadence to whether the
 * exchange is actually open.
 *
 * Market-open is taken from the provider's own `market_state` rather than a
 * hardcoded 09:15–15:30 IST window, which would be wrong on every NSE
 * holiday and would need maintaining forever.
 */
export function useLiveQuotes(symbols: string[]): LiveQuoteState {
  const [state, setState] = useState<LiveQuoteState>({ bySymbol: {}, isLive: false });

  // Symbols arrive as a new array identity on every parent render; keying
  // the effect off the joined string means it only re-subscribes when the
  // actual list changes, not on every keystroke elsewhere in the panel.
  const key = symbols.join(",");

  useEffect(() => {
    // No symbols: the panel renders its empty state and never reads these,
    // so there is nothing to clear and no reason to touch state here.
    if (!key) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // The loop's own liveness, kept in the closure rather than read back
    // out of React state — the next delay is a property of the poll that
    // just finished, not of what has been rendered since.
    let open = false;

    async function poll() {
      try {
        const res = await fetch(`/api/quotes?symbols=${encodeURIComponent(key)}`, {
          cache: "no-store",
        });
        const data: { quotes: LiveQuote[]; live: boolean } = await res.json();
        if (cancelled) return;

        open = data.live && data.quotes.some((q) => q.market_state === "REGULAR");
        setState({
          bySymbol: Object.fromEntries(data.quotes.map((q) => [q.symbol, q])),
          isLive: open,
        });
      } catch {
        // Drop the quotes rather than keeping the last good ones. Holding
        // them shows an intraday price with a day-change beside it while
        // the panel's own footnote says the feed is unavailable — a stale
        // number that reads exactly like a current one, which is the single
        // thing this panel must not do. Falling back to the stored close
        // costs one poll interval of precision and stays honest.
        if (cancelled) return;
        open = false;
        setState({ bySymbol: {}, isLive: false });
      } finally {
        if (!cancelled) {
          timer = setTimeout(poll, open ? LIVE_POLL_MS : CLOSED_POLL_MS);
        }
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [key]);

  // With no symbols there is nothing live, whatever a previous list left
  // behind — derived at render rather than written back into state.
  return key ? state : { bySymbol: {}, isLive: false };
}
