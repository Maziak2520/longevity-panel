#!/usr/bin/env python3
"""Full pipeline: scout → ingest → extract → build."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent


def run(script: str, *args: str) -> None:
    result = subprocess.run([sys.executable, str(SCRIPTS / script), *args], check=True)


def main() -> None:
    print("=== Longevity Panel — Full Rebuild ===")
    print("\n[1/4] Scout...")
    run("scout.py")
    print("\n[2/4] Ingest...")
    run("ingest.py")
    print("\n[3/4] Extract...")
    run("extract.py")
    print("\n[4/4] Build...")
    run("build.py")
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
