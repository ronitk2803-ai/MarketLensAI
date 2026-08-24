import { num } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Compact "where does the current price sit between low and high" strip —
 * the in-cell chart for a watchlist row's 52-week and all-time ranges.
 *
 * Deliberately a bar, not a second sparkline: a range only has three facts
 * that matter (low, high, where "now" falls between them), and a bar makes
 * the third one — position — a single glance rather than something you
 * have to read off two numbers and subtract.
 */
export function RangeBar({
  high,
  low,
  position,
  className,
}: {
  high: number;
  low: number;
  /** 0..1, or null when high === low (nothing to position against). */
  position: number | null;
  className?: string;
}) {
  const pct = position == null ? 50 : Math.min(100, Math.max(0, position * 100));
  // Near the low end reads as opportunity-adjacent (down), near the high
  // end as extended (up) — same semantic as the rest of the app's up/down
  // tokens, not a value judgement on the stock itself.
  const tone = position == null ? "bg-muted-foreground" : position >= 0.5 ? "bg-up" : "bg-down";

  return (
    <div className={cn("flex w-full min-w-[88px] flex-col gap-0.5", className)}>
      <div className="relative h-1 w-full rounded-full bg-border">
        <div
          className={cn("absolute top-1/2 size-1.5 -translate-y-1/2 rounded-full", tone)}
          style={{ left: `calc(${pct}% - 3px)` }}
        />
      </div>
      <div className="flex justify-between text-[10px] leading-none text-muted-foreground">
        <span className="num">{num(low, 0)}</span>
        <span className="num">{num(high, 0)}</span>
      </div>
    </div>
  );
}
