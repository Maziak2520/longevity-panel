import pytest
from unittest.mock import MagicMock, patch
from pipeline.extract.extractor import extract_claims_from_chunk, EXTRACTION_SYSTEM_PROMPT
from pipeline.models import Claim

VALID_TOPICS = ["sleep", "nutrition", "supplements", "longevity", "exercise",
                "stress_recovery", "hormones", "gut", "brain"]


def make_mock_claim(topic="sleep"):
    return {
        "topic": topic,
        "subtopic": "sleep duration",
        "claim_text": "Eight hours is optimal.",
        "protocol_details": "8 hours per night",
        "strength": "strong",
        "conditions": "",
        "contraindications": "",
        "extracted_quote": "I aim for eight hours.",
    }


def _response(claims):
    r = MagicMock()
    r.claims = claims
    return r


def test_extraction_system_prompt_contains_topics():
    for topic in VALID_TOPICS:
        assert topic in EXTRACTION_SYSTEM_PROMPT


def test_extract_claims_returns_claim_objects():
    mock = MagicMock(return_value=_response([MagicMock(**make_mock_claim())]))
    with patch("pipeline.extract.extractor.structured_extract", mock):
        claims = extract_claims_from_chunk(
            chunk="I aim for eight hours every night.",
            chunk_index=0,
            person_id="peter-attia",
            person_name="Peter Attia",
            source_id="yt-test001",
            source_title="Sleep Episode",
            source_url="https://youtube.com/watch?v=test001",
            source_date="2023-01-15",
            valid_topics=VALID_TOPICS,
            model="claude-haiku-4-5-20251001",
            max_output_tokens=8192,
        )
    assert len(claims) == 1
    assert isinstance(claims[0], Claim)
    assert claims[0].person == "peter-attia"
    assert claims[0].topic == "sleep"


def test_extract_claims_returns_empty_for_irrelevant_chunk():
    mock = MagicMock(return_value=_response([]))
    with patch("pipeline.extract.extractor.structured_extract", mock):
        claims = extract_claims_from_chunk(
            chunk="That was a great recipe for pasta.",
            chunk_index=0,
            person_id="peter-attia",
            person_name="Peter Attia",
            source_id="yt-test002",
            source_title="Cooking Episode",
            source_url="https://youtube.com/watch?v=test002",
            source_date="2023-02-01",
            valid_topics=VALID_TOPICS,
            model="claude-haiku-4-5-20251001",
            max_output_tokens=8192,
        )
    assert claims == []


def _kwargs(chunk="I aim for eight hours every night.", chunk_index=0):
    return dict(
        chunk=chunk,
        chunk_index=chunk_index,
        person_id="peter-attia",
        person_name="Peter Attia",
        source_id="yt-test001",
        source_title="Sleep Episode",
        source_url="https://youtube.com/watch?v=test001",
        source_date="2023-01-15",
        valid_topics=VALID_TOPICS,
        model="claude-haiku-4-5-20251001",
        max_output_tokens=8192,
    )


def test_truncated_chunk_splits_and_merges():
    from instructor.core import IncompleteOutputException
    from pipeline.extract.extractor import extract_claims_splitting

    long_chunk = " ".join(f"word{i}" for i in range(400))

    def fake_extract(*, user, **_):
        if len(user.split()) > 300:      # `user` includes the prompt preamble + chunk
            raise IncompleteOutputException()
        return _response([MagicMock(**make_mock_claim())])

    with patch("pipeline.extract.extractor.structured_extract", side_effect=fake_extract):
        claims = extract_claims_splitting(
            **_kwargs(chunk=long_chunk, chunk_index=3),
            overlap_words=10,
            min_split_words=50,
        )

    assert len(claims) == 2
    assert claims[0].claim_id != claims[1].claim_id


def test_truncation_below_min_split_raises_without_retry():
    from instructor.core import IncompleteOutputException
    from pipeline.extract.extractor import extract_claims_splitting

    mock = MagicMock(side_effect=IncompleteOutputException())
    with patch("pipeline.extract.extractor.structured_extract", mock):
        with pytest.raises(IncompleteOutputException):
            extract_claims_splitting(
                **_kwargs(chunk="short chunk"),
                overlap_words=10,
                min_split_words=50,
            )

    assert mock.call_count == 1


def test_nested_splitting_produces_unique_claim_ids():
    from instructor.core import IncompleteOutputException
    from pipeline.extract.extractor import extract_claims_splitting

    long_chunk = " ".join(f"word{i}" for i in range(800))

    def fake_extract(*, user, **_):
        if len(user.split()) > 150:
            raise IncompleteOutputException()
        return _response([MagicMock(**make_mock_claim())])

    with patch("pipeline.extract.extractor.structured_extract", side_effect=fake_extract):
        claims = extract_claims_splitting(
            **_kwargs(chunk=long_chunk, chunk_index=0),
            overlap_words=5,
            min_split_words=50,
        )

    ids = [c.claim_id for c in claims]
    assert len(claims) >= 4
    assert len(set(ids)) == len(ids)
