"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { Fragment, useState } from "react";

import { cn } from "@/lib/utils";
import { pct, price, tone } from "@/lib/format";
import type { PortfolioBroker, PortfolioHolding, PortfolioLot } from "@/lib/api";

const BROKER_LABELS: Record<PortfolioBroker, string> = {
  manual: "Manual",
  zerodha: "Zerodha",
  upstox: "Upstox",
};

/** Holdings list, one row per asset — consolidated across every lot
 * (broker import or manual entry) for that asset, since a user can hold
 * the same stock across multiple demat accounts. The common case (one
 * lot) edits/deletes inline exactly as before; a symbol held via more
 * than one broker gets an expandable breakdown instead, so the extra
 * complexity only shows up when the data actually has it. No separate
 * detail route — mutations go through app/api/portfolio/[id]/route.ts,
 * then router.refresh() re-runs the Server Component page for fresh
 * props, same pattern as ThesisActions. Deliberately no live-quote
 * polling (useLiveQuotes from WatchlistPanel) — portfolio P&L is
 * EOD-only, matching the backend's stored-data-only discipline. */
export function PortfolioTable({ holdings }: { holdings: PortfolioHolding[] }) {
  const router = useRouter();
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const [editingLotId, setEditingLotId] = useState<number | null>(null);
  const [draftQuantity, setDraftQuantity] = useState("");
  const [draftAvgCost, setDraftAvgCost] = useState("");
  const [busyLotId, setBusyLotId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (holdings.length === 0) {
    return (
      <p className="px-3 py-8 text-center text-xs text-muted-foreground">
        No holdings yet — add one manually or import from a broker.
      </p>
    );
  }

  function startEdit(lot: PortfolioLot) {
    setEditingLotId(lot.holding_id);
    setDraftQuantity(String(lot.quantity));
    setDraftAvgCost(String(lot.avg_cost));
  }

  /** Both mutations previously ignored the response, which was safe only
   *  while they could not fail. The verified-email gate can now refuse them
   *  with a 403, and an edit that silently reverts is worse than an error. */
  async function failureMessage(res: Response): Promise<string | null> {
    if (res.ok) return null;
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    return body.error ?? "That didn't save. Try again.";
  }

  async function saveEdit(holdingId: number) {
    const quantity = Number.parseFloat(draftQuantity);
    const avgCost = Number.parseFloat(draftAvgCost);
    if (!(quantity > 0) || !(avgCost > 0)) return;

    setBusyLotId(holdingId);
    setError(null);
    try {
      const res = await fetch(`/api/portfolio/${holdingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity, avg_cost: avgCost }),
      });
      const message = await failureMessage(res);
      if (message) {
        setError(message);
        return;
      }
      setEditingLotId(null);
      router.refresh();
    } finally {
      setBusyLotId(null);
    }
  }

  async function handleDelete(holdingId: number) {
    if (!confirm("Remove this holding?")) return;
    setBusyLotId(holdingId);
    setError(null);
    try {
      const res = await fetch(`/api/portfolio/${holdingId}`, { method: "DELETE" });
      const message = await failureMessage(res);
      if (message) {
        setError(message);
        return;
      }
      router.refresh();
    } finally {
      setBusyLotId(null);
    }
  }

  const inputClass =
    "h-7 w-20 rounded-sm border border-input bg-surface px-1.5 text-xs outline-none focus:border-ring focus:ring-1 focus:ring-ring";

  function LotActions({ lot }: { lot: PortfolioLot }) {
    const isEditing = editingLotId === lot.holding_id;
    const isBusy = busyLotId === lot.holding_id;
    return (
      <div className="flex justify-end gap-1.5">
        {isEditing ? (
          <>
            <button
              type="button"
              onClick={() => saveEdit(lot.holding_id)}
              disabled={isBusy}
              className="rounded-sm border border-border px-2 py-1 text-[11px] hover:bg-accent/60 disabled:opacity-50"
            >
              {isBusy ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => setEditingLotId(null)}
              disabled={isBusy}
              className="rounded-sm border border-border px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent/60 disabled:opacity-50"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => startEdit(lot)}
              disabled={isBusy}
              className="rounded-sm border border-border px-2 py-1 text-[11px] hover:bg-accent/60 disabled:opacity-50"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={() => handleDelete(lot.holding_id)}
              disabled={isBusy}
              className="rounded-sm border border-border px-2 py-1 text-[11px] text-down hover:bg-down/10 disabled:opacity-50"
            >
              {isBusy ? "…" : "Remove"}
            </button>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted-foreground">
            <th className="px-3 py-2 font-medium">Symbol</th>
            <th className="px-3 py-2 text-right font-medium">Qty</th>
            <th className="px-3 py-2 text-right font-medium">Avg. cost</th>
            <th className="px-3 py-2 text-right font-medium">Last price</th>
            <th className="px-3 py-2 text-right font-medium">Market value</th>
            <th className="px-3 py-2 text-right font-medium">P&amp;L</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {holdings.map((h) => {
            const singleLot = h.lots.length === 1 ? h.lots[0] : null;
            const isExpanded = expandedSymbol === h.symbol;
            const isEditing = singleLot != null && editingLotId === singleLot.holding_id;

            return (
              <Fragment key={h.symbol}>
                <tr className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-2">
                    <span className="num font-medium">{h.symbol}</span>{" "}
                    {singleLot ? (
                      <span
                        className={cn(
                          "rounded-sm px-1 py-0.5 text-[9px] uppercase",
                          singleLot.broker === "manual"
                            ? "bg-muted text-muted-foreground"
                            : "bg-primary/10 text-primary",
                        )}
                      >
                        {BROKER_LABELS[singleLot.broker]}
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setExpandedSymbol(isExpanded ? null : h.symbol)}
                        className="inline-flex items-center gap-0.5 rounded-sm bg-primary/10 px-1 py-0.5 text-[9px] uppercase text-primary hover:bg-primary/20"
                      >
                        {isExpanded ? (
                          <ChevronDown className="size-2.5" aria-hidden />
                        ) : (
                          <ChevronRight className="size-2.5" aria-hidden />
                        )}
                        {h.lots.map((lot) => BROKER_LABELS[lot.broker]).join(" · ")}
                      </button>
                    )}
                    <span className="block truncate text-[11px] text-muted-foreground">
                      {h.asset_name}
                    </span>
                  </td>
                  <td className="num px-3 py-2 text-right">
                    {isEditing ? (
                      <input
                        value={draftQuantity}
                        onChange={(e) => setDraftQuantity(e.target.value)}
                        inputMode="decimal"
                        className={inputClass}
                      />
                    ) : (
                      h.quantity
                    )}
                  </td>
                  <td className="num px-3 py-2 text-right">
                    {isEditing ? (
                      <input
                        value={draftAvgCost}
                        onChange={(e) => setDraftAvgCost(e.target.value)}
                        inputMode="decimal"
                        className={inputClass}
                      />
                    ) : (
                      price(h.avg_cost)
                    )}
                  </td>
                  <td className="num px-3 py-2 text-right">{price(h.last_price)}</td>
                  <td className="num px-3 py-2 text-right">{price(h.market_value)}</td>
                  <td className={cn("num px-3 py-2 text-right", tone(h.unrealized_pnl))}>
                    {price(h.unrealized_pnl)}
                    <span className="block text-[10px]">{pct(h.unrealized_pnl_pct)}</span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {singleLot ? (
                      <LotActions lot={singleLot} />
                    ) : (
                      <span className="text-[10px] text-muted-foreground">
                        {h.lots.length} sources
                      </span>
                    )}
                  </td>
                </tr>
                {!singleLot && isExpanded &&
                  h.lots.map((lot) => (
                    <tr
                      key={lot.holding_id}
                      className="border-b border-border/60 bg-accent/20 last:border-0"
                    >
                      <td className="px-3 py-1.5 pl-6 text-[11px] text-muted-foreground">
                        {BROKER_LABELS[lot.broker]}
                      </td>
                      <td className="num px-3 py-1.5 text-right">
                        {editingLotId === lot.holding_id ? (
                          <input
                            value={draftQuantity}
                            onChange={(e) => setDraftQuantity(e.target.value)}
                            inputMode="decimal"
                            className={inputClass}
                          />
                        ) : (
                          lot.quantity
                        )}
                      </td>
                      <td className="num px-3 py-1.5 text-right">
                        {editingLotId === lot.holding_id ? (
                          <input
                            value={draftAvgCost}
                            onChange={(e) => setDraftAvgCost(e.target.value)}
                            inputMode="decimal"
                            className={inputClass}
                          />
                        ) : (
                          price(lot.avg_cost)
                        )}
                      </td>
                      <td className="px-3 py-1.5" colSpan={3} />
                      <td className="px-3 py-1.5 text-right">
                        <LotActions lot={lot} />
                      </td>
                    </tr>
                  ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {error && <p className="px-3 py-1.5 text-[11px] text-down">{error}</p>}
    </div>
  );
}
