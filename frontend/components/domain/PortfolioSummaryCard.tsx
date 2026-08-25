import { Panel } from "@/components/terminal/Panel";
import { pct, price, tone } from "@/lib/format";
import type { PortfolioTotals } from "@/lib/api";

function Stat({ label, value, valueClassName }: { label: string; value: string; valueClassName?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="label-caps text-[10px]">{label}</span>
      <span className={`num text-base font-semibold ${valueClassName ?? ""}`}>{value}</span>
    </div>
  );
}

export function PortfolioSummaryCard({ totals }: { totals: PortfolioTotals }) {
  return (
    <Panel>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Cost basis" value={price(totals.cost_basis)} />
        <Stat label="Market value" value={price(totals.market_value)} />
        <Stat
          label="Unrealized P&L"
          value={price(totals.unrealized_pnl)}
          valueClassName={tone(totals.unrealized_pnl)}
        />
        <Stat
          label="P&L %"
          value={pct(totals.unrealized_pnl_pct)}
          valueClassName={tone(totals.unrealized_pnl_pct)}
        />
      </div>
      {totals.holdings_total > 0 && totals.holdings_priced < totals.holdings_total && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          P&amp;L based on {totals.holdings_priced} of {totals.holdings_total} holdings — the rest
          have no stored price history yet.
        </p>
      )}
    </Panel>
  );
}
