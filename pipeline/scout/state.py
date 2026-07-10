from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class PendingItem:
    source_id: str
    expert_id: str
    source_type: str
    url: str
    title: str
    published_date: str


class StateManager:
    def __init__(self, index_dir: Path) -> None:
        self._dir = index_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._downloaded_file = self._dir / "downloaded.json"
        self._pending_file = self._dir / "pending.json"
        self._failed_file = self._dir / "failed.json"

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text())

    def _write_json(self, path: Path, data) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(path)

    def is_downloaded(self, source_id: str) -> bool:
        data = self._load_json(self._downloaded_file, {})
        return source_id in data

    def mark_downloaded(self, source_id: str, expert_id: str, source_type: str, url: str) -> None:
        data = self._load_json(self._downloaded_file, {})
        data[source_id] = {"expert_id": expert_id, "source_type": source_type, "url": url, "extracted": False}
        self._write_json(self._downloaded_file, data)

    def mark_extracted(self, source_id: str) -> None:
        data = self._load_json(self._downloaded_file, {})
        if source_id in data:
            data[source_id]["extracted"] = True
            self._write_json(self._downloaded_file, data)

    def unextracted_source_ids(self) -> list[str]:
        data = self._load_json(self._downloaded_file, {})
        return [sid for sid, meta in data.items() if not meta.get("extracted", False)]

    def add_pending(self, item: PendingItem) -> None:
        items = self._load_json(self._pending_file, [])
        items.append(asdict(item))
        self._write_json(self._pending_file, items)

    def pop_pending(self) -> list[PendingItem]:
        items = self._load_json(self._pending_file, [])
        self._write_json(self._pending_file, [])
        downloaded = self._load_json(self._downloaded_file, {})
        seen: set[str] = set()
        result = []
        for i in items:
            sid = i["source_id"]
            if sid in seen or sid in downloaded:
                continue
            seen.add(sid)
            result.append(PendingItem(**i))
        return result

    def known_source_ids(self) -> set[str]:
        downloaded = self._load_json(self._downloaded_file, {})
        pending = self._load_json(self._pending_file, [])
        failed = self._load_json(self._failed_file, {})
        return set(downloaded) | {i["source_id"] for i in pending} | set(failed)

    def add_failed(self, source_id: str, reason: str, detail: str) -> None:
        data = self._load_json(self._failed_file, {})
        data[source_id] = {"reason": reason, "detail": detail}
        self._write_json(self._failed_file, data)

    def load_failed(self) -> dict:
        return self._load_json(self._failed_file, {})

    def clear_failed(self, source_id: str | None = None) -> int:
        data = self._load_json(self._failed_file, {})
        if source_id is None:
            count = len(data)
            data = {}
        else:
            count = 1 if data.pop(source_id, None) is not None else 0
        self._write_json(self._failed_file, data)
        return count
