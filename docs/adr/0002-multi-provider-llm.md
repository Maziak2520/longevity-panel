# 2. Multi-provider LLM path (support OpenAI models alongside Claude)

- Status: Accepted
- Date: 2026-08-09
- Deciders: Jiri Manas
- Related: [0001](0001-route-llm-via-litellm-gateway.md)

## Context

The pipeline was hard-bound to the Anthropic SDK in two places — claim extraction
(`instructor.from_anthropic` + TOOLS mode) and topic-summary build
(`anthropic.Anthropic().messages.create`). Everything already routes through the
LiteLLM gateway (ADR 0001), which also fronts OpenAI, xAI, Groq, and others.

Benchmarking cheaper models against the Haiku extraction baseline showed
`openai/gpt-5.6-luna` is materially better on both axes: on a 5-transcript
validation it produced **130% of Haiku's claim volume at 100% valid topics** for
**~5.6× lower cost per claim**, and faster. Realising that saving requires the
pipeline to call a non-Claude model — but OpenAI's gpt-5.6 models are *reasoning*
models and **reject function-tools**, so instructor's TOOLS mode 400s; they need
JSON structured-output mode.

## Decision

Introduce a single provider seam, `pipeline/llm.py`, that both call sites use:

- `structured_extract(model, system, user, response_model, max_output_tokens)` —
  Claude → `instructor.from_anthropic` + TOOLS (unchanged behaviour); OpenAI
  (`openai/*`, `gpt-*`) → `instructor.from_openai` + **JSON** mode via the gateway's
  OpenAI-compatible endpoint.
- `complete_text(model, prompt, max_tokens, system=None)` — the freeform build
  path, same provider split.

Provider is chosen by model id (`is_openai_model`). The OpenAI path reuses the
existing gateway credentials (`ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`, targeting
`<base>/v1`) — no new secrets; it fails loud if they are unset. Model choice stays
in `config/settings.yaml` (`extraction.model`, `build_map_model`, `build_model`),
so switching a stage to Luna is a one-line config change plus scoping the virtual
key to the model.

## Consequences

Positive:
- Any gateway model is usable per stage via config; unlocks the validated ~5.6×
  extraction saving and a cheaper build map phase.
- Claude path is byte-for-byte unchanged (still anthropic-native + TOOLS).
- Reasoning-model compatibility handled centrally (JSON mode), not per call site.

Negative / trade-offs:
- Adds an OpenAI dependency surface (already an indirect gateway dep).
- The truncation-splitting fallback keys off Anthropic's `IncompleteOutputException`;
  on the OpenAI path a truncation would surface as a different error. Low risk at
  3k-token chunks, but the fallback is Claude-specific.
- Using a wildcard-only model would mis-bill at the gateway floor — must use a
  price-mapped/shadow-priced model id (gpt-5.6-luna is shadow-priced) and scope the
  key to it.

## Alternatives considered

- **Route everything through the gateway's OpenAI endpoint (drop the anthropic SDK).**
  Uniform, but changes Claude's proven path (cache_control/anthropic-native) for no
  benefit. Rejected — keep Claude native, add OpenAI only when selected.
- **Keep Haiku, don't add a provider.** Simplest, but forgoes a validated 5.6× saving.
- **DeepSeek / Groq models.** Benchmarked and rejected: DeepSeek returned empty
  structured output; Groq is throttled at 12k TPM on the current tier.

## Panel review

Skipped per user direction (iterative, user-driven change; reversible via config +
key scope). Validated empirically on 5 transcripts instead.
