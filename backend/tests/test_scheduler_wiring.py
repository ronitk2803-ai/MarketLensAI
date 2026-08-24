"""Guards the one piece of this system that runs with nobody watching.

The scheduler is what keeps the deployment fresh after launch day, and its
failure mode is silence — a wrong flag or a mistimed cron doesn't raise, it
just means the data quietly stops updating. These assert the wiring rather
than waiting on a clock.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.main as main


class _SpyScheduler:
    """Stands in for BackgroundScheduler and records what it was asked to do."""

    instances: list["_SpyScheduler"] = []

    def __init__(self, timezone: object = None) -> None:
        self.timezone = timezone
        self.jobs: list[dict] = []
        self.started = False
        self.shutdown_called = False
        _SpyScheduler.instances.append(self)

    def add_job(self, func: object, **kwargs: object) -> None:
        self.jobs.append({"func": func, **kwargs})

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_called = True


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> type[_SpyScheduler]:
    _SpyScheduler.instances = []
    monkeypatch.setattr(main, "BackgroundScheduler", _SpyScheduler)
    return _SpyScheduler


def test_scheduler_is_off_by_default(
    spy: type[_SpyScheduler], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing the app must not start an unattended batch job.

    Every test in this suite builds a TestClient, and a scheduler that
    defaulted to on would have each of them firing ingestion at the real
    database.
    """
    monkeypatch.setattr(main.settings, "enable_scheduler", False)

    with TestClient(main.app):
        pass

    assert spy.instances == []


def test_enabling_the_scheduler_registers_the_daily_job(
    spy: type[_SpyScheduler], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main.settings, "enable_scheduler", True)
    monkeypatch.setattr(main.settings, "daily_ingestion_hour_ist", 20)

    with TestClient(main.app):
        assert len(spy.instances) == 1
        scheduler = spy.instances[0]
        assert scheduler.started

        job = scheduler.jobs[0]
        assert job["func"] is main._run_daily_ingestion_job
        assert job["trigger"] == "cron"
        assert job["hour"] == 20
        assert job["minute"] == 0


def test_the_job_is_scheduled_in_ist_not_the_host_timezone(
    spy: type[_SpyScheduler], monkeypatch: pytest.MonkeyPatch
) -> None:
    """20:00 has to mean 20:00 in Mumbai.

    NSE publishes Bhavcopy after the Indian close, so the hour is chosen
    relative to that market. A container running on UTC (every platform in
    the runbook does) would otherwise fire at 20:00 UTC — 01:30 IST the
    next morning, ingesting before the day it was meant to cover existed.
    """
    monkeypatch.setattr(main.settings, "enable_scheduler", True)

    with TestClient(main.app):
        assert spy.instances[0].timezone == ZoneInfo("Asia/Kolkata")


def test_the_configured_hour_is_honoured(
    spy: type[_SpyScheduler], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main.settings, "enable_scheduler", True)
    monkeypatch.setattr(main.settings, "daily_ingestion_hour_ist", 6)

    with TestClient(main.app):
        assert spy.instances[0].jobs[0]["hour"] == 6


def test_a_missed_run_still_fires_within_the_grace_window(
    spy: type[_SpyScheduler], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A redeploy or a brief restart across 20:00 must not skip the day.

    APScheduler drops a misfired run unless misfire_grace_time allows it,
    which would leave a silent one-day hole in prices and scores.
    """
    monkeypatch.setattr(main.settings, "enable_scheduler", True)

    with TestClient(main.app):
        assert spy.instances[0].jobs[0]["misfire_grace_time"] >= 3600


def test_the_scheduler_is_shut_down_with_the_app(
    spy: type[_SpyScheduler], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main.settings, "enable_scheduler", True)

    with TestClient(main.app):
        pass

    assert spy.instances[0].shutdown_called


def test_a_failing_run_does_not_escape_the_scheduled_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception reaching APScheduler kills that job's future runs.

    The callable has to swallow and log instead, so one bad night (a Yahoo
    outage, a delisted ticker) doesn't silently end all ingestion until
    somebody notices the data is stale.
    """

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated ingestion failure")

    monkeypatch.setattr("app.jobs.daily_ingestion.run_daily_ingestion", boom)

    main._run_daily_ingestion_job()  # must not raise


def test_the_ist_hour_maps_to_the_expected_utc_instant() -> None:
    """Pins the intent behind the default: 20:00 IST is 14:30 UTC, after the
    15:30 IST close and after Bhavcopy is published."""
    ist_2000 = dt.datetime(2026, 8, 24, 20, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert ist_2000.astimezone(dt.UTC).strftime("%H:%M") == "14:30"
