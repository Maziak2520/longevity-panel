import pytest
from unittest.mock import patch

from pydantic import BaseModel

import pipeline.llm as llm
from pipeline.cli_providers import ProviderError


class _R(BaseModel):
    x: int


def test_structured_extract_parses_and_delegates():
    with patch("pipeline.llm.structured_via_cli", return_value=_R(x=1)) as m:
        out = llm.structured_extract(
            "cli/claude:claude-haiku-4-5-20251001", "sys", "usr", _R, 256)
    assert out.x == 1
    m.assert_called_once_with(
        "claude", "claude-haiku-4-5-20251001", "sys", "usr", _R, 256)


def test_structured_extract_provider_only():
    with patch("pipeline.llm.structured_via_cli", return_value=_R(x=2)) as m:
        llm.structured_extract("cli/claude", "sys", "usr", _R, 256)
    m.assert_called_once_with("claude", None, "sys", "usr", _R, 256)


def test_complete_text_parses_and_delegates():
    with patch("pipeline.llm.run_freeform", return_value="hi") as m:
        out = llm.complete_text("cli/claude:claude-sonnet-4-6", "prompt", 512, system="s")
    assert out == "hi"
    m.assert_called_once_with("claude", "claude-sonnet-4-6", "prompt", 512, "s")


def test_complete_text_default_system():
    with patch("pipeline.llm.run_freeform", return_value="ok") as m:
        llm.complete_text("cli/gemini", "p", 128)
    m.assert_called_once_with("gemini", None, "p", 128, None)


def test_rejects_non_cli_model():
    with pytest.raises(ProviderError):
        llm.complete_text("openai/gpt-5.6-luna", "p", 128)
