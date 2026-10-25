# GitHub App setup

1. Create a GitHub App (Settings → Developer settings → GitHub Apps) with repository permissions:
   **Contents: read & write**, **Pull requests: read & write**, **Metadata: read**; subscribe to
   `pull_request` and `deployment_status`. Setup URL / callback: `{PUBLIC_WEB_URL}/api/v1/integrations/github/callback`.
   Webhook URL: `{PUBLIC_API_URL}/api/v1/webhooks/github` with a secret.
2. Configure `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY` (PEM, `\n` escaped is fine), `GITHUB_WEBHOOK_SECRET`.
3. Install the app on **only** the site repository. In Lodestar connect with owner, repo, base branch,
   installation id and the framework mapping:
   * `markdown-frontmatter` — edits `description:` / `title:` in front matter (Hugo, Jekyll, Astro, MDX).
   * `static-html` — edits `<meta name="description">` / `<title>`.
   * `path_map` (JSON) maps URL paths to files when conventions don't apply, e.g. `{"/": "src/pages/index.md"}`.

Lodestar creates a `lodestar/…` branch, commits the change and opens a PR with the before/after table.
It never pushes to the base branch. The change stays **awaiting deploy** until the PR is merged and the
live page shows the new value (re-checked on `pull_request`/`deployment_status` webhooks). Rollback
closes an unmerged PR or opens a revert PR.
