import Link from "next/link";
import { notFound } from "next/navigation";

import { PriceChart } from "@/components/charts/PriceChart";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { TechnicalPanel } from "@/components/domain/TechnicalPanel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, getCompany, getCorporateActions, getPrices, getTechnicals, type PriceRange } from "@/lib/api";

const RANGES: PriceRange[] = ["1m", "3m", "6m", "1y", "5y"];

function isPriceRange(value: string | undefined): value is PriceRange {
  return (RANGES as string[]).includes(value ?? "");
}

export default async function CompanyPage({
  params,
  searchParams,
}: {
  params: Promise<{ symbol: string }>;
  searchParams: Promise<{ range?: string }>;
}) {
  const { symbol } = await params;
  const { range: rawRange } = await searchParams;
  const range = isPriceRange(rawRange) ? rawRange : "1y";

  let company: Awaited<ReturnType<typeof getCompany>>;
  try {
    company = await getCompany(symbol);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  const [prices, technicals, corporateActions] = await Promise.all([
    getPrices(symbol, range),
    getTechnicals(symbol, range),
    getCorporateActions(symbol),
  ]);

  const header = company.data;
  const changePct = header.latest_price.change_pct;

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">{header.name}</h1>
            <Badge variant="outline">{header.symbol}</Badge>
            <Badge variant="outline">{header.exchange}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            {header.sector ?? "Sector unavailable"}
            {header.industry && ` · ${header.industry}`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-2xl font-semibold tabular-nums">
              {header.latest_price.close === null
                ? "—"
                : `₹${header.latest_price.close.toFixed(2)}`}
            </div>
            {changePct !== null && (
              <div className={changePct >= 0 ? "text-sm text-emerald-600" : "text-sm text-red-600"}>
                {changePct >= 0 ? "+" : ""}
                {changePct.toFixed(2)}%
              </div>
            )}
          </div>
          <ProvenanceBadge
            source={company.meta.source}
            asOf={company.meta.as_of}
            confidence={company.meta.confidence}
          />
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">Price</CardTitle>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <Link
                key={r}
                href={`/company/${symbol}?range=${r}`}
                className={`rounded px-2 py-1 text-xs ${
                  r === range ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent"
                }`}
              >
                {r}
              </Link>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          <PriceChart
            bars={prices.data}
            technicals={technicals.data.series}
            corporateActions={corporateActions.data}
          />
        </CardContent>
      </Card>

      <TechnicalPanel snapshot={technicals.data.latest} meta={technicals.meta} />
    </main>
  );
}
