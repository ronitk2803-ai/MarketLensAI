"use client";

import { useSyncExternalStore } from "react";

/**
 * Client-only persistence for the watchlist widget's delta-window choice
 * (which three trading-session windows show as columns) — a display
 * preference, not data, so it stays in the browser even though the
 * watchlist's actual membership moved to the account-backed
 * GET/POST/DELETE /api/watchlist* endpoints (P1: see WatchlistPanel.tsx).
 *
 * Before accounts existed, this module also held *which symbols* were on
 * the list (the same reasoning that still applies to the delta window
 * today — Build_plan.md §Q: a real watchlist needs accounts). That's gone
 * now that there's somewhere real to put it; readLocalWatchlistSymbols/
 * clearLocalWatchlistSymbols below are what's left of it, kept only long
 * enough to import whatever an already-existing anonymous list had on it
 * into a freshly-created account (see WatchlistPanel.tsx's first-load
 * effect) — a one-shot read, not a live-updating hook, since nothing
 * writes new symbols there anymore.
 */

const SYMBOLS_KEY = "mlai-watchlist-symbols";
const DELTAS_KEY = "mlai-watchlist-deltas";

export const DEFAULT_DELTA_DAYS: [number, number, number] = [7, 14, 30];

function isDeltaTriple(v: unknown): v is [number, number, number] {
  return Array.isArray(v) && v.length === 3 && v.every((n) => Number.isInteger(n) && n > 0);
}

/** Minimal localStorage-backed store: cached snapshot + manual pub/sub,
 * since same-tab writes don't fire the browser's `storage` event. */
function createStore<T>(key: string, fallback: T, isValid: (v: unknown) => v is T) {
  let cache = fallback;
  let cached = false;
  const listeners = new Set<() => void>();

  function read(): T {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      return isValid(parsed) ? parsed : fallback;
    } catch {
      return fallback;
    }
  }

  return {
    getSnapshot(): T {
      if (!cached) {
        cache = read();
        cached = true;
      }
      return cache;
    },
    getServerSnapshot: () => fallback,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    set(value: T) {
      cache = value;
      cached = true;
      try {
        localStorage.setItem(key, JSON.stringify(value));
      } catch {
        // Private-mode storage denial shouldn't break the widget itself —
        // the in-memory cache still lets the session work, it just won't
        // persist across a reload.
      }
      listeners.forEach((l) => l());
    },
  };
}

const deltaStore = createStore<[number, number, number]>(
  DELTAS_KEY,
  DEFAULT_DELTA_DAYS,
  isDeltaTriple,
);

export function useDeltaDays(): [
  [number, number, number],
  (next: [number, number, number]) => void,
] {
  const days = useSyncExternalStore(
    deltaStore.subscribe,
    deltaStore.getSnapshot,
    deltaStore.getServerSnapshot,
  );
  return [days, deltaStore.set];
}

/** One-shot, non-reactive — call once (e.g. on first authenticated load),
 * not from render. Returns [] on anything unexpected (private-mode
 * storage denial, corrupted JSON) rather than throwing, same tolerance
 * the old symbol store had. */
export function readLocalWatchlistSymbols(): string[] {
  try {
    const raw = localStorage.getItem(SYMBOLS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) && parsed.every((s) => typeof s === "string") ? parsed : [];
  } catch {
    return [];
  }
}

export function clearLocalWatchlistSymbols(): void {
  try {
    localStorage.removeItem(SYMBOLS_KEY);
  } catch {
    // Nothing to clean up if storage was never writable in the first place.
  }
}
