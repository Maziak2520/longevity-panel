# CLI-subscription LLM path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the pipeline's LLM calls through subscription-backed agentic CLIs (Claude Code headless first; gemini/codex/grok wired but off), dropping the LiteLLM gateway and its metered $20 cap.

**Architecture:** Keep `pipeline/llm.py`'s two functions (`structured_extract`, `complete_text`) with identical signatures; swap their internals to dispatch on a `cli/<provider>[:<model>]` model id into a new `pipeline/cli_providers.py` registry of headless-CLI adapters. Structured output is prompt-enforced with a validate+repair loop; detected truncation re-raises `instructor.core.IncompleteOutputException` so the existing half-split fallback in `extractor.py` keeps working. Rate limits are absorbed by CLI-layer backoff plus existing tenacity/dead-letter resume.

**Tech Stack:** Python 3, Pydantic, `subprocess`, `instructor` (kept only for `IncompleteOutputException`), Claude Code / Gemini / Codex / Grok CLIs, pytest.

**Reference:** Design spec `docs/superpowers/specs/2026-08-17-cli-subscription-llm-design.md`, ADR `docs/adr/0003-cli-subscription-llm.md`.

---

### Task 1: Config schema — providers registry + CLI timeout, drop the $20 cap

**Files:**
- Modify: `pipeline/config.py` (`ApiConfig`, new `ProviderConfig`, `AppConfig`, `load_config`)
- Modify: `config/settings.yaml`
- Test: `tests/test_config.py` (3 fixtures at lines ~50, ~106, ~152)

- [ ] **Step 1: Update the test fixtures to the new config shape (failing test)**

In `tests/test_config.py`, replace **each of the three** occurrences of:
```yaml
api:
  monthly_spend_limit_usd: 20
  extract_limit: null
```
with:
```yaml
providers:
  claude:
    enabled: true
api:
  cli_timeout_s: 180
  extract_limit: null
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/coder/Devel/personal/longevity-panel && python3 -m pytest tests/test_config.py -q`
Expected: FAIL — `AppConfig` has no `providers` field / `ApiConfig` unexpected/missing keys.

- [ ] **Step 3: Update `pipeline/config.py`**

Add a provider model and adjust `ApiConfig`:
```python
class ProviderConfig(BaseModel):
    enabled: bool = False


class ApiConfig(BaseModel):
    cli_timeout_s: int = 180
    extract_limit: int | None
```
Add `providers` to `AppConfig` (after `experts`/before `paths` is fine):
```python
class AppConfig(BaseModel):
    experts: list[Expert]
    topics: dict[str, list[str]]
    providers: dict[str, ProviderConfig]
    paths: PathsConfig
    extraction: ExtractionConfig
    transcription: TranscriptionConfig
    build: BuildConfig
    api: ApiConfig
```
In `load_config`, parse providers and pass it in:
```python
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
```

- [ ] **Step 4: Update `config/settings.yaml`**

Replace the `extraction.model`/`build_model`/`build_map_model` values, add a `providers:` block, and replace the `api:` block:
```yaml
extraction:
  # Subscription CLI path (ADR 0003). Extraction + build map run on Haiku (cheap,
  # fast, conserves the Max 20x window); the final reduce uses Sonnet for quality.
  model: "cli/claude:claude-haiku-4-5-20251001"
  build_model: "cli/claude:claude-sonnet-4-6"
  build_map_model: "cli/claude:claude-haiku-4-5-20251001"
  chunk_size_tokens: 3000
  chunk_overlap_tokens: 200
  max_output_tokens: 8192
  min_split_words: 120
  max_retries: 3
  dead_letter_after: 3

# ... transcription: and build: blocks unchanged ...

providers:
  claude: { enabled: true }
  gemini: { enabled: false }
  codex:  { enabled: false }
  grok:   { enabled: false }

api:
  cli_timeout_s: 180
  extract_limit: null
```
(Leave `paths:`, `transcription:`, and `build:` exactly as they are.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/config.py config/settings.yaml tests/test_config.py
git commit -m "feat: config providers registry + cli_timeout_s, drop metered spend cap"
```

---

### Task 2: `cli_providers.py` — model-id parsing + adapter registry + run/backoff

**Files:**
- Create: `pipeline/cli_providers.py`
- Test: `tests/test_cli_providers.py`

- [ ] **Step 1: Write failing tests for `parse_model_id`**

Create `tests/test_cli_providers.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_cli_providers.py -q`
Expected: FAIL — module/attributes not defined.

- [ ] **Step 3: Create `pipeline/cli_providers.py` (parsing + registry + run + backoff)**

```python
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
# so it behaves as a pure completion. VERIFY in Task 7's smoke test that it never
# tries to touch the filesystem.
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
```

- [ ] **Step 4: Run to verify parsing tests pass**

Run: `python3 -m pytest tests/test_cli_providers.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/cli_providers.py tests/test_cli_providers.py
git commit -m "feat: cli_providers registry, model-id parsing, rate-limit backoff"
```

---

### Task 3: Structured output — `structured_via_cli` with repair + truncation split

**Files:**
- Modify: `pipeline/cli_providers.py` (append helpers + `structured_via_cli`)
- Test: `tests/test_cli_providers.py` (append)

- [ ] **Step 1: Write failing tests (happy, fenced, prose, repair, truncated)**

Append to `tests/test_cli_providers.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_cli_providers.py -q`
Expected: FAIL — `structured_via_cli`, `_extract_json`, `_balanced` not defined.

- [ ] **Step 3: Append helpers + `structured_via_cli` to `pipeline/cli_providers.py`**

```python
_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


def _extract_json(text: str) -> str:
    """Strip fences/prose and return the JSON substring (from first { or [)."""
    t = _FENCE.sub("", text).replace("```", "").strip()
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        return ""
    return t[min(starts):].strip()


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
```

- [ ] **Step 4: Run to verify all pass**

Run: `python3 -m pytest tests/test_cli_providers.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/cli_providers.py tests/test_cli_providers.py
git commit -m "feat: structured_via_cli with JSON repair loop + truncation->split"
```

---

### Task 4: Freeform completion + readiness helpers

**Files:**
- Modify: `pipeline/cli_providers.py` (append `run_freeform`, `providers_for`, `ensure_cli_ready`)
- Test: `tests/test_cli_providers.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli_providers.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_cli_providers.py -q`
Expected: FAIL — `run_freeform`/`providers_for`/`ensure_cli_ready` not defined.

- [ ] **Step 3: Append to `pipeline/cli_providers.py`**

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_cli_providers.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/cli_providers.py tests/test_cli_providers.py
git commit -m "feat: run_freeform + ensure_cli_ready/providers_for preflight"
```

---

### Task 5: Rewire `pipeline/llm.py` to the CLI seam

**Files:**
- Modify: `pipeline/llm.py` (full replace)

- [ ] **Step 1: Replace `pipeline/llm.py` entirely**

```python
"""Provider seam: route both LLM call sites to subscription-backed CLIs (ADR 0003).

Model ids are `cli/<provider>[:<model>]`; dispatch is by prefix, the work lives in
pipeline.cli_providers. Signatures are unchanged so extractor.py / compiler.py /
scripts are untouched.
"""
from __future__ import annotations
from typing import TypeVar

from pydantic import BaseModel

from pipeline.cli_providers import parse_model_id, run_freeform, structured_via_cli

T = TypeVar("T", bound=BaseModel)


def structured_extract(model: str, system: str, user: str, response_model: type[T],
                       max_output_tokens: int) -> T:
    """Return a validated response_model instance from the given `cli/...` model."""
    provider, cli_model = parse_model_id(model)
    return structured_via_cli(provider, cli_model, system, user,
                              response_model, max_output_tokens)


def complete_text(model: str, prompt: str, max_tokens: int, system: str | None = None) -> str:
    """Freeform text completion across CLI providers (used by the build compiler)."""
    provider, cli_model = parse_model_id(model)
    return run_freeform(provider, cli_model, prompt, max_tokens, system)
```

- [ ] **Step 2: Verify nothing else imports the removed symbols**

Run: `cd /home/coder/Devel/personal/longevity-panel && grep -rn "is_openai_model\|_openai_client\|from pipeline.llm import" pipeline scripts tests`
Expected: only `from pipeline.llm import structured_extract` (extractor) and `from pipeline.llm import complete_text` (compiler). No `is_openai_model`/`_openai_client` references remain.

- [ ] **Step 3: Verify imports resolve**

Run: `python3 -c "import pipeline.llm, pipeline.cli_providers; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (existing tests + new cli_providers tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/llm.py
git commit -m "feat: llm.py dispatches to CLI providers, drops gateway/openai path"
```

---

### Task 6: Preflight wiring in the entry scripts

**Files:**
- Modify: `scripts/extract.py`
- Modify: `scripts/build.py`

- [ ] **Step 1: Update `scripts/extract.py`**

Remove the top-level API-key guard (the `if not os.environ.get("ANTHROPIC_API_KEY"): raise SystemExit(...)` block) and the now-unused `import os`. Keep `load_dotenv()`. Add the CLI provider import near the other `pipeline` imports:
```python
from pipeline import cli_providers
```
In `main()`, immediately after `config = load_config(CONFIG_DIR)`:
```python
    cli_providers.configure(config.api.cli_timeout_s, config.extraction.max_retries)
    for provider in cli_providers.providers_for([config.extraction.model]):
        cli_providers.ensure_cli_ready(provider, config.providers)
```

- [ ] **Step 2: Update `scripts/build.py`**

Add near the other `pipeline` imports:
```python
from pipeline import cli_providers
```
In `main()`, immediately after `config = load_config(CONFIG_DIR)`:
```python
    cli_providers.configure(config.api.cli_timeout_s, config.extraction.max_retries)
    for provider in cli_providers.providers_for(
        [config.extraction.build_model, config.extraction.build_map_model]
    ):
        cli_providers.ensure_cli_ready(provider, config.providers)
```

- [ ] **Step 3: Verify both scripts import cleanly**

Run: `cd /home/coder/Devel/personal/longevity-panel && python3 -c "import ast; [ast.parse(open(f).read()) for f in ('scripts/extract.py','scripts/build.py')]; print('parsed ok')"`
Expected: `parsed ok`.

- [ ] **Step 4: Confirm the old API-key check is gone**

Run: `grep -n "ANTHROPIC_API_KEY\|ANTHROPIC_BASE_URL" scripts/*.py pipeline/*.py`
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add scripts/extract.py scripts/build.py
git commit -m "feat: preflight CLI provider readiness in extract/build, drop API-key gate"
```

---

### Task 7: Self-check script + real Claude smoke test

**Files:**
- Create: `scripts/selfcheck.py`

- [ ] **Step 1: Create `scripts/selfcheck.py`**

```python
#!/usr/bin/env python3
"""Smoke-test each enabled CLI provider with one text + one structured call."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel

from pipeline.config import load_config
from pipeline import cli_providers

CONFIG_DIR = Path(__file__).parent.parent / "config"


class Ping(BaseModel):
    ok: bool


def main() -> None:
    config = load_config(CONFIG_DIR)
    cli_providers.configure(config.api.cli_timeout_s, config.extraction.max_retries)
    enabled = [p for p, c in config.providers.items() if c.enabled]
    if not enabled:
        print("No providers enabled in config/settings.yaml.")
        return
    for provider in enabled:
        try:
            cli_providers.ensure_cli_ready(provider, config.providers)
            text = cli_providers.run_freeform(provider, None, "Reply with the word: pong", 16)
            res = cli_providers.structured_via_cli(
                provider, None, "You output JSON.",
                'Return {"ok": true}', Ping, 64,
            )
            print(f"OK  {provider}: text={text.strip()[:40]!r} structured={res}")
        except Exception as exc:  # noqa: BLE001 - report-only smoke tool
            print(f"ERR {provider}: {exc}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the real smoke test (Claude subscription)**

Run: `cd /home/coder/Devel/personal/longevity-panel && python3 scripts/selfcheck.py`
Expected: `OK  claude: text='pong' structured=ok=True` (or similar). **This verifies the Claude gotcha:** the CLI answered as a pure completion without touching the filesystem or hanging on a tool prompt. If it hangs or errors on tool permissions, add `--permission-mode plan` (or the current equivalent) to the claude adapter's `flags` in `pipeline/cli_providers.py` and re-run.

- [ ] **Step 3: Run one real extraction end-to-end on a tiny limit**

Run: `python3 scripts/extract.py --limit 1`
Expected: either `OK: <source_id> — N claim(s)` or a clean, loud failure logged to stdout (no silent exit). Confirms the extractor path works through the CLI.

- [ ] **Step 4: Commit**

```bash
git add scripts/selfcheck.py
git commit -m "feat: selfcheck script for enabled CLI providers"
```

---

### Task 8: Full verification + docs cross-check

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `cd /home/coder/Devel/personal/longevity-panel && python3 -m pytest -q`
Expected: all PASS.

- [ ] **Step 2: Confirm no gateway references linger**

Run: `grep -rn "litellm\|ANTHROPIC_BASE_URL\|ANTHROPIC_API_KEY\|monthly_spend_limit_usd\|instructor.from_openai\|is_openai_model" pipeline scripts config tests`
Expected: no matches (the only `instructor` use left is `IncompleteOutputException` in `pipeline/cli_providers.py`).

- [ ] **Step 3: Update the ADR status note if needed**

Confirm `docs/adr/0003-cli-subscription-llm.md` Status is `Accepted` and the design/plan links resolve. No code change.

- [ ] **Step 4: Final commit / open PR**

```bash
git push -u origin feat/cli-subscription-llm
gh pr create --title "feat: subscription CLI LLM path (drop LiteLLM gateway)" \
  --body "Implements ADR 0003. Routes extraction/build through Claude Code headless (gemini/codex/grok wired but off). Drops LiteLLM + \$20 cap; constraint shifts to Max 20x rate limits, mitigated by backoff + existing resume/dead-letter."
```

---

## Self-Review

**Spec coverage:**
- Seam preserved (llm.py signatures) — Task 5. ✓
- `cli/<provider>[:<model>]` scheme + dispatch — Tasks 2, 5. ✓
- Provider registry, claude enabled + others off — Tasks 2, 1. ✓
- Structured output prompt-enforced + repair — Task 3. ✓
- Truncation → `IncompleteOutputException` → existing split — Task 3 (verified `IncompleteOutputException()` takes no required args). ✓
- Rate-limit backoff + loud failures — Tasks 2, 4. ✓
- Config: providers block, `cli_timeout_s`, drop `monthly_spend_limit_usd` — Task 1. ✓
- Preflight `ensure_cli_ready` replaces API-key check — Tasks 4, 6. ✓
- Removed gateway/openai path — Tasks 5, 8. ✓
- Cloudflare `direct/` seam named in `parse_model_id` error — Task 2. ✓
- `--selfcheck` — Task 7. ✓
- Claude-agent side-effect gotcha verified — Task 7 Step 2. ✓
- Tests for parse/happy/fenced/prose/repair/truncated/rate-limit — Tasks 2–4. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `parse_model_id -> (provider, model|None)`, `structured_via_cli(provider, model, system, user, response_model, max_output_tokens)`, `run_freeform(provider, model, prompt, max_tokens, system=None)`, `ensure_cli_ready(provider, providers_cfg)`, `providers_for(model_ids)`, `ProviderConfig(enabled=bool)` — used consistently across llm.py, scripts, selfcheck, and tests. ✓

**Note (op-item, not in scope):** the monthly `0 11 1 * *` force rebuild in `~/.crontab` is unchanged; revisit pacing after cutover is stable (design §Open op-items).
