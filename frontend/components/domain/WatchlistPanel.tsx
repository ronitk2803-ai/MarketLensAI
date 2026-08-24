"use client";

import { Plus, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Delta } from "@/components/terminal/Delta";
import { Panel } from "@/components/terminal/Panel";
import { RangeBar } from "@/components/terminal/RangeBar";
import { Sparkline } from "@/components/terminal/Sparkline";
import type { AssetSearchResult, LiveQuote, WatchlistQuote } from "@/lib/api";
import { price, tradingDate } from "@/lib/format";
import { useLiveQuotes } from "@/lib/use-live-quotes";
import { usePriceFlash } from "@/lib/use-price-flash";
import { cn } from "@/lib/utils";
import { useDeltaDays, useWatchlistSymbols } from "@/lib/watchlist-storage";

/**
 * User-curated multi-symbol quote panel for the home dashboard.
 *
 * Two different clocks meet in each row, and the UI has to keep them
 * distinguishable. The derived columns (multi-window deltas, 52-week and
 * all-time ranges, sparkline) come from stored EOD history and only change
 * once a day. "Last" is live during market hours, polled from a separate
 * lightweight endpoint — so it is labelled LIVE and shown against the
 * previous close, and falls back to the stored close (labelled with its own
 * date) whenever the session is shut or the provider is unreachable.
 *
 * No account system exists yet (Build_plan.md §Q: watchlist is P1), so the
 * symbol list and delta-window choice live in this browser only — see
 * lib/watchlist-storage.ts.
 */
export function WatchlistPanel() {
  const [symbols, setSymbols] = useWatchlistSymbols();
  const [deltaDays, setDeltaDays] = useDeltaDays();
  const live = useLiveQuotes(symbols);
  const [quotes, setQuotes] = useState<Record<string, WatchlistQuote>>({});
  const [unknown, setUnknown] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Nothing to fetch, and whatever's left in `quotes`/`unknown` from a
    // previous non-empty state is simply not rendered while the list is
    // empty (see the symbols.length === 0 branch below) — no need to clear
    // it, and clearing it here would be a synchronous setState in an effect
    // body for no visible benefit.
    if (symbols.length === 0) return;
    let cancelled = false;
    // Legitimate loading flag for a cancelable fetch below (guarded by
    // `cancelled`) — not the "derive state from a prop" case the rule is
    // meant to catch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const params = new URLSearchParams({
      symbols: symbols.join(","),
      deltas: deltaDays.join(","),
    });
    fetch(`/api/watchlist?${params.toString()}`)
      .then((res) => res.json())
      .then((data: { quotes: WatchlistQuote[]; unknown_symbols: string[] }) => {
        if (cancelled) return;
        setQuotes(Object.fromEntries(data.quotes.map((q) => [q.symbol, q])));
        setUnknown(data.unknown_symbols);
      })
      .catch(() => {
        if (!cancelled) setUnknown(symbols);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbols, deltaDays]);

  function addSymbol(symbol: string) {
    const upper = symbol.trim().toUpperCase();
    if (!upper || symbols.includes(upper)) return;
    setSymbols([...symbols, upper]);
  }

  function removeSymbol(symbol: string) {
    setSymbols(symbols.filter((s) => s !== symbol));
  }

  // Three genuinely different states, and the footnote has to tell them
  // apart: a closing price from the provider is real and current-as-of-close
  // (not the same claim as "the feed is down"), and neither is the same as a
  // live tick.
  const hasQuotes = Object.keys(live.bySymbol).length > 0;
  const quoteSourceNote = live.isLive
    ? "Live price from Yahoo Finance, refreshed every 15s, shown against the previous close."
    : hasQuotes
      ? "Market closed — showing today's closing price against the prior close."
      : "Live prices unavailable — showing the last stored close, labelled with its own date.";

  return (
    <Panel
      title={
        <div className="flex items-center gap-2">
          <h2 className="label-caps">Watchlist</h2>
          {live.isLive && (
            <span className="flex items-center gap-1 text-[10px] text-up" title="Market is open — prices update every 15s">
              <span className="size-1.5 animate-pulse rounded-full bg-up" />
              LIVE
            </span>
          )}
        </div>
      }
      actions={
        <div className="flex items-center gap-3">
          <DeltaEditor days={deltaDays} onChange={setDeltaDays} />
          <AddSymbolInput onAdd={addSymbol} existing={symbols} />
        </div>
      }
      bodyClassName="p-0"
      footnote={`${quoteSourceNote} Δ windows and ranges are end-of-day and corporate-action adjusted; 'all-time' means since this deployment started tracking each stock, not its full listed history.`}
      fullscreenable
    >
      {symbols.length === 0 ? (
        <p className="px-3 py-8 text-center text-xs text-muted-foreground">
          Add a symbol above to start your watchlist.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border text-left text-[11px] text-muted-foreground">
                <th className="px-3 py-1.5 font-normal">Symbol</th>
                <th className="px-2 py-1.5 font-normal">30d</th>
                <th className="px-2 py-1.5 text-right font-normal">Last</th>
                {deltaDays.map((d, i) => (
                  <th key={`${d}-${i}`} className="px-2 py-1.5 text-right font-normal">
                    Δ{d}d
                  </th>
                ))}
                <th className="px-2 py-1.5 font-normal">52w range</th>
                <th className="px-2 py-1.5 font-normal">All-time range</th>
                <th className="w-8 px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {symbols.map((symbol) => (
                <WatchlistRow
                  key={symbol}
                  symbol={symbol}
                  quote={quotes[symbol]}
                  liveQuote={live.bySymbol[symbol]}
                  isUnknown={unknown.includes(symbol)}
                  deltaDays={deltaDays}
                  onRemove={() => removeSymbol(symbol)}
                />
              ))}
            </tbody>
          </table>
          {loading && (
            <p className="border-t border-border px-3 py-1 text-[11px] text-muted-foreground">
              Refreshing…
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}

function WatchlistRow({
  symbol,
  quote,
  liveQuote,
  isUnknown,
  deltaDays,
  onRemove,
}: {
  symbol: string;
  quote: WatchlistQuote | undefined;
  liveQuote: LiveQuote | undefined;
  isUnknown: boolean;
  deltaDays: [number, number, number];
  onRemove: () => void;
}) {
  const flash = usePriceFlash(liveQuote?.ltp);

  if (isUnknown) {
    return (
      <tr className="border-b border-border/60 last:border-0">
        <td className="px-3 py-2">
          <span className="num font-medium text-muted-foreground">{symbol}</span>
          <span className="ml-2 text-[11px] text-down">not found on NSE</span>
        </td>
        <td colSpan={4 + deltaDays.length} />
        <td className="px-2 py-2 text-right">
          <RemoveButton onRemove={onRemove} symbol={symbol} />
        </td>
      </tr>
    );
  }

  if (!quote) {
    return (
      <tr className="border-b border-border/60 last:border-0">
        <td className="px-3 py-2">
          <span className="num font-medium">{symbol}</span>
        </td>
        <td colSpan={4 + deltaDays.length} className="px-2 py-2 text-muted-foreground">
          Loading…
        </td>
        <td className="px-2 py-2 text-right">
          <RemoveButton onRemove={onRemove} symbol={symbol} />
        </td>
      </tr>
    );
  }

  return (
    <tr className="border-b border-border/60 last:border-0 hover:bg-accent/40">
      <td className="min-w-0 px-3 py-2">
        <Link href={`/company/${quote.symbol}`} className="block">
          <span className="num block font-medium whitespace-nowrap">{quote.symbol}</span>
          <span className="block max-w-[160px] truncate text-[11px] text-muted-foreground">
            {quote.name}
          </span>
        </Link>
      </td>
      <td className="px-2 py-2">
        <Sparkline values={quote.spark} />
      </td>
      {/* Live LTP when the session is trading, otherwise the stored close.
          The subline always says which one you're looking at — an
          unlabelled price is the one thing this panel must never show,
          since a stale number and a live number look identical. */}
      <td
        className={cn(
          "rounded-sm px-2 py-2 text-right transition-colors",
          flash === "up" && "flash-up",
          flash === "down" && "flash-down",
        )}
      >
        {liveQuote ? (
          <>
            <span className="num block whitespace-nowrap">{price(liveQuote.ltp)}</span>
            <span className="block text-[10px] whitespace-nowrap">
              {liveQuote.change_pct === null ? (
                <span className="text-muted-foreground">live</span>
              ) : (
                <Delta value={liveQuote.change_pct} digits={2} showIcon={false} />
              )}
            </span>
          </>
        ) : (
          <>
            <span className="num block whitespace-nowrap">{price(quote.close)}</span>
            <span className="block text-[10px] text-muted-foreground">
              {tradingDate(quote.as_of)}
            </span>
          </>
        )}
      </td>
      {deltaDays.map((d, i) => (
        <td key={`${d}-${i}`} className="px-2 py-2 text-right">
          {quote.deltas[String(d)] === undefined ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <Delta value={quote.deltas[String(d)]} digits={1} showIcon={false} />
          )}
        </td>
      ))}
      <td className="px-2 py-2">
        {quote.week_52 ? (
          <RangeBar
            high={quote.week_52.high}
            low={quote.week_52.low}
            position={quote.week_52.position}
          />
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="px-2 py-2" title={quote.all_time ? `Since ${tradingDate(quote.all_time.since)}` : undefined}>
        {quote.all_time ? (
          <RangeBar
            high={quote.all_time.high}
            low={quote.all_time.low}
            position={quote.all_time.position}
          />
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="px-2 py-2 text-right">
        <RemoveButton onRemove={onRemove} symbol={symbol} />
      </td>
    </tr>
  );
}

function RemoveButton({ onRemove, symbol }: { onRemove: () => void; symbol: string }) {
  return (
    <button
      type="button"
      onClick={onRemove}
      aria-label={`Remove ${symbol} from watchlist`}
      className="grid size-6 shrink-0 place-items-center rounded-sm text-muted-foreground hover:bg-accent hover:text-down"
    >
      <X className="size-3.5" />
    </button>
  );
}

function DeltaEditor({
  days,
  onChange,
}: {
  days: [number, number, number];
  onChange: (days: [number, number, number]) => void;
}) {
  const [drafts, setDrafts] = useState<[string, string, string]>([
    String(days[0]),
    String(days[1]),
    String(days[2]),
  ]);
  // Tracks the `days` this component last rendered `drafts` for, so a
  // change from outside (the SSR→client snapshot swap useSyncExternalStore
  // does right after mount) can be picked up without an effect — the
  // React-sanctioned way to reset derived state when a prop changes:
  // compare during render and adjust before this render commits, instead
  // of committing stale drafts and correcting them a tick later in
  // useEffect.
  const [prevDaysKey, setPrevDaysKey] = useState(days.join(","));
  const daysKey = days.join(",");
  if (daysKey !== prevDaysKey) {
    setPrevDaysKey(daysKey);
    setDrafts([String(days[0]), String(days[1]), String(days[2])]);
  }

  function commit(index: 0 | 1 | 2, raw: string) {
    const n = Number.parseInt(raw, 10);
    if (!Number.isInteger(n) || n <= 0) {
      setDrafts((prev) => {
        const next = [...prev] as [string, string, string];
        next[index] = String(days[index]);
        return next;
      });
      return;
    }
    const next = [...days] as [number, number, number];
    next[index] = n;
    onChange(next);
  }

  return (
    <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
      <span className="label-caps">Δ</span>
      {drafts.map((value, i) => (
        <input
          key={i}
          value={value}
          onChange={(e) => {
            const v = e.target.value.replace(/[^0-9]/g, "");
            setDrafts((prev) => {
              const next = [...prev] as [string, string, string];
              next[i] = v;
              return next;
            });
          }}
          onBlur={() => commit(i as 0 | 1 | 2, drafts[i])}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          inputMode="numeric"
          aria-label={`Delta window ${i + 1} in trading days`}
          className="num h-6 w-9 rounded-sm border border-input bg-surface text-center text-[11px] outline-none focus:border-ring focus:ring-1 focus:ring-ring"
        />
      ))}
      <span className="label-caps">d</span>
    </div>
  );
}

function AddSymbolInput({
  onAdd,
  existing,
}: {
  onAdd: (symbol: string) => void;
  existing: string[];
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AssetSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const trimmed = query.trim();
    const timeout = setTimeout(() => {
      if (trimmed.length < 1) {
        setResults([]);
        return;
      }
      fetch(`/api/search?q=${encodeURIComponent(trimmed)}`)
        .then((res) => res.json())
        .then((data: AssetSearchResult[]) => {
          setResults(data.filter((r) => !existing.includes(r.symbol)));
          setOpen(true);
        })
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function pick(symbol: string) {
    onAdd(symbol);
    setQuery("");
    setResults([]);
    setOpen(false);
  }

  // Enter must not depend on the 200ms debounce having already resolved —
  // typing a full symbol and hitting Enter immediately is the fast path,
  // and it landed on `results` from the *previous* keystroke otherwise
  // (verified live: typing "TCS" + Enter silently added nothing, because
  // the debounced fetch for "TCS" hadn't come back yet). Enter now runs its
  // own immediate, undebounced lookup instead of trusting stale state.
  async function pickFirstMatch() {
    const trimmed = query.trim();
    if (!trimmed) return;
    if (results.length > 0) {
      pick(results[0].symbol);
      return;
    }
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(trimmed)}`);
      const data: AssetSearchResult[] = await res.json();
      const match = data.find((r) => !existing.includes(r.symbol));
      if (match) pick(match.symbol);
    } catch {
      // No match found — leave the input as-is rather than erroring.
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <Plus
          className="pointer-events-none absolute top-1/2 left-1.5 size-3 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void pickFirstMatch();
            }
            if (e.key === "Escape") setOpen(false);
          }}
          placeholder="Add symbol"
          aria-label="Add a symbol to your watchlist"
          className="h-6 w-32 rounded-sm border border-input bg-surface pl-5 text-[11px] outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
        />
      </div>
      {open && results.length > 0 && (
        <ul className="absolute right-0 z-40 mt-1 w-56 overflow-hidden rounded-sm border border-border bg-popover shadow-xl">
          {results.slice(0, 8).map((result) => (
            <li key={`${result.exchange}:${result.symbol}`}>
              <button
                type="button"
                onClick={() => pick(result.symbol)}
                className={cn(
                  "flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left hover:bg-accent",
                )}
              >
                <span className="num w-20 shrink-0 text-[12px] font-medium">{result.symbol}</span>
                <span className="truncate text-[11px] text-muted-foreground">{result.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
