# Google Search Console setup

1. In Google Cloud Console create an OAuth client (Web application). Enable the **Google Search Console API**.
2. Authorized redirect URI: `{PUBLIC_WEB_URL}/api/v1/integrations/gsc/callback`.
3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Scope requested: `webmasters.readonly` only.
4. In Lodestar: **Site settings → Connect Search Console**. The flow uses PKCE and a single-use state bound to your user.
   Lodestar matches a verified property (`sc-domain:` or URL-prefix) for the site.

Sync: last 180 days by date and date+page, and 28 days by query+page, ending 3 days before today
(data is delayed). Google omits anonymised queries, so totals are not exhaustive. Lodestar never
estimates search volume; the volume column stays empty unless a paid provider is configured.

Without credentials in demo mode, "Load demo Search Console data" creates rows labelled
`demo_fixture`, shown with a "Demo data" badge everywhere.
