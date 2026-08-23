"""Provider capability interfaces (Build_plan.md §F).

Four capabilities; each market registers an ordered [primary, fallback, ...]
list of implementations behind these Protocols (see registry.py). No
capability here talks to a database or references India specifically —
that's what keeps a dead source a one-class fix instead of a rewrite.
"""

import datetime as dt
from typing import Protocol

from app.domain.models import (
    Article,
    AssetRef,
    Bar,
    CompanyProfile,
    CorporateActionEvent,
    Quote,
    Ratios,
    Statements,
)


class MarketDataProvider(Protocol):
    def get_universe(self, index: str) -> list[AssetRef]: ...

    def get_ohlcv(
        self, asset: AssetRef, start: dt.date, end: dt.date, interval: str
    ) -> list[Bar]: ...

    def get_quote(self, assets: list[AssetRef]) -> dict[str, Quote]: ...

    def get_corporate_actions(self, asset: AssetRef) -> list[CorporateActionEvent]: ...


class FundamentalDataProvider(Protocol):
    def get_statements(self, asset: AssetRef, period: str) -> Statements: ...

    def get_ratios(self, asset: AssetRef) -> Ratios: ...


class NewsProvider(Protocol):
    def get_news(self, target: AssetRef, since: dt.datetime) -> list[Article]: ...


class CompanyDataProvider(Protocol):
    def get_profile(self, asset: AssetRef) -> CompanyProfile: ...
