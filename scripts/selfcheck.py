#!/usr/bin/env python3
"""Smoke-test each enabled CLI provider with one text + one structured call."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel

from pipeline.config import load_config
from pipeline import cli_providers

CONFIG_DIR = Path(__file__).parent.parent / "config"


class Ping(BaseModel):
    ok: bool


def main() -> None:
    config = load_config(CONFIG_DIR)
    cli_providers.configure(config.api.cli_timeout_s, config.extraction.max_retries)
    enabled = [p for p, c in config.providers.items() if c.enabled]
    if not enabled:
        print("No providers enabled in config/settings.yaml.")
        return
    for provider in enabled:
        try:
            cli_providers.ensure_cli_ready(provider, config.providers)
            text = cli_providers.run_freeform(provider, None, "Reply with the word: pong", 16)
            res = cli_providers.structured_via_cli(
                provider, None, "You output JSON.",
                'Return {"ok": true}', Ping, 64,
            )
            print(f"OK  {provider}: text={text.strip()[:40]!r} structured={res}")
        except Exception as exc:  # noqa: BLE001 - report-only smoke tool
            print(f"ERR {provider}: {exc}")


if __name__ == "__main__":
    main()
