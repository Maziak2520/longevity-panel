import pytest
import json
from pathlib import Path
from pipeline.models import Claim, make_claim_id, load_claims, append_claim


def make_sample_claim(**overrides) -> Claim:
    defaults = dict(
        claim_id="abc123def456",
        person="peter-attia",
        person_name="Peter Attia",
        topic="sleep",
        subtopic="sleep duration",
        claim_text="Adults need 7-9 hours of sleep.",
        protocol_details="Target 7-9h consistently.",
        strength="strong",
        conditions="healthy adults",
        contraindications="",
        extracted_quote="You need 7 to 9 hours.",
        source_id="yt-abc123",
        source_title="Sleep Science Episode",
        source_url="https://yt.com/watch?v=abc123",
        source_date="2023-05-10",
        extracted_at="2026-06-29T10:00:00",
        superseded_by="",
        schema_version="1.0",
    )
    defaults.update(overrides)
    return Claim(**defaults)


def test_make_claim_id_is_deterministic():
    id1 = make_claim_id("peter-attia", "yt-abc", 0, 0)
    id2 = make_claim_id("peter-attia", "yt-abc", 0, 0)
    assert id1 == id2


def test_make_claim_id_differs_for_different_inputs():
    id1 = make_claim_id("peter-attia", "yt-abc", 0, 0)
    id2 = make_claim_id("peter-attia", "yt-abc", 0, 1)
    assert id1 != id2


def test_make_claim_id_is_12_chars():
    cid = make_claim_id("person", "source", 0, 0)
    assert len(cid) == 12


def test_claim_serializes_to_json():
    claim = make_sample_claim()
    data = claim.model_dump()
    assert data["claim_id"] == "abc123def456"
    assert data["schema_version"] == "1.0"


def test_append_and_load_claims(tmp_path):
    f = tmp_path / "claims.jsonl"
    c1 = make_sample_claim(claim_id="id1")
    c2 = make_sample_claim(claim_id="id2", person="rhonda-patrick", person_name="Rhonda Patrick")
    append_claim(f, c1)
    append_claim(f, c2)
    loaded = load_claims(f)
    assert len(loaded) == 2
    assert loaded[0].claim_id == "id1"
    assert loaded[1].claim_id == "id2"


def test_load_claims_returns_empty_for_missing_file(tmp_path):
    f = tmp_path / "missing.jsonl"
    assert load_claims(f) == []
