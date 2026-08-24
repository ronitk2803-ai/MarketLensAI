/**
 * Large/Mid/Small-cap classification from market capitalization.
 *
 * NOT the official SEBI/AMFI classification. SEBI's actual rule (Oct 2017
 * circular) ranks *every* listed company by full market cap and defines
 * the bands by rank — top 100 large-cap, 101–250 mid-cap, 251+ small-cap —
 * republished twice a year as ranks shift. Reproducing that correctly
 * would mean ranking the entire listed market, not just this app's
 * Nifty 500 universe (whose own 251st–500th members are already a strict
 * subset of the true small-cap universe, not the small-cap universe
 * itself), and the app doesn't have that data. What's here instead is the
 * commonly-used fixed-rupee-threshold approximation (the same shorthand
 * most retail research tools show) — good enough to orient at a glance,
 * not a claim of the regulatory ranking. Say so wherever this shows up.
 */

export type MarketCapCategory = "Large Cap" | "Mid Cap" | "Small Cap";

const LARGE_CAP_MIN_CRORES = 20_000;
const MID_CAP_MIN_CRORES = 5_000;

export function marketCapCategory(marketCapRupees: number | null | undefined): MarketCapCategory | null {
  if (marketCapRupees == null) return null;
  const crores = marketCapRupees / 1e7;
  if (crores >= LARGE_CAP_MIN_CRORES) return "Large Cap";
  if (crores >= MID_CAP_MIN_CRORES) return "Mid Cap";
  return "Small Cap";
}

export function marketCapCategoryTone(category: MarketCapCategory | null): string {
  if (category === "Large Cap") return "text-up";
  if (category === "Mid Cap") return "text-[color:var(--chart-2)]";
  if (category === "Small Cap") return "text-down";
  return "text-muted-foreground";
}
