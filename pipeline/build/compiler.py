from __future__ import annotations
import json
from pathlib import Path

import anthropic
from pipeline.models import Claim

BUILD_PROMPT_TEMPLATE = """You are compiling a longevity knowledge reference from expert claims.

Topic: {topic}
Expert claims (JSON list):
{claims_json}

Write a concise, well-structured Markdown reference file for this topic. Format:

# {topic_title}

*{claim_count} claims · {expert_count} experts · last updated {today}*

> **Note:** This is a synthesis of expert opinions for personal research. Not medical advice. Consult a physician before changing your health protocol.

## Expert positions

For each expert (sorted by strength of advocacy), write:
### [Expert Name] — [position: Strong advocate / Moderate advocate / Neutral / Sceptical]
**Protocol:** [if specific protocol given, else omit]
- [claim 1] *(Source: [source_title], [source_date])*
- [claim 2] *(Source: ...)*

## Consensus ([N]/[total] experts agree)
[1-2 sentence consensus statement]

## Active disagreements
[bullet each notable disagreement between experts, or "None identified" if absent]

## Evidence quality note
[1 sentence on study quality / anecdote ratio]
"""


def group_claims_by_topic(claims: list[Claim]) -> dict[str, list[Claim]]:
    grouped: dict[str, list[Claim]] = {}
    for claim in claims:
        if claim.superseded_by:
            continue
        grouped.setdefault(claim.topic, []).append(claim)
    return grouped


def meets_build_threshold(claims: list[Claim], min_experts: int, min_claims: int) -> bool:
    if len(claims) < min_claims:
        return False
    experts = {c.person for c in claims}
    return len(experts) >= min_experts


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def compile_topic_markdown(
    topic: str,
    claims: list[Claim],
    model: str,
    today: str,
    map_reduce_threshold: int = 50,
    map_chunk_size: int = 100,
) -> str:
    client = anthropic.Anthropic()
    topic_title = topic.replace("_", " ").replace("-", " ").title()
    expert_count = len({c.person for c in claims})

    if len(claims) <= map_reduce_threshold:
        claims_json = json.dumps([c.model_dump() for c in claims], indent=2)
        prompt = BUILD_PROMPT_TEMPLATE.format(
            topic=topic,
            topic_title=topic_title,
            claims_json=claims_json,
            claim_count=len(claims),
            expert_count=expert_count,
            today=today,
        )
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    # Map: summarise each expert's claims in chunks to stay within token limits
    intermediate_blocks = []
    by_expert: dict[str, list[Claim]] = {}
    for claim in claims:
        by_expert.setdefault(claim.person, []).append(claim)

    for expert_claims in by_expert.values():
        expert_name = expert_claims[0].person_name
        chunk_summaries: list[str] = []

        for chunk in _chunk(expert_claims, map_chunk_size):
            claims_json = json.dumps([c.model_dump() for c in chunk], indent=2)
            map_prompt = (
                f"Summarise {expert_name}'s position on {topic_title} "
                f"in 3-5 bullet points with source citations:\n\n{claims_json}"
            )
            map_resp = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[{"role": "user", "content": map_prompt}],
            )
            chunk_summaries.append(map_resp.content[0].text)

        intermediate_blocks.append(f"### {expert_name}\n" + "\n".join(chunk_summaries))

    # Reduce: compile final markdown from per-expert summaries
    reduce_prompt = BUILD_PROMPT_TEMPLATE.format(
        topic=topic,
        topic_title=topic_title,
        claims_json="\n\n".join(intermediate_blocks),
        claim_count=len(claims),
        expert_count=expert_count,
        today=today,
    )
    reduce_resp = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": reduce_prompt}],
    )
    return reduce_resp.content[0].text
