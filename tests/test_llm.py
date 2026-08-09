from unittest.mock import MagicMock, patch
import pytest
import pipeline.llm as llm


def test_is_openai_model():
    assert llm.is_openai_model("openai/gpt-5.6-luna")
    assert llm.is_openai_model("gpt-4o-mini")
    assert not llm.is_openai_model("claude-haiku-4-5-20251001")
    assert not llm.is_openai_model("claude-sonnet-4-6")


@pytest.fixture
def gateway_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_openai_client_requires_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        llm._openai_client()


def test_structured_extract_routes_openai_for_openai_model(gateway_env):
    sentinel = object()
    fake_instructor = MagicMock()
    fake_instructor.chat.completions.create.return_value = sentinel
    with patch("pipeline.llm.instructor.from_openai", return_value=fake_instructor) as from_oai, \
         patch("pipeline.llm.instructor.from_anthropic") as from_anthropic, \
         patch("pipeline.llm.OpenAI"):
        out = llm.structured_extract("openai/gpt-5.6-luna", "sys", "user", MagicMock, 100)
    assert out is sentinel
    from_oai.assert_called_once()
    from_anthropic.assert_not_called()
    # system prompt becomes a message on the OpenAI path (no `system=` kwarg)
    _, kwargs = fake_instructor.chat.completions.create.call_args
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}


def test_structured_extract_routes_anthropic_for_claude():
    sentinel = object()
    fake_instructor = MagicMock()
    fake_instructor.chat.completions.create.return_value = sentinel
    with patch("pipeline.llm.instructor.from_anthropic", return_value=fake_instructor) as from_anthropic, \
         patch("pipeline.llm.instructor.from_openai") as from_oai, \
         patch("pipeline.llm.anthropic.Anthropic"):
        out = llm.structured_extract("claude-haiku-4-5-20251001", "sys", "user", MagicMock, 100)
    assert out is sentinel
    from_anthropic.assert_called_once()
    from_oai.assert_not_called()
    _, kwargs = fake_instructor.chat.completions.create.call_args
    assert kwargs["system"] == "sys"   # Claude path passes system= directly


def test_complete_text_openai(gateway_env):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "hello"
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    with patch("pipeline.llm.OpenAI", return_value=client):
        assert llm.complete_text("openai/gpt-5.6-luna", "prompt", 50) == "hello"


def test_complete_text_anthropic():
    resp = MagicMock()
    resp.content = [MagicMock(text="world")]
    client = MagicMock()
    client.messages.create.return_value = resp
    with patch("pipeline.llm.anthropic.Anthropic", return_value=client):
        assert llm.complete_text("claude-sonnet-4-6", "prompt", 50) == "world"
