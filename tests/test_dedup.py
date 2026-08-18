from pipeline.extract.dedup import dedup_claims
from pipeline.models import Claim


def make_claim(claim_id, person, subtopic, text, source_date="2023-01-01"):
    return Claim(
        claim_id=claim_id,
        person=person,
        person_name=person.replace("-", " ").title(),
        topic="sleep",
        subtopic=subtopic,
        claim_text=text,
        protocol_details="",
        strength="strong",
        conditions="",
        contraindications="",
        extracted_quote=text,
        source_id=f"yt-{claim_id}",
        source_title="Episode",
        source_url="https://yt.com",
        source_date=source_date,
        extracted_at="2026-06-29T10:00:00",
        superseded_by="",
        schema_version="1.0",
    )


def test_dedup_removes_identical_claims():
    c1 = make_claim("id001", "peter-attia", "sleep duration", "Eight hours is optimal.")
    c2 = make_claim("id002", "peter-attia", "sleep duration", "Eight hours is optimal.")
    result = dedup_claims([c1, c2])
    active = [c for c in result if not c.superseded_by]
    assert len(active) == 1


def test_dedup_keeps_newer_claim_active():
    old = make_claim("id001", "peter-attia", "sleep duration", "Seven hours may be enough.", source_date="2021-01-01")
    new = make_claim("id002", "peter-attia", "sleep duration", "Seven hours may be enough.", source_date="2023-06-01")
    result = dedup_claims([old, new])
    active = [c for c in result if not c.superseded_by]
    assert len(active) == 1
    assert active[0].claim_id == "id002"


def test_dedup_different_people_not_deduped():
    c1 = make_claim("id001", "peter-attia", "sleep duration", "Eight hours is optimal.")
    c2 = make_claim("id002", "rhonda-patrick", "sleep duration", "Eight hours is optimal.")
    result = dedup_claims([c1, c2])
    active = [c for c in result if not c.superseded_by]
    assert len(active) == 2


def test_dedup_different_subtopic_not_deduped():
    c1 = make_claim("id001", "peter-attia", "sleep duration", "Eight hours optimal.")
    c2 = make_claim("id002", "peter-attia", "sleep timing", "Eight hours optimal.")
    result = dedup_claims([c1, c2])
    active = [c for c in result if not c.superseded_by]
    assert len(active) == 2


def test_dedup_collapses_reextraction_by_claim_id():
    # Same source position extracted twice -> identical claim_id, but the model
    # re-phrased the text (and even re-labelled the subtopic), so the text-based
    # pass can't catch it. It must collapse by claim_id, keeping the latest
    # generation and DROPPING the rest (not retaining them as superseded).
    gen1 = make_claim("dup01", "peter-attia", "circadian",
                      "Morning sunlight within 30-60 min of waking.")
    gen2 = make_claim("dup01", "peter-attia", "light",
                      "Viewing bright sunlight shortly after waking helps.")
    result = dedup_claims([gen1, gen2])
    assert len(result) == 1
    assert result[0].claim_id == "dup01"
    assert result[0].claim_text == gen2.claim_text  # latest generation kept


def test_dedup_claim_id_collapse_preserves_distinct_ids():
    # Distinct claim_ids with different text are untouched by the collapse.
    a = make_claim("idA", "peter-attia", "sleep", "Cold showers help sleep.")
    b = make_claim("idB", "peter-attia", "sleep", "Magnesium helps sleep.")
    result = dedup_claims([a, b])
    active = [c for c in result if not c.superseded_by]
    assert len(active) == 2
