"""Seed weights for the score profiles (Build_plan.md §L: "Weights are
versioned configuration, never code constants"). These dicts are written
into `score_profile.weights` once, at seed time — every actual scoring run
reads weights back out of the DB row, never these constants directly, so
changing weights later is a data change, not a deploy.

An earlier version of this module refused to seed any industry profile at
all, on the grounds that with only generic Yahoo ratios (no NIM/GNPA, no
deal-wins/attrition) a "Banking" profile would be the same metrics under a
different label — fake differentiation. That objection was right about
*reweighting* and wrong about *exclusion*, so the bar it set still holds
with one addition: a profile earns its existence only when a component's
normalization is structurally invalid for that sector, never by nudging
weights on metrics that mean the same thing everywhere.

`financials` clears that bar on measured evidence. Across the live Nifty
500, every leg of `fundamental_quality` means something different for a
lender than for everyone else:

    metric              financial-services      everything else
    debtToEquity        1.81x median            0.08x - 0.49x
    grossMargins        0.652                   0.427
    operatingMargins    0.472                   0.127 - 0.187

Leverage is a lender's business model rather than distress, and Yahoo's
gross/operating-margin constructs for a lender aren't cost-efficiency
reads. Worse, those distortions point in opposite directions — the D/E leg
pins financials near 0 while the margin leg inflates them — so the blended
component isn't merely wrong for banks, it's noise that partially cancels
and looks like signal. Dropping it is the honest treatment.

Deliberately NOT seeded, having failed the same test:
  - information-technology: its P/B (5.05 median) is *lower* than capital
    goods (8.02), FMCG (7.70) and healthcare (6.39); P/E (27.7) and
    operating margin (0.157) sit inside the normal range. Nothing is
    structurally invalid, so a profile would only relabel.
  - manufacturing: would be `default` plus weight nudges — exactly what
    the paragraph above rules out.
  - power, despite a 1.51x median D/E: unlike a bank's, a utility's
    leverage is genuine financial risk, so scoring it as such is correct.

Thresholds inside each component remain absolute, not peer-relative, so
scores stay only approximately comparable across industries — the
technical half (technical_setup + participation, identical functions at an
identical combined 0.30 in every profile) is exactly comparable, the
fundamental half is not. Peer-percentile normalization (§L, §X.4) is the
separate, still-unbuilt P2 item that would close that gap.
"""

DEFAULT_WEIGHTS: dict[str, float] = {
    "valuation": 0.25,
    "fundamental_quality": 0.25,
    "growth": 0.20,
    "technical_setup": 0.15,
    "participation": 0.15,
}

# Same 0.70 fundamentals / 0.30 technicals balance as DEFAULT_WEIGHTS, so
# the two profiles stay on roughly the same scale. `fundamental_quality`'s
# 0.25 is redistributed across a second valuation read (P/E, ~100% covered
# for this sector) and growth, rather than piled onto P/B alone — for a
# book-value-driven business P/B is the right primary multiple, but 0.40 on
# a single ratio would be a lot of weight for one number to carry.
FINANCIALS_WEIGHTS: dict[str, float] = {
    "valuation": 0.25,
    "earnings_valuation": 0.20,
    "growth": 0.25,
    "technical_setup": 0.15,
    "participation": 0.15,
}

# industry_code -> seed weights, for the migration that inserts the rows and
# for the test that asserts every seeded weight key resolves to a real
# COMPONENT_FUNCS entry (an unknown key is silently treated as missing data
# *and* still counts toward total weight, which would quietly depress
# coverage with no error anywhere).
SEED_PROFILES: dict[str, dict[str, float]] = {
    "default": DEFAULT_WEIGHTS,
    "financials": FINANCIALS_WEIGHTS,
}
