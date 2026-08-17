# 3. Subscription-backed CLI LLM path (drop the LiteLLM gateway)

- Status: Accepted
- Date: 2026-08-17
- Deciders: Jiri Manas
- Related: [0001](0001-route-llm-via-litellm-gateway.md), [0002](0002-multi-provider-llm.md)
- Design: [../superpowers/specs/2026-08-17-cli-subscription-llm-design.md](../superpowers/specs/2026-08-17-cli-subscription-llm-design.md)

## Context

The pipeline pays metered API spend through the LiteLLM gateway (ADR 0001/0002),
capped at `api.monthly_spend_limit_usd: 20`. That cap is now being hit, so
extraction/build calls fail mid-run. The operator holds paid subscriptions —
Claude **Max 20×**, x.ai, Google, and soon Codex — whose capacity is idle, and
the `litellm` node itself is currently offline (last seen 28d). Paying per token
while subscriptions sit unused is the wrong trade.

Subscriptions can only be driven programmatically via each vendor's **agentic CLI
in headless mode**, which authenticates through the subscription's OAuth session
rather than a metered API key: Claude Code (`claude -p`), Gemini CLI, Codex
(`codex exec`), Grok. These are installed and (for `claude`) authenticated in the
container that runs the pipeline.

## Decision

Reroute both LLM call sites through subscription CLIs, behind the **existing**
`pipeline/llm.py` seam (unchanged signatures — `structured_extract` /
`complete_text`, so `extractor.py`, `compiler.py`, and scripts are untouched):

- A new `pipeline/cli_providers.py` registry maps a provider to a headless CLI
  adapter (argv-builder + output-parser + `enabled` flag).
- Model ids become `cli/<provider>[:<model>]` (e.g. `cli/claude:claude-haiku-4-5-20251001`
  for extraction, `cli/claude:claude-sonnet-4-6` for the build reduce). `llm.py`
  dispatches on the `cli/` prefix; a non-`cli/` id fails loud.
- Structured output is prompt-enforced: inject the Pydantic schema, then
  `model_validate_json` with a repair-retry loop. Detected truncation re-raises
  `instructor.core.IncompleteOutputException`, keeping the existing
  `extract_claims_splitting` half-split fallback working unchanged.
- Rate-limit signals trigger generous CLI-layer backoff; exhaustion surfaces as a
  normal exception handled by the existing `tenacity` retry + dead-letter/resume.
  All failures log loudly.
- Only `claude` is enabled at cutover; `gemini/codex/grok` are wired but off.
- The LiteLLM gateway dependency (`ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY`), the
  `instructor.from_openai` path, and the `$20` cap are removed. Preflight becomes
  `ensure_cli_ready(provider)` (binary + auth probe) instead of the API-key check.

A `direct/<provider>` seam pointing at a future **Cloudflare-fronted** private
endpoint is named but not built, for any later raw-API need.

## Consequences

Positive:
- No metered dollar spend; the $20 cap that was breaking runs is gone.
- Uses already-paid Max 20× capacity; Claude path is a subscription, not a bill.
- Loud, actionable failures replace the ADR-0001 silent-401 class of outage.
- Provider is swappable per stage via config, as with ADR 0002.

Negative / trade-offs:
- **Constraint shifts from dollars to rate limits** (Max 5h/weekly windows);
  throughput is bounded by the window, mitigated by sequential pacing + existing
  resumability (dead-letter, incremental build cache).
- **ToS grey area** — automating a consumer subscription; Claude Code headless is
  the most defensible but the risk is named and owned.
- **Structured output is prompt-enforced, not tool-enforced** — weaker guarantee,
  mitigated by validate+repair and the truncation→split hinge.
- `claude -p` is an agent; it must be invoked with tools disabled + neutral cwd so
  it acts as a pure completion (build-time verification item).
- Non-Claude adapters are unverified until individually enabled.

## Alternatives considered

- **Raise the $20 cap / keep metered API.** Simplest, but keeps paying per token
  while subscriptions sit idle — the opposite of the goal. Rejected.
- **Keep LiteLLM, add a subscription→OpenAI-compatible shim behind it.** Minimal
  code change, but keeps the gateway (now offline) and a shim service to maintain;
  the operator explicitly wants off LiteLLM, with Cloudflare as the only direct
  path. Rejected.
- **Direct API via Cloudflare now.** Still metered spend, not subscription. Kept
  as an unbuilt future seam only.

## Validation (live)

Verified end-to-end against the live Claude **Max 20×** subscription on 2026-08-17:
`scripts/selfcheck.py` → `OK claude: text='pong' structured=ok=True`; a real
Peter-Attia transcript (163 540 chars → 9 chunks) extracted 9 + 17 = 26 valid
claims from its first two chunks (`cli/claude:claude-haiku-4-5-20251001`). Two
integration bugs surfaced only under live fire and were fixed with tests:
1. **Hook-polluted exit code** — `claude -p` returns a non-zero exit when an
   unrelated environment `SessionEnd` hook is cancelled, even on success; the
   adapter now trusts a valid parsed payload over the exit code.
2. **Gateway creds leaking via `.env`** — `load_dotenv()` put the old
   `ANTHROPIC_API_KEY`/`BASE_URL` in the environment, flipping Claude Code into
   API mode against the retired gateway; the adapter now scrubs provider-API env
   vars so the CLIs always use subscription OAuth.

## Known costs / follow-ups (not blocking)

- **Per-call overhead — largely MITIGATED (2026-08-17).** A `claude -p` call
  loads its context once per 5-minute cache window (`cache_creation`), then reads
  it cheaply on subsequent calls (`cache_creation=0`, `cache_read`). The bulk of
  that context was the built-in tool schemas, so the claude adapter now passes
  `--tools ""` (no tools — these are pure completions that never act) and
  `--strict-mcp-config` (no MCP schemas). Measured context dropped from ~17 k to
  **~2.4 k tokens** per call. Note `--system-prompt` was already ours (the default
  "coding assistant" prompt was never in play); the prompt was not the overhead,
  the tools were. `--bare` would cut the last ~2 k too but disables subscription
  auth, so it stays unused. Remaining ~2.4 k is Claude Code's irreducible base.
- **SessionEnd hook latency — RESOLVED (2026-08-17).** The user-global
  `~/.claude/settings.json` SessionStart/SessionEnd hooks run a C.A.S.E. `sync.sh`
  git push/pull on every call and, when the git op stalled to its cancellation
  timeout, dominated runtime and timed out long transcripts. The claude adapter now
  passes `--settings '{"disableAllHooks": true}'`, which skips all hooks for these
  non-interactive calls while keeping subscription OAuth (unlike `--bare`, which
  forces API-key auth). Verified live: clean stderr, no hook noise, `is_error=false`.
  Interactive Claude Code sessions are unaffected (global settings untouched).
- **`.env` cleanup (2026-08-17).** The dead gateway creds (`ANTHROPIC_BASE_URL`,
  `ANTHROPIC_API_KEY`) were removed from `.env`; only `GROQ_API_KEY` (Whisper
  transcription) and `CASE_BASE_DIR` remain. The adapter's env-scrub still guards
  against a stray key being reintroduced.

## Panel review

Skipped per user direction (user-driven, reversible: model ids + provider-enabled
flags are config; the old gateway path is recoverable from git). Cutover is
validated by `--selfcheck` + keeping the existing test suite green.
