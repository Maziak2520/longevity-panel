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
