"""Corporate-actions provider via Yahoo Finance's public chart API
(Build_plan.md §6 — `yfinance` fallback/cross-check tier).

NSE's own corporate-actions JSON API (www.nseindia.com) is blocked by
Akamai bot protection at the connection level from this environment
(verified live — TLS-level reset before any request completes), consistent
with Build_plan.md §12's note that NSE is "friendlier to in-country IPs."
Yahoo's chart API — what the `yfinance` Python library wraps — is the
documented fallback and is reachable; called directly via httpx here to
avoid the extra dependency for one endpoint.

Reconciliation against NSE (Build_plan.md §6: "a mismatch blocks adjustment
until resolved") isn't implemented — there's nothing to reconcile against
until an NSE-reachable deployment exists. Single-source for now; flagged,
not silently pretended away.

Yahoo also doesn't distinguish a face-value stock split from a bonus issue
(both are just a numerator/denominator ratio to it) — both are reported
here as `type="split"`.
"""

import datetime as dt

import httpx

from app.domain.models import AssetRef, CorporateActionEvent
from app.providers.errors import ProviderError

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; mlai-data-pipeline/1.0)"}


def _yahoo_symbol(asset: AssetRef) -> str:
    if asset.exchange != "NSE":
        raise ProviderError("yfinance_actions", f"unsupported exchange: {asset.exchange}")
    return f"{asset.symbol}.NS"


def fetch_actions_raw(asset: AssetRef, *, client: httpx.Client | None = None) -> dict:
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0, headers=_HEADERS)
    try:
        response = client.get(
            CHART_URL.format(symbol=_yahoo_symbol(asset)),
            params={"range": "max", "interval": "1d", "events": "div,splits"},
        )
    finally:
        if owns_client:
            client.close()
    if response.status_code != 200:
        raise ProviderError("yfinance_actions", f"chart fetch failed: {response.status_code}")

    body = response.json()
    error = body.get("chart", {}).get("error")
    if error:
        raise ProviderError("yfinance_actions", f"chart API error: {error}")
    return body


def parse_actions(body: dict) -> list[CorporateActionEvent]:
    result = body["chart"]["result"][0]
    events = result.get("events", {})

    actions = []
    for split in events.get("splits", {}).values():
        denominator = split["denominator"]
        if not denominator:
            continue
        actions.append(
            CorporateActionEvent(
                type="split",
                ex_date=dt.datetime.fromtimestamp(split["date"], tz=dt.UTC).date(),
                ratio=split["numerator"] / denominator,
            )
        )
    for dividend in events.get("dividends", {}).values():
        actions.append(
            CorporateActionEvent(
                type="dividend",
                ex_date=dt.datetime.fromtimestamp(dividend["date"], tz=dt.UTC).date(),
                amount=dividend["amount"],
            )
        )
    return sorted(actions, key=lambda a: a.ex_date)


class YFinanceCorporateActionsProvider:
    name = "yfinance_actions"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def get_corporate_actions(self, asset: AssetRef) -> list[CorporateActionEvent]:
        body = fetch_actions_raw(asset, client=self._client)
        return parse_actions(body)
