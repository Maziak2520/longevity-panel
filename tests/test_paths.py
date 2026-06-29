import os
import pytest
from pathlib import Path
from pipeline.paths import resolve_path, AppPaths, startup_check


def test_resolve_path_expands_home():
    result = resolve_path("~/foo/bar")
    assert str(result).startswith("/")
    assert "~" not in str(result)


def test_resolve_path_substitutes_case_base_dir(monkeypatch):
    monkeypatch.setenv("CASE_BASE_DIR", "/custom/case")
    result = resolve_path("${CASE_BASE_DIR}/Family/Health")
    assert str(result) == "/custom/case/Family/Health"


def test_resolve_path_uses_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("CASE_BASE_DIR", raising=False)
    result = resolve_path("${CASE_BASE_DIR}/Family/Health")
    assert str(result).endswith("/Family/Health")
    assert "CASE_BASE_DIR" not in str(result)


def test_startup_check_creates_missing_dirs(tmp_path):
    knowledge_store = tmp_path / "Longevity"
    skill_output = tmp_path / "skills" / "health-longevity"
    paths = AppPaths(
        knowledge_store=knowledge_store,
        skill_output=skill_output,
    )
    assert not knowledge_store.exists()
    startup_check(paths)
    assert (knowledge_store / "Transcripts").exists()
    assert (knowledge_store / "Claims").exists()
    assert (knowledge_store / "Index").exists()
    assert skill_output.exists()


def test_app_paths_transcript_dir(tmp_path):
    paths = AppPaths(knowledge_store=tmp_path / "Longevity", skill_output=tmp_path / "skill")
    assert paths.transcripts_dir("brian-johnson") == tmp_path / "Longevity" / "Transcripts" / "brian-johnson"
