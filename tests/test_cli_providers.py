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


from pipeline.config import ProviderConfig


def test_run_freeform_returns_text(monkeypatch):
    _install(monkeypatch, ["hello world"])
    assert cp.run_freeform("claude", None, "say hi", 32) == "hello world"


def test_providers_for_dedupes():
    got = cp.providers_for(["cli/claude:claude-sonnet-4-6", "cli/claude", "cli/gemini"])
    assert got == {"claude", "gemini"}


def test_ensure_cli_ready_rejects_disabled():
    with pytest.raises(SystemExit):
        cp.ensure_cli_ready("claude", {"claude": ProviderConfig(enabled=False)})


import subprocess as _subprocess


def test_structured_strips_trailing_prose(monkeypatch):
    fake = _install(monkeypatch, ['{"items": [{"a": 5}]}\n\nNote: use {x} carefully.'])
    out = cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)
    assert out.items[0].a == 5
    assert fake.calls == 1  # no wasted repair iteration


def test_structured_trailing_unbalanced_brace_not_truncation(monkeypatch):
    # Extra stray '}' in trailing prose must NOT be read as truncation.
    _install(monkeypatch, ['{"items": [{"a": 6}]} oops }'])
    out = cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)
    assert out.items[0].a == 6


def test_structured_exhausts_and_raises(monkeypatch):
    _install(monkeypatch, ['{"items": "bad"}'])  # balanced but wrong schema, forever
    with pytest.raises(cp.ProviderError):
        cp.structured_via_cli("claude", None, "sys", "user", _Resp, 256)


def _fake_completed(returncode=0, stdout="", stderr=""):
    return _subprocess.CompletedProcess(args=[], returncode=returncode,
                                        stdout=stdout, stderr=stderr)


def test_adapter_run_success(monkeypatch):
    adapter = cp.ProviderAdapter("t", "tbin", [], None, None, cp._parse_raw)
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: _fake_completed(0, "hi\n"))
    assert adapter.run(None, "u", None, 5) == "hi"


def test_adapter_run_rate_limit(monkeypatch):
    adapter = cp.ProviderAdapter("t", "tbin", [], None, None, cp._parse_raw)
    monkeypatch.setattr(cp.subprocess, "run",
                        lambda *a, **k: _fake_completed(1, "", "429 too many requests"))
    with pytest.raises(cp.RateLimited):
        adapter.run(None, "u", None, 5)


def test_adapter_run_generic_error(monkeypatch):
    adapter = cp.ProviderAdapter("t", "tbin", [], None, None, cp._parse_raw)
    monkeypatch.setattr(cp.subprocess, "run", lambda *a, **k: _fake_completed(2, "", "boom"))
    with pytest.raises(cp.ProviderError):
        adapter.run(None, "u", None, 5)


def test_adapter_run_timeout(monkeypatch):
    adapter = cp.ProviderAdapter("t", "tbin", [], None, None, cp._parse_raw)
    def _raise(*a, **k):
        raise cp.subprocess.TimeoutExpired(cmd="tbin", timeout=5)
    monkeypatch.setattr(cp.subprocess, "run", _raise)
    with pytest.raises(cp.ProviderError):
        adapter.run(None, "u", None, 5)


def _claude_envelope(result, is_error=False):
    import json as _json
    return _json.dumps({"type": "result", "is_error": is_error, "result": result})


def test_adapter_run_rescues_valid_payload_on_nonzero_exit(monkeypatch):
    # claude exits 1 due to a failing SessionEnd hook, but stdout is a valid
    # envelope — the completion succeeded and must be returned, not raised.
    adapter = cp.ProviderAdapter("claude", "claude", [], None, None, cp._parse_claude)
    monkeypatch.setattr(cp.subprocess, "run",
                        lambda *a, **k: _fake_completed(1, _claude_envelope("pong"),
                                                        "SessionEnd hook failed: Hook cancelled"))
    assert adapter.run(None, "u", None, 5) == "pong"


def test_adapter_run_nonzero_exit_empty_stdout_raises(monkeypatch):
    # Non-zero exit with no usable payload is still a real failure.
    adapter = cp.ProviderAdapter("claude", "claude", [], None, None, cp._parse_claude)
    monkeypatch.setattr(cp.subprocess, "run",
                        lambda *a, **k: _fake_completed(1, "", "some auth error"))
    with pytest.raises(cp.ProviderError):
        adapter.run(None, "u", None, 5)


def test_adapter_run_nonzero_exit_api_error_envelope_raises(monkeypatch):
    # A valid envelope with is_error=True is a real API error, not a rescue.
    adapter = cp.ProviderAdapter("claude", "claude", [], None, None, cp._parse_claude)
    monkeypatch.setattr(cp.subprocess, "run",
                        lambda *a, **k: _fake_completed(1, _claude_envelope("boom", is_error=True), ""))
    with pytest.raises(cp.ProviderError):
        adapter.run(None, "u", None, 5)


def test_adapter_run_scrubs_provider_api_env(monkeypatch):
    # A stale ANTHROPIC_API_KEY / BASE_URL (e.g. from load_dotenv) must NOT leak
    # into the CLI subprocess — otherwise claude uses metered API, not the sub.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-removed")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("LP_KEEP_ME", "keepme")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["env"] = kwargs.get("env")
        return _fake_completed(0, "hi")

    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    adapter = cp.ProviderAdapter("claude", "claude", [], None, None, cp._parse_raw)
    assert adapter.run(None, "u", None, 5) == "hi"
    env = captured["env"]
    assert env is not None
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert env.get("LP_KEEP_ME") == "keepme"  # non-provider vars are preserved
