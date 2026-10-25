# AI provider

* `AI_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=…`, optional `AI_MODEL` (default `claude-opus-5-5`).
  Calls use Pydantic structured outputs, a 90 s timeout with SDK retries, and server-side refusal
  fallback (`fallbacks: "default"`). Token usage, latency and USD cost are recorded per agent run and
  converted to credits (1 credit / 1k tokens).
* `AI_PROVIDER=deterministic` (default) — no model calls; all agent outputs come from labelled templates.
* A self-hosted model can be added by implementing `PrivateModelProvider.generate` in `aseo/ai/gateway.py`.
