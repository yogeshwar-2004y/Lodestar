# Billing

* Plans are rows in `plans` (seeded Starter/Growth/Agency) — edit prices, credits and quotas there.
* `BILLING_PROVIDER=test` (default): plan changes apply immediately via a signed test webhook through
  the same verification path as production. No payment is taken; no invoices exist.
* `BILLING_PROVIDER=stripe`: set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` and each plan's
  `provider_price_ref`; point Stripe webhooks at `/api/v1/webhooks/billing`.
* Credits: append-only `credit_ledger`; every charge has an idempotency key; crawls reserve credits
  before scheduling and refund unused credits after; `/usage` shows a reconciliation check.
