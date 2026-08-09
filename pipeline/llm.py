"""Provider abstraction so the pipeline can run any model on the LiteLLM gateway.

Two providers, chosen by model id:
- Anthropic models (``claude-*``) go through the anthropic SDK with instructor's
  TOOLS mode — the long-standing path, unchanged in behaviour.
- OpenAI models (``openai/*`` / ``gpt-*``, e.g. ``openai/gpt-5.6-luna``) go through
  the gateway's OpenAI-compatible endpoint with instructor's JSON mode. gpt-5.6 are
  reasoning models and OpenAI rejects function-tools on them, so JSON structured
  output is required — TOOLS mode 400s.

Both reuse the gateway credentials already in the environment (ADR 0001):
``ANTHROPIC_BASE_URL`` + ``ANTHROPIC_API_KEY``. The OpenAI path targets
``<ANTHROPIC_BASE_URL>/v1``. No new secrets; the virtual key must be scoped to the
models used.
"""
from __future__ import annotations
import os
from typing import TypeVar

import anthropic
import instructor
from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def is_openai_model(model: str) -> bool:
    return model.startswith("openai/") or model.startswith("gpt-")


def _openai_client() -> OpenAI:
    base = os.environ.get("ANTHROPIC_BASE_URL", "")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not base or not key:
        raise RuntimeError(
            "OpenAI-path models need ANTHROPIC_BASE_URL and ANTHROPIC_API_KEY (the LiteLLM "
            "gateway URL + a virtual key scoped to the model). Set them in .env."
        )
    return OpenAI(base_url=f"{base.rstrip('/')}/v1", api_key=key)


def structured_extract(model: str, system: str, user: str, response_model: type[T],
                       max_output_tokens: int) -> T:
    """Return a validated ``response_model`` instance from the given model."""
    if is_openai_model(model):
        client = instructor.from_openai(_openai_client(), mode=instructor.Mode.JSON)
        return client.chat.completions.create(
            model=model, max_tokens=max_output_tokens, response_model=response_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
    client = instructor.from_anthropic(anthropic.Anthropic())
    return client.chat.completions.create(
        model=model, max_tokens=max_output_tokens, system=system, response_model=response_model,
        messages=[{"role": "user", "content": user}],
    )


def complete_text(model: str, prompt: str, max_tokens: int, system: str | None = None) -> str:
    """Freeform text completion across providers (used by the build compiler)."""
    if is_openai_model(model):
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        resp = _openai_client().chat.completions.create(
            model=model, max_tokens=max_tokens, messages=msgs)
        return resp.choices[0].message.content or ""
    resp = anthropic.Anthropic().messages.create(
        model=model, max_tokens=max_tokens,
        **({"system": system} if system else {}),
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text
