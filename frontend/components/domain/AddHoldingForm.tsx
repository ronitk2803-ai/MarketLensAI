"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Panel } from "@/components/terminal/Panel";
import type { AssetSearchResult } from "@/lib/api";

/** Add-one-holding form — same debounced symbol-search idiom as
 * CreateThesisForm, with quantity/avg_cost instead of thesis fields.
 * Posts to app/api/portfolio/route.ts (a Client Component can't reach
 * API_BASE_URL or read the session cookie itself). Re-submitting an
 * already-held symbol updates it in place (app/services/portfolio.py's
 * add_or_update_holding), so this form doubles as "edit my position." */
export function AddHoldingForm() {
  const router = useRouter();

  const [symbolQuery, setSymbolQuery] = useState("");
  const [symbolResults, setSymbolResults] = useState<AssetSearchResult[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<AssetSearchResult | null>(null);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const [quantity, setQuantity] = useState("");
  const [avgCost, setAvgCost] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = symbolQuery.trim();
    const timeout = setTimeout(() => {
      if (trimmed.length < 1) {
        setSymbolResults([]);
        return;
      }
      fetch(`/api/search?q=${encodeURIComponent(trimmed)}`)
        .then((res) => res.json())
        .then((data: AssetSearchResult[]) => {
          setSymbolResults(data);
          setOpen(true);
        })
        .catch(() => setSymbolResults([]));
    }, 200);
    return () => clearTimeout(timeout);
  }, [symbolQuery]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!selectedSymbol) {
      setError("Pick a company from the search results.");
      return;
    }
    const parsedQuantity = Number.parseFloat(quantity);
    const parsedAvgCost = Number.parseFloat(avgCost);
    if (!(parsedQuantity > 0) || !(parsedAvgCost > 0)) {
      setError("Quantity and average cost must be positive numbers.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/portfolio", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: selectedSymbol.symbol,
          quantity: parsedQuantity,
          avg_cost: parsedAvgCost,
        }),
      });
      const body = (await res.json()) as { error?: string };
      if (!res.ok) {
        setError(body.error ?? "Couldn't add the holding.");
        return;
      }
      setSelectedSymbol(null);
      setSymbolQuery("");
      setQuantity("");
      setAvgCost("");
      router.refresh();
    } catch {
      setError("Something went wrong — try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "h-8 w-full rounded-sm border border-input bg-surface px-2.5 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring";

  return (
    <Panel title="Add a holding">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-3 py-3">
        <div ref={containerRef} className="relative flex flex-col gap-1">
          <span className="label-caps">Company</span>
          {selectedSymbol ? (
            <div className="flex items-center justify-between rounded-sm border border-input bg-surface px-2.5 py-1.5 text-sm">
              <span>
                <span className="num font-medium">{selectedSymbol.symbol}</span>{" "}
                <span className="text-muted-foreground">{selectedSymbol.name}</span>
              </span>
              <button
                type="button"
                onClick={() => {
                  setSelectedSymbol(null);
                  setSymbolQuery("");
                }}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Change
              </button>
            </div>
          ) : (
            <input
              value={symbolQuery}
              onChange={(e) => setSymbolQuery(e.target.value)}
              onFocus={() => symbolResults.length > 0 && setOpen(true)}
              placeholder="Search symbol or company"
              className={inputClass}
            />
          )}
          {open && !selectedSymbol && symbolResults.length > 0 && (
            <ul className="absolute top-full z-40 mt-1 w-full overflow-hidden rounded-sm border border-border bg-popover shadow-xl">
              {symbolResults.slice(0, 8).map((r) => (
                <li key={`${r.exchange}:${r.symbol}`}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedSymbol(r);
                      setOpen(false);
                    }}
                    className="flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-accent"
                  >
                    <span className="num w-20 shrink-0 font-medium">{r.symbol}</span>
                    <span className="truncate text-xs text-muted-foreground">{r.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex gap-3">
          <label className="flex flex-1 flex-col gap-1">
            <span className="label-caps">Quantity</span>
            <input
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              inputMode="decimal"
              placeholder="e.g. 10"
              className={inputClass}
            />
          </label>
          <label className="flex flex-1 flex-col gap-1">
            <span className="label-caps">Avg. cost</span>
            <input
              value={avgCost}
              onChange={(e) => setAvgCost(e.target.value)}
              inputMode="decimal"
              placeholder="e.g. 3500"
              className={inputClass}
            />
          </label>
        </div>

        {error && <p className="text-xs text-down">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="h-9 rounded-sm bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/80 disabled:opacity-50"
        >
          {loading ? "Saving…" : "Add holding"}
        </button>
      </form>
    </Panel>
  );
}
