import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import type { Meta, TechnicalSnapshot } from "@/lib/api";

function fmt(value: number | null, digits = 2) {
  return value === null ? "—" : value.toFixed(digits);
}

function StatItem({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums">{value}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}

export function TechnicalPanel({
  snapshot,
  meta,
}: {
  snapshot: TechnicalSnapshot;
  meta: Meta;
}) {
  const rsiHint =
    snapshot.rsi14 === null
      ? undefined
      : snapshot.rsi14 >= 70
        ? "Overbought territory"
        : snapshot.rsi14 <= 30
          ? "Oversold territory"
          : "Neutral";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm font-medium">Technicals</CardTitle>
        <ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <StatItem label="20 DMA" value={fmt(snapshot.dma20)} />
        <StatItem label="50 DMA" value={fmt(snapshot.dma50)} />
        <StatItem label="100 DMA" value={fmt(snapshot.dma100)} />
        <StatItem label="200 DMA" value={fmt(snapshot.dma200)} />
        <StatItem label="RSI (14)" value={fmt(snapshot.rsi14, 1)} hint={rsiHint} />
        <StatItem
          label="MACD"
          value={fmt(snapshot.macd_line)}
          hint={snapshot.macd_signal === null ? undefined : `Signal ${fmt(snapshot.macd_signal)}`}
        />
        <StatItem
          label="Volatility (20d, ann.)"
          value={snapshot.volatility20 === null ? "—" : `${(snapshot.volatility20 * 100).toFixed(1)}%`}
        />
        <StatItem
          label="Drawdown from peak"
          value={snapshot.drawdown_pct === null ? "—" : `${(snapshot.drawdown_pct * 100).toFixed(1)}%`}
        />
      </CardContent>
    </Card>
  );
}
