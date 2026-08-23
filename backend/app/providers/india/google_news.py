"""News via Google News RSS, per-company query (Build_plan.md §8 — "Primary
(targeted)" tier; verified live 2026-08-23: real, unauthenticated, no key).

The general market-wide RSS backbone (Moneycontrol/ET/Business Standard/
LiveMint) is also live and free, but those feeds aren't company-scoped —
matching them to a specific asset needs text-matching heuristics that are a
different, broader feature (market-wide news / event detection across the
universe) than this company-page news panel. Out of scope here, not
forgotten.

Google News wraps the true article URL behind its own redirect link (its
RSS doesn't expose the canonical publisher URL directly) — the link still
resolves correctly when opened, so this is a cosmetic limitation, not a
functional one.
"""

import datetime as dt
import hashlib
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from app.domain.models import Article, AssetRef
from app.providers.errors import ProviderError

RSS_URL = "https://news.google.com/rss/search"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; mlai-data-pipeline/1.0)"}
_WHITESPACE = re.compile(r"\s+")


def _dedup_hash(title: str) -> str:
    normalized = _WHITESPACE.sub(" ", title).strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def fetch_news_raw(query: str, *, client: httpx.Client | None = None) -> bytes:
    owns_client = client is None
    client = client or httpx.Client(timeout=15.0, headers=_HEADERS)
    try:
        response = client.get(
            RSS_URL, params={"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
        )
    finally:
        if owns_client:
            client.close()
    if response.status_code != 200:
        raise ProviderError("google_news", f"RSS fetch failed: {response.status_code}")
    return response.content


def parse_news(raw_xml: bytes, asset: AssetRef, *, limit: int = 30) -> list[Article]:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as error:
        raise ProviderError("google_news", f"malformed RSS: {error}") from error

    articles = []
    seen_hashes: set[str] = set()
    for item in root.findall(".//item")[:limit]:
        title_el = item.find("title")
        link_el = item.find("link")
        pub_date_el = item.find("pubDate")
        source_el = item.find("source")
        if title_el is None or title_el.text is None or link_el is None or link_el.text is None:
            continue
        if pub_date_el is None or pub_date_el.text is None:
            continue

        title = title_el.text
        dedup_hash = _dedup_hash(title)
        if dedup_hash in seen_hashes:
            continue
        seen_hashes.add(dedup_hash)

        try:
            published_at = parsedate_to_datetime(pub_date_el.text)
        except (TypeError, ValueError):
            continue

        source = source_el.text if source_el is not None and source_el.text else "Google News"
        articles.append(
            Article(
                url=link_el.text,
                source=source,
                published_at=published_at,
                title=title,
                dedup_hash=dedup_hash,
                asset=asset,
            )
        )
    return articles


class GoogleNewsProvider:
    """Implements `NewsProvider` for Google News RSS."""

    name = "google_news"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def get_news(self, target: AssetRef, since: dt.datetime) -> list[Article]:
        query = f"{target.name or target.symbol} stock"
        raw = fetch_news_raw(query, client=self._client)
        articles = parse_news(raw, target)
        return [a for a in articles if a.published_at >= since]
