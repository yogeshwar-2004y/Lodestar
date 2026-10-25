# ADR 0004 — Custom typed state machine instead of LangGraph

**Status:** accepted

Our workflows are short, linear and must be auditable: crawl → audit → strategy → proposals, and
the change lifecycle. A persisted `workflow_runs.steps` list plus explicit status columns gives
resumability and inspection without another framework. Agents call bounded tools chosen by our
code and make a single structured-output model call; no open-ended tool loop is needed, which
keeps prompt-injection surface and cost low.
