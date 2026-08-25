"""Cache-first reads of NSE's daily sectoral-index P/E (see
app/providers/india/nse_sector_pe.py for why this is the authoritative
source, and app/services/fundamentals.py's get_sector_ratio_stats for the
per-company-median fallback used where no mapping exists below).

One HTTP call refreshes every index at once — unlike fundamentals, which
are fetched per company on that company's own page view, this is fetched
once and read by every company in every mapped industry, so there's no
per-page-view cost to worry about.
"""

import datetime as dt

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import SectorIndexPe
from app.providers.errors import ProviderError
from app.providers.india.nse_sector_pe import fetch_latest_index_pe

SOURCE = "nse_sector_pe"

# NSE publishes this file once per trading day; refetching within the same
# day would just get the same numbers back. A generous same-day window
# (not a strict 24h) means the first read after each morning's daily
# ingestion run picks up the new file rather than waiting out a rolling
# window from whenever it was last fetched.
SECTOR_PE_TTL = dt.timedelta(hours=20)

# This app's industry taxonomy (app/db/models.py Industry, sourced from
# NSE's own nifty500 constituent CSV) doesn't perfectly line up with NSE's
# separate sectoral-index naming — most map cleanly, but "Diversified" (a
# classification for conglomerates spanning multiple sectors, not a
# sector itself) and "Textiles" (no official Nifty sectoral index exists
# for it) have nothing to map to. Left out on purpose rather than guessed
# at — those two industries fall back to the per-company median instead
# (app/api/v1/companies.py's get_fundamentals).
INDUSTRY_TO_NIFTY_INDEX: dict[str, str] = {
    "automobile-and-auto-components": "Nifty Auto",
    "capital-goods": "Nifty Capital Goods",
    "chemicals": "Nifty Chemicals",
    "construction": "Nifty Construction",
    "construction-materials": "Nifty Cement",
    "consumer-durables": "Nifty Consumer Durables",
    "consumer-services": "Nifty Consumer Services",
    "fast-moving-consumer-goods": "Nifty FMCG",
    "financial-services": "Nifty Financial Services",
    "healthcare": "Nifty Healthcare Index",
    "information-technology": "Nifty IT",
    "media-entertainment-publication": "Nifty Media",
    "metals-mining": "Nifty Metal",
    "oil-gas-consumable-fuels": "Nifty Oil & Gas",
    "power": "Nifty Power",
    "realty": "Nifty Realty",
    "services": "Nifty Services Sector",
    "telecommunication": "Nifty Telecommunications",
}


def _is_stale(rows: list[SectorIndexPe]) -> bool:
    if not rows:
        return True
    newest = max(r.as_of for r in rows)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=dt.UTC)
    return (dt.datetime.now(dt.UTC) - newest) >= SECTOR_PE_TTL


def get_or_fetch_sector_index_pe(db: Session) -> dict[str, SectorIndexPe]:
    """Every cached index row, keyed by index name."""
    rows = db.query(SectorIndexPe).all()
    if rows and not _is_stale(rows):
        return {r.index_name: r for r in rows}

    try:
        fetched = fetch_latest_index_pe()
    except ProviderError:
        # Stale-but-real beats nothing — same reasoning as
        # get_or_fetch_ratios: a transient NSE hiccup on the refresh
        # attempt must not blank out yesterday's perfectly good figures.
        return {r.index_name: r for r in rows}

    rows_to_write = [
        {
            "index_name": r.index_name,
            "pe": r.pe,
            "pb": r.pb,
            "div_yield": r.div_yield,
            "index_date": r.index_date,
        }
        for r in fetched
    ]
    if rows_to_write:
        statement = pg_insert(SectorIndexPe).values(rows_to_write)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["index_name"],
                set_={
                    "pe": statement.excluded.pe,
                    "pb": statement.excluded.pb,
                    "div_yield": statement.excluded.div_yield,
                    "index_date": statement.excluded.index_date,
                    "as_of": func.now(),
                },
            )
        )
        db.flush()
        # Raw-SQL upsert bypasses the identity map — see the matching
        # comment in get_or_fetch_ratios for why this matters.
        db.expire_all()
    return {r.index_name: r for r in db.query(SectorIndexPe).all()}


def get_sector_pe_for_industry(db: Session, industry_code: str | None) -> SectorIndexPe | None:
    """None whenever there's no official Nifty sectoral index for this
    industry (see INDUSTRY_TO_NIFTY_INDEX) or NSE hasn't published data
    for it — never a fabricated or zeroed-out figure."""
    if industry_code is None:
        return None
    nifty_index_name = INDUSTRY_TO_NIFTY_INDEX.get(industry_code)
    if nifty_index_name is None:
        return None
    return get_or_fetch_sector_index_pe(db).get(nifty_index_name)
