#!/usr/bin/env python3
"""Scout: check for new content from all active experts."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from dotenv import load_dotenv

load_dotenv()

from pipeline.config import load_config
from pipeline.paths import resolve_path, AppPaths, startup_check
from pipeline.scout.scanner import scan_expert
from pipeline.scout.state import StateManager

CONFIG_DIR = Path(__file__).parent.parent / "config"


@click.command()
@click.option("--expert-id", default=None, help="Limit to one expert ID")
def main(expert_id: str | None) -> None:
    config = load_config(CONFIG_DIR)
    paths = AppPaths(
        knowledge_store=resolve_path(config.paths.knowledge_store),
        skill_output=resolve_path(config.paths.skill_output),
    )
    startup_check(paths)
    state = StateManager(paths.index_dir)
    keywords = config.all_topic_keywords

    experts = config.active_experts
    if expert_id:
        experts = [e for e in experts if e.id == expert_id]
        if not experts:
            click.echo(f"Expert '{expert_id}' not found or inactive.")
            return

    total = 0
    for expert in experts:
        count = scan_expert(expert, state, keywords)
        if count:
            click.echo(f"  {expert.name}: {count} new item(s)")
        total += count

    now = datetime.now(timezone.utc).isoformat()
    last_scout = {"timestamp": now, "new_items_found": total}
    paths.last_scout_file.write_text(json.dumps(last_scout, indent=2))
    click.echo(f"\nScout complete. {total} new item(s) queued.")


if __name__ == "__main__":
    main()
