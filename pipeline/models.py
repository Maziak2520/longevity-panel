from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel


def make_claim_id(person_id: str, source_id: str, chunk_index: int | str, claim_index: int) -> str:
    key = f"{person_id}::{source_id}::{chunk_index}::{claim_index}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


class Claim(BaseModel):
    claim_id: str
    person: str
    person_name: str
    topic: str
    subtopic: str
    claim_text: str
    protocol_details: str
    strength: Literal["strong", "moderate", "weak", "anecdotal"]
    conditions: str
    contraindications: str
    extracted_quote: str
    source_id: str
    source_title: str
    source_url: str
    source_date: str
    extracted_at: str
    superseded_by: str
    schema_version: str = "1.0"


def load_claims(path: Path) -> list[Claim]:
    if not path.exists():
        return []
    claims = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            claims.append(Claim(**json.loads(line)))
    return claims


def append_claim(path: Path, claim: Claim) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    line = claim.model_dump_json() + "\n"
    if path.exists():
        tmp.write_text(path.read_text() + line)
    else:
        tmp.write_text(line)
    tmp.rename(path)
