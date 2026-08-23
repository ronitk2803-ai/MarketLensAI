from sqlalchemy.orm import Session

from app.providers.fetch_log import record_fetch


def test_record_fetch_roundtrip(db: Session) -> None:
    log = record_fetch(
        db,
        provider="upstox",
        endpoint="get_ohlcv",
        status="success",
        latency_ms=142,
        ttl_seconds=86_400,
    )

    assert log.id is not None
    assert log.status == "success"
    assert log.asset_id is None


def test_record_fetch_error_status(db: Session) -> None:
    log = record_fetch(db, provider="upstox", endpoint="get_quote", status="error")

    assert log.status == "error"
    assert log.latency_ms is None
