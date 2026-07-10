import pytest
from pathlib import Path
from pipeline.config import load_config, AppConfig, Expert, PodcastSource


def test_load_config_returns_app_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "experts.yaml").write_text("""
experts:
  - id: test-expert
    name: Test Expert
    active: true
    since: "2020-01-01"
    sources:
      youtube:
        - url: "https://youtube.com/@test"
          filter_topics: true
      podcast: []
""")
    (config_dir / "topics.yaml").write_text("""
topics:
  sleep:
    - sleep
""")
    (config_dir / "settings.yaml").write_text("""
paths:
  knowledge_store: "/tmp/test/Longevity"
  skill_output: "/tmp/test/skills"
extraction:
  model: "claude-haiku-4-5-20251001"
  build_model: "claude-sonnet-4-6"
  chunk_size_tokens: 3000
  chunk_overlap_tokens: 200
  max_output_tokens: 8192
  min_split_words: 120
  max_retries: 3
  dead_letter_after: 3
transcription:
  provider: "groq"
  model: "whisper-large-v3"
  use_for_youtube: false
  use_for_podcast_audio: true
build:
  map_reduce_threshold: 50
  map_chunk_size: 100
  min_experts_to_publish: 2
  min_claims_to_publish: 3
api:
  monthly_spend_limit_usd: 20
  extract_limit: null
""")
    config = load_config(config_dir)
    assert isinstance(config, AppConfig)
    assert len(config.experts) == 1
    assert config.experts[0].id == "test-expert"
    assert config.experts[0].active is True


def test_load_config_filters_inactive_experts(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "experts.yaml").write_text("""
experts:
  - id: active-expert
    name: Active
    active: true
    since: "2020-01-01"
    sources:
      youtube: []
      podcast: []
  - id: inactive-expert
    name: Inactive
    active: false
    since: "2020-01-01"
    sources:
      youtube: []
      podcast: []
""")
    (config_dir / "topics.yaml").write_text("topics:\n  sleep:\n    - sleep\n")
    (config_dir / "settings.yaml").write_text("""
paths:
  knowledge_store: "/tmp/test/Longevity"
  skill_output: "/tmp/test/skills"
extraction:
  model: "claude-haiku-4-5-20251001"
  build_model: "claude-sonnet-4-6"
  chunk_size_tokens: 3000
  chunk_overlap_tokens: 200
  max_output_tokens: 8192
  min_split_words: 120
  max_retries: 3
  dead_letter_after: 3
transcription:
  provider: "groq"
  model: "whisper-large-v3"
  use_for_youtube: false
  use_for_podcast_audio: true
build:
  map_reduce_threshold: 50
  map_chunk_size: 100
  min_experts_to_publish: 2
  min_claims_to_publish: 3
api:
  monthly_spend_limit_usd: 20
  extract_limit: null
""")
    config = load_config(config_dir)
    active = config.active_experts
    assert len(active) == 1
    assert active[0].id == "active-expert"


def test_all_topic_keywords_flat(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "experts.yaml").write_text("experts: []\n")
    (config_dir / "topics.yaml").write_text("""
topics:
  sleep:
    - sleep
    - REM
  nutrition:
    - diet
""")
    (config_dir / "settings.yaml").write_text("""
paths:
  knowledge_store: "/tmp/test/Longevity"
  skill_output: "/tmp/test/skills"
extraction:
  model: "claude-haiku-4-5-20251001"
  build_model: "claude-sonnet-4-6"
  chunk_size_tokens: 3000
  chunk_overlap_tokens: 200
  max_output_tokens: 8192
  min_split_words: 120
  max_retries: 3
  dead_letter_after: 3
transcription:
  provider: "groq"
  model: "whisper-large-v3"
  use_for_youtube: false
  use_for_podcast_audio: true
build:
  map_reduce_threshold: 50
  map_chunk_size: 100
  min_experts_to_publish: 2
  min_claims_to_publish: 3
api:
  monthly_spend_limit_usd: 20
  extract_limit: null
""")
    config = load_config(config_dir)
    flat = config.all_topic_keywords
    assert "sleep" in flat
    assert "REM" in flat
    assert "diet" in flat
