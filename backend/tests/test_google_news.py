import datetime as dt

import httpx
import pytest

from app.domain.models import AssetRef
from app.providers.errors import ProviderError
from app.providers.india.google_news import GoogleNewsProvider, fetch_news_raw, parse_news

RELIANCE = AssetRef(symbol="RELIANCE", exchange="NSE", name="Reliance Industries")

# Real RSS shape captured live 2026-08-23 for query "Reliance Industries stock"
# (trimmed to 2 items + one hand-added duplicate-title item for dedup testing).
SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Reliance Industries Share Price Rallies 3%: What's Driving the Stock Higher? - India Infoline</title>
      <link>https://news.google.com/rss/articles/ABC123?oc=5</link>
      <guid isPermaLink="false">ABC123</guid>
      <pubDate>Thu, 06 Aug 2026 07:00:00 GMT</pubDate>
      <description>&lt;a href="https://news.google.com/rss/articles/ABC123"&gt;Reliance Industries Share Price Rallies 3%&lt;/a&gt;</description>
      <source url="https://www.indiainfoline.com">India Infoline</source>
    </item>
    <item>
      <title>Stocks to Watch for August 24: Reliance Industries, NATCO Pharma - CNBC TV18</title>
      <link>https://news.google.com/rss/articles/DEF456?oc=5</link>
      <guid isPermaLink="false">DEF456</guid>
      <pubDate>Sun, 23 Aug 2026 09:35:01 GMT</pubDate>
      <description>desc</description>
      <source url="https://www.cnbctv18.com">CNBC TV18</source>
    </item>
    <item>
      <!-- Same title as item 1, different guid/link (Google News sometimes
      re-syndicates); must be deduped by normalized title. -->
      <title>Reliance Industries Share Price Rallies 3%: What's Driving the Stock Higher?  -   India Infoline</title>
      <link>https://news.google.com/rss/articles/GHI789?oc=5</link>
      <guid isPermaLink="false">GHI789</guid>
      <pubDate>Thu, 06 Aug 2026 08:00:00 GMT</pubDate>
      <description>desc</description>
      <source url="https://www.indiainfoline.com">India Infoline</source>
    </item>
  </channel>
</rss>
"""


def test_parse_news_extracts_real_fields() -> None:
    articles = parse_news(SAMPLE_RSS, RELIANCE)

    assert len(articles) == 2  # third item deduped away
    first = articles[0]
    assert first.title.startswith("Reliance Industries Share Price Rallies 3%")
    assert first.source == "India Infoline"
    assert first.published_at == dt.datetime(2026, 8, 6, 7, 0, 0, tzinfo=dt.UTC)
    assert first.url == "https://news.google.com/rss/articles/ABC123?oc=5"
    assert first.asset == RELIANCE


def test_parse_news_dedupes_by_normalized_title() -> None:
    articles = parse_news(SAMPLE_RSS, RELIANCE)
    hashes = [a.dedup_hash for a in articles]
    assert len(hashes) == len(set(hashes))


def test_parse_news_raises_on_malformed_xml() -> None:
    with pytest.raises(ProviderError):
        parse_news(b"<not valid xml", RELIANCE)


def test_parse_news_respects_limit() -> None:
    articles = parse_news(SAMPLE_RSS, RELIANCE, limit=1)
    assert len(articles) == 1


def test_fetch_news_raw_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        fetch_news_raw("Reliance Industries stock", client=client)


def test_fetch_news_raw_builds_query_params() -> None:
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, content=SAMPLE_RSS)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch_news_raw("Reliance Industries stock", client=client)
    assert "q=Reliance" in seen_urls[0]
    assert "hl=en-IN" in seen_urls[0]


def test_provider_get_news_filters_by_since() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SAMPLE_RSS)

    provider = GoogleNewsProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    articles = provider.get_news(RELIANCE, dt.datetime(2026, 8, 10, tzinfo=dt.UTC))

    assert len(articles) == 1
    assert articles[0].title.startswith("Stocks to Watch")


def test_provider_get_news_uses_company_name_in_query() -> None:
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, content=SAMPLE_RSS)

    provider = GoogleNewsProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.get_news(RELIANCE, dt.datetime(2020, 1, 1, tzinfo=dt.UTC))

    assert "Reliance+Industries" in seen_urls[0] or "Reliance%20Industries" in seen_urls[0]
