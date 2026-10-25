# ADR 0005 — Immutable patch versions and hash-bound approvals

**Status:** accepted

Patch content lives only in `patch_versions` (database trigger forbids updates). The hash covers
change id, version, site id, resource, before value, after value and resource version. Approve,
reject and execute require the caller to send the hash they reviewed; revising creates a new
version so existing approvals stop applying. `execute` accepts no patch content (`extra=forbid`).
