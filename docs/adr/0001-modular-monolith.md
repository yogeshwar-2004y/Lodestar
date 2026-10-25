# ADR 0001 — Modular monolith with background workers

**Status:** accepted

A team of 2–3 developers and a $200–500/month pilot budget favour one deployable API + one
worker image sharing the same package. Module boundaries (services, connectors, agents) are
enforced by code structure and tests rather than network calls. Splitting a module out later
(e.g. crawler workers) only requires moving its outbox handler.
