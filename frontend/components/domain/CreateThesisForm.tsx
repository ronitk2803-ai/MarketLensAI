"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Panel } from "@/components/terminal/Panel";
import { THESIS_METRICS, THESIS_OPERATORS } from "@/lib/thesis-metrics";
import type { AssetSearchResult } from "@/lib/api";

interface TriggerDraft {
  metric: string;
  operator: string;
  threshold: string;
  description: string;
}

const EMPTY_TRIGGER: TriggerDraft = {
  metric: THESIS_METRICS[0].value,
  operator: "gt",
  threshold: "",
  description: "",
};

/** The create flow for a thesis — title/body/stance/conviction, an asset
 * search (same debounced-search idiom as WatchlistPanel's AddSymbolInput),
 * and one-or-more trigger rows framed as "what would invalidate this?"
 * per Build_plan.md §X.1's UI note. Posts to app/api/theses/route.ts. */
export function CreateThesisForm() {
  const router = useRouter();

  const [symbolQuery, setSymbolQuery] = useState("");
  const [symbolResults, setSymbolResults] = useState<AssetSearchResult[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<AssetSearchResult | null>(null);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [stance, setStance] = useState<"bull" | "bear" | "neutral">("bull");
  const [conviction, setConviction] = useState(3);
  const [triggers, setTriggers] = useState<TriggerDraft[]>([{ ...EMPTY_TRIGGER }]);

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

  function updateTrigger(index: number, patch: Partial<TriggerDraft>) {
    setTriggers((prev) => prev.map((t, i) => (i === index ? { ...t, ...patch } : t)));
  }

  function addTrigger() {
    setTriggers((prev) => [...prev, { ...EMPTY_TRIGGER }]);
  }

  function removeTrigger(index: number) {
    setTriggers((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!selectedSymbol) {
      setError("Pick a company from the search results.");
      return;
    }
    const parsedTriggers = triggers.map((t) => ({
      metric: t.metric,
      operator: t.operator,
      threshold: Number.parseFloat(t.threshold),
      description: t.description.trim() || undefined,
    }));
    if (parsedTriggers.some((t) => Number.isNaN(t.threshold))) {
      setError("Every trigger needs a numeric threshold.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/theses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: selectedSymbol.symbol,
          title,
          body,
          stance,
          conviction,
          triggers: parsedTriggers,
        }),
      });
      const responseBody = (await res.json()) as { id?: number; error?: string };
      if (!res.ok) {
        setError(responseBody.error ?? "Couldn't create the thesis.");
        return;
      }
      router.push(`/theses/${responseBody.id}`);
    } catch {
      setError("Something went wrong — try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "h-8 w-full rounded-sm border border-input bg-surface px-2.5 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring";

  return (
    <Panel title="New thesis">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4 px-3 py-4">
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

        <label className="flex flex-col gap-1">
          <span className="label-caps">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="e.g. Ola's battery arm is the real long-term value"
            className={inputClass}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="label-caps">Thesis</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            required
            rows={4}
            className="w-full rounded-sm border border-input bg-surface px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
          />
        </label>

        <div className="flex gap-4">
          <label className="flex flex-1 flex-col gap-1">
            <span className="label-caps">Stance</span>
            <select
              value={stance}
              onChange={(e) => setStance(e.target.value as "bull" | "bear" | "neutral")}
              className={inputClass}
            >
              <option value="bull">Bull</option>
              <option value="bear">Bear</option>
              <option value="neutral">Neutral</option>
            </select>
          </label>
          <label className="flex flex-1 flex-col gap-1">
            <span className="label-caps">Conviction</span>
            <select
              value={conviction}
              onChange={(e) => setConviction(Number(e.target.value))}
              className={inputClass}
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n} / 5
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex flex-col gap-2">
          <span className="label-caps">What would invalidate this?</span>
          {triggers.map((t, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-sm border border-border p-2">
              <select
                value={t.metric}
                onChange={(e) => updateTrigger(i, { metric: e.target.value })}
                className="h-8 rounded-sm border border-input bg-surface px-2 text-xs"
              >
                {THESIS_METRICS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <select
                value={t.operator}
                onChange={(e) => updateTrigger(i, { operator: e.target.value })}
                className="h-8 rounded-sm border border-input bg-surface px-2 text-xs"
              >
                {THESIS_OPERATORS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <input
                value={t.threshold}
                onChange={(e) => updateTrigger(i, { threshold: e.target.value })}
                placeholder="threshold"
                inputMode="decimal"
                className="h-8 w-24 rounded-sm border border-input bg-surface px-2 text-xs"
              />
              <input
                value={t.description}
                onChange={(e) => updateTrigger(i, { description: e.target.value })}
                placeholder="note (optional)"
                className="h-8 min-w-32 flex-1 rounded-sm border border-input bg-surface px-2 text-xs"
              />
              {triggers.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeTrigger(i)}
                  className="text-xs text-muted-foreground hover:text-down"
                >
                  Remove
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={addTrigger}
            className="self-start text-xs text-primary hover:underline"
          >
            + Add another trigger
          </button>
        </div>

        {error && <p className="text-xs text-down">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="h-9 rounded-sm bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/80 disabled:opacity-50"
        >
          {loading ? "Creating…" : "Create thesis"}
        </button>
      </form>
    </Panel>
  );
}
