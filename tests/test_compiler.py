import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from pipeline.build.compiler import group_claims_by_topic, meets_build_threshold, compile_topic_markdown, _chunk
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


def test_chunk_splits_evenly():
    assert _chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_chunk_handles_remainder():
    assert _chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_smaller_than_size():
    assert _chunk([1, 2], 10) == [[1, 2]]


def test_compile_topic_map_chunks_large_expert(tmp_path):
    """When one expert has more claims than map_chunk_size, map is called multiple times for that expert."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="summary text")]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    # 3 claims for expert-a, chunk size 2 → 2 map calls for expert-a, 1 for expert-b, 1 reduce = 4 total
    claims = [make_claim("expert-a", f"sub{i}", topic="nutrition") for i in range(3)]
    claims += [make_claim("expert-b", "sub0", topic="nutrition")]

    with patch("pipeline.build.compiler.anthropic.Anthropic", return_value=mock_client):
        result = compile_topic_markdown(
            topic="nutrition",
            claims=claims,
            model="test-model",
            today="2026-07-02",
            map_reduce_threshold=2,
            map_chunk_size=2,
        )

    total_calls = mock_client.messages.create.call_count
    # 2 map chunks for expert-a + 1 for expert-b + 1 reduce = 4
    assert total_calls == 4
    assert result == "summary text"
