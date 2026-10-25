# Shopify setup

Option A — custom app (single store): in Shopify admin **Settings → Apps → Develop apps**, create an
app with Admin API scopes `read_products, write_products, read_content, write_content`, install it,
copy the Admin API access token, and paste it in Lodestar (**Add website → Shopify**).

Option B — OAuth (multiple stores): create an app in the Shopify Partner dashboard,
set the redirect URL to `{PUBLIC_WEB_URL}/api/v1/integrations/shopify/callback`, and configure
`SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET` (and optionally `SHOPIFY_API_VERSION`). Lodestar validates
the callback HMAC, the single-use state and the shop domain before exchanging the code.

Webhooks: point `products/update`, `collections/update`, `pages/update` and `app/uninstalled` at
`{PUBLIC_API_URL}/api/v1/webhooks/shopify`. They are HMAC-verified and replay-protected; updates
trigger a deduplicated re-crawl; uninstall revokes stored credentials.

Verification: a site is verified through Shopify when the store's primary domain matches the site.
Supported writes: product/collection SEO title & description, page `global.title_tag` /
`global.description_tag`. Theme edits are never automated.
