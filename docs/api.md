# API

* Interactive docs: `http://localhost:8400/api/v1/docs` (OpenAPI 3.1 at `/api/v1/openapi.json`).
* Committed contract: `packages/contracts/openapi.json`; TypeScript types: `packages/contracts/src/schema.d.ts`
  (regenerate with `make contracts`).
* Errors: `{"error": {"code", "message", "details", "request_id"}}`.
* Auth: browser — httpOnly session cookie + `X-CSRF-Token` header (double submit); API clients —
  `Authorization: Bearer <token>` from `/auth/login`.
* Writes accept `Idempotency-Key`. A reused key with a different body returns `409 idempotency_key_reused`.
* Queued work returns `202 Accepted` with a `Location`/`status_url`.
* Lists use opaque cursors (`next_cursor`).
* Rate limits: `RATE_LIMIT_PER_MINUTE` per IP (Redis-backed when available), stricter on `/auth/*`.
