const INR = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const COMPACT = new Intl.NumberFormat("en-IN", {
  notation: "compact",
  maximumFractionDigits: 2,
});

export const DASH = "—";

export function price(value: number | null | undefined): string {
  return value == null ? DASH : `₹${INR.format(value)}`;
}

export function num(value: number | null | undefined, digits = 2): string {
  return value == null ? DASH : value.toFixed(digits);
}

/** Always signed — on a market screen "+0.42%" and "0.42%" read differently. */
export function pct(value: number | null | undefined, digits = 2): string {
  if (value == null) return DASH;
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

/** For ratios stored as fractions (0.0842) that display as percentages. */
export function fracPct(value: number | null | undefined, digits = 1): string {
  return value == null ? DASH : `${(value * 100).toFixed(digits)}%`;
}

export function compact(value: number | null | undefined): string {
  return value == null ? DASH : COMPACT.format(value);
}

/** Raw rupees -> "₹X,XX,XXX Cr" (1 crore = 1e7), en-IN grouped — the
 * standard Indian convention for company-scale rupee figures (revenue,
 * net income, market cap), where the Western "T"/"B" from `compact()`
 * isn't how these numbers are normally read here. */
export function crores(value: number | null | undefined): string {
  if (value == null) return DASH;
  return `₹${(value / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
}

/** Raw share count -> "X.XX Cr" — same crore convention as `crores()`, but
 * for a share count rather than a rupee amount, so no ₹ prefix. */
export function croreShares(value: number | null | undefined): string {
  if (value == null) return DASH;
  // Verified live: without a unit this rendered as a bare "1,353.25" next
  // to a label reading just "Shares outstanding" — indistinguishable from
  // a raw share count, a lakh figure, or anything else. The unit has to be
  // in the string itself, not implied by the label.
  return `${(value / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`;
}

/**
 * Direction classes for a change value. `null` deliberately maps to the
 * neutral tone rather than to "down" — unknown is not a decline.
 */
export function tone(value: number | null | undefined): string {
  if (value == null) return "text-muted-foreground";
  if (value > 0) return "text-up";
  if (value < 0) return "text-down";
  return "text-muted-foreground";
}

export function toneBg(value: number | null | undefined): string {
  if (value == null) return "bg-muted";
  if (value > 0) return "bg-up";
  if (value < 0) return "bg-down";
  return "bg-muted";
}

/**
 * Opportunity Score band. Higher = more research-worthy, never "buy" —
 * the copy around this must keep saying so (product_principles.md).
 */
export function scoreTone(value: number | null | undefined): string {
  if (value == null) return "text-muted-foreground";
  if (value >= 66) return "text-up";
  if (value >= 33) return "text-[color:var(--chart-2)]";
  return "text-down";
}

export function scoreBarTone(value: number | null | undefined): string {
  if (value == null) return "bg-muted";
  if (value >= 66) return "bg-up";
  if (value >= 33) return "bg-[color:var(--chart-2)]";
  return "bg-down";
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return DASH;
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function tradingDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}
