from __future__ import annotations
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoMeta:
    video_id: str
    title: str
    description: str
    upload_date: str  # YYYYMMDD

    @property
    def source_id(self) -> str:
        return f"yt-{self.video_id}"

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def iso_date(self) -> str:
        d = self.upload_date
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def list_channel_videos(channel_url: str, since: str) -> list[VideoMeta]:
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--print", '{"id": "%(id)s", "title": "%(title)s", "description": "%(description)s", "upload_date": "%(upload_date)s"}',
            channel_url,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    since_compact = since.replace("-", "")
    videos = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get("upload_date", "00000000") >= since_compact:
                videos.append(VideoMeta(
                    video_id=data["id"],
                    title=data.get("title", ""),
                    description=data.get("description", ""),
                    upload_date=data.get("upload_date", "00000000"),
                ))
        except json.JSONDecodeError:
            continue
    return videos


def download_captions(video_id: str, output_dir: Path) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "yt-dlp",
            "--write-auto-subs",
            "--sub-format", "vtt",
            "--sub-langs", "en",
            "--skip-download",
            "--output", str(output_dir / "%(id)s"),
            f"https://www.youtube.com/watch?v={video_id}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    vtt_candidates = list(output_dir.glob(f"{video_id}*.vtt"))
    return vtt_candidates[0] if vtt_candidates else None


def clean_vtt(vtt_content: str) -> str:
    lines = vtt_content.splitlines()
    cleaned_lines = []
    seen = set()
    for line in lines:
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}", line):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line not in seen:
            seen.add(line)
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)
