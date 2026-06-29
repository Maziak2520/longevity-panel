#!/usr/bin/env python3
"""Extract: extract claims from new transcripts."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from dotenv import load_dotenv
from filelock import FileLock

load_dotenv()

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise SystemExit(
        "ANTHROPIC_API_KEY is not set. Add it to your .env file or environment. "
        "Get a key at https://console.anthropic.com/"
    )

from pipeline.config import load_config
from pipeline.paths import resolve_path, AppPaths, startup_check
from pipeline.scout.state import StateManager
from pipeline.extract.chunker import chunk_text
from pipeline.extract.extractor import extract_claims_from_chunk
from pipeline.extract.dedup import dedup_claims
from pipeline.models import load_claims, append_claim

CONFIG_DIR = Path(__file__).parent.parent / "config"


@click.command()
@click.option("--limit", default=None, type=int, help="Max transcripts to process")
def main(limit: int | None) -> None:
    config = load_config(CONFIG_DIR)
    extract_limit = limit or config.api.extract_limit
    paths = AppPaths(
        knowledge_store=resolve_path(config.paths.knowledge_store),
        skill_output=resolve_path(config.paths.skill_output),
    )
    startup_check(paths)
    state = StateManager(paths.index_dir)
    valid_topics = list(config.topics.keys())

    unextracted = state.unextracted_source_ids()
    if extract_limit:
        unextracted = unextracted[:extract_limit]

    expert_map = {e.id: e for e in config.active_experts}
    downloaded = json.loads(paths.downloaded_file.read_text()) if paths.downloaded_file.exists() else {}

    success = 0
    for source_id in unextracted:
        meta = downloaded.get(source_id, {})
        expert_id = meta.get("expert_id")
        if not expert_id or expert_id not in expert_map:
            continue

        expert = expert_map[expert_id]
        txt_file = paths.transcripts_dir(expert_id) / f"{source_id}.txt"
        meta_file = paths.transcripts_dir(expert_id) / f"{source_id}.meta.json"

        if not txt_file.exists():
            continue

        transcript = txt_file.read_text()
        source_meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        chunks = chunk_text(transcript, config.extraction.chunk_size_tokens, config.extraction.chunk_overlap_tokens)

        all_new_claims = []
        try:
            for chunk_idx, chunk in enumerate(chunks):
                claims = extract_claims_from_chunk(
                    chunk=chunk,
                    chunk_index=chunk_idx,
                    person_id=expert_id,
                    person_name=expert.name,
                    source_id=source_id,
                    source_title=source_meta.get("title", ""),
                    source_url=source_meta.get("url", ""),
                    source_date=source_meta.get("published_date", ""),
                    valid_topics=valid_topics,
                    model=config.extraction.model,
                )
                all_new_claims.extend(claims)
        except Exception as exc:
            click.echo(f"  FAIL: {source_id} — {exc}")
            state.add_failed(source_id, "extract_error", str(exc))
            continue

        claims_file = paths.claims_file(expert_id)
        lock_file = paths.claims_lock(expert_id)
        with FileLock(str(lock_file)):
            existing = load_claims(claims_file)
            combined = dedup_claims(existing + all_new_claims)
            content = "".join(c.model_dump_json() + "\n" for c in combined)
            tmp = claims_file.with_suffix(".jsonl.tmp")
            tmp.write_text(content)
            tmp.rename(claims_file)

        state.mark_extracted(source_id)
        success += 1
        click.echo(f"  OK: {source_id} — {len(all_new_claims)} claim(s)")

    click.echo(f"\nExtract complete. {success}/{len(unextracted)} transcripts processed.")


if __name__ == "__main__":
    main()
