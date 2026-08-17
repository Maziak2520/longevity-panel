"""Subscription-backed CLI providers (ADR 0003).

Each provider is an agentic CLI run in headless mode, authenticated by the user's
subscription (OAuth), not a metered API key. `pipeline/llm.py` dispatches here on a
`cli/<provider>[:<model>]` model id. Structured output is prompt-enforced with a
validate+repair loop; truncation re-raises instructor's IncompleteOutputException so
the existing extractor split fallback still works.
"""
from __future__ import annotations
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from instructor.core import IncompleteOutputException
from pydantic import BaseModel, ValidationError

log = logging.getLogger("pipeline.cli")
T = TypeVar("T", bound=BaseModel)

_SETTINGS = {"timeout_s": 180, "max_retries": 3}
_MAX_RATE_RETRIES = 4
_NEUTRAL_CWD = tempfile.gettempdir()

# Env vars that would flip an agentic CLI from subscription OAuth to metered API
# mode. Scrubbed from every CLI subprocess so ADR 0003's subscription auth holds
# even when a stale .env (loaded via load_dotenv) sets gateway credentials.
_SCRUB_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "GEMINI_API_KEY", "GOOGLE_API_KEY",
    "XAI_API_KEY", "GROK_API_KEY",
)


class ProviderError(RuntimeError):
    """CLI failed in a non-retryable way (bad invocation, auth, no adapter)."""


class RateLimited(ProviderError):
    """CLI reported a usage/rate limit — retry after backoff."""


def configure(timeout_s: int | None = None, max_retries: int | None = None) -> None:
    if timeout_s is not None:
        _SETTINGS["timeout_s"] = int(timeout_s)
    if max_retries is not None:
        _SETTINGS["max_retries"] = int(max_retries)


def parse_model_id(model_id: str) -> tuple[str, str | None]:
    """'cli/claude:claude-haiku-4-5' -> ('claude', 'claude-haiku-4-5')."""
    if not model_id.startswith("cli/"):
        raise ProviderError(
            f"Unsupported model id {model_id!r}. Use 'cli/<provider>[:<model>]' "
            "(subscription CLI). The Cloudflare 'direct/' path is not implemented."
        )
    provider, _, model = model_id[len("cli/"):].partition(":")
    return provider, (model or None)


_RATE_RE = re.compile(
    r"rate.?limit|usage limit|quota|429|too many requests|try again later|5-hour",
    re.IGNORECASE,
)


def _is_rate_limit(msg: str) -> bool:
    return bool(_RATE_RE.search(msg or ""))


@dataclass
class ProviderAdapter:
    name: str
    binary: str
    flags: list[str]
    model_flag: str | None
    system_flag: str | None
    parse: Callable[[str], str]
    cwd: str | None = None

    def run(self, system: str | None, user: str, model: str | None, timeout: int) -> str:
        argv = [self.binary, *self.flags]
        if model and self.model_flag:
            argv += [self.model_flag, model]
        if system and self.system_flag:
            argv += [self.system_flag, system]
            stdin = user
        else:
            stdin = f"{system}\n\n{user}" if system else user
        env = {k: v for k, v in os.environ.items() if k not in _SCRUB_ENV}
        try:
            proc = subprocess.run(
                argv, input=stdin, capture_output=True, text=True,
                timeout=timeout, cwd=self.cwd, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f"{self.name} timed out after {timeout}s") from exc
        if proc.returncode == 0:
            return self.parse(proc.stdout)
        # Non-zero exit: some CLIs (e.g. claude) return a non-zero code from an
        # unrelated environment hook even when the completion succeeded. Trust a
        # valid, non-empty parsed payload over the exit code; only treat it as a
        # real failure when no usable output came back.
        try:
            rescued = self.parse(proc.stdout)
        except Exception:
            rescued = None
        if rescued:
            return rescued
        msg = (proc.stderr or proc.stdout or "").strip()
        if _is_rate_limit(msg):
            raise RateLimited(msg)
        raise ProviderError(f"{self.name} exited {proc.returncode}: {msg[:500]}")


def _parse_claude(stdout: str) -> str:
    obj = json.loads(stdout)
    if obj.get("is_error"):
        raise ProviderError(f"claude error: {str(obj.get('result',''))[:300]}")
    return obj.get("result", "") or ""


def _parse_gemini(stdout: str) -> str:
    obj = json.loads(stdout)
    return obj.get("response", "") or ""


def _parse_raw(stdout: str) -> str:
    return stdout.strip()


# claude runs in a neutral cwd with tools effectively unusable in headless -p mode,
# so it behaves as a pure completion (validated live: is_error=false, no tool use,
# permission_denials=[], clean JSON on stdout). See ADR 0003 "Validation (live)".
REGISTRY: dict[str, ProviderAdapter] = {
    "claude": ProviderAdapter(
        "claude", "claude",
        ["-p", "--output-format", "json"], "--model", "--system-prompt",
        _parse_claude, cwd=_NEUTRAL_CWD,
    ),
    "gemini": ProviderAdapter(
        "gemini", "gemini", ["-o", "json"], "-m", None, _parse_gemini,
    ),
    "codex": ProviderAdapter(
        "codex", "codex", ["exec"], "-m", None, _parse_raw,
    ),
    "grok": ProviderAdapter(
        "grok", "grok", [], None, None, _parse_raw,
    ),
}


def _adapter(provider: str) -> ProviderAdapter:
    try:
        return REGISTRY[provider]
    except KeyError:
        raise ProviderError(
            f"No CLI adapter for provider {provider!r}. Known: {', '.join(REGISTRY)}"
        )


def _run_with_backoff(adapter: ProviderAdapter, system: str | None,
                      user: str, model: str | None) -> str:
    timeout = _SETTINGS["timeout_s"]
    delay = 30
    for i in range(_MAX_RATE_RETRIES):
        try:
            return adapter.run(system, user, model, timeout)
        except RateLimited as exc:
            if i == _MAX_RATE_RETRIES - 1:
                raise
            log.warning("%s rate-limited; backing off %ss (%s)",
                        adapter.name, delay, str(exc)[:120])
            time.sleep(delay)
            delay = min(delay * 2, 600)
    raise ProviderError(f"{adapter.name}: rate-limit retries exhausted")


_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


def _extract_json(text: str) -> str:
    """Return the first balanced JSON value (object/array), trimming leading
    fences/prose and any trailing prose. If the value never closes (truncated),
    return from the opening bracket to end-of-string so _balanced() flags it."""
    t = _FENCE.sub("", text).replace("```", "").strip()
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        return ""
    start = min(starts)
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        ch = t[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return t[start:i + 1]
    return t[start:]  # never closed → truncated; _balanced() returns False


def _balanced(s: str) -> bool:
    """Crude brace/bracket balance, ignoring string contents. Empty => False."""
    if not s:
        return False
    depth = 0
    in_str = False
    esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
    return depth == 0


def structured_via_cli(provider: str, model: str | None, system: str | None,
                       user: str, response_model: type[T], max_output_tokens: int) -> T:
    """Return a validated response_model from the provider CLI.

    Prompt-enforces JSON, validates, and repairs on validation failure up to
    max_retries. Unbalanced (truncated) JSON re-raises IncompleteOutputException
    so extract_claims_splitting can halve the chunk. max_output_tokens is accepted
    for signature compatibility but the CLIs manage their own output length.
    """
    adapter = _adapter(provider)
    schema = json.dumps(response_model.model_json_schema())
    instruction = (
        "\n\nReturn ONLY a single JSON object matching this schema. "
        "No prose, no markdown fences.\nSchema:\n" + schema
    )
    prompt = user + instruction
    last_err: Exception | None = None
    for _ in range(_SETTINGS["max_retries"]):
        text = _run_with_backoff(adapter, system, prompt, model)
        raw = _extract_json(text)
        if raw and not _balanced(raw):
            raise IncompleteOutputException()
        try:
            return response_model.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            last_err = exc
            prompt = (
                user + instruction +
                f"\n\nYour previous reply was invalid ({exc}). Return corrected JSON only."
            )
    raise ProviderError(
        f"{provider} structured output failed after "
        f"{_SETTINGS['max_retries']} attempts: {last_err}"
    )


def run_freeform(provider: str, model: str | None, prompt: str,
                 max_tokens: int, system: str | None = None) -> str:
    """Freeform text completion (build path). max_tokens accepted for signature
    compatibility; the CLI manages output length."""
    return _run_with_backoff(_adapter(provider), system, prompt, model)


def providers_for(model_ids) -> set[str]:
    return {parse_model_id(m)[0] for m in model_ids}


def ensure_cli_ready(provider: str, providers_cfg) -> None:
    """Preflight: provider enabled in config, binary present, and authenticated.
    Raises SystemExit with an actionable message on any failure."""
    cfg = providers_cfg.get(provider)
    if cfg is None or not cfg.enabled:
        raise SystemExit(
            f"Provider '{provider}' is referenced by a model id but not enabled in "
            f"config/settings.yaml (providers.{provider}.enabled: true)."
        )
    adapter = _adapter(provider)
    if shutil.which(adapter.binary) is None:
        raise SystemExit(
            f"CLI '{adapter.binary}' not found on PATH. Install it and run "
            f"`{adapter.binary} login`."
        )
    try:
        adapter.run(None, "Reply with the single word ok.", None,
                    min(60, _SETTINGS["timeout_s"]))
    except RateLimited:
        return  # reachable + authed, just throttled
    except Exception as exc:
        raise SystemExit(
            f"CLI '{adapter.binary}' is installed but not ready (auth?): {exc}. "
            f"Try `{adapter.binary} login`."
        )
