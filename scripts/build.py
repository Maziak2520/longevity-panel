#!/usr/bin/env python3
"""Build: compile skill from all claims."""
from __future__ import annotations
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from dotenv import load_dotenv

load_dotenv()

from pipeline.config import load_config
from pipeline.paths import resolve_path, AppPaths, startup_check
from pipeline.models import load_claims
from pipeline.build.compiler import group_claims_by_topic, meets_build_threshold, compile_topic_markdown
from pipeline.build.skill_writer import write_skill_md, TopicSummary

CONFIG_DIR = Path(__file__).parent.parent / "config"


@click.command()
def main() -> None:
    config = load_config(CONFIG_DIR)
    paths = AppPaths(
        knowledge_store=resolve_path(config.paths.knowledge_store),
        skill_output=resolve_path(config.paths.skill_output),
    )
    startup_check(paths)
    today = date.today().isoformat()

    all_claims = []
    for expert in config.active_experts:
        claims_file = paths.claims_file(expert.id)
        all_claims.extend(load_claims(claims_file))

    grouped = group_claims_by_topic(all_claims)
    topic_summaries = []

    for topic, claims in grouped.items():
        if not meets_build_threshold(claims, config.build.min_experts_to_publish, config.build.min_claims_to_publish):
            click.echo(f"  SKIP {topic}: below threshold ({len(claims)} claims, {len({c.person for c in claims})} experts)")
            continue

        click.echo(f"  Compiling {topic} ({len(claims)} claims)...")
        try:
            markdown = compile_topic_markdown(
                topic=topic,
                claims=claims,
                model=config.extraction.build_model,
                today=today,
                map_reduce_threshold=config.build.map_reduce_threshold,
            )
            topic_file = paths.skill_references_dir / f"{topic.replace('_', '-')}.md"
            topic_file.write_text(markdown)
            topic_summaries.append(TopicSummary(
                topic=topic,
                filename=topic_file.name,
                claim_count=len(claims),
                expert_count=len({c.person for c in claims}),
                last_updated=today,
            ))
        except Exception as exc:
            click.echo(f"  FAIL {topic}: {exc}")

    panel_names = [e.name for e in config.active_experts]
    write_skill_md(paths.skill_output, topic_summaries, panel_names)
    click.echo(f"\nBuild complete. {len(topic_summaries)} topic file(s) written to {paths.skill_output}")


if __name__ == "__main__":
    main()
