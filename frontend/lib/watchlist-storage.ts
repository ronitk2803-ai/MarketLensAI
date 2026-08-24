"use client";

import { useSyncExternalStore } from "react";

/**
 * Client-only persistence for the watchlist widget: which symbols and which
 * three delta windows the user has chosen. Build_plan.md §Q lists a real
 * watchlist as out of MVP scope specifically because it needs accounts
 * (P1, not built) — this gets the feature without that prerequisite by
 * keeping the list in the browser rather than a user_id-scoped table. It
 * will not follow the user across devices; that's the tradeoff for not
 * needing to log in.
 *
 * localStorage as a `useSyncExternalStore` source, same idiom as
 * useIsLightTheme in lib/use-theme.ts: the server can't read localStorage,
 * so getServerSnapshot returns the empty default and React reconciles to
 * the real client value after mount. That sidesteps both the hydration
 * mismatch AND the "setState synchronously in a mount effect" pattern the
 * lint rule (react-hooks/set-state-in-effect) correctly objects to — there
 * is no effect here at all, the store is read during render.
 */

const SYMBOLS_KEY = "mlai-watchlist-symbols";
const DELTAS_KEY = "mlai-watchlist-deltas";

export const DEFAULT_DELTA_DAYS: [number, number, number] = [7, 14, 30];
const EMPTY_SYMBOLS: string[] = [];

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === "string");
}

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

const symbolsStore = createStore<string[]>(SYMBOLS_KEY, EMPTY_SYMBOLS, isStringArray);
const deltaStore = createStore<[number, number, number]>(
  DELTAS_KEY,
  DEFAULT_DELTA_DAYS,
  isDeltaTriple,
);

export function useWatchlistSymbols(): [string[], (next: string[]) => void] {
  const symbols = useSyncExternalStore(
    symbolsStore.subscribe,
    symbolsStore.getSnapshot,
    symbolsStore.getServerSnapshot,
  );
  return [symbols, symbolsStore.set];
}

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
