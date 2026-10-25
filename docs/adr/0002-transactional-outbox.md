# ADR 0002 — Transactional outbox instead of direct task publishing

**Status:** accepted

Publishing to Celery inside a request risks "job sent but transaction rolled back" (or the
reverse). We insert `outbox_events` in the same transaction and relay them afterwards. Celery is
only a trigger (`aseo.relay`); Redis loss never loses work. The same relay runs in-process in
`TASK_EXECUTION=inline` mode, so local development needs no broker.
