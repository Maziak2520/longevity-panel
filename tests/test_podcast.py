import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pipeline.ingest.podcast import parse_rss_episodes, scrape_transcript, EpisodeMeta

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_rss_episodes_filters_by_date():
    rss_xml = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Sleep Science 2023</title>
      <link>https://podcast.com/episodes/sleep-2023</link>
      <description>All about sleep</description>
      <pubDate>Mon, 15 Jan 2023 00:00:00 +0000</pubDate>
      <guid>ep-001</guid>
    </item>
    <item>
      <title>Old Episode</title>
      <link>https://podcast.com/episodes/old</link>
      <description>Old stuff</description>
      <pubDate>Mon, 01 Jan 2018 00:00:00 +0000</pubDate>
      <guid>ep-000</guid>
    </item>
  </channel>
</rss>"""
    parsed = feedparser_fixture(rss_xml)
    with patch("feedparser.parse") as mock_parse:
        mock_parse.return_value = parsed
        episodes = parse_rss_episodes("https://podcast.com/feed.rss", since="2020-01-01")
    assert len(episodes) == 1
    assert "Sleep" in episodes[0].title


def feedparser_fixture(rss_xml):
    import feedparser
    return feedparser.parse(rss_xml)


def test_scrape_transcript_extracts_text():
    html = (FIXTURES / "sample_podcast.html").read_text()
    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text=html)
        text = scrape_transcript("https://podcast.com/ep/sleep", selector=".transcript-content")
    assert "sleep" in text.lower()
    assert "REM" in text


def test_scrape_transcript_returns_none_on_failure():
    with patch("httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, text="")
        result = scrape_transcript("https://podcast.com/missing", selector=".transcript-content")
    assert result is None
