import Link from "next/link";

import { AddHoldingForm } from "@/components/domain/AddHoldingForm";
import { ImportHoldingsForm } from "@/components/domain/ImportHoldingsForm";
import { Panel } from "@/components/terminal/Panel";
import { PortfolioSummaryCard } from "@/components/domain/PortfolioSummaryCard";
import { PortfolioTable } from "@/components/domain/PortfolioTable";
import { getPortfolio } from "@/lib/api";
import { getSignedInSession } from "@/lib/session";

export const dynamic = "force-dynamic";

const EMPTY_TOTALS = {
  cost_basis: 0,
  market_value: null,
  unrealized_pnl: null,
  unrealized_pnl_pct: null,
  holdings_priced: 0,
  holdings_total: 0,
};

export default async function PortfolioPage() {
  const session = await getSignedInSession();

  if (!session) {
    return (
      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
        <Panel title="Portfolio" bodyClassName="p-0">
          <p className="px-3 py-8 text-center text-xs text-muted-foreground">
            <Link href="/login" className="text-primary hover:underline">
              Sign in
            </Link>{" "}
            to track your holdings.
          </p>
        </Panel>
      </main>
    );
  }

  const portfolio = await getPortfolio(session.accessToken).catch(() => ({
    holdings: [],
    totals: EMPTY_TOTALS,
  }));

  return (
    <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-3 px-4 py-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Portfolio</h1>
        <p className="text-xs text-muted-foreground">
          What you hold, and what it&apos;s worth right now.
        </p>
      </div>

      <PortfolioSummaryCard totals={portfolio.totals} />

      <div className="grid gap-3 sm:grid-cols-2">
        <AddHoldingForm />
        <ImportHoldingsForm />
      </div>

      <Panel title="Holdings" bodyClassName="p-0">
        <PortfolioTable holdings={portfolio.holdings} />
      </Panel>
    </main>
  );
}
