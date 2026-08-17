from __future__ import annotations
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel


class YoutubeSource(BaseModel):
    url: str
    filter_topics: bool = True


class PodcastSource(BaseModel):
    url: str
    transcript_strategy: Literal["website_scrape", "rss_tag", "whisper", "skip"] = "skip"
    transcript_url_pattern: str = ""


class ExpertSources(BaseModel):
    youtube: list[YoutubeSource] = []
    podcast: list[PodcastSource] = []


class Expert(BaseModel):
    id: str
    name: str
    active: bool
    since: str
    sources: ExpertSources


class PathsConfig(BaseModel):
    knowledge_store: str
    skill_output: str


class ExtractionConfig(BaseModel):
    model: str
    build_model: str
    build_map_model: str
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    max_output_tokens: int
    min_split_words: int
    max_retries: int
    dead_letter_after: int


class TranscriptionConfig(BaseModel):
    provider: Literal["groq", "local_whisper"]
    model: str
    use_for_youtube: bool
    use_for_podcast_audio: bool


class BuildConfig(BaseModel):
    map_reduce_threshold: int
    map_chunk_size: int
    min_experts_to_publish: int
    min_claims_to_publish: int


class ProviderConfig(BaseModel):
    enabled: bool = False


class ApiConfig(BaseModel):
    cli_timeout_s: int = 180
    extract_limit: int | None


class AppConfig(BaseModel):
    experts: list[Expert]
    topics: dict[str, list[str]]
    providers: dict[str, ProviderConfig]
    paths: PathsConfig
    extraction: ExtractionConfig
    transcription: TranscriptionConfig
    build: BuildConfig
    api: ApiConfig

    @property
    def active_experts(self) -> list[Expert]:
        return [e for e in self.experts if e.active]

    @property
    def all_topic_keywords(self) -> list[str]:
        keywords = []
        for kws in self.topics.values():
            keywords.extend(kws)
        return keywords


def load_config(config_dir: Path) -> AppConfig:
    experts_raw = yaml.safe_load((config_dir / "experts.yaml").read_text())
    topics_raw = yaml.safe_load((config_dir / "topics.yaml").read_text())
    settings_raw = yaml.safe_load((config_dir / "settings.yaml").read_text())

    experts = [Expert(**e) for e in experts_raw["experts"]]
    topics = topics_raw["topics"]

    providers = {
        name: ProviderConfig(**(spec or {}))
        for name, spec in (settings_raw.get("providers") or {}).items()
    }

    return AppConfig(
        experts=experts,
        topics=topics,
        providers=providers,
        paths=PathsConfig(**settings_raw["paths"]),
        extraction=ExtractionConfig(**settings_raw["extraction"]),
        transcription=TranscriptionConfig(**settings_raw["transcription"]),
        build=BuildConfig(**settings_raw["build"]),
        api=ApiConfig(**settings_raw["api"]),
    )
