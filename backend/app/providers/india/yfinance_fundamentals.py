"""Fundamentals via Yahoo Finance's quoteSummary API (Build_plan.md §7/§H —
yfinance tier: "coverage spotty & inconsistent for India" — confirmed live:
for RELIANCE, income-statement fields beyond totalRevenue/netIncome and
almost all balance-sheet/cash-flow fields come back as an empty-sentinel
`{"raw": 0, "fmt": null}`, not real zeros. Yahoo's own convention for "no
data" is `fmt: null`, even when `raw` shows 0 — treating that as a real
zero would silently fabricate a balance sheet. `_extract` below only
accepts a field when `fmt` is present.

quoteSummary requires an anonymous session cookie + crumb (unlike the plain
chart API used for corporate actions) — this is Yahoo's generic anti-bot
gate applied to every caller, not a personal login; no account or
credentials are involved anywhere in this flow. `yfinance` performs the
same two-step bootstrap internally.
"""

import datetime as dt

import httpx

from app.domain.models import AssetRef, Ratios, Statements
from app.providers.errors import ProviderError

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; mlai-data-pipeline/1.0)"}
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
COOKIE_BOOTSTRAP_URL = "https://fc.yahoo.com"
QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"

RATIO_FIELDS = [
    "debtToEquity",
    "grossMargins",
    "operatingMargins",
    "profitMargins",
    "revenueGrowth",
    "earningsGrowth",
    "returnOnEquity",
    "returnOnAssets",
    "priceToBook",
    "forwardPE",
    "trailingPE",
    "beta",
    "marketCap",
    "sharesOutstanding",
    # "Shares available for trading" — the free float, i.e. shares actually
    # held by the public and tradeable, as opposed to sharesOutstanding
    # (the full share count, including promoter/founder holdings that
    # rarely trade). Verified live across RELIANCE/TCS/INFY/GVT&D/E2E —
    # both fields resolve for companies spanning large- to small-cap.
    "floatShares",
]

STATEMENT_LINE_FIELDS = {
    "income": ["totalRevenue", "netIncome", "grossProfit", "operatingIncome", "ebit"],
    "balance_sheet": [
        "totalAssets",
        "totalLiab",
        "totalStockholderEquity",
        "cash",
        "shortLongTermDebt",
        "longTermDebt",
    ],
    "cash_flow": ["netIncome", "totalCashFromOperatingActivities", "capitalExpenditures"],
}

_MODULE_NAME = {
    ("income", "FY"): "incomeStatementHistory",
    ("income", "Q"): "incomeStatementHistoryQuarterly",
    ("balance_sheet", "FY"): "balanceSheetHistory",
    ("balance_sheet", "Q"): "balanceSheetHistoryQuarterly",
    ("cash_flow", "FY"): "cashflowStatementHistory",
    ("cash_flow", "Q"): "cashflowStatementHistoryQuarterly",
}
_ARRAY_KEY = {
    "income": "incomeStatementHistory",
    "balance_sheet": "balanceSheetStatements",
    "cash_flow": "cashflowStatements",
}


class YahooSession:
    """Caches the anonymous cookie jar + crumb for the process lifetime,
    re-bootstrapping once on a 401 (crumb rotated/expired)."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=15.0, headers=_HEADERS, follow_redirects=True)
        self._crumb: str | None = None

    def _bootstrap(self) -> None:
        self._client.get(COOKIE_BOOTSTRAP_URL)
        response = self._client.get(CRUMB_URL)
        if response.status_code != 200 or not response.text:
            raise ProviderError("yfinance_fundamentals", "failed to obtain Yahoo session crumb")
        self._crumb = response.text

    def get(self, url: str, params: dict) -> httpx.Response:
        if self._crumb is None:
            self._bootstrap()
        response = self._client.get(url, params={**params, "crumb": self._crumb})
        if response.status_code == 401:
            self._bootstrap()
            response = self._client.get(url, params={**params, "crumb": self._crumb})
        return response


def _extract(raw_field: dict | None) -> float | None:
    if not raw_field or raw_field.get("fmt") is None:
        return None
    value = raw_field.get("raw")
    return float(value) if isinstance(value, int | float) else None


def _yahoo_symbol(asset: AssetRef) -> str:
    if asset.exchange != "NSE":
        raise ProviderError("yfinance_fundamentals", f"unsupported exchange: {asset.exchange}")
    return f"{asset.symbol}.NS"


def fetch_quote_summary(asset: AssetRef, modules: list[str], *, session: YahooSession) -> dict:
    response = session.get(
        QUOTE_SUMMARY_URL.format(symbol=_yahoo_symbol(asset)), params={"modules": ",".join(modules)}
    )
    if response.status_code != 200:
        raise ProviderError(
            "yfinance_fundamentals", f"quoteSummary fetch failed: {response.status_code}"
        )

    body = response.json()
    error = body.get("quoteSummary", {}).get("error")
    if error:
        raise ProviderError("yfinance_fundamentals", f"quoteSummary API error: {error}")

    results = body.get("quoteSummary", {}).get("result")
    if not results:
        raise ProviderError("yfinance_fundamentals", "quoteSummary returned no result")
    return results[0]


def parse_ratios(asset: AssetRef, body: dict) -> Ratios:
    financial_data = body.get("financialData", {})
    key_stats = body.get("defaultKeyStatistics", {})
    # Verified live across RELIANCE/TCS/INFY: Yahoo puts trailingPE (the
    # ratio people mean by "P/E ratio" — forwardPE is a different, forward-
    # looking number and was the only one of the two we had) only here, not
    # in financialData or defaultKeyStatistics — it was silently absent from
    # every company's fundamentals panel, not a per-stock coverage gap.
    summary_detail = body.get("summaryDetail", {})
    values = {}
    for field in RATIO_FIELDS:
        # `or`-chaining would treat a genuine 0.0 (a real beta, a real 0%
        # debtToEquity) as falsy and wrongly fall through to the next
        # module's value for the same field — check each source in order
        # and take the first that actually resolved, not the first truthy
        # one.
        value = None
        for source in (financial_data, key_stats, summary_detail):
            value = _extract(source.get(field))
            if value is not None:
                break
        if value is not None:
            values[field] = value
    return Ratios(asset=asset, as_of=dt.date.today(), values=values)


def parse_statements(
    asset: AssetRef, body: dict, statement_type: str, period: str
) -> list[Statements]:
    module_name = _MODULE_NAME[(statement_type, period)]
    array_key = _ARRAY_KEY[statement_type]
    entries = body.get(module_name, {}).get(array_key, [])

    results = []
    for entry in entries:
        end_date_raw = entry.get("endDate", {}).get("raw")
        if end_date_raw is None:
            continue
        line_items = {
            field: value
            for field in STATEMENT_LINE_FIELDS[statement_type]
            if (value := _extract(entry.get(field))) is not None
        }
        if not line_items:
            continue
        results.append(
            Statements(
                asset=asset,
                period_type=period,
                period_end=dt.datetime.fromtimestamp(end_date_raw, tz=dt.UTC).date(),
                statement_type=statement_type,
                line_items=line_items,
            )
        )
    return results


class YFinanceFundamentalDataProvider:
    """Implements `FundamentalDataProvider` for Yahoo Finance."""

    name = "yfinance_fundamentals"

    def __init__(self, *, session: YahooSession | None = None) -> None:
        self._session = session or YahooSession()

    def get_ratios(self, asset: AssetRef) -> Ratios:
        body = fetch_quote_summary(
            asset,
            ["financialData", "defaultKeyStatistics", "summaryDetail"],
            session=self._session,
        )
        return parse_ratios(asset, body)

    def get_statements(self, asset: AssetRef, period: str) -> Statements:
        """Returns the most recent period only. For the full available
        history use `get_all_statements`."""
        statements = self.get_all_statements(asset, "income", period)
        if not statements:
            raise ProviderError(
                "yfinance_fundamentals", f"no income statement data for {asset.symbol}"
            )
        return statements[0]

    def get_all_statements(
        self, asset: AssetRef, statement_type: str, period: str = "FY"
    ) -> list[Statements]:
        if (statement_type, period) not in _MODULE_NAME:
            raise ProviderError(
                "yfinance_fundamentals",
                f"unsupported statement_type/period: {statement_type!r}/{period!r}",
            )
        module_name = _MODULE_NAME[(statement_type, period)]
        body = fetch_quote_summary(asset, [module_name], session=self._session)
        return parse_statements(asset, body, statement_type, period)
