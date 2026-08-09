# Architecture Decision Records

This directory records significant, hard-to-reverse decisions for the longevity
panel. One file per decision, named `NNNN-kebab-title.md`. Format: MADR/Nygard
(Status → Context → Decision → Consequences → Alternatives).

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-route-llm-via-litellm-gateway.md) | Route LLM calls through the LiteLLM gateway | Accepted |
| [0002](0002-multi-provider-llm.md) | Multi-provider LLM path (OpenAI models alongside Claude) | Accepted |
