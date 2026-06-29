#!/usr/bin/env python3
"""Ingest: download transcripts for all pending items."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from dotenv import load_dotenv

load_dotenv()

from pipeline.config import load_config
from pipeline.paths import resolve_path, AppPaths, startup_check
from pipeline.scout.state import StateManager
from pipeline.ingest.youtube import download_captions, clean_vtt
from pipeline.ingest.podcast import scrape_transcript

CONFIG_DIR = Path(__file__).parent.parent / "config"


@click.command()
@click.option("--limit", default=None, type=int, help="Max items to process")
def main(limit: int | None) -> None:
    config = load_config(CONFIG_DIR)
    paths = AppPaths(
        knowledge_store=resolve_path(config.paths.knowledge_store),
        skill_output=resolve_path(config.paths.skill_output),
    )
    startup_check(paths)
    state = StateManager(paths.index_dir)
    items = state.pop_pending()

    if limit:
        items = items[:limit]

    success = 0
    for item in items:
        expert_dir = paths.transcripts_dir(item.expert_id)
        expert_dir.mkdir(parents=True, exist_ok=True)
        txt_file = expert_dir / f"{item.source_id}.txt"
        meta_file = expert_dir / f"{item.source_id}.meta.json"

        try:
            if item.source_type == "youtube":
                video_id = item.source_id.removeprefix("yt-")
                vtt_path = download_captions(video_id, expert_dir)
                if vtt_path:
                    cleaned = clean_vtt(vtt_path.read_text())
                    txt_file.write_text(cleaned)
                    vtt_path.unlink()
                else:
                    click.echo(f"  SKIP (no captions): {item.title}")
                    state.add_pending(item)
                    continue

            elif item.source_type == "podcast":
                expert = next((e for e in config.active_experts if e.id == item.expert_id), None)
                pod_source = None
                if expert:
                    for p in expert.sources.podcast:
                        if p.transcript_strategy != "skip":
                            pod_source = p
                            break
                if pod_source and pod_source.transcript_url_pattern:
                    slug = item.url.rstrip("/").split("/")[-1]
                    transcript_url = pod_source.transcript_url_pattern.replace("{slug}", slug)
                    text = scrape_transcript(transcript_url, selector=".transcript-content, .episode-transcript, article")
                    if text:
                        txt_file.write_text(text)
                    else:
                        click.echo(f"  SKIP (scrape failed): {item.title}")
                        continue
                else:
                    click.echo(f"  SKIP (no transcript strategy): {item.title}")
                    continue

            meta_file.write_text(json.dumps({
                "source_id": item.source_id,
                "expert_id": item.expert_id,
                "source_type": item.source_type,
                "title": item.title,
                "url": item.url,
                "published_date": item.published_date,
            }, indent=2))

            state.mark_downloaded(item.source_id, item.expert_id, item.source_type, item.url)
            success += 1
            click.echo(f"  OK: {item.title[:60]}")

        except Exception as exc:
            click.echo(f"  FAIL: {item.title[:60]} — {exc}")
            state.add_failed(item.source_id, "ingest_error", str(exc))

    click.echo(f"\nIngest complete. {success}/{len(items)} downloaded.")


if __name__ == "__main__":
    main()
