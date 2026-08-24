"use client";

import { useCallback, useSyncExternalStore } from "react";

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

const EMPTY: LiveQuoteState = { bySymbol: {}, isLive: false };

/**
 * One polling loop per distinct symbol list, shared by every component that
 * asks for it.
 *
 * The company page mounts two consumers of the same symbol — the header
 * price and the chart's forming candle — and a naive per-hook loop would
 * poll twice for identical data. The server-side cache would absorb the
 * duplicate, but the honest fix is not to make the request twice. Keeping
 * the loop in a module-level registry rather than a React context also
 * avoids threading a provider through a server-rendered page just to share
 * a timer.
 *
 * The loop starts with the first subscriber and stops with the last, so a
 * page with no live consumers polls nothing.
 */
interface Entry {
  state: LiveQuoteState;
  listeners: Set<() => void>;
  timer?: ReturnType<typeof setTimeout>;
  open: boolean;
}

const registry = new Map<string, Entry>();

function emit(entry: Entry, state: LiveQuoteState): void {
  entry.state = state;
  entry.listeners.forEach((l) => l());
}

async function poll(key: string): Promise<void> {
  const entry = registry.get(key);
  if (!entry) return;

  // After every await, the entry this call belongs to may have been torn
  // down and a fresh one put in its place (a remount, or a symbol list that
  // changed and changed back). Comparing identity — not just presence —
  // stops a stale in-flight poll from resolving into an entry that no
  // longer owns it, which would leave the new entry with no data and no
  // scheduled retry.
  const stillOurs = () => registry.get(key) === entry;

  try {
    const res = await fetch(`/api/quotes?symbols=${encodeURIComponent(key)}`, {
      cache: "no-store",
    });
    const data: { quotes: LiveQuote[]; live: boolean } = await res.json();
    if (!stillOurs()) return;

    entry.open = data.live && data.quotes.some((q) => q.market_state === "REGULAR");
    emit(entry, {
      bySymbol: Object.fromEntries(data.quotes.map((q) => [q.symbol, q])),
      isLive: entry.open,
    });
  } catch {
    // Drop the quotes rather than keeping the last good ones. Holding them
    // shows an intraday price with a day-change beside it while the UI
    // says the feed is unavailable — a stale number that reads exactly
    // like a current one, which is the single thing this must not do.
    // Falling back to stored data costs one poll interval of precision and
    // stays honest.
    if (!stillOurs()) return;
    entry.open = false;
    emit(entry, EMPTY);
  } finally {
    if (stillOurs()) {
      entry.timer = setTimeout(() => void poll(key), entry.open ? LIVE_POLL_MS : CLOSED_POLL_MS);
    }
  }
}

function subscribe(key: string, listener: () => void): () => void {
  let entry = registry.get(key);
  if (!entry) {
    entry = { state: EMPTY, listeners: new Set(), open: false };
    registry.set(key, entry);
    void poll(key);
  }
  entry.listeners.add(listener);

  return () => {
    const current = registry.get(key);
    if (!current) return;
    current.listeners.delete(listener);
    if (current.listeners.size === 0) {
      if (current.timer) clearTimeout(current.timer);
      registry.delete(key);
    }
  };
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
  // Symbols arrive as a new array identity on every parent render; the
  // joined string is what actually identifies the subscription.
  const key = symbols.join(",");

  // Stable per key. Without useCallback this identity changes on every
  // render, so React tears the subscription down and rebuilds it each time
  // — and since the last unsubscribe deletes the registry entry and clears
  // its timer, the loop would be destroyed before any poll could land.
  const subscribeToKey = useCallback(
    (listener: () => void) => (key ? subscribe(key, listener) : () => {}),
    [key],
  );

  return useSyncExternalStore(
    subscribeToKey,
    () => (key ? (registry.get(key)?.state ?? EMPTY) : EMPTY),
    // The server has no live feed and must render the stored values, which
    // is also what the client shows until the first poll lands.
    () => EMPTY,
  );
}
