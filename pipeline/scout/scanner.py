from __future__ import annotations
from pipeline.config import Expert
from pipeline.ingest.filter import matches_topics
from pipeline.ingest.youtube import list_channel_videos
from pipeline.scout.state import StateManager, PendingItem


def scan_expert(expert: Expert, state: StateManager, keywords: list[str]) -> int:
    new_count = 0
    # Skip everything already downloaded, queued, or failed — otherwise daily
    # scouts between weekly ingests re-queue the same backlog every day.
    # Failed items are retried via `manage.py retry-failed`, not automatically.
    known = state.known_source_ids()
    for yt_source in expert.sources.youtube:
        videos = list_channel_videos(yt_source.url, since=expert.since)
        for video in videos:
            if video.source_id in known:
                continue
            if yt_source.filter_topics and not matches_topics(video.title, video.description, keywords):
                continue
            state.add_pending(PendingItem(
                source_id=video.source_id,
                expert_id=expert.id,
                source_type="youtube",
                url=video.url,
                title=video.title,
                published_date=video.iso_date,
            ))
            known.add(video.source_id)
            new_count += 1
    return new_count
