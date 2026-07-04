import pytest
from types import SimpleNamespace
from pathlib import Path
from pipeline.build.skill_writer import write_skill_md, collect_topic_summaries, TopicSummary


def test_write_skill_md_creates_file(tmp_path):
    topics = [
        TopicSummary(topic="sleep", filename="sleep.md", claim_count=84, expert_count=9, last_updated="2026-06-29"),
        TopicSummary(topic="supplements", filename="supplements.md", claim_count=156, expert_count=11, last_updated="2026-06-29"),
    ]
    panel_members = ["Brian Johnson", "Peter Attia", "Rhonda Patrick"]
    write_skill_md(tmp_path, topics, panel_members)
    skill_file = tmp_path / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text()
    assert "health-panel" in content
    assert "sleep" in content
    assert "sleep.md" in content
    assert "Brian Johnson" in content
    assert "Not medical advice" in content


def test_write_skill_md_topic_map_has_all_topics(tmp_path):
    topics = [
        TopicSummary(topic="sleep", filename="sleep.md", claim_count=10, expert_count=3, last_updated="2026-06-29"),
        TopicSummary(topic="brain", filename="brain.md", claim_count=20, expert_count=4, last_updated="2026-06-29"),
    ]
    write_skill_md(tmp_path, topics, ["Expert A"])
    content = (tmp_path / "SKILL.md").read_text()
    assert "sleep.md" in content
    assert "brain.md" in content


def test_collect_topic_summaries_includes_every_reference_file(tmp_path):
    """A single-topic rebuild must not drop other topics from the map."""
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "nutrition.md").write_text("x")
    (refs / "stress-recovery.md").write_text("y")
    grouped = {
        "nutrition": [SimpleNamespace(person="a"), SimpleNamespace(person="b")],
        "stress_recovery": [SimpleNamespace(person="a")],
    }
    # Only nutrition was rebuilt this run.
    rebuilt = {"nutrition": TopicSummary("nutrition", "nutrition.md", 999, 5, "2026-07-04")}

    out = collect_topic_summaries(refs, grouped, rebuilt)
    by = {t.topic: t for t in out}

    # Both topics present even though only one was rebuilt.
    assert set(by) == {"nutrition", "stress_recovery"}
    # Rebuilt topic keeps its fresh stats.
    assert by["nutrition"].claim_count == 999
    # Non-rebuilt topic is recomputed from claims; hyphen filename -> underscore topic.
    assert by["stress_recovery"].claim_count == 1
    assert by["stress_recovery"].expert_count == 1
    assert by["stress_recovery"].filename == "stress-recovery.md"
