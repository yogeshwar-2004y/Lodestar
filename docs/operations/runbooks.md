# Runbooks

## Emergency: stop all changes
1. UI: **Automations → Emergency kill switch** (or `POST /api/v1/organizations/current/kill-switch?engaged=true`).
   Queued executions are cancelled; new ones are refused; running writes finish their single API call.
2. Platform-wide: set `GLOBAL_KILL_SWITCH=true` on API and workers and restart.
3. Investigate via **Audit log** (filter by change id) and `execution_runs`.

## Execution failed / dead-lettered
* `stale_resource_version`: someone edited the field after the patch was prepared. Open the change,
  **Revise** (re-reads the current value, creates v2), review, approve again.
* `dead_letter` after retries (429/5xx from the platform): check the connector (**Site settings → Test**),
  platform status, then **Retry execution** with a new approval if the patch changed.
* Outbox dead letters: `select topic, last_error from outbox_events where status='dead'`. Fix the cause and
  `update outbox_events set status='pending', attempts=0, available_at=now() where id=…`.

## Verification failed or stuck "verifying"
* Page caches/CDNs can delay the live value. Verification re-checks up to 6 times with backoff.
* If the live page never shows the value (e.g. Yoast indexables cache), purge the site/CDN cache;
  verification is re-runnable by retrying the execution. Rollback is available meanwhile.

## Rollback needs manual action
The field changed after our write, so Lodestar refuses to overwrite it. Compare the value in the
platform with the change's **Before/After**, restore manually if appropriate, and note it in the change.

## Rotate secrets
* Connector credential: re-connect with the new credential (the old blob is deleted, `rotated_at` set),
  then revoke the old credential in the platform.
* `SECRETS_ENCRYPTION_KEY`: decrypt-and-re-encrypt is required (Fernet). For AWS, rotate in Secrets Manager.
* `SECRET_KEY`: invalidates nothing persistent (sessions are opaque random tokens); rotate freely.

## Backup & restore
* Daily `pg_dump -Fc` (or managed PITR). Drill: `scripts/backup_restore_check.sh <db>` restores into a
  scratch DB and verifies row counts, every tenant's audit hash chain and ledger reconciliation.
* Snapshots/reports in object storage: enable bucket versioning.

## Data retention & deletion
* Daily job (scheduler/beat) deletes snapshots older than each org's retention (latest per page kept)
  and purges organizations 30 days after deletion was requested (secrets revoked first).

## Alerts to configure
Dead-lettered executions, verification failures, rollback failures (all create critical
notifications), outbox backlog (`pending` older than 5 min), crawl failure rate, 5xx rate, AI
provider errors, ledger reconciliation failures.
