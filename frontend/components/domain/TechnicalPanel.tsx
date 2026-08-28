import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { Stat } from "@/components/terminal/Stat";
import { DASH, fracPct, num, price } from "@/lib/format";
import type { Meta, TechnicalSnapshot } from "@/lib/api";

/** Where price sits relative to the average — the read most people actually
 *  want from a DMA, and the direction the sign refers to must be unambiguous. */
function dmaHint(close: number | null, dma: number | null): { text: string; tone: string } | null {
  if (close == null || dma == null || dma === 0) return null;
  const diff = ((close - dma) / dma) * 100;
  return {
    text: `price ${diff >= 0 ? "+" : ""}${diff.toFixed(1)}%`,
    tone: diff >= 0 ? "text-up" : "text-down",
  };
}

export function TechnicalPanel({ snapshot, meta }: { snapshot: TechnicalSnapshot; meta: Meta }) {
  const rsi = snapshot.rsi14;
  const rsiHint =
    rsi == null
      ? undefined
      : rsi >= 70
        ? "Overbought"
        : rsi <= 30
          ? "Oversold"
          : "Neutral";
  const rsiTone =
    rsi == null ? undefined : rsi >= 70 ? "text-down" : rsi <= 30 ? "text-up" : undefined;

  const dmas = [
    { label: "20 DMA", value: snapshot.dma20 },
    { label: "50 DMA", value: snapshot.dma50 },
    { label: "100 DMA", value: snapshot.dma100 },
    { label: "200 DMA", value: snapshot.dma200 },
  ];

  const macdHist = snapshot.macd_histogram;

  return (
    <Panel
      title="Technicals"
      actions={<ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />}
      bodyClassName="p-3"
      footnote="Indicators only — not a trading signal, forecast, or buy/sell/hold recommendation. MarketLens AI is not a SEBI-registered investment adviser or research analyst."
      fullscreenable
    >
      <div className="grid grid-cols-2 gap-y-3 sm:grid-cols-4">
        {dmas.map((dma) => {
          const hint = dmaHint(snapshot.close, dma.value);
          return (
            <Stat
              key={dma.label}
              label={dma.label}
              glossaryKey="dma"
              value={price(dma.value)}
              hint={hint?.text}
              hintTone={hint?.tone}
            />
          );
        })}
        <Stat
          label="RSI (14)"
          glossaryKey="rsi"
          value={num(rsi, 1)}
          hint={rsiHint}
          hintTone={rsiTone}
        />
        <Stat
          label="MACD"
          glossaryKey="macd"
          value={num(snapshot.macd_line)}
          hint={
            macdHist == null
              ? undefined
              : `Hist ${macdHist >= 0 ? "+" : ""}${macdHist.toFixed(2)}`
          }
          hintTone={macdHist == null ? undefined : macdHist >= 0 ? "text-up" : "text-down"}
        />
        <Stat
          label="Volatility 20d"
          glossaryKey="volatility"
          value={snapshot.volatility20 == null ? DASH : fracPct(snapshot.volatility20)}
          hint="annualized"
        />
        <Stat
          label="Drawdown"
          glossaryKey="drawdown"
          value={snapshot.drawdown_pct == null ? DASH : fracPct(snapshot.drawdown_pct)}
          hint="from peak"
          hintTone={snapshot.drawdown_pct == null ? undefined : "text-down"}
        />
      </div>
    </Panel>
  );
}
