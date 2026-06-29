import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pipeline.scout.scanner import scan_expert
from pipeline.scout.state import StateManager, PendingItem
from pipeline.config import Expert, YoutubeSource, ExpertSources


def make_expert(filter_topics=True):
    return Expert(
        id="test-expert",
        name="Test Expert",
        active=True,
        since="2022-01-01",
        sources=ExpertSources(
            youtube=[YoutubeSource(url="https://youtube.com/@test", filter_topics=filter_topics)],
            podcast=[],
        ),
    )


def test_scan_expert_adds_new_videos_to_pending(tmp_path):
    state = StateManager(tmp_path / "Index")
    keywords = ["sleep", "longevity"]

    mock_videos = [
        MagicMock(video_id="vid1", title="Sleep Science", description="about sleep",
                  upload_date="20230115", source_id="yt-vid1", url="https://yt.com/watch?v=vid1", iso_date="2023-01-15"),
    ]

    with patch("pipeline.scout.scanner.list_channel_videos", return_value=mock_videos):
        count = scan_expert(make_expert(), state, keywords)

    assert count == 1
    items = state.pop_pending()
    assert len(items) == 1
    assert items[0].source_id == "yt-vid1"


def test_scan_expert_skips_already_downloaded(tmp_path):
    state = StateManager(tmp_path / "Index")
    state.mark_downloaded("yt-vid1", "test-expert", "youtube", "https://yt.com/watch?v=vid1")
    keywords = ["sleep"]

    mock_videos = [
        MagicMock(video_id="vid1", title="Sleep Science", description="about sleep",
                  upload_date="20230115", source_id="yt-vid1", url="https://yt.com/watch?v=vid1", iso_date="2023-01-15"),
    ]

    with patch("pipeline.scout.scanner.list_channel_videos", return_value=mock_videos):
        count = scan_expert(make_expert(), state, keywords)

    assert count == 0


def test_scan_expert_filters_by_topic_when_enabled(tmp_path):
    state = StateManager(tmp_path / "Index")
    keywords = ["sleep"]

    mock_videos = [
        MagicMock(video_id="v1", title="Sleep Science", description="",
                  upload_date="20230115", source_id="yt-v1", url="https://yt.com/watch?v=v1", iso_date="2023-01-15"),
        MagicMock(video_id="v2", title="Cooking Show", description="pasta recipes",
                  upload_date="20230115", source_id="yt-v2", url="https://yt.com/watch?v=v2", iso_date="2023-01-15"),
    ]

    with patch("pipeline.scout.scanner.list_channel_videos", return_value=mock_videos):
        count = scan_expert(make_expert(filter_topics=True), state, keywords)

    assert count == 1
