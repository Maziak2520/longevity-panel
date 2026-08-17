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


class ProviderError(RuntimeError):
    """CLI failed in a non-retryable way (bad invocation, auth, no adapter)."""


class RateLimited(ProviderError):
    """CLI reported a usage/rate limit — retry after backoff."""


def configure(timeout_s: int | None = None, max_retries: int | None = None) -> None:
    if timeout_s:
        _SETTINGS["timeout_s"] = int(timeout_s)
    if max_retries:
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
        try:
            proc = subprocess.run(
                argv, input=stdin, capture_output=True, text=True,
                timeout=timeout, cwd=self.cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f"{self.name} timed out after {timeout}s") from exc
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            if _is_rate_limit(msg):
                raise RateLimited(msg)
            raise ProviderError(f"{self.name} exited {proc.returncode}: {msg[:500]}")
        return self.parse(proc.stdout)


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
# so it behaves as a pure completion. VERIFY in a later task's smoke test that it
# never tries to touch the filesystem.
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
