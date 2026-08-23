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
import { useIsLightTheme } from "@/lib/use-theme";

const DMA_LINES: { key: keyof TechnicalSeries; color: string; title: string }[] = [
  { key: "dma20", color: "#38bdf8", title: "DMA 20" },
  { key: "dma50", color: "#fbbf24", title: "DMA 50" },
  { key: "dma100", color: "#c084fc", title: "DMA 100" },
  { key: "dma200", color: "#fb7185", title: "DMA 200" },
];

// Candle colours are fixed rather than themed: up/down is the one signal a
// trader reads pre-attentively, and it must stay identical across themes.
const UP = "#22c55e";
const DOWN = "#ef4444";

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
  // Chart colours are read out of CSS custom properties once, at build time
  // — canvas can't participate in the cascade — so a theme switch has to
  // rebuild the chart, or the axis text keeps the old theme's contrast and
  // becomes unreadable (light-grey labels on the light palette's white).
  const isLight = useIsLightTheme();

  useEffect(() => {
    const container = containerRef.current;
    if (!container || bars.length === 0) return;

    const mutedForeground = cssVar("--muted-foreground");
    const border = cssVar("--border");
    const foreground = cssVar("--foreground");

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: mutedForeground,
        fontFamily: getComputedStyle(document.body).fontFamily,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: border, style: 1 },
        horzLines: { color: border, style: 1 },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: mutedForeground, width: 1, style: 2, labelBackgroundColor: border },
        horzLine: { color: mutedForeground, width: 1, style: 2, labelBackgroundColor: border },
      },
      rightPriceScale: { borderColor: border, scaleMargins: { top: 0.08, bottom: 0.25 } },
      timeScale: { borderColor: border, rightOffset: 2 },
      autoSize: true,
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
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
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volumeSeries.setData(
      bars.map((b) => ({
        time: b.date as Time,
        value: b.volume,
        // Tint volume by the session's own direction so a heavy down-day is
        // distinguishable from a heavy up-day at a glance. Kept translucent
        // so it stays subordinate to the candles.
        color: b.close >= b.open ? `${UP}66` : `${DOWN}66`,
      })),
    );

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

    // Two distinct failure modes, both verified live, both fixed by pinning
    // the logical range to the real data span instead of trusting
    // fitContent():
    //   1. fitContent() leaves ~110 empty logical slots to the left of a
    //      short (7-bar) series rather than stretching bar spacing to fill
    //      the container ({from: -113, to: 6} for a 721px-wide chart).
    //   2. The chart computes bar spacing against whatever width the
    //      container has when the series is set, then *preserves that
    //      spacing* when the container later grows. Inside a grid/flex
    //      layout the first measurement is narrower than the settled one,
    //      so a 69-bar series ends up crammed into the right ~15% of a
    //      full-width chart.
    // Re-applying on every resize is what keeps (2) fixed rather than
    // merely fixed-on-first-paint.
    const fill = () => chart.timeScale().setVisibleLogicalRange({ from: 0, to: bars.length - 1 });
    fill();
    const observer = new ResizeObserver(fill);
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, technicals, corporateActions, isLight]);

  if (bars.length === 0) {
    return (
      <div className="flex h-96 items-center justify-center text-sm text-muted-foreground">
        No price history available yet.
      </div>
    );
  }

  return <div ref={containerRef} className="h-[420px] w-full" />;
}
