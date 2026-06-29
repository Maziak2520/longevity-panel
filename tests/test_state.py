import pytest
from pathlib import Path
from pipeline.scout.state import StateManager, PendingItem


def test_mark_downloaded_and_check(tmp_path):
    sm = StateManager(tmp_path / "Index")
    sm.mark_downloaded("yt-abc123", "brian-johnson", "youtube", "https://yt.com/watch?v=abc")
    assert sm.is_downloaded("yt-abc123")
    assert not sm.is_downloaded("yt-xyz999")


def test_add_pending_and_pop(tmp_path):
    sm = StateManager(tmp_path / "Index")
    sm.add_pending(PendingItem(
        source_id="yt-abc123",
        expert_id="brian-johnson",
        source_type="youtube",
        url="https://yt.com/watch?v=abc",
        title="Sleep Episode",
        published_date="2023-01-15",
    ))
    items = sm.pop_pending()
    assert len(items) == 1
    assert items[0].source_id == "yt-abc123"
    remaining = sm.pop_pending()
    assert remaining == []


def test_add_failed(tmp_path):
    sm = StateManager(tmp_path / "Index")
    sm.add_failed("yt-abc123", "network_error", "Connection timeout")
    failed = sm.load_failed()
    assert "yt-abc123" in failed
    assert failed["yt-abc123"]["reason"] == "network_error"


def test_state_persists_across_instances(tmp_path):
    idx = tmp_path / "Index"
    sm1 = StateManager(idx)
    sm1.mark_downloaded("yt-abc123", "brian-johnson", "youtube", "https://yt.com/watch?v=abc")
    sm2 = StateManager(idx)
    assert sm2.is_downloaded("yt-abc123")
