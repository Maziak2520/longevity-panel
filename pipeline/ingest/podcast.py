from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from bs4 import BeautifulSoup


@dataclass
class EpisodeMeta:
    episode_id: str
    title: str
    description: str
    url: str
    published_date: str  # ISO 8601

    @property
    def source_id(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:40]
        return f"pod-{slug}"


def parse_rss_episodes(feed_url: str, since: str) -> list[EpisodeMeta]:
    feed = feedparser.parse(feed_url)
    since_dt = datetime.fromisoformat(since)
    episodes = []
    for entry in feed.entries:
        pub_date_str = entry.get("published", "")
        if not pub_date_str:
            continue
        try:
            pub_dt = parsedate_to_datetime(pub_date_str)
            pub_dt = pub_dt.replace(tzinfo=None)
        except Exception:
            continue
        if pub_dt < since_dt:
            continue
        episodes.append(EpisodeMeta(
            episode_id=entry.get("id", entry.get("link", "")),
            title=entry.get("title", ""),
            description=entry.get("summary", ""),
            url=entry.get("link", ""),
            published_date=pub_dt.date().isoformat(),
        ))
    return episodes


def scrape_transcript(url: str, selector: str) -> str | None:
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.select_one(selector)
        if not el:
            return None
        return el.get_text(separator="\n", strip=True)
    except Exception:
        return None
