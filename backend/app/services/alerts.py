"""Generates and serves in-app alerts (Build_plan.md §S step 24).

Two sources, both computed from stored data only — no live provider call,
same discipline as every other batch step:

  thesis_challenged  a ThesisEvent the daily eval already wrote. §X.1
                     always intended to "emit an alert" here and deferred
                     it to P2; this is that deferral being paid off.
  watchlist signals  system-chosen notable moves on watchlisted stocks
                     (Screener.md §16). Deliberately four kinds, no
                     user-authored rules, per that section's own "do not
                     implement unnecessary alert complexity in V1".

Generation is idempotent: every alert carries a `dedup_key` unique per
user, and inserts use ON CONFLICT DO NOTHING. Re-running the job — on a
weekend, after a missed-run catch-up, or twice by hand — creates nothing
new.
"""

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Alert, Asset, Thesis, ThesisEvent, ThesisTrigger, WatchlistItem
from app.domain.models import Bar
from app.engines.opportunity import metrics as m
from app.services.corporate_actions import get_stored_corporate_actions_bulk
from app.services.opportunities import calendar_lookback_for, load_universe_bars_with_ids
from app.services.watchlist import _range_stat

logger = logging.getLogger(__name__)

# A one-session move this large is worth surfacing. Deliberately stricter
# than the down_5d screen (5% over five sessions), so no looser notion of
# "notable" enters the app's vocabulary.
PRICE_MOVE_PCT = 5.0

# The exact multiplier app/engines/opportunity/registry.py's
# UnusualVolume screen uses. Two different definitions of "unusual" in one
# product would be worse than either.
UNUSUAL_VOLUME_MULTIPLE = 2.0

# How close to the 52-week extreme counts as being at it. Keyed off
# _range_stat's `position` (0..1 between the window's low and high) rather
# than comparing the close to the high directly — those extremes are
# *intraday* and include today's bar, so a direct comparison would only
# ever fire when a stock closed exactly at its own day's high. Using the
# same figure the watchlist row renders also means the bell can't claim
# "52-week high" beside a position of 0.94 on the same screen.
WEEK52_EDGE = 0.99

# Sessions of history behind the 52-week range. ~252 trading days a year.
WEEK52_BARS = 252

# Most watchlist alerts one user can receive from a single run. Fan-out
# scales with how many stocks a user watches times how many signals fire,
# and peaks on a market-wide selloff — the moment an individual "-6%"
# carries the least information. There's no index price series in the
# schema, so market-relative filtering isn't possible; capping is the
# honest mitigation rather than inventing a benchmark. Thesis alerts are
# never capped: those are the user's own stated conditions.
MAX_WATCHLIST_ALERTS_PER_USER = 8

# Read alerts older than this are swept, so an inbox nobody empties can't
# grow without bound (product_principles.md #9). Unread ones are kept
# however old — deleting something the user never saw would be worse.
RETENTION_DAYS = 90


@dataclass(frozen=True, slots=True)
class AlertGenerationResult:
    thesis_alerts: int = 0
    watchlist_alerts: int = 0
    pruned: int = 0


@dataclass(frozen=True, slots=True)
class _Candidate:
    user_id: int
    asset_id: int
    kind: str
    title: str
    body: str
    dedup_key: str
    as_of: dt.date
    thesis_event_id: int | None = None
    # Only used to rank candidates when a user is over the cap.
    magnitude: float = 0.0


def _insert_candidates(db: Session, candidates: list[_Candidate]) -> int:
    """ON CONFLICT DO NOTHING rather than checking first: a constraint
    violation aborts the whole Postgres transaction, and this runs inside
    the daily job's shared session, so one collision would poison every
    step since the last commit. Same pattern as fundamentals.py and
    sector_index.py."""
    if not candidates:
        return 0
    statement = pg_insert(Alert).values(
        [
            {
                "user_id": c.user_id,
                "asset_id": c.asset_id,
                "kind": c.kind,
                "title": c.title,
                "body": c.body,
                "dedup_key": c.dedup_key,
                "thesis_event_id": c.thesis_event_id,
                "as_of": c.as_of,
            }
            for c in candidates
        ]
    )
    # RETURNING id rather than rowcount: with ON CONFLICT DO NOTHING only
    # the rows that actually inserted come back, which is exactly the
    # count we want to report (and rowcount isn't typed on Result).
    inserted = db.execute(
        statement.on_conflict_do_nothing(
            constraint="uq_alert_user_dedup_key"
        ).returning(Alert.id)
    ).all()
    db.flush()
    return len(inserted)


def _thesis_candidates(db: Session) -> list[_Candidate]:
    """Derived from ThesisEvent rows rather than emitted inside
    run_thesis_eval: that keeps the eval loop — and the eight tests that
    assert on its error counting — completely untouched, and means an
    alert failure can never be mistaken for an evaluation failure.

    Bounded to the last week so restoring an old backup can't resurrect
    years of history as "new".
    """
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=7)
    already_alerted = select(Alert.thesis_event_id).where(Alert.thesis_event_id.is_not(None))
    rows = (
        db.query(ThesisEvent, Thesis, ThesisTrigger, Asset)
        .join(Thesis, Thesis.id == ThesisEvent.thesis_id)
        .join(ThesisTrigger, ThesisTrigger.id == ThesisEvent.trigger_id)
        .join(Asset, Asset.id == Thesis.asset_id)
        .filter(
            ThesisEvent.fired_at >= cutoff,
            ThesisEvent.id.not_in(already_alerted),
        )
        .all()
    )

    candidates = []
    for event, thesis, trigger, asset in rows:
        observed = (
            f"{float(event.observed_value):g}" if event.observed_value is not None else "n/a"
        )
        candidates.append(
            _Candidate(
                user_id=thesis.user_id,
                asset_id=thesis.asset_id,
                kind="thesis_challenged",
                title=f"{asset.symbol}: a trigger on your thesis fired",
                body=(
                    f'"{thesis.title}" — {trigger.metric} {trigger.operator} '
                    f"{float(trigger.threshold):g}, observed {observed}."
                ),
                dedup_key=f"thesis_event:{event.id}",
                as_of=event.fired_at.date(),
                thesis_event_id=event.id,
            )
        )
    return candidates


def _signals_for(
    bars: list[Bar], *, has_action_on_latest_bar: bool
) -> list[tuple[str, str, float]]:
    """(kind, detail, magnitude) for one asset's bars. Pure apart from the
    corporate-action flag the caller looks up."""
    if not bars:
        return []
    signals: list[tuple[str, str, float]] = []

    change = m.change_pct(bars, 1)
    # app/engines/adjustment.py handles splits and bonuses only — a special
    # dividend or a rights issue leaves a genuine ex-date gap it won't
    # remove, which would surface here as a price move that never happened.
    if change is not None and not has_action_on_latest_bar:
        if change <= -PRICE_MOVE_PCT:
            signals.append(("price_drop", f"fell {abs(change):.1f}% in one session", abs(change)))
        elif change >= PRICE_MOVE_PCT:
            signals.append(("price_surge", f"rose {change:.1f}% in one session", abs(change)))

    rel_volume = m.relative_volume20(bars)
    if rel_volume is not None and rel_volume >= UNUSUAL_VOLUME_MULTIPLE:
        detail = f"traded {rel_volume:.1f}x its 20-session average volume"
        signals.append(("unusual_volume", detail, rel_volume))

    window = bars[-WEEK52_BARS:]
    stat = _range_stat(window, latest_close=bars[-1].close)
    if stat is not None and stat.position is not None:
        if stat.position >= WEEK52_EDGE:
            signals.append(("week52_high", "is at its 52-week high", stat.position))
        elif stat.position <= 1 - WEEK52_EDGE:
            signals.append(("week52_low", "is at its 52-week low", stat.position))

    return signals


def _watchlist_candidates(db: Session) -> list[_Candidate]:
    watchers: dict[int, list[int]] = {}
    for asset_id, user_id in db.query(WatchlistItem.asset_id, WatchlistItem.user_id).all():
        watchers.setdefault(asset_id, []).append(user_id)
    if not watchers:
        return []

    universe, asset_ids = load_universe_bars_with_ids(
        db, calendar_lookback_for(WEEK52_BARS), asset_ids=set(watchers)
    )
    actions_by_asset = get_stored_corporate_actions_bulk(db, list(asset_ids.values()))

    by_user: dict[int, list[_Candidate]] = {}
    for ref, bars in universe.items():
        asset_id = asset_ids[ref]
        if not bars:
            continue
        latest = bars[-1].date
        has_action = any(a.ex_date == latest for a in actions_by_asset.get(asset_id, []))
        for kind, detail, magnitude in _signals_for(bars, has_action_on_latest_bar=has_action):
            for user_id in watchers.get(asset_id, []):
                by_user.setdefault(user_id, []).append(
                    _Candidate(
                        user_id=user_id,
                        asset_id=asset_id,
                        kind=kind,
                        title=f"{ref.symbol} {detail}",
                        body=f"On your watchlist. Session of {latest.isoformat()}.",
                        dedup_key=f"{kind}:{asset_id}:{latest.isoformat()}",
                        as_of=latest,
                        magnitude=magnitude,
                    )
                )

    candidates: list[_Candidate] = []
    for user_candidates in by_user.values():
        user_candidates.sort(key=lambda c: -c.magnitude)
        candidates.extend(user_candidates[:MAX_WATCHLIST_ALERTS_PER_USER])
    return candidates


def _prune_old_read_alerts(db: Session) -> int:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=RETENTION_DAYS)
    deleted = (
        db.query(Alert)
        .filter(Alert.read_at.is_not(None), Alert.read_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.flush()
    return deleted


def generate_alerts(db: Session) -> AlertGenerationResult:
    """Idempotent: safe to run repeatedly. Flushes but does not commit —
    the caller (app/jobs/daily_ingestion.py) owns the transaction, same as
    every other step."""
    thesis_written = _insert_candidates(db, _thesis_candidates(db))
    watchlist_written = _insert_candidates(db, _watchlist_candidates(db))
    pruned = _prune_old_read_alerts(db)
    return AlertGenerationResult(
        thesis_alerts=thesis_written, watchlist_alerts=watchlist_written, pruned=pruned
    )


def list_alerts(
    db: Session, user_id: int, *, unread_only: bool = False, limit: int = 50
) -> list[Alert]:
    query = db.query(Alert).filter(Alert.user_id == user_id)
    if unread_only:
        query = query.filter(Alert.read_at.is_(None))
    return query.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit).all()


def unread_count(db: Session, user_id: int) -> int:
    return (
        db.query(Alert).filter(Alert.user_id == user_id, Alert.read_at.is_(None)).count()
    )


def mark_all_read(db: Session, user_id: int) -> int:
    """Marks, never deletes: the row is also the record that this alert
    was already generated, so removing it would let the next run recreate
    it."""
    updated = (
        db.query(Alert)
        .filter(Alert.user_id == user_id, Alert.read_at.is_(None))
        .update({Alert.read_at: dt.datetime.now(dt.UTC)}, synchronize_session=False)
    )
    db.flush()
    return updated
