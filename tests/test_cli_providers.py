import pytest
from pipeline import cli_providers as cp


def test_parse_model_id_provider_only():
    assert cp.parse_model_id("cli/claude") == ("claude", None)


def test_parse_model_id_with_model():
    assert cp.parse_model_id("cli/claude:claude-haiku-4-5-20251001") == (
        "claude", "claude-haiku-4-5-20251001")


def test_parse_model_id_rejects_non_cli():
    with pytest.raises(cp.ProviderError):
        cp.parse_model_id("openai/gpt-5.6-luna")
