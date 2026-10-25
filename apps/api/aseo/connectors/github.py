"""GitHub connector (GitHub App).

Changes are always proposed as a branch + pull request against the configured base branch —
never pushed to the default branch. A PR is not a live deployment: verification stays
``awaiting_deploy`` until the PR is merged and the live page shows the new value (triggered by
``pull_request``/``deployment_status`` webhooks or periodic re-checks).

Framework mapping (``config.framework``):
* ``markdown-frontmatter`` — Hugo/Jekyll/Astro/Next MDX style: ``description:``/``title:`` in YAML front matter.
* ``static-html`` — edits ``<meta name="description">`` / ``<title>`` in an HTML file.
URL → file resolution uses ``config.path_map`` first, then ``config.content_root`` conventions.
"""

from __future__ import annotations

import base64
import html as htmllib
import json
import re
import time
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import jwt

from aseo.connectors.base import (
    ApplyResult,
    Capability,
    ConnectorContext,
    PreparedPatch,
    ResourceState,
    RollbackResult,
    StaleResourceError,
    VerifyResult,
    unsupported,
)
from aseo.connectors.live_check import compare, fetch_live_fields
from aseo.core.config import get_settings
from aseo.core.errors import ConnectorError

API = "https://api.github.com"
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def app_jwt() -> str:
    s = get_settings()
    if not s.github_app_id or not s.github_app_private_key:
        raise ConnectorError("GitHub App is not configured (GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY).", code="connector_not_configured")
    now = int(time.time())
    key = s.github_app_private_key.replace("\\n", "\n")
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": s.github_app_id}, key, algorithm="RS256")


class GitHubConnector:
    provider = "github"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _token(self, ctx: ConnectorContext) -> str:
        inst = ctx.config.get("installation_id")
        if not inst:
            raise ConnectorError("GitHub installation id missing.", code="connector_not_configured")
        r = await self._req("POST", f"/app/installations/{int(inst)}/access_tokens", auth=f"Bearer {app_jwt()}")
        return r["token"]

    async def _req(self, method: str, path: str, *, auth: str, body: Any = None, ok404: bool = False) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            r = await client.request(method, API + path, json=body, headers={"Authorization": auth, "Accept": "application/vnd.github+json",
                                                                              "X-GitHub-Api-Version": "2022-11-28"})
        finally:
            if self._client is None:
                await client.aclose()
        if r.status_code == 404 and ok404:
            return {}
        if r.status_code in (401, 403) and "rate limit" not in r.text.lower():
            raise ConnectorError("GitHub denied access (check app installation and repository permissions).", code="connector_unauthorized")
        if r.status_code in (403, 429) or r.status_code >= 500:
            raise ConnectorError(f"GitHub returned {r.status_code}", retryable=True)
        if r.status_code == 409 or (r.status_code == 422 and "sha" in r.text):
            raise StaleResourceError("The file changed on the base branch after the patch was prepared.")
        if r.status_code >= 400:
            raise ConnectorError(f"GitHub returned {r.status_code}: {r.json().get('message', '')[:200]}")
        return r.json() if r.content else {}

    def _repo(self, ctx: ConnectorContext) -> str:
        owner, repo = ctx.config.get("owner"), ctx.config.get("repo")
        if not owner or not repo or not re.match(r"^[\w.-]+$", f"{owner}{repo}"):
            raise ConnectorError("GitHub owner/repo missing or invalid.", code="connector_not_configured")
        return f"/repos/{owner}/{repo}"

    def _base(self, ctx: ConnectorContext) -> str:
        return str(ctx.config.get("base_branch") or "main")

    def _file_for(self, ctx: ConnectorContext, url: str) -> str:
        path = urlsplit(url).path or "/"
        mapping = ctx.config.get("path_map") or {}
        if path in mapping:
            return mapping[path]
        root = str(ctx.config.get("content_root") or ("content" if ctx.config.get("framework") != "static-html" else "public")).strip("/")
        slug = path.strip("/") or "index"
        if ctx.config.get("framework") == "static-html":
            return f"{root}/{slug}.html" if slug == "index" else f"{root}/{slug}/index.html"
        return f"{root}/{slug}.md" if slug != "index" else f"{root}/_index.md"

    # ---------------------------------------------------------------- content transforms

    @staticmethod
    def extract(framework: str, text: str) -> dict[str, str]:
        if framework == "static-html":
            d = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']', text, re.I)
            t = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
            return {"meta_description": htmllib.unescape(d.group(1)) if d else "", "title": htmllib.unescape(t.group(1).strip()) if t else ""}
        m = FRONT.match(text)
        fm = m.group(1) if m else ""

        def val(key: str) -> str:
            mm = re.search(rf"^{key}:\s*(.*)$", fm, re.M)
            return mm.group(1).strip().strip("\"'") if mm else ""

        return {"meta_description": val("description"), "title": val("title")}

    @staticmethod
    def transform(framework: str, text: str, field: str, value: str) -> str:
        if framework == "static-html":
            if field == "title":
                return re.sub(r"<title>.*?</title>", f"<title>{htmllib.escape(value)}</title>", text, count=1, flags=re.I | re.S)
            tag = f'<meta name="description" content="{htmllib.escape(value, quote=True)}">'
            if re.search(r'<meta\s+name=["\']description["\']', text, re.I):
                return re.sub(r'<meta\s+name=["\']description["\'][^>]*>', tag, text, count=1, flags=re.I)
            return re.sub(r"</head>", f"  {tag}\n</head>", text, count=1, flags=re.I)
        key = "description" if field == "meta_description" else "title"
        line = f"{key}: {json.dumps(value, ensure_ascii=False)}"
        m = FRONT.match(text)
        if not m:
            return f"---\n{line}\n---\n{text}"
        fm = m.group(1)
        fm = re.sub(rf"^{key}:.*$", line, fm, count=1, flags=re.M) if re.search(rf"^{key}:", fm, re.M) else f"{fm}\n{line}"
        return f"---\n{fm}\n---\n" + text[m.end():]

    # ---------------------------------------------------------------- protocol

    async def verify_ownership(self, ctx: ConnectorContext) -> dict[str, Any]:
        token = await self._token(ctx)
        repo = await self._req("GET", self._repo(ctx), auth=f"token {token}")
        return {"repository": repo.get("full_name"), "default_branch": repo.get("default_branch"), "homepage": repo.get("homepage"),
                "domain_match": bool(repo.get("homepage")) and ctx.site_host.split(":")[0] in str(repo.get("homepage"))}

    async def capabilities(self, ctx: ConnectorContext) -> list[Capability]:
        perms = ["GitHub App: contents read/write, pull requests read/write, metadata read (selected repository only)"]
        pre = ["Framework mapping configured", "URL maps to a file in the repository", "Deployment pipeline publishes merged changes"]
        return [
            Capability("meta_description", True, "pull_request", True, pre, perms, "Opens a PR; live only after merge + deploy. Rollback = close or revert PR."),
            Capability("title", True, "pull_request", True, pre, perms, "Opens a PR; live only after merge + deploy."),
            unsupported("structured_data", "Recommendation only in V1."),
            unsupported("internal_link", "Recommendation only in V1."),
            unsupported("redirect", "Restricted."),
        ]

    async def discover_pages(self, ctx: ConnectorContext) -> list[str]:
        return []

    async def read_resource(self, ctx: ConnectorContext, url: str) -> ResourceState:
        token = await self._token(ctx)
        path = self._file_for(ctx, url)
        data = await self._req("GET", f"{self._repo(ctx)}/contents/{quote(path)}?ref={quote(self._base(ctx))}", auth=f"token {token}", ok404=True)
        if not data:
            raise ConnectorError(f"No file at {path} on {self._base(ctx)} for this URL. Add it to the connector's path_map.", code="connector_not_found")
        text = base64.b64decode(data["content"]).decode("utf-8")
        return ResourceState(ref={"type": "file", "id": path, "url": url}, fields=self.extract(str(ctx.config.get("framework")), text),
                             version=data["sha"], url=url, extra={"text": text})

    async def prepare_patch(self, ctx: ConnectorContext, url: str, action_type: str, after: dict[str, Any]) -> PreparedPatch:
        if action_type not in ("meta_description", "title"):
            raise ConnectorError(f"GitHub connector cannot write '{action_type}'.", code="unsupported_action")
        state = await self.read_resource(ctx, url)
        return PreparedPatch(ref=state.ref, before={action_type: state.fields[action_type]}, after={action_type: after[action_type]},
                             resource_version=state.version, warnings=["Change ships as a pull request; it is not live until merged and deployed."])

    async def apply_patch(self, ctx: ConnectorContext, patch: dict[str, Any], *, expected_version: str | None, change_ref: str) -> ApplyResult:
        token = await self._token(ctx)
        auth = f"token {token}"
        repo, base = self._repo(ctx), self._base(ctx)
        state = await self.read_resource(ctx, patch["resource"]["url"])
        if expected_version and state.version != expected_version:
            raise StaleResourceError("File changed on the base branch.")
        branch = "lodestar/" + re.sub(r"[^a-z0-9-]", "-", change_ref.lower())[-48:].strip("-")
        if branch == base:
            raise ConnectorError("Refusing to write to the base branch.")
        ref = await self._req("GET", f"{repo}/git/ref/heads/{quote(base)}", auth=auth)
        await self._req("POST", f"{repo}/git/refs", auth=auth, body={"ref": f"refs/heads/{branch}", "sha": ref["object"]["sha"]})
        text = state.extra["text"]
        for field, value in patch["after"].items():
            text = self.transform(str(ctx.config.get("framework")), text, field, value)
        path = patch["resource"]["id"]
        await self._req("PUT", f"{repo}/contents/{quote(path)}", auth=auth, body={
            "message": f"SEO: update {', '.join(patch['after'])} for {urlsplit(patch['resource']['url']).path or '/'}",
            "content": base64.b64encode(text.encode()).decode(), "sha": state.version, "branch": branch})
        field = next(iter(patch["after"]))
        body = (f"Proposed by Lodestar after human approval.\n\n**Page:** {patch['resource']['url']}\n\n| | {field} |\n|---|---|\n"
                f"| Before | {patch['before'].get(field) or '_(empty)_'} |\n| After | {patch['after'][field]} |\n\nPatch ref: `{change_ref}`\n\n"
                "Lodestar will verify the live page after this is merged and deployed.")
        pr = await self._req("POST", f"{repo}/pulls", auth=auth, body={"title": f"SEO: {field.replace('_', ' ')} for {urlsplit(patch['resource']['url']).path or '/'}",
                                                                         "head": branch, "base": base, "body": body})
        return ApplyResult(applied=True, live=False, resource_version=state.version, previous=state.fields,
                           response={"pr_number": pr["number"], "branch": branch}, external_url=pr.get("html_url"))

    async def verify_patch(self, ctx: ConnectorContext, patch: dict[str, Any], apply: dict[str, Any]) -> VerifyResult:
        pr_no = (apply.get("response") or {}).get("pr_number")
        details: dict[str, Any] = {"pull_request": apply.get("external_url")}
        if pr_no:
            token = await self._token(ctx)
            pr = await self._req("GET", f"{self._repo(ctx)}/pulls/{int(pr_no)}", auth=f"token {token}")
            details.update({"pr_state": pr.get("state"), "merged": pr.get("merged")})
            if not pr.get("merged"):
                closed = pr.get("state") == "closed"
                return VerifyResult(False, not closed, "pull_request_status", patch["after"], {}, details)
        live = await fetch_live_fields(patch["resource"]["url"])
        ok, mm = compare(patch["after"], live)
        return VerifyResult(ok, not ok, "merged+live_html", patch["after"], {"live_html": {k: live.get(k) for k in patch["after"]}},
                            {**details, "live_mismatch": mm, "fetched_url": live.get("fetched_url")})

    async def rollback(self, ctx: ConnectorContext, patch: dict[str, Any], snapshot: dict[str, Any], *, current_version: str | None, change_ref: str) -> RollbackResult:
        token = await self._token(ctx)
        auth = f"token {token}"
        repo = self._repo(ctx)
        applied = snapshot.get("apply") or {}
        pr_no = (applied.get("response") or {}).get("pr_number")
        if pr_no:
            pr = await self._req("GET", f"{repo}/pulls/{int(pr_no)}", auth=auth)
            if not pr.get("merged"):
                await self._req("PATCH", f"{repo}/pulls/{int(pr_no)}", auth=auth, body={"state": "closed"})
                return RollbackResult(True, False, f"Pull request #{pr_no} closed before merge — nothing was deployed.")
        revert = await self.apply_patch(ctx, {**patch, "after": snapshot["previous_value"], "before": patch["after"]}, expected_version=None,
                                        change_ref=f"{change_ref}-revert")
        return RollbackResult(True, False, f"Revert pull request opened ({revert.external_url}); live after merge and deploy.",
                              {"pr": revert.external_url})
