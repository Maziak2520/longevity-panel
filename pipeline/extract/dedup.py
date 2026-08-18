from __future__ import annotations
import hashlib
from pipeline.models import Claim


def _dedup_key(claim: Claim) -> str:
    text_prefix = claim.claim_text[:100].lower().strip()
    return hashlib.sha256(f"{claim.person}::{claim.subtopic}::{text_prefix}".encode()).hexdigest()


def dedup_claims(claims: list[Claim]) -> list[Claim]:
    # Collapse exact re-extractions first: rows sharing a claim_id are the same
    # source-position claim (person::source::chunk::index) extracted more than
    # once, where the model re-phrased the text (and sometimes re-labelled the
    # subtopic/topic). The text-based pass below cannot catch these because the
    # wording differs, so key on claim_id, keep the latest generation (last
    # occurrence), and drop the rest outright. (Fixes ~37% historical inflation
    # from the pre-scout-fix daily re-queue.)
    by_id: dict[str, Claim] = {}
    for claim in claims:
        by_id[claim.claim_id] = claim
    claims = list(by_id.values())

    by_key: dict[str, list[Claim]] = {}
    for claim in claims:
        key = _dedup_key(claim)
        by_key.setdefault(key, []).append(claim)

    result = []
    for key, group in by_key.items():
        if len(group) == 1:
            result.append(group[0])
            continue
        sorted_group = sorted(group, key=lambda c: c.source_date)
        for i, claim in enumerate(sorted_group[:-1]):
            superseding = sorted_group[i + 1]
            claim_copy = claim.model_copy(update={"superseded_by": superseding.claim_id})
            result.append(claim_copy)
        result.append(sorted_group[-1])

    return result
