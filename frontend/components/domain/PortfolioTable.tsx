"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { cn } from "@/lib/utils";
import { pct, price, tone } from "@/lib/format";
import type { PortfolioHolding } from "@/lib/api";

/** Holdings list with inline per-row edit/delete — no separate detail
 * route, unlike Thesis. Deliberately no live-quote polling
 * (useLiveQuotes from WatchlistPanel) — portfolio P&L is EOD-only,
 * matching the backend's stored-data-only discipline. Mutations go
 * through app/api/portfolio/[id]/route.ts, then router.refresh() re-runs
 * the Server Component page for fresh props, same pattern as
 * ThesisActions. */
export function PortfolioTable({ holdings }: { holdings: PortfolioHolding[] }) {
  const router = useRouter();
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftQuantity, setDraftQuantity] = useState("");
  const [draftAvgCost, setDraftAvgCost] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  if (holdings.length === 0) {
    return (
      <p className="px-3 py-8 text-center text-xs text-muted-foreground">
        No holdings yet — add one manually or import a Zerodha CSV.
      </p>
    );
  }

  function startEdit(h: PortfolioHolding) {
    setEditingId(h.id);
    setDraftQuantity(String(h.quantity));
    setDraftAvgCost(String(h.avg_cost));
  }

  async function saveEdit(id: number) {
    const quantity = Number.parseFloat(draftQuantity);
    const avgCost = Number.parseFloat(draftAvgCost);
    if (!(quantity > 0) || !(avgCost > 0)) return;

    setBusyId(id);
    try {
      await fetch(`/api/portfolio/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity, avg_cost: avgCost }),
      });
      setEditingId(null);
      router.refresh();
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Remove this holding?")) return;
    setBusyId(id);
    try {
      await fetch(`/api/portfolio/${id}`, { method: "DELETE" });
      router.refresh();
    } finally {
      setBusyId(null);
    }
  }

  const inputClass =
    "h-7 w-20 rounded-sm border border-input bg-surface px-1.5 text-xs outline-none focus:border-ring focus:ring-1 focus:ring-ring";

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
            const isEditing = editingId === h.id;
            const isBusy = busyId === h.id;
            return (
              <tr key={h.id} className="border-b border-border/60 last:border-0">
                <td className="px-3 py-2">
                  <span className="num font-medium">{h.symbol}</span>{" "}
                  <span
                    className={cn(
                      "rounded-sm px-1 py-0.5 text-[9px] uppercase",
                      h.source === "csv"
                        ? "bg-primary/10 text-primary"
                        : "bg-muted text-muted-foreground",
                    )}
                  >
                    {h.source === "csv" ? "Imported" : "Manual"}
                  </span>
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
                  <div className="flex justify-end gap-1.5">
                    {isEditing ? (
                      <>
                        <button
                          type="button"
                          onClick={() => saveEdit(h.id)}
                          disabled={isBusy}
                          className="rounded-sm border border-border px-2 py-1 text-[11px] hover:bg-accent/60 disabled:opacity-50"
                        >
                          {isBusy ? "Saving…" : "Save"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingId(null)}
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
                          onClick={() => startEdit(h)}
                          disabled={isBusy}
                          className="rounded-sm border border-border px-2 py-1 text-[11px] hover:bg-accent/60 disabled:opacity-50"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(h.id)}
                          disabled={isBusy}
                          className="rounded-sm border border-border px-2 py-1 text-[11px] text-down hover:bg-down/10 disabled:opacity-50"
                        >
                          {isBusy ? "…" : "Remove"}
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
