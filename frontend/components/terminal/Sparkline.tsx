import { cn } from "@/lib/utils";

/**
 * Trailing closing-price line for one row.
 *
 * Inline SVG rather than lightweight-charts: that library is worth its
 * weight for the interactive company chart, but instantiating a chart per
 * row for two dozen rows is not. This renders as plain markup on the
 * server with no client JS at all.
 *
 * Each line is scaled to its OWN min/max, so the shape is readable for a
 * ₹40 stock and a ₹4,000 one alike. That means height is not comparable
 * between rows — deliberately: the row already carries the actual change %
 * next to it, and this is here to show the path, not the magnitude.
 */
export function Sparkline({
  values,
  className,
  width = 56,
  height = 16,
}: {
  values: number[] | undefined;
  className?: string;
  width?: number;
  height?: number;
}) {
  // Two points is the minimum that describes a direction; below that there
  // is nothing honest to draw, so render nothing rather than a flat line
  // that would imply "unchanged".
  if (!values || values.length < 2) {
    return <span className={cn("inline-block shrink-0", className)} style={{ width, height }} />;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;

  // Inset by half the stroke so the extremes aren't clipped at the edges.
  const pad = 1;
  const usableH = height - pad * 2;
  const stepX = width / (values.length - 1);

  const points = values
    .map((value, i) => {
      // A perfectly flat series has no range to normalise against; centre it.
      const t = span === 0 ? 0.5 : (value - min) / span;
      const y = pad + (1 - t) * usableH;
      return `${(i * stepX).toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const rising = values[values.length - 1] >= values[0];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn("shrink-0 overflow-visible", className)}
      // Decorative: the change % beside it already states the move in text,
      // so announcing this again would just be noise for a screen reader.
      aria-hidden
      focusable="false"
    >
      <polyline
        points={points}
        fill="none"
        stroke={rising ? "var(--up)" : "var(--down)"}
        strokeWidth="1"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
