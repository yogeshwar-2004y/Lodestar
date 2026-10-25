# WordPress setup (companion plugin)

1. Zip `integrations/wordpress/lodestar-companion/` and upload it in **Plugins → Add New → Upload**, then activate.
   Activation adds a least-privilege role **Lodestar SEO Agent** (edit posts/pages + `lodestar_manage_seo`, no plugin/theme/user rights).
2. Create a WordPress user with that role. Under **Users → Profile → Application Passwords** create a password for Lodestar.
3. In Lodestar: **Add website → WordPress → Via the WordPress plugin**. Copy the verification token into
   **Settings → Lodestar** in WordPress, then connect with the username + application password.
4. Click **Check verification**. Writes are only possible after verification.

The plugin exposes `GET /wp-json/lodestar/v1/status|resolve|resources|seo/{id}|seo/{id}/history` and
`POST /wp-json/lodestar/v1/seo/{id}` with `expected_version` (409 on conflict) and keeps the last 50
SEO revisions per post. Disable the plugin or revoke the application password to cut access instantly.

**Local test fixture:** `make fixture` runs a server implementing the same REST contract on :8481
(username `lodestar-agent`, application password `fixture-app-password`). It is labelled "Fixture" in the UI and only allowed in demo mode.
