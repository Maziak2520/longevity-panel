# 1. Route LLM calls through the LiteLLM gateway

- Status: Accepted
- Date: 2026-08-02
- Deciders: Jiri Manas

## Context

The pipeline calls Claude in two places — claim extraction
(`pipeline/extract/extractor.py`) and topic-summary compilation
(`pipeline/build/compiler.py`) — both via a bare `anthropic.Anthropic()` client
that reads credentials from the environment.

From 2026-07-12 every call returned `401 – API key is invalid`: the raw
`sk-ant-...` key in `.env` had been revoked/expired. Extraction and build were
fully broken for three weeks while scout and ingest (which do not call Claude)
kept running, silently accumulating a backlog of unprocessed transcripts. The
failure produced no alert — the pipeline just logged 401s to `logs/pipeline.log`
and moved on.

A LiteLLM gateway (`https://litellm.aicognitiveleap.com`) already exists and is
the sanctioned LLM entry point for other services on this host — the
concierge-bot cut over to it on 2026-07-18 using the Anthropic-native
passthrough. Routing the panel through the same gateway centralises key
management, budget/cost tracking, and provider fallback, and removes the
per-project raw provider key.

## Decision

Route the panel's Claude calls through the LiteLLM gateway using the
**Anthropic-native passthrough**, configured entirely via environment variables
— no pipeline code change:

- `ANTHROPIC_BASE_URL=https://litellm.aicognitiveleap.com`
- `ANTHROPIC_API_KEY=<dedicated LiteLLM virtual key>`

The `anthropic` SDK honours `ANTHROPIC_BASE_URL`, so both existing
`anthropic.Anthropic()` call sites transparently target the gateway. The virtual
key is a **dedicated, panel-scoped key** with its own budget
(`settings.yaml api.monthly_spend_limit_usd: 20`), not a shared/borrowed key, so
the panel's spend is isolated and independently revocable. Credentials live only
in the gitignored `.env`; no key is ever written as a code default.

## Consequences

Positive:
- Restores extraction and build with zero application code change.
- Central key rotation: a revoked upstream key is fixed at the gateway, not in
  each repo. Per-key budget and usage visibility.
- Consistent with the concierge-bot's proven passthrough pattern.
- Anthropic-native passthrough preserves `cache_control`/model semantics (model
  names pass through unchanged).

Negative / trade-offs:
- Adds a dependency on the gateway's availability and on whoever administers it
  (dedicated keys must be minted with the gateway master key, which is not stored
  on the application host).
- Model names in `config/settings.yaml` must match what the gateway serves; a
  future gateway rename/prefix change requires a config update.
- Does not by itself fix the missing-alert gap — a dead key still fails quietly
  unless a preflight/health check is added (tracked separately).

Rollback: remove the two env lines (`ANTHROPIC_BASE_URL`, and restore a direct
`ANTHROPIC_API_KEY`) and restart. The SDK falls straight back to
`api.anthropic.com` with no code change.

## Alternatives considered

- **Rotate the raw Anthropic key, keep calling `api.anthropic.com` directly.**
  Simplest, but keeps a long-lived provider key per repo, no central budget/rotation,
  and repeats the same silent-failure exposure. Rejected in favour of the gateway
  already adopted elsewhere on the host.
- **Reuse the concierge-bot's LiteLLM key.** Fastest, but couples the panel's
  budget and blast radius to the concierge and offers no independent cost tracking.
  Rejected for isolation.
- **Introduce a provider abstraction (LiteLLM Python SDK / OpenAI-shaped calls).**
  More flexible for multi-provider fallback, but adds a dependency and code churn
  for no immediate benefit; the env-only passthrough already routes through LiteLLM.
  Deferred.

## Panel review

Cross-model panel skipped by explicit user decision — this is a contained,
reversible change (env-var routing mirroring an already-proven cutover, plus a
cron path fix), not a new security boundary.
