"""Indian-convention number formatting for AI-generated prose
(company_summary.py, research_assistant.py) — pure, no IO.

Verified live 2026-08-30: left to its own judgment, the model reads a raw
`marketCap` figure like 160000000000 and narrates it as "$1.6 trillion" —
correct arithmetic, wrong convention for an app entirely about Indian
equities, where the same figure is always read as "₹1.6 lakh crore" (1
lakh crore = 1e12, so the two are the same magnitude, just different
units of speech). Converting the raw number is exactly the kind of
computation this app's architecture rule reserves for code, not the
model (Build_plan.md §D: "AI consumes engine/DB output; never computes
financial numbers") — unit conversion is a computation like any other,
so it happens here and the model only ever reads an already-correct
string, the same way frontend/lib/format.ts's `crores()` does for the UI.

Deliberately a different convention from `crores()`, not a port of it:
that function labels a UI field where a bare number next to a "₹...Cr"
unit is fine even at large magnitudes (e.g. "₹16,00,000 Cr"). This is for
prose a human reads in a sentence, where "₹16 lakh crore" is how that
magnitude is actually said out loud in Indian financial writing, not
"₹16,00,000 crore".
"""

_LAKH_CRORE = 10**12  # 1 lakh crore == 1 trillion
_CRORE = 10**7
_LAKH = 10**5


def format_inr_prose(value: float | None) -> str | None:
    """Raw rupees -> "₹1.60 lakh crore" / "₹4,523 crore" / "₹85.00 lakh" /
    "₹45,000", picking whichever unit keeps the leading number readable.
    None in, None out — never fabricate a figure for missing data."""
    if value is None:
        return None
    magnitude = abs(value)
    sign = "-" if value < 0 else ""
    if magnitude >= _LAKH_CRORE:
        return f"{sign}₹{magnitude / _LAKH_CRORE:.2f} lakh crore"
    if magnitude >= _CRORE:
        return f"{sign}₹{magnitude / _CRORE:,.0f} crore"
    if magnitude >= _LAKH:
        return f"{sign}₹{magnitude / _LAKH:.2f} lakh"
    return f"{sign}₹{magnitude:,.0f}"


def format_count_prose(value: float | None, *, unit: str) -> str | None:
    """Same convention as format_inr_prose but for a plain count (shares
    outstanding, float shares) rather than a rupee amount — no ₹ prefix,
    and the unit noun is appended (e.g. "2.71 crore shares")."""
    if value is None:
        return None
    magnitude = abs(value)
    sign = "-" if value < 0 else ""
    if magnitude >= _CRORE:
        return f"{sign}{magnitude / _CRORE:.2f} crore {unit}"
    if magnitude >= _LAKH:
        return f"{sign}{magnitude / _LAKH:.2f} lakh {unit}"
    return f"{sign}{magnitude:,.0f} {unit}"


# Ratio-field names (app/providers/india/yfinance_fundamentals.py's
# RATIO_FIELDS) that are actually rupee amounts or share counts rather
# than a ratio/percentage/multiple — the only ones this conversion
# applies to. Everything else in that list (P/E, P/B, D/E, margins,
# growth, beta, ROE, ROA) is dimensionless and must pass through as-is;
# running it through lakh/crore conversion would misrepresent a ratio as
# a rupee figure.
RUPEE_METRICS = {"marketCap"}
SHARE_COUNT_METRICS = {"sharesOutstanding", "floatShares"}


def format_metric_for_prose(metric: str, value: float | None) -> str:
    """The exact string an AI prompt should show for one fundamentals
    metric — Indian-convention prose for the metrics that need it,
    unchanged for everything else (a ratio, percentage, or multiple reads
    correctly as a bare number already)."""
    if metric in RUPEE_METRICS:
        formatted = format_inr_prose(value)
        return formatted if formatted is not None else "unavailable"
    if metric in SHARE_COUNT_METRICS:
        formatted = format_count_prose(value, unit="shares")
        return formatted if formatted is not None else "unavailable"
    return str(value)
