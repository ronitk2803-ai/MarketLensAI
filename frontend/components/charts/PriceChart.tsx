"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { CorporateAction, PriceBar, TechnicalSeries } from "@/lib/api";

const DMA_LINES: { key: keyof TechnicalSeries; color: string; title: string }[] = [
  { key: "dma20", color: "#60a5fa", title: "DMA 20" },
  { key: "dma50", color: "#f59e0b", title: "DMA 50" },
  { key: "dma100", color: "#a78bfa", title: "DMA 100" },
  { key: "dma200", color: "#f87171", title: "DMA 200" },
];

const ACTION_LABEL: Record<string, (a: CorporateAction) => string> = {
  split: (a) => `Split/bonus ${a.ratio ?? ""}x`,
  dividend: (a) => `Dividend ₹${a.amount ?? ""}`,
};

// Canvas (what lightweight-charts renders to) resolves colors through the
// browser's CSS <color> parser, but only for literal values — `var(--x)`
// is a cascade-time CSS construct with no meaning to a canvas fillStyle
// setter, so it silently fails to apply. Our theme tokens are oklch(...),
// and — verified live — modern browsers now preserve that through
// getComputedStyle (serializing as oklch/lab) rather than always
// collapsing to legacy rgb() as they used to; lightweight-charts has its
// own regex-based color parser that only understands hex/rgb/rgba/hsl, so
// either form throws "Failed to parse color". The reliable fix: paint the
// raw value onto a real canvas — whose native fillStyle parser does
// understand oklch/lab, since it's the same CSS <color> parser the
// browser uses everywhere else — then read the pixel back. Canvas
// ImageData is always 8-bit sRGB regardless of the input color space, so
// this deterministically yields an rgb(...) string lightweight-charts can
// parse.
function cssVar(name: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext("2d");
  if (!ctx) return raw;
  ctx.fillStyle = raw;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
}

export function PriceChart({
  bars,
  technicals,
  corporateActions,
}: {
  bars: PriceBar[];
  technicals: TechnicalSeries | null;
  corporateActions: CorporateAction[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || bars.length === 0) return;

    const mutedForeground = cssVar("--muted-foreground");
    const border = cssVar("--border");
    const muted = cssVar("--muted");
    const foreground = cssVar("--foreground");

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: mutedForeground,
      },
      grid: {
        vertLines: { color: border },
        horzLines: { color: border },
      },
      rightPriceScale: { borderColor: border },
      timeScale: { borderColor: border },
      autoSize: true,
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#dc2626",
      borderVisible: false,
      wickUpColor: "#16a34a",
      wickDownColor: "#dc2626",
    });
    candleSeries.setData(
      bars.map((b) => ({
        time: b.date as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: mutedForeground,
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    volumeSeries.setData(bars.map((b) => ({ time: b.date as Time, value: b.volume, color: muted })));

    if (technicals) {
      for (const { key, color, title } of DMA_LINES) {
        const series = technicals[key] as (number | null)[];
        const points = technicals.dates
          .map((date, i) => ({ time: date as Time, value: series[i] }))
          .filter((p): p is { time: Time; value: number } => p.value !== null);
        if (points.length === 0) continue;
        const line = chart.addSeries(LineSeries, {
          color,
          lineWidth: 1,
          title,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        line.setData(points);
      }
    }

    const barDates = new Set(bars.map((b) => b.date));
    const markers: SeriesMarker<Time>[] = corporateActions
      .filter((a) => barDates.has(a.ex_date) && ACTION_LABEL[a.type])
      .map((a) => ({
        time: a.ex_date as Time,
        position: "aboveBar",
        color: foreground,
        shape: "circle",
        text: ACTION_LABEL[a.type](a),
      }));
    if (markers.length > 0) {
      createSeriesMarkers(candleSeries, markers);
    }

    // fitContent() alone was leaving ~110 empty logical slots to the left
    // of a short (7-bar) series instead of stretching bar spacing to fill
    // the container (verified live via logicalRange debugging — {from:
    // -113, to: 6} for a 721px-wide, 7-bar chart). Setting the visible
    // logical range explicitly to the real data span forces it to compute
    // spacing that actually fills the width.
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: bars.length - 1 });

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, technicals, corporateActions]);

  if (bars.length === 0) {
    return (
      <div className="flex h-96 items-center justify-center text-sm text-muted-foreground">
        No price history available yet.
      </div>
    );
  }

  return <div ref={containerRef} className="h-96 w-full" />;
}
