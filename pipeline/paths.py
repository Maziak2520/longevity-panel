from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass


def resolve_path(template: str) -> Path:
    case_base = os.environ.get("CASE_BASE_DIR", str(Path.home() / "C.A.S.E."))
    resolved = template.replace("${CASE_BASE_DIR}", case_base)
    return Path(resolved).expanduser()


@dataclass
class AppPaths:
    knowledge_store: Path
    skill_output: Path

    @property
    def transcripts_root(self) -> Path:
        return self.knowledge_store / "Transcripts"

    def transcripts_dir(self, expert_id: str) -> Path:
        return self.transcripts_root / expert_id

    @property
    def claims_root(self) -> Path:
        return self.knowledge_store / "Claims"

    def claims_file(self, expert_id: str) -> Path:
        return self.claims_root / f"{expert_id}.jsonl"

    def claims_lock(self, expert_id: str) -> Path:
        return self.claims_root / f"{expert_id}.jsonl.lock"

    @property
    def index_dir(self) -> Path:
        return self.knowledge_store / "Index"

    @property
    def downloaded_file(self) -> Path:
        return self.index_dir / "downloaded.json"

    @property
    def pending_file(self) -> Path:
        return self.index_dir / "pending.json"

    @property
    def failed_file(self) -> Path:
        return self.index_dir / "failed.json"

    @property
    def last_scout_file(self) -> Path:
        return self.index_dir / "last_scout.json"

    @property
    def skill_references_dir(self) -> Path:
        return self.skill_output / "references"


def startup_check(paths: AppPaths) -> None:
    for d in [
        paths.transcripts_root,
        paths.claims_root,
        paths.index_dir,
        paths.skill_output,
        paths.skill_references_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)
