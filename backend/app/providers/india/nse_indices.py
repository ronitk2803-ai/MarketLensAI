"""NSE index-constituent provider — the Nifty 500 universe definition
(Build_plan.md §F `get_universe(index)`, API_Sources.md §2 "Primary";
verified live 2026-08-24).

Auth-free static CSV on the same archives host as Bhavcopy, so it shares
that provider's reliability profile rather than the bot-protected
www.nseindia.com APIs. One file per index, refreshed by NSE on rebalance —
API_Sources.md §2 calls for a monthly refresh, not a daily one.

The CSV also carries each constituent's Industry, which is the designated
source for sector classification. It is parsed and returned here; wiring it
through to `company.industry_id` is separate work and not done yet.
"""

import csv
import io
from dataclasses import dataclass

import httpx

from app.domain.models import AssetRef
from app.providers.errors import ProviderError

INDEX_CSV_URL = "https://archives.nseindia.com/content/indices/{filename}"

# Index id -> NSE's filename. Sector indices (API_Sources.md §2, for
# relative-strength-vs-sector) drop in here as one line each.
INDEX_FILES: dict[str, str] = {
    "nifty500": "ind_nifty500list.csv",
    "nifty50": "ind_nifty50list.csv",
}

# NSE series representing ordinary equity trading, mirroring nse_bhavcopy.
EQUITY_SERIES = {"EQ", "BE"}


@dataclass(frozen=True, slots=True)
class IndexConstituent:
    symbol: str
    name: str
    industry: str | None
    isin: str | None
    series: str

    def to_asset_ref(self) -> AssetRef:
        return AssetRef(
            symbol=self.symbol,
            exchange="NSE",
            market="IN",
            name=self.name,
            isin=self.isin,
        )


def fetch_index_constituents_raw(index: str, *, client: httpx.Client | None = None) -> str:
    filename = INDEX_FILES.get(index)
    if filename is None:
        raise ProviderError("nse_indices", f"unknown index {index!r}")

    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        response = client.get(
            INDEX_CSV_URL.format(filename=filename),
            # The archives host serves the CSV to a plain client, but a
            # default httpx UA occasionally trips the edge; Bhavcopy has the
            # same characteristic.
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        raise ProviderError(
            "nse_indices", f"index constituents fetch failed: {response.status_code}"
        )
    return response.text


def parse_index_constituents(raw_csv: str) -> list[IndexConstituent]:
    """Columns: Company Name, Industry, Symbol, Series, ISIN Code."""
    reader = csv.DictReader(io.StringIO(raw_csv))
    constituents: list[IndexConstituent] = []
    for row in reader:
        symbol = (row.get("Symbol") or "").strip()
        if not symbol:
            continue
        series = (row.get("Series") or "").strip()
        if series and series not in EQUITY_SERIES:
            continue
        industry = (row.get("Industry") or "").strip() or None
        isin = (row.get("ISIN Code") or "").strip() or None
        constituents.append(
            IndexConstituent(
                symbol=symbol,
                name=(row.get("Company Name") or "").strip(),
                industry=industry,
                isin=isin,
                series=series,
            )
        )
    if not constituents:
        raise ProviderError("nse_indices", "index constituents CSV parsed to zero rows")
    return constituents


class NSEIndexProvider:
    """Implements the `get_universe(index)` capability of MarketDataProvider."""

    def get_constituents(
        self, index: str = "nifty500", *, client: httpx.Client | None = None
    ) -> list[IndexConstituent]:
        return parse_index_constituents(fetch_index_constituents_raw(index, client=client))

    def get_universe(self, index: str = "nifty500") -> list[AssetRef]:
        return [c.to_asset_ref() for c in self.get_constituents(index)]
