from __future__ import annotations
from datetime import datetime, timezone

import anthropic
import instructor
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.models import Claim, make_claim_id

VALID_TOPICS = ["sleep", "nutrition", "supplements", "longevity", "exercise",
                "stress_recovery", "hormones", "gut", "brain"]

EXTRACTION_SYSTEM_PROMPT = """You extract structured health and longevity claims from transcripts.

For each discrete, actionable claim about: sleep, nutrition, supplements, longevity, exercise,
stress_recovery, hormones, gut, or brain — output a structured entry.

Rules:
- One entry per discrete claim (do not bundle multiple claims)
- protocol_details: exact numbers, doses, durations if stated, else empty string
- extracted_quote: verbatim text from the transcript supporting this claim
- strength: strong=cites studies, moderate=expert opinion, weak=speculative, anecdotal=personal experience
- If a claim is incomplete at the start or end of the text, skip it
- topic must be one of: sleep, nutrition, supplements, longevity, exercise, stress_recovery, hormones, gut, brain
- Return empty list if no relevant health/longevity claims are present"""


class ClaimExtraction(BaseModel):
    topic: str
    subtopic: str
    claim_text: str
    protocol_details: str
    strength: str
    conditions: str
    contraindications: str
    extracted_quote: str


class ExtractionResponse(BaseModel):
    claims: list[ClaimExtraction]


def build_instructor_client():
    client = anthropic.Anthropic()
    return instructor.from_anthropic(client)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=60))
def extract_claims_from_chunk(
    chunk: str,
    chunk_index: int,
    person_id: str,
    person_name: str,
    source_id: str,
    source_title: str,
    source_url: str,
    source_date: str,
    valid_topics: list[str],
    model: str,
) -> list[Claim]:
    client = build_instructor_client()
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Extract health/longevity claims from this transcript excerpt by {person_name}:\n\n{chunk}",
            }
        ],
        response_model=ExtractionResponse,
    )

    now = datetime.now(timezone.utc).isoformat()
    claims = []
    for i, raw in enumerate(response.claims):
        topic = raw.topic if hasattr(raw, "topic") else raw["topic"]
        if topic not in valid_topics:
            continue
        claims.append(Claim(
            claim_id=make_claim_id(person_id, source_id, chunk_index, i),
            person=person_id,
            person_name=person_name,
            topic=topic,
            subtopic=raw.subtopic if hasattr(raw, "subtopic") else raw["subtopic"],
            claim_text=raw.claim_text if hasattr(raw, "claim_text") else raw["claim_text"],
            protocol_details=raw.protocol_details if hasattr(raw, "protocol_details") else raw["protocol_details"],
            strength=raw.strength if hasattr(raw, "strength") else raw["strength"],
            conditions=raw.conditions if hasattr(raw, "conditions") else raw["conditions"],
            contraindications=raw.contraindications if hasattr(raw, "contraindications") else raw["contraindications"],
            extracted_quote=raw.extracted_quote if hasattr(raw, "extracted_quote") else raw["extracted_quote"],
            source_id=source_id,
            source_title=source_title,
            source_url=source_url,
            source_date=source_date,
            extracted_at=now,
            superseded_by="",
            schema_version="1.0",
        ))
    return claims
