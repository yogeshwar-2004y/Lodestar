"""SSRF-safe outbound HTTP.

Every request (including each redirect hop):
1. accepts only http/https and ports 80/443 (plus explicit dev allowlist);
2. resolves DNS itself and rejects private, loopback, link-local, multicast, reserved,
   unspecified, CGNAT, and cloud-metadata addresses (IPv4 and IPv6, incl. mapped forms);
3. connects to the *validated IP* (pinning), sending the original Host header and TLS SNI,
   so a DNS answer cannot change between validation and connection (rebinding);
4. caps response size and total time.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from aseo.core.config import get_settings

ALLOWED_PORTS = {80, 443}
METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data", "metadata.azure.com"}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class BlockedDestination(Exception):
    """The URL resolves to a destination we refuse to contact."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    redirect_chain: list[dict[str, object]] = field(default_factory=list)
    elapsed_ms: int = 0
    truncated: bool = False
    error: str | None = None

    @property
    def text(self) -> str:
        ctype = self.headers.get("content-type", "")
        charset = "utf-8"
        if "charset=" in ctype:
            charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def ip_is_forbidden(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip_is_forbidden(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return ip_is_forbidden(ip.sixtofour)
        if ip.teredo is not None:
            return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT)
        or str(ip) in {"169.254.169.254", "fd00:ec2::254"}
    )


def _allowlisted(host: str, port: int) -> bool:
    settings = get_settings()
    if settings.environment == "production":
        return False
    return f"{host}:{port}" in settings.crawler_allowed_private_hosts


def validate_url(url: str) -> tuple[str, int, str]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedDestination(f"scheme not allowed: {parts.scheme}")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise BlockedDestination("missing host")
    if parts.username or parts.password:
        raise BlockedDestination("credentials in URL not allowed")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if host in METADATA_HOSTS or host.endswith(".internal") or host == "localhost" or host.endswith(".localhost"):
        if not _allowlisted(host, port):
            raise BlockedDestination(f"host not allowed: {host}")
    if port not in ALLOWED_PORTS and not _allowlisted(host, port):
        raise BlockedDestination(f"port not allowed: {port}")
    return host, port, parts.scheme


def resolve_safe(host: str, port: int) -> str:
    """Resolve and return one validated IP for host. Raises BlockedDestination."""
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        candidates = [literal]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise BlockedDestination(f"DNS resolution failed for {host}") from exc
        candidates = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not candidates:
        raise BlockedDestination(f"no addresses for {host}")
    allow = _allowlisted(host, port)
    for ip in candidates:
        if ip_is_forbidden(ip) and not allow:
            # Reject if ANY answer is internal: prevents mixed-answer rebinding tricks.
            raise BlockedDestination(f"{host} resolves to a non-public address")
    return str(candidates[0])


async def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    max_redirects: int = 5,
    max_bytes: int | None = None,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
    user_agent: str | None = None,
    json_body: object | None = None,
) -> FetchResult:
    settings = get_settings()
    max_bytes = max_bytes or settings.crawler_max_bytes
    timeout = timeout or settings.crawler_timeout_seconds
    req_headers = {"User-Agent": user_agent or settings.crawler_user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5"}
    req_headers.update(headers or {})
    chain: list[dict[str, object]] = []
    current = url
    started = time.monotonic()
    deadline = started + timeout
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, verify=True, trust_env=False) as client:
        for _hop in range(max_redirects + 1):
            host, port, scheme = validate_url(current)
            ip = await asyncio.to_thread(resolve_safe, host, port)
            parts = urlsplit(current)
            ip_netloc = f"[{ip}]" if ":" in ip else ip
            if parts.port:
                ip_netloc += f":{parts.port}"
            pinned = urlunsplit((scheme, ip_netloc, parts.path or "/", parts.query, ""))
            hop_headers = dict(req_headers)
            hop_headers["Host"] = parts.netloc
            extensions = {"sni_hostname": host} if scheme == "https" else {}
            remaining = max(1.0, deadline - time.monotonic())
            request = client.build_request(
                method, pinned, headers=hop_headers, extensions=extensions, timeout=remaining,
                json=json_body if json_body is not None else None,
            )
            resp = await client.send(request, stream=True)
            try:
                if resp.is_redirect and "location" in resp.headers and method == "GET":
                    nxt = urljoin(current, resp.headers["location"])
                    chain.append({"url": current, "status": resp.status_code, "location": nxt})
                    if urlsplit(nxt).netloc != urlsplit(current).netloc:
                        # never forward credentials to another host
                        req_headers = {k: v for k, v in req_headers.items() if k.lower() not in ("authorization", "cookie")}
                    current = nxt
                    continue
                body = bytearray()
                truncated = False
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        truncated = True
                        del body[max_bytes:]
                        break
                return FetchResult(
                    url=url,
                    final_url=current,
                    status_code=resp.status_code,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    body=bytes(body),
                    redirect_chain=chain,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    truncated=truncated,
                )
            finally:
                await resp.aclose()
    return FetchResult(
        url=url,
        final_url=current,
        status_code=0,
        headers={},
        body=b"",
        redirect_chain=chain,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        error="too_many_redirects",
    )
