from sqlalchemy.orm import Session

from app.db.models import Asset
from app.services.search import search_assets


def _seed(db: Session) -> None:
    db.add_all(
        [
            Asset(symbol="ZZSEARCH1", exchange="NSE", market="IN", name="Zeta Search Alpha Ltd"),
            Asset(symbol="ZZSEARCH2", exchange="NSE", market="IN", name="Zeta Search Beta Ltd"),
            Asset(
                symbol="ZZSEARCH3",
                exchange="NSE",
                market="IN",
                name="Inactive Co",
                active=False,
            ),
        ]
    )
    db.flush()


def test_search_matches_symbol_prefix(db: Session) -> None:
    _seed(db)
    results = search_assets(db, "ZZSEARCH")
    assert {a.symbol for a in results} == {"ZZSEARCH1", "ZZSEARCH2"}


def test_search_matches_name_case_insensitively(db: Session) -> None:
    _seed(db)
    results = search_assets(db, "zeta search alpha")
    assert [a.symbol for a in results] == ["ZZSEARCH1"]


def test_search_excludes_inactive_assets(db: Session) -> None:
    _seed(db)
    results = search_assets(db, "Inactive Co")
    assert results == []


def test_search_respects_limit(db: Session) -> None:
    _seed(db)
    results = search_assets(db, "ZZSEARCH", limit=1)
    assert len(results) == 1
