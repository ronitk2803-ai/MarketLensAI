"""Seed weights for the "default" score profile (Build_plan.md §L: "Weights
are versioned configuration, never code constants"). This dict is written
into `score_profile.weights` once, at seed time — every actual scoring run
reads weights back out of the DB row, never this constant directly, so
changing weights later is a data change, not a deploy.

Industry-specific profiles (Banking/IT/Manufacturing per Build_plan.md §M)
are explicitly P2 and not seeded here: our fundamentals coverage (a handful
of generic Yahoo ratios — no NIM/GNPA, no deal-wins/attrition) has no real
industry-specific signal to differentiate a "Banking" profile from
"Manufacturing" with today's data. Seeding hollow profiles that use the same
generic metrics under a different label would be fake differentiation, not
real industry awareness. The profile-resolution mechanism (industry code ->
profile, falling back to "default") is still the intended extension point.
"""

DEFAULT_WEIGHTS: dict[str, float] = {
    "valuation": 0.25,
    "fundamental_quality": 0.25,
    "growth": 0.20,
    "technical_setup": 0.15,
    "participation": 0.15,
}
