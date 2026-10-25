# ADR 0006 — AI gateway with a deterministic fallback

**Status:** accepted

The product must run without paid credentials and must never let model output authorize a
write. The gateway calls Claude (`claude-opus-5-5` by default, configurable) with Pydantic
structured outputs and server-side refusal fallback, validates citations, and otherwise falls back
to labelled deterministic implementations. A `PrivateModelProvider` interface exists for
self-hosted models. Policy decisions never take model confidence as an input.
