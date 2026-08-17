# CLI-subscription LLM path (drop LiteLLM gateway)

- Date: 2026-08-17
- Status: Approved design, pre-implementation
- Author: Jiri Manas (with Claude)
- Related: ADR [0001](../../adr/0001-route-llm-via-litellm-gateway.md), [0002](../../adr/0002-multi-provider-llm.md), ADR 0003 (this change)

## Problem

The pipeline pays **metered API spend** through the LiteLLM gateway (ADR 0001/0002)
against a self-imposed `api.monthly_spend_limit_usd: 20` cap. That cap is now
being hit, so extraction/build calls fail mid-run. Meanwhile the operator holds
paid **subscriptions** (Claude **Max 20×**, x.ai, Google, soon Codex) whose
capacity sits unused. The `litellm` node is also currently offline (last seen 28d).

**Goal:** route the pipeline's LLM work through subscription-backed **agentic CLIs**
(headless mode, OAuth-authenticated by the subscription) instead of metered API
keys — eliminating per-call dollar spend. Claude is the only active provider at
cutover; the others are wired but disabled.

## Non-goals

- No change to what the pipeline extracts/builds or its data contracts.
- No concurrency/throughput rework (calls stay sequential — see Rate limits).
- No Cloudflare direct-API path built now; only a named seam for the future.
- Grok/Codex/Gemini/Kimi adapters are scaffolded but unverified and off.

## Constraints & reality

- **Constraint flips from dollars → rate limits.** Max 20× uses 5-hour rolling +
  weekly usage windows. Sequential calls + existing resumability (dead-letter,
  incremental build cache) keep runs within the window; a paused run resumes next
  cron tick with no lost work.
- **Structured output is prompt-enforced, not tool-enforced.** CLIs don't expose
  `instructor` tool/JSON mode; we prompt for JSON and validate+repair ourselves.
- **ToS grey area** (named, accepted by operator). Claude Code headless is the
  most defensible — it is designed for scripting/CI.
- **Execution host = this code-server container.** `claude/gemini/codex/grok` are
  installed here and `claude` is authenticated; the pipeline runs here via
  supercronic `~/.crontab`. No remote deploy.

## Current schedule (supercronic `~/.crontab`, for reference)

| Job | Cron | Runs | LLM load |
|-----|------|------|----------|
| scout | `0 9 * * *` | `scout.py` | none |
| weekly | `0 10 * * 0` | `ingest → extract → build` (incremental) | main load |
| monthly force | `0 11 1 * *` | `rebuild_all.py` → `build --force` | burst — paced by sequential calls |

The monthly `--force` recompiles every topic through the build model; sequential
CLI calls naturally drip it across the Max window. No cron change required, but
the monthly force is flagged as an op-item to revisit (below).

## Design

### Seam preserved
`pipeline/llm.py` keeps its two public functions with **identical signatures**, so
`extractor.py`, `compiler.py`, and all scripts are untouched:
- `structured_extract(model, system, user, response_model, max_output_tokens) -> T`
- `complete_text(model, prompt, max_tokens, system=None) -> str`

Only the internals change: dispatch on a `cli/` model-id prefix to a new
`pipeline/cli_providers.py` registry instead of the Anthropic SDK / gateway.

### Model-id scheme
`cli/<provider>[:<model>]`. Examples:
- `cli/claude` → default Claude model
- `cli/claude:claude-haiku-4-5-20251001` → pin Haiku (cheap/fast, conserves window)
- `cli/claude:claude-sonnet-4-6` → pin Sonnet (build reduce quality)

`llm.py` parses the prefix; a non-`cli/` id raises a clear error naming the two
options (configure a `cli/` provider, or the unbuilt Cloudflare `direct/` seam).
This is the deliberate removal of the metered/gateway path.

### Provider registry (`pipeline/cli_providers.py`)
A dict `provider -> ProviderAdapter`, each knowing: binary, argv-builder
(system+user+model → command), stdin handling, output-parser (extract the model's
text from the CLI's JSON envelope), and `enabled`. Adapters:

| provider | invocation (headless) | text extraction | enabled |
|----------|----------------------|-----------------|---------|
| claude | `claude -p --output-format json --model <m> --system-prompt <s>` (user on stdin), **tools disabled, neutral cwd** | `.result` from JSON envelope | **yes** |
| gemini | `gemini -p <prompt> -m <m> -o json` | `.response` from JSON | no |
| codex  | `codex exec -m <m> <prompt>` | last message text | no |
| grok   | `grok <prompt>` (TUI-first — best-effort) | raw stdout | no |
| kimi   | not installed — placeholder | — | no |

**Claude gotcha (must verify in impl):** `claude -p` is an agent with tool access.
Invoke it as a pure completion — disable tools (e.g. `--disallowedTools "*"` or
equivalent) and run in a neutral working directory — so it never reads/edits repo
files. This is a build-time verification item.

### Structured output: `structured_via_cli(...)`
1. Append the Pydantic JSON schema to the user prompt ("return ONLY JSON matching
   this schema, no prose").
2. Run the adapter; get the model's text.
3. Strip code fences / leading prose; `response_model.model_validate_json()`.
4. **On validation failure:** retry with a repair prompt including the exact
   validation error, up to `max_retries`.
5. **On detected truncation** (unterminated JSON / stop-reason=max_tokens):
   raise `instructor.core.IncompleteOutputException` — the SAME exception
   `extract_claims_splitting` already catches — so the half-split fallback keeps
   working unchanged. This is the key compatibility hinge.

`complete_text` (build path) is a thin freeform wrapper over the adapter (no
schema, no repair loop).

### Rate-limit handling
The CLI layer detects usage-limit signals (non-zero exit + known strings /
retry-after) and backs off with generous waits (longer than the current 60s cap,
honoring any retry-after hint) before surfacing. On exhaustion it raises a normal
exception, which the existing `tenacity` retry in `extractor.py` and the
dead-letter/`unextracted` resumption handle. A per-call `api.cli_timeout_s` bounds
hangs. **All failures log loudly** — directly closing the ADR-0001 silent-401 gap.

### Config (`config/settings.yaml` + `pipeline/config.py`)
```yaml
extraction:
  model: "cli/claude:claude-haiku-4-5-20251001"   # extraction: high-volume, cheap/fast
  build_model: "cli/claude:claude-sonnet-4-6"      # reduce: quality
  build_map_model: "cli/claude:claude-haiku-4-5-20251001"
  # ... chunking/retry fields unchanged ...
providers:                 # new registry; only claude on
  claude: { enabled: true }
  gemini: { enabled: false }
  codex:  { enabled: false }
  grok:   { enabled: false }
api:
  cli_timeout_s: 180
  extract_limit: null
  # monthly_spend_limit_usd: removed (no metered spend)
```
`pipeline/config.py`: add a `providers` model + `ApiConfig.cli_timeout_s`; remove
`monthly_spend_limit_usd`. Update `test_config.py` fixtures (3 sites).

### Preflight (`scripts/extract.py`, `scripts/build.py`)
Replace the `ANTHROPIC_API_KEY` env check with `ensure_cli_ready(provider)`:
binary on PATH + a cheap auth probe; fail with an actionable message
("run `claude login`"). Drop `load_dotenv`-gated gateway creds.

### Removed / seams
- **Removed:** LiteLLM gateway dep (`ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY`),
  `instructor.from_openai`/`openai` gateway path, `is_openai_model`, the $20 cap.
  (`instructor` stays only for `IncompleteOutputException`.)
- **Seam left unbuilt:** a `direct/<provider>` model-id branch that would target a
  **Cloudflare-fronted private endpoint** for any future raw-API need. Documented,
  not implemented.

## Testing

- Unit-test `structured_via_cli` with a monkeypatched adapter returning canned
  strings: clean JSON, fenced JSON, prose-then-JSON, garbage-then-valid (repair
  path), and truncated JSON (must raise `IncompleteOutputException`). No network.
- Unit-test model-id parsing (`cli/claude`, `cli/claude:model`, bad id raises).
- `--selfcheck` command: one real tiny call per enabled provider.
- Existing `tests/` (config, compiler, paths) updated to the new config shape and
  kept green.

## Risks

- **ToS grey area** — accepted; Claude headless most defensible.
- **Monthly `--force` window burn** — mitigated by sequential pacing + resumability;
  op-item: consider splitting/spreading the monthly force, or dropping it in favor
  of incremental (which already catches prompt-format changes on changed topics).
- **Prompt-enforced JSON < tool-enforced** — mitigated by validate+repair + the
  truncation→split hinge.
- **Claude-agent side effects** — mitigated by disabling tools + neutral cwd
  (must verify).
- **Non-Claude adapters unverified** — off at cutover; each needs its own
  invocation/parse verification before enabling.

## Open op-items (not blocking)

1. Revisit the monthly `0 11 1 * *` force rebuild once cutover is stable.
2. Build the Cloudflare `direct/` path if/when a raw-API need appears.
3. Verify + enable gemini/codex adapters as fallback providers for window relief.
