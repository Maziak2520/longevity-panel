from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TopicSummary:
    topic: str
    filename: str
    claim_count: int
    expert_count: int
    last_updated: str


def write_skill_md(skill_dir: Path, topics: list[TopicSummary], panel_members: list[str]) -> None:
    panel_line = " · ".join(panel_members)
    topic_rows = "\n".join(
        f"| {t.topic.replace('_', ' ').title()} | references/{t.filename} | {t.claim_count} | {t.expert_count} | {t.last_updated} |"
        for t in topics
    )

    content = f"""---
name: health-longevity
description: >
  Longevity panel of 12 experts. Use when asked about health protocols,
  longevity strategies, supplements, sleep, nutrition, exercise, stress recovery,
  hormones, gut health, brain health, or any question about optimising healthspan
  and lifespan. Consult this skill before making any protocol recommendation.
  Panel members: {panel_line}.
---

# health-longevity — Longevity Panel

> **Not medical advice.** This skill synthesises expert opinions for personal research. Always discuss protocol changes with your physician. For symptoms, diagnosed conditions, or prescription medications: consult a doctor first.

## Panel members

{panel_line}

## How to use this skill

1. Identify the topic(s) from the user's question (see topic map below)
2. Load the matching `references/{{topic}}.md` file(s)
3. For cross-topic questions, load all relevant files
4. Synthesise: lead with consensus, then surface disagreements, then give a protocol recommendation naming which experts back each element
5. Cite the source episode when stating a specific protocol or number
6. Flag when an expert has changed their position over time (shown in each reference file)
7. For any question involving symptoms, a diagnosed condition, or prescription drugs: respond with "This is outside the scope of this skill — consult your physician"

## Topic map

| Topic | File | Claims | Experts | Updated |
|-------|------|--------|---------|---------|
{topic_rows}

## Example consultation

**User:** "I want to add cold exposure to my morning routine — is it worth it and what protocol should I follow?"

**Approach:** Load `references/stress-recovery.md` (cold exposure is under stress_recovery), synthesise the expert positions on cold exposure specifically, lead with consensus (most advocates), surface Attia's scepticism on post-resistance timing, recommend Huberman's specific protocol, note the evidence quality.
"""
    (skill_dir / "SKILL.md").write_text(content)
