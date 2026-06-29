#!/usr/bin/env python3
"""Manage: add/remove/list panel experts."""
from __future__ import annotations
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

load_dotenv()

CONFIG_DIR = Path(__file__).parent.parent / "config"
EXPERTS_FILE = CONFIG_DIR / "experts.yaml"


@click.group()
def cli() -> None:
    pass


@cli.command()
def list() -> None:
    data = yaml.safe_load(EXPERTS_FILE.read_text())
    for e in data["experts"]:
        status = "active" if e["active"] else "inactive"
        click.echo(f"  [{status}] {e['name']} ({e['id']})")


@cli.command()
@click.argument("name")
@click.option("--youtube-url", prompt="YouTube channel URL", help="e.g. https://www.youtube.com/@ChannelName")
def add(name: str, youtube_url: str) -> None:
    expert_id = name.lower().replace(" ", "-").replace(".", "")
    data = yaml.safe_load(EXPERTS_FILE.read_text())
    existing_ids = [e["id"] for e in data["experts"]]
    if expert_id in existing_ids:
        click.echo(f"Expert '{expert_id}' already exists.")
        return
    new_expert = {
        "id": expert_id,
        "name": name,
        "active": True,
        "since": "2020-01-01",
        "sources": {
            "youtube": [{"url": youtube_url, "filter_topics": True}],
            "podcast": [],
        },
    }
    data["experts"].append(new_expert)
    EXPERTS_FILE.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    click.echo(f"Added {name} ({expert_id}). Run 'python scripts/rebuild_all.py' to sync.")


@cli.command()
@click.argument("expert_id")
def remove(expert_id: str) -> None:
    data = yaml.safe_load(EXPERTS_FILE.read_text())
    for expert in data["experts"]:
        if expert["id"] == expert_id:
            expert["active"] = False
            EXPERTS_FILE.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
            click.echo(f"Set {expert_id} to inactive. Run 'python scripts/build.py' to rebuild skill.")
            return
    click.echo(f"Expert '{expert_id}' not found.")


if __name__ == "__main__":
    cli()
