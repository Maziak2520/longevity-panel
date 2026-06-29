import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
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


def test_extraction_system_prompt_contains_topics():
    for topic in VALID_TOPICS:
        assert topic in EXTRACTION_SYSTEM_PROMPT


def test_extract_claims_returns_claim_objects(mocker):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.claims = [MagicMock(**make_mock_claim())]
    mock_client.chat.completions.create.return_value = mock_response

    with patch("pipeline.extract.extractor.build_instructor_client", return_value=mock_client):
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
        )
    assert len(claims) == 1
    assert isinstance(claims[0], Claim)
    assert claims[0].person == "peter-attia"
    assert claims[0].topic == "sleep"


def test_extract_claims_returns_empty_for_irrelevant_chunk(mocker):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.claims = []
    mock_client.chat.completions.create.return_value = mock_response

    with patch("pipeline.extract.extractor.build_instructor_client", return_value=mock_client):
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
        )
    assert claims == []
