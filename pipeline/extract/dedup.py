from __future__ import annotations
import hashlib
from pipeline.models import Claim


def _dedup_key(claim: Claim) -> str:
    text_prefix = claim.claim_text[:100].lower().strip()
    return hashlib.sha256(f"{claim.person}::{claim.subtopic}::{text_prefix}".encode()).hexdigest()


def dedup_claims(claims: list[Claim]) -> list[Claim]:
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
