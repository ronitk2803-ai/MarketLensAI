"""Corporate-actions provider via NSE's own `corporates-corporateActions`
JSON endpoint (Build_plan.md §6/§F — the documented **primary** source;
`yfinance_actions.py` was the fallback because this endpoint was believed
unreachable).

That belief is now stale. `yfinance_actions.py`'s docstring records a
TLS-level reset against `www.nseindia.com` verified live 2026-08-23 or
earlier. Re-verified live 2026-08-29 via the same `httpx.Client` this
codebase actually uses (not a browser, not curl-with-cookie-priming): the
homepage still 403s, but the JSON API itself answers 200 directly, no
session/cookie primer needed, for both the whole-market bulk query
(`index=equities`, no `symbol`) and a single-symbol query. Whatever blocked
it earlier — a since-lifted IP-level rule, a transient Akamai rule change —
isn't blocking it now. This is treated as a fact about today, not a
permanent guarantee: every call here is wrapped in `ProviderError` so
`app/services/corporate_actions.py` falls back to yfinance the moment NSE
blocks again, exactly per the registry's ordered-fallback design.

**This is why §U.11 exists.** Measured against this endpoint, live: BAJFINANCE's
missing "4:1 bonus" (2025-06-16), ABFRL's and VEDL's demergers, 360ONE's
missing bonus+split, BAJAJFINSV's missing bonus and SIEMENS's demerger are
all present here, at the exact dates the historical-falls panel flagged as
suspect. Yahoo's `.actions` never carried them — it round-trips through a
different data pipeline than the exchange's own filings.

**Bulk-shaped, like `nse_bhavcopy.py`, not per-instrument-shaped like
Upstox.** One request with `index=equities` and a date range returns every
listed company's actions in that window — ~12,300 rows for a 5-year span
observed live — so a full-universe refresh is one HTTP call, not 500.
`get_corporate_actions` below still offers the single-asset shape (the
`symbol=` parameter works too) so this drops into
`get_or_fetch_corporate_actions`'s existing per-asset interface unchanged;
the bulk path is `fetch_actions_bulk`, used by the batch ingestion callers.

**Classification is conservative by construction — see `classify_subject`.**
`subject` is free text a human wrote for a filing, not a structured ratio
field, and this app's one unbreakable rule is "never fabricate, never
silently mis-adjust" (`Build_plan.md` §U.6, `app/engines/adjustment.py`'s
own docstring). So a row is only ever typed `"split"` or `"bonus"` — the
two types `adjustment.py`'s `ADJUSTABLE_ACTION_TYPES` actually apply a
price/share factor to — when a concrete ratio was parsed from unambiguous
text. A face-value split's ratio comes straight from the stated
"From Rs X To Rs Y" (exact, no convention to guess); a bonus ratio comes
from the market-standard "N:M" = N new shares per M held (so "1:1" halves
the price, matching this codebase's existing `ratio=2.0` convention — see
`app/db/models.py`'s `CorporateAction` docstring). Anything that *reads*
like a split/bonus but doesn't parse cleanly is typed `"other"`, not
`"split"`/`"bonus"` — recording a wrong type here would make
`adjustment.py` skip it (safe) but would also make the frontend's
`EXPLAINED_ACTION_TYPES` allowlist (`HistoricalEventsPanel.tsx`) wrongly
call it "explained" when it was never actually adjusted. A demerger,
amalgamation, scheme of arrangement or capital reduction is typed
`"demerger"` and a rights issue `"rights"` — deliberately never adjusted
(no price-ratio model for either exists here, matching `adjustment.py`'s
own stated reasoning for excluding rights), but now *recorded*, which is
the actual fix: the historical-falls panel's `unexplainedActionsInsideFalls`
already flags any type outside `{"split","bonus","dividend"}` as suspect —
today it had nothing to flag because these rows didn't exist at all. Pure
calendar noise (AGM, board meetings, postal ballots, interest payments on
bonds) is dropped entirely rather than stored as `"other"` — it has no
price effect and would just be table noise the UI has to filter past.
"""

import datetime as dt
import re

import httpx

from app.domain.models import AssetRef, CorporateActionEvent
from app.providers.errors import ProviderError

ACTIONS_URL = "https://www.nseindia.com/api/corporates-corporateActions"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
_DATE_FMT_NSE = "%d-%m-%Y"  # request params
_DATE_FMT_ROW = "%d-%b-%Y"  # response rows, e.g. "16-Jun-2025"

_DEMERGER_RE = re.compile(
    r"(?i)demerger|scheme of arrangement|amalgamation|merger|reduction of capital"
)
_RIGHTS_RE = re.compile(r"(?i)rights issue|rights\b")
_BONUS_RE = re.compile(r"(?i)bonus.*?(\d+)\s*:\s*(\d+)")
_FACE_VALUE_SPLIT_RE = re.compile(
    r"(?i)from\s+r[es]?\.?\s*([\d.]+).*?to\s+r[es]?\.?\s*([\d.]+)"
)
_SPLIT_KEYWORD_RE = re.compile(r"(?i)split|sub-division|sub division")
_DIVIDEND_RE = re.compile(r"(?i)dividend")
_DIVIDEND_AMOUNT_RE = re.compile(r"(?i)rs\.?\s*([\d.]+)\s*per\s*share")


def classify_subject(subject: str) -> tuple[str, float | None, float | None] | None:
    """`(type, ratio, amount)`, or `None` to drop the row entirely (AGM,
    board meeting, interest payment, and anything else with no price
    effect). See the module docstring for why each branch is ordered and
    guarded the way it is."""
    text = subject.strip()
    if not text:
        return None

    if _DEMERGER_RE.search(text):
        return "demerger", None, None
    if _RIGHTS_RE.search(text):
        return "rights", None, None

    bonus_match = _BONUS_RE.search(text)
    if bonus_match:
        new, held = int(bonus_match.group(1)), int(bonus_match.group(2))
        if held > 0:
            return "bonus", (new + held) / held, None
        return "other", None, None

    split_match = _FACE_VALUE_SPLIT_RE.search(text)
    if split_match:
        old_face, new_face = float(split_match.group(1)), float(split_match.group(2))
        if new_face > 0:
            return "split", old_face / new_face, None
        return "other", None, None
    if _SPLIT_KEYWORD_RE.search(text):
        # Reads like a split but no clean "From Rs X To Rs Y" — never guess
        # a ratio; "other" keeps adjustment.py from skipping-as-if-explained
        # (it already skips any row with ratio=None) while still making the
        # frontend flag it as unexplained rather than silently "handled".
        return "other", None, None

    if _DIVIDEND_RE.search(text):
        amount_match = _DIVIDEND_AMOUNT_RE.search(text)
        amount = float(amount_match.group(1)) if amount_match else None
        return "dividend", None, amount

    return None


def _parse_ex_date(raw: str) -> dt.date | None:
    raw = raw.strip()
    if not raw or raw == "-":
        return None
    try:
        return dt.datetime.strptime(raw, _DATE_FMT_ROW).date()
    except ValueError:
        return None


def _fetch_raw(
    params: dict[str, str], *, client: httpx.Client | None = None
) -> list[dict]:
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0, headers=_HEADERS)
    try:
        response = client.get(ACTIONS_URL, params=params)
    except httpx.HTTPError as error:
        raise ProviderError("nse_actions", f"request failed: {error}", retryable=True) from error
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        raise ProviderError(
            "nse_actions",
            f"actions fetch failed: {response.status_code}",
            retryable=response.status_code >= 500,
        )
    try:
        return response.json()
    except ValueError as error:
        raise ProviderError("nse_actions", f"non-JSON response: {error}") from error


def fetch_actions_bulk(
    from_date: dt.date, to_date: dt.date, *, client: httpx.Client | None = None
) -> dict[str, list[CorporateActionEvent]]:
    """Every NSE-listed equity's actions in `[from_date, to_date]`, one HTTP
    call, grouped by NSE symbol. Rows with no confident classification
    (`classify_subject` returning `None`) or an unparseable `exDate` are
    dropped, not fabricated into a row."""
    rows = _fetch_raw(
        {
            "index": "equities",
            "from_date": from_date.strftime(_DATE_FMT_NSE),
            "to_date": to_date.strftime(_DATE_FMT_NSE),
        },
        client=client,
    )
    by_symbol: dict[str, list[CorporateActionEvent]] = {}
    for row in rows:
        ex_date = _parse_ex_date(row.get("exDate", ""))
        classification = classify_subject(row.get("subject", ""))
        symbol = row.get("symbol", "").strip()
        if ex_date is None or classification is None or not symbol:
            continue
        action_type, ratio, amount = classification
        by_symbol.setdefault(symbol, []).append(
            CorporateActionEvent(type=action_type, ex_date=ex_date, ratio=ratio, amount=amount)
        )
    for events in by_symbol.values():
        events.sort(key=lambda e: e.ex_date)
    return by_symbol


class NSECorporateActionsProvider:
    """Single-asset shape, for interface parity with
    `YFinanceCorporateActionsProvider` — used by the lazy on-demand path
    (`get_or_fetch_corporate_actions`) where fetching the whole market for
    one page view would be wasteful. Batch ingestion should call
    `fetch_actions_bulk` directly instead."""

    name = "nse_actions"

    # Wide enough to predate `price_ohlcv`'s earliest stored bar
    # (2021-08-25 — Build_plan.md §U.3) with margin; actions before the
    # priced history begins can't affect any stored bar anyway.
    _DEFAULT_FROM = dt.date(2020, 1, 1)

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def get_corporate_actions(self, asset: AssetRef) -> list[CorporateActionEvent]:
        if asset.exchange != "NSE":
            raise ProviderError("nse_actions", f"unsupported exchange: {asset.exchange}")
        rows = _fetch_raw(
            {
                "index": "equities",
                "symbol": asset.symbol,
                "from_date": self._DEFAULT_FROM.strftime(_DATE_FMT_NSE),
                "to_date": dt.date.today().strftime(_DATE_FMT_NSE),
            },
            client=self._client,
        )
        events = []
        for row in rows:
            ex_date = _parse_ex_date(row.get("exDate", ""))
            classification = classify_subject(row.get("subject", ""))
            if ex_date is None or classification is None:
                continue
            action_type, ratio, amount = classification
            events.append(
                CorporateActionEvent(type=action_type, ex_date=ex_date, ratio=ratio, amount=amount)
            )
        return sorted(events, key=lambda e: e.ex_date)
