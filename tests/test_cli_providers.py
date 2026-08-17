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


from pydantic import BaseModel
from instructor.core import IncompleteOutputException


class _Item(BaseModel):
    a: int


class _Resp(BaseModel):
    items: list[_Item]


class FakeAdapter:
    """Stand-in for a CLI: returns queued strings (or raises queued exceptions)."""
    def __init__(self, name, outputs):
        self.name = name
        self.outputs = list(outputs)
        self.calls = 0

    def run(self, system, user, model, timeout):
        out = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        if isinstance(out, Exception):
            raise out
        return out


def _install(monkeypatch, outputs):
    fake = FakeAdapter("claude", outputs)
    monkeypatch.setitem(cp.REGISTRY, "claude", fake)
    return fake


def test_structured_happy(monkeypatch):
    _install(monkeypatch, ['{"items": [{"a": 1}]}'])
    out = cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)
    assert out.items[0].a == 1


def test_structured_strips_fences(monkeypatch):
    _install(monkeypatch, ['```json\n{"items": [{"a": 2}]}\n```'])
    out = cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)
    assert out.items[0].a == 2


def test_structured_strips_prose(monkeypatch):
    _install(monkeypatch, ['Sure! Here you go:\n{"items": [{"a": 3}]}'])
    out = cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)
    assert out.items[0].a == 3


def test_structured_repairs_then_succeeds(monkeypatch):
    fake = _install(monkeypatch, ['{"items": "nope"}', '{"items": [{"a": 4}]}'])
    out = cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)
    assert out.items[0].a == 4
    assert fake.calls == 2


def test_structured_truncation_raises_incomplete(monkeypatch):
    _install(monkeypatch, ['{"items": [{"a": 1}, {"a": 2}'])  # unterminated
    with pytest.raises(IncompleteOutputException):
        cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)


def test_structured_rate_limit_then_success(monkeypatch):
    monkeypatch.setattr(cp.time, "sleep", lambda *_: None)
    _install(monkeypatch, [cp.RateLimited("rate limit"), '{"items": [{"a": 9}]}'])
    out = cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)
    assert out.items[0].a == 9
