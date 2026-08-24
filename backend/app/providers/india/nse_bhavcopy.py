"""NSE Bhavcopy (`sec_bhavdata_full`) provider — the auth-free, unattended
EOD price spine + delivery % (Build_plan.md §G/§H; verified live 2026-08-23).

No auth, no token lifecycle: this is what guarantees the daily ingestion
pipeline survives an Upstox token lapse. One file per trading day covers
the *whole* exchange, unlike Upstox's one-instrument-per-request historical
API — so this provider is batch-shaped, not single-asset-shaped. A 404 for
a given date means no trading session that day (weekend/holiday), not a
transient error to retry.
"""

import csv
import datetime as dt
import io
from dataclasses import dataclass

import httpx

from app.domain.models import AssetRef, Bar, CorporateActionEvent, Quote
from app.providers.errors import ProviderError

BHAVCOPY_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"

# NSE series that represent ordinary equity trading (excludes gilts, T-bills, etc.)
EQUITY_SERIES = {"EQ", "BE"}


@dataclass(frozen=True, slots=True)
class BhavcopyRow:
    symbol: str
    series: str
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int
    delivery_qty: int | None
    delivery_pct: float | None


def fetch_bhavcopy_raw(date: dt.date, *, client: httpx.Client | None = None) -> str | None:
    """Raw CSV text for `date`, or None if there was no trading session that day."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        response = client.get(BHAVCOPY_URL.format(date=date.strftime("%d%m%Y")))
    finally:
        if owns_client:
            client.close()

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ProviderError("nse_bhavcopy", f"bhavcopy fetch failed: {response.status_code}")
    return response.text


def _parse_int(raw: str) -> int | None:
    raw = raw.strip()
    return None if raw in ("-", "") else int(raw)


def _parse_float(raw: str) -> float | None:
    raw = raw.strip()
    return None if raw in ("-", "") else float(raw)


def parse_bhavcopy(raw_csv: str) -> list[BhavcopyRow]:
    # Verified live on a 5-year backfill: NSE's archive served 2022-08-08's
    # file as a genuine .xlsx (an Office Open XML zip) with a `text/csv`
    # Content-Type and a `.csv` URL, rather than the plain CSV every
    # neighbouring day gets. Handed to `csv.DictReader`, the binary zip
    # bytes surfaced as an opaque "new-line character seen in unquoted
    # field" — the true cause (a mislabelled response) is unrecoverable
    # from that message alone, so it's detected explicitly here instead of
    # left for the CSV parser to fail on cryptically.
    if raw_csv.startswith("PK\x03\x04"):
        raise ProviderError(
            "nse_bhavcopy",
            "response is a zip/xlsx archive, not CSV — NSE mislabelled this file",
        )
    reader = csv.DictReader(io.StringIO(raw_csv), skipinitialspace=True)
    rows = []
    for record in reader:
        series = record["SERIES"].strip()
        if series not in EQUITY_SERIES:
            continue
        rows.append(
            BhavcopyRow(
                symbol=record["SYMBOL"].strip(),
                series=series,
                date=dt.datetime.strptime(record["DATE1"].strip(), "%d-%b-%Y").date(),
                open=float(record["OPEN_PRICE"]),
                high=float(record["HIGH_PRICE"]),
                low=float(record["LOW_PRICE"]),
                close=float(record["CLOSE_PRICE"]),
                volume=int(record["TTL_TRD_QNTY"]),
                delivery_qty=_parse_int(record["DELIV_QTY"]),
                delivery_pct=_parse_float(record["DELIV_PER"]),
            )
        )
    return rows


class NSEBhavcopyProvider:
    """Batch-shaped: `get_day_bars` (below) is the intended path for the daily
    ingestion job. `get_ohlcv` exists for `MarketDataProvider` conformance —
    it re-fetches one whole-exchange file per day in the range and filters
    to one symbol, which is fine for occasional single-asset fallback but
    not how the universe-wide job should use this provider.
    """

    name = "nse_bhavcopy"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def get_day_bars(self, date: dt.date) -> list[BhavcopyRow]:
        """All equity-series rows for one trading day, or [] if markets were closed.

        NSE's archive quietly serves the *last available* session's file for
        a same-day/future request instead of 404ing (verified live) — filter
        to an exact date match on each row's own `DATE1` rather than trust
        the URL, so a weekend/holiday `date` reliably returns [].
        """
        raw = fetch_bhavcopy_raw(date, client=self._client)
        if raw is None:
            return []
        return [row for row in parse_bhavcopy(raw) if row.date == date]

    def get_universe(self, index: str) -> list[AssetRef]:
        raise NotImplementedError(
            "NSE Bhavcopy has no index membership — use the NSE index CSV provider"
        )

    def get_ohlcv(self, asset: AssetRef, start: dt.date, end: dt.date, interval: str) -> list[Bar]:
        if interval != "day":
            raise ProviderError("nse_bhavcopy", f"unsupported interval: {interval!r} (EOD-only)")

        bars = []
        current = start
        while current <= end:
            for row in self.get_day_bars(current):
                if row.symbol == asset.symbol:
                    bars.append(
                        Bar(
                            date=row.date,
                            open=row.open,
                            high=row.high,
                            low=row.low,
                            close=row.close,
                            volume=row.volume,
                            delivery_qty=row.delivery_qty,
                            delivery_pct=row.delivery_pct,
                        )
                    )
                    break
            current += dt.timedelta(days=1)
        return bars

    def get_quote(self, assets: list[AssetRef]) -> dict[str, Quote]:
        raise NotImplementedError("Bhavcopy is EOD-only — no live quotes")

    def get_corporate_actions(self, asset: AssetRef) -> list[CorporateActionEvent]:
        raise NotImplementedError(
            "Corporate actions come from the NSE corporate-actions feed, not Bhavcopy"
        )
