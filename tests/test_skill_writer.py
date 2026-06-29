import pytest
from pathlib import Path
from pipeline.build.skill_writer import write_skill_md, TopicSummary


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
    assert "health-longevity" in content
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
