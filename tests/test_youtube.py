import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pipeline.ingest.youtube import clean_vtt, list_channel_videos, VideoMeta

FIXTURES = Path(__file__).parent / "fixtures"


def test_clean_vtt_strips_timing_and_tags():
    vtt = (FIXTURES / "sample_vtt.txt").read_text()
    cleaned = clean_vtt(vtt)
    assert "00:00:00" not in cleaned
    assert "WEBVTT" not in cleaned
    assert "<c>" not in cleaned
    assert "sleep" in cleaned
    assert "rapamycin" in cleaned


def test_clean_vtt_deduplicates_lines():
    vtt = """WEBVTT

00:00:00.000 --> 00:00:03.000
Hello world.

00:00:02.500 --> 00:00:05.000
Hello world.

00:00:05.000 --> 00:00:08.000
New sentence here.
"""
    cleaned = clean_vtt(vtt)
    lines = [l for l in cleaned.splitlines() if l.strip()]
    assert lines.count("Hello world.") == 1


def test_list_channel_videos_calls_ytdlp(tmp_path):
    mock_output = '{"id": "abc123", "title": "Sleep Science", "description": "about sleep", "upload_date": "20230115"}\n'
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
        videos = list_channel_videos("https://youtube.com/@test", since="2020-01-01")
    assert len(videos) == 1
    assert videos[0].video_id == "abc123"
    assert videos[0].title == "Sleep Science"


def test_list_channel_videos_filters_by_date(tmp_path):
    mock_output = (
        '{"id": "new1", "title": "Sleep", "description": "", "upload_date": "20230115"}\n'
        '{"id": "old1", "title": "Old sleep", "description": "", "upload_date": "20190101"}\n'
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
        videos = list_channel_videos("https://youtube.com/@test", since="2020-01-01")
    assert len(videos) == 1
    assert videos[0].video_id == "new1"
