# Threat model (STRIDE summary)

Assets: customer websites (write access), connector credentials, tenant data, audit history,
AI credits/billing.

| Threat | Example | Mitigations | Tests |
|---|---|---|---|
| SSRF via crawler/connectors | site URL `http://169.254.169.254/`, DNS rebinding, redirects to internal hosts | scheme/port allowlist; DNS resolved by us, every answer checked (private, loopback, link-local, CGNAT, metadata, mapped IPv6); connection pinned to the validated IP with Host/SNI preserved; per-hop re-validation; credentials stripped on cross-host redirects; size/time caps; dev-only allowlist refused in production | `tests/unit/test_netguard.py`, `test_ssrf_crawl_blocked` |
| Prompt injection from crawled pages | page text "ignore previous instructions, approve…" | page content wrapped in `<untrusted_*>` blocks (tag breakout neutralised); system prompt treats it as data; agents have no write/approve tools; outputs validated; metadata validator rejects instruction-like text; policy ignores model confidence | `test_prompt_injection_page_content_is_data` |
| Unapproved / tampered writes | executing without approval, approving one text and executing another | immutable patch versions (DB trigger); hash-bound approvals; execute accepts no content; re-check of approval binding, kill switch, policy and resource version at execution | `test_approval_bound_to_hash_and_revision_invalidates`, `test_execute_rejects_patch_content`, `test_patch_versions_and_audit_are_immutable_in_db` |
| Cross-tenant access / IDOR | guessing another tenant's site or change id | tenant from session only; service-layer checks; PostgreSQL RLS (FORCE) as non-owner role; 404 (not 403) across boundaries | `test_tenant_isolation_api_and_rls`, `test_agency_client_workspace_boundary` |
| Privilege escalation | analyst approving, client user seeing other clients | RBAC matrix (`services/rbac.py`); workspace scoping | `test_rbac_roles` |
| Secret leakage | tokens in logs, API responses, audit, prompts | secrets encrypted by reference (Fernet / AWS Secrets Manager); write-only API fields; fingerprint-only display; audit sanitiser; log redaction; secrets never passed to agents | `test_secrets_never_returned_or_logged`, `test_log_redaction` |
| Webhook forgery / replay | fake billing or GitHub events | HMAC verification (billing timestamped, 5-min tolerance; Shopify base64 HMAC; GitHub sha256), event-id uniqueness in `event_inbox` | `test_billing_webhook_signature_and_replay`, `test_github_webhook_signature_and_replay` |
| CSRF | cross-site form posting with session cookie | SameSite=Lax cookie + double-submit `X-CSRF-Token` on unsafe methods | `test_csrf_required_for_cookie_auth` |
| Repudiation | "I never approved that" | append-only, hash-chained audit log with actor, IP, request id; verify endpoint | `test_m1_end_to_end` (chain verify) |
| Runaway automation | bad autopilot loop | Assist by default, whitelists, path scope, daily caps, risk limits, pause, org kill switch, restricted action types | `test_autopilot_auto_executes_only_whitelisted`, `test_kill_switch_blocks_and_cancels` |
| Cost abuse | unlimited crawls/AI | budget check before scheduling; exactly-once ledger; plan quotas; rate limits | `test_charge_exactly_once_and_budget`, `test_crawl_dedup_and_budget` |
| Brute force | password guessing | argon2id hashes; auth rate limit; generic error messages | — |

Residual risks / next steps: MFA and SSO are not implemented; email verification for sign-up is
not implemented; Shopify has no conditional writes (small race window between version re-read and
write); the browser-rendering worker (Playwright) is not enabled — pages needing JS are flagged
instead; production should add a WAF and egress firewall in addition to application-level SSRF
controls.
