import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pipeline.build.compiler import group_claims_by_topic, meets_build_threshold
from pipeline.models import Claim


def make_claim(person, subtopic, topic="sleep", source_date="2023-01-01"):
    return Claim(
        claim_id=f"{person}-{subtopic[:4]}",
        person=person,
        person_name=person.replace("-", " ").title(),
        topic=topic,
        subtopic=subtopic,
        claim_text=f"Claim about {subtopic} by {person}.",
        protocol_details="",
        strength="strong",
        conditions="",
        contraindications="",
        extracted_quote=f"I recommend {subtopic}.",
        source_id="yt-test",
        source_title="Test Episode",
        source_url="https://yt.com",
        source_date=source_date,
        extracted_at="2026-06-29T10:00:00",
        superseded_by="",
        schema_version="1.0",
    )


def test_group_claims_by_topic():
    claims = [
        make_claim("peter-attia", "sleep duration", topic="sleep"),
        make_claim("rhonda-patrick", "sleep quality", topic="sleep"),
        make_claim("peter-attia", "rapamycin", topic="supplements"),
    ]
    grouped = group_claims_by_topic(claims)
    assert "sleep" in grouped
    assert "supplements" in grouped
    assert len(grouped["sleep"]) == 2
    assert len(grouped["supplements"]) == 1


def test_group_claims_excludes_superseded():
    active = make_claim("peter-attia", "sleep duration", topic="sleep")
    superseded = make_claim("peter-attia", "sleep quality", topic="sleep")
    superseded = superseded.model_copy(update={"superseded_by": "some-id"})
    grouped = group_claims_by_topic([active, superseded])
    assert len(grouped.get("sleep", [])) == 1


def test_meets_build_threshold_passes():
    claims = [make_claim(f"expert-{i}", "sleep") for i in range(4)]
    assert meets_build_threshold(claims, min_experts=2, min_claims=3)


def test_meets_build_threshold_fails_insufficient_experts():
    claims = [make_claim("peter-attia", "sleep") for _ in range(5)]
    assert not meets_build_threshold(claims, min_experts=2, min_claims=3)


def test_meets_build_threshold_fails_insufficient_claims():
    claims = [make_claim(f"expert-{i}", "sleep") for i in range(2)]
    assert not meets_build_threshold(claims, min_experts=2, min_claims=3)
