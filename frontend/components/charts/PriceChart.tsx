"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { CorporateAction, PriceBar, TechnicalSeries } from "@/lib/api";
import { useLiveQuotes } from "@/lib/use-live-quotes";
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

/** YYYY-MM-DD for an instant, in the exchange's own timezone. `en-CA`
 * formats as ISO, which is also what the chart's time axis expects. */
const IST_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Kolkata",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function istDate(iso: string): string {
  return IST_DATE.format(new Date(iso));
}

export function PriceChart({
  symbol,
  bars,
  technicals,
  corporateActions,
}: {
  symbol: string;
  bars: PriceBar[];
  technicals: TechnicalSeries | null;
  corporateActions: CorporateAction[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // Held so the live-candle effect can update the last bar in place. A
  // rebuild-per-tick would throw away the user's pan/zoom every 15s and
  // re-run the whole series setup for one changed candle.
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // Whether a provisional candle is currently appended past the stored
  // bars, so the visible-range fill (and the ResizeObserver that re-applies
  // it) accounts for it instead of cutting it off the right edge.
  const liveBarRef = useRef(false);

  const live = useLiveQuotes([symbol]);
  const liveQuote = live.isLive ? live.bySymbol[symbol] : undefined;
  const liveCandle = liveQuote?.day_candle ?? null;
  // The candle belongs to the exchange's trading day, not the viewer's. A
  // browser in New York would otherwise place an NSE session on the
  // previous calendar date and push the bar behind the series' last point.
  const liveDate = liveQuote ? istDate(liveQuote.as_of) : null;
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
    candleSeriesRef.current = candleSeries;
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
    volumeSeriesRef.current = volumeSeries;
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
    const fill = () =>
      chart
        .timeScale()
        .setVisibleLogicalRange({ from: 0, to: bars.length - 1 + (liveBarRef.current ? 1 : 0) });
    fill();
    const observer = new ResizeObserver(fill);
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      liveBarRef.current = false;
    };
  }, [bars, technicals, corporateActions, isLight]);

  // Today's forming candle, applied with update() rather than by rebuilding
  // the chart. Two reasons this is a separate effect and not part of the one
  // above: a rebuild every 15s would discard the user's pan/zoom and redo
  // the whole series setup for one changed bar, and update() is the API
  // lightweight-charts provides precisely for a bar that is still forming.
  //
  // The DMA overlays deliberately stop at the last completed session. They
  // are computed server-side from ingested bars, and extending them through
  // a provisional candle would mean recomputing indicators in the browser
  // against a close that is still moving — a 200-day average that flickers
  // intraday is worse than one that plainly ends at Friday.
  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!candleSeries || !volumeSeries || bars.length === 0) return;

    const lastStored = bars[bars.length - 1];

    if (!liveCandle) {
      // Nothing live (market shut, or the feed dropped). If a provisional
      // candle was drawn earlier in this session, put the last stored bar
      // back so the chart never keeps a stale forming candle on screen.
      if (liveBarRef.current) {
        candleSeries.setData(
          bars.map((b) => ({
            time: b.date as Time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          })),
        );
        volumeSeries.setData(
          bars.map((b) => ({
            time: b.date as Time,
            value: b.volume,
            color: b.close >= b.open ? `${UP}66` : `${DOWN}66`,
          })),
        );
        liveBarRef.current = false;
        chartRef.current?.timeScale().setVisibleLogicalRange({ from: 0, to: bars.length - 1 });
      }
      return;
    }

    // update() requires a time at or after the series' last point. Equal
    // means the session has already been ingested, and the provisional
    // candle simply refreshes that bar in place rather than appending.
    if (!liveDate || liveDate < lastStored.date) return;
    const liveTime = liveDate;
    const appends = liveDate > lastStored.date;

    candleSeries.update({
      time: liveTime as Time,
      open: liveCandle.open,
      high: liveCandle.high,
      low: liveCandle.low,
      close: liveCandle.close,
    });
    if (liveCandle.volume !== null) {
      volumeSeries.update({
        time: liveTime as Time,
        value: liveCandle.volume,
        color: liveCandle.close >= liveCandle.open ? `${UP}66` : `${DOWN}66`,
      });
    }

    if (appends && !liveBarRef.current) {
      liveBarRef.current = true;
      chartRef.current?.timeScale().setVisibleLogicalRange({ from: 0, to: bars.length });
    }
  }, [liveCandle, liveDate, bars]);

  if (bars.length === 0) {
    return (
      <div className="flex h-96 items-center justify-center text-sm text-muted-foreground">
        No price history available yet.
      </div>
    );
  }

  return <div ref={containerRef} className="h-[420px] w-full" />;
}
