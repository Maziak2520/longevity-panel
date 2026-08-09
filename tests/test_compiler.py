import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from pipeline.build.compiler import (
    group_claims_by_topic,
    meets_build_threshold,
    compile_topic_markdown,
    _chunk,
    topic_fingerprint,
    should_rebuild,
    load_build_state,
    save_build_state,
)
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
    mock = MagicMock(return_value="summary text")

    # 3 claims for expert-a, chunk size 2 → 2 map calls for expert-a, 1 for expert-b, 1 reduce = 4 total
    claims = [make_claim("expert-a", f"sub{i}", topic="nutrition") for i in range(3)]
    claims += [make_claim("expert-b", "sub0", topic="nutrition")]

    with patch("pipeline.build.compiler.complete_text", mock):
        result = compile_topic_markdown(
            topic="nutrition",
            claims=claims,
            model="test-model",
            today="2026-07-02",
            map_reduce_threshold=2,
            map_chunk_size=2,
        )

    # 2 map chunks for expert-a + 1 for expert-b + 1 reduce = 4
    assert mock.call_count == 4
    assert result == "summary text"


def test_compile_topic_uses_cheap_map_model_and_sonnet_reduce():
    """Map calls use map_model (cheap); the final reduce uses the reduce model."""
    mock = MagicMock(return_value="summary text")

    # 2 experts, 1 claim each, chunk size 1, threshold 1 → 2 map calls + 1 reduce.
    claims = [make_claim("expert-a", "sub0", topic="nutrition"),
              make_claim("expert-b", "sub0", topic="nutrition")]

    with patch("pipeline.build.compiler.complete_text", mock):
        compile_topic_markdown(
            topic="nutrition",
            claims=claims,
            model="reduce-model",
            today="2026-08-02",
            map_reduce_threshold=1,
            map_chunk_size=1,
            map_model="map-model",
        )

    models_used = [c.args[0] for c in mock.call_args_list]   # model is the first positional arg
    # First two calls are the map phase, the last is the reduce.
    assert models_used[:2] == ["map-model", "map-model"]
    assert models_used[-1] == "reduce-model"


def test_compile_topic_map_model_defaults_to_model():
    """When map_model is omitted, both phases use `model` (backwards compatible)."""
    mock = MagicMock(return_value="summary text")

    claims = [make_claim("expert-a", "sub0", topic="nutrition"),
              make_claim("expert-b", "sub0", topic="nutrition")]

    with patch("pipeline.build.compiler.complete_text", mock):
        compile_topic_markdown(
            topic="nutrition", claims=claims, model="only-model", today="2026-08-02",
            map_reduce_threshold=1, map_chunk_size=1,
        )

    models_used = {c.args[0] for c in mock.call_args_list}
    assert models_used == {"only-model"}


def test_topic_fingerprint_is_order_independent():
    a = make_claim("peter-attia", "sleep duration")
    b = make_claim("rhonda-patrick", "sleep quality")
    assert topic_fingerprint([a, b]) == topic_fingerprint([b, a])


def test_topic_fingerprint_ignores_extracted_at():
    a = make_claim("peter-attia", "sleep duration")
    a2 = a.model_copy(update={"extracted_at": "2030-01-01T00:00:00"})
    assert topic_fingerprint([a]) == topic_fingerprint([a2])


def test_topic_fingerprint_changes_on_content_change():
    a = make_claim("peter-attia", "sleep duration")
    changed = a.model_copy(update={"claim_text": "A materially different claim."})
    assert topic_fingerprint([a]) != topic_fingerprint([changed])


def test_topic_fingerprint_changes_when_claim_added():
    a = make_claim("peter-attia", "sleep duration")
    b = make_claim("rhonda-patrick", "sleep quality")
    assert topic_fingerprint([a]) != topic_fingerprint([a, b])


@pytest.mark.parametrize("fp,prev,ref_exists,force,expected", [
    ("x", "x", True, False, False),   # unchanged + file present → skip
    ("x", "y", True, False, True),    # changed claims → rebuild
    ("x", "x", False, False, True),   # reference file missing → rebuild
    ("x", None, True, False, True),   # never built before → rebuild
    ("x", "x", True, True, True),     # --force → rebuild regardless
])
def test_should_rebuild(fp, prev, ref_exists, force, expected):
    assert should_rebuild(fp, prev, ref_exists, force) is expected


def test_build_state_round_trip(tmp_path):
    path = tmp_path / "build_state.json"
    assert load_build_state(path) == {}          # missing file → empty
    save_build_state(path, {"sleep": "abc", "gut": "def"})
    assert load_build_state(path) == {"sleep": "abc", "gut": "def"}
