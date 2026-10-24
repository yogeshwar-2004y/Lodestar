"""URL normalization and scope rules."""

from __future__ import annotations

import posixpath
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from aseo.core.security import sha256_hex

TRACKING_PARAMS = re.compile(r"^(utm_[a-z]+|gclid|fbclid|msclkid|mc_cid|mc_eid|_hsenc|_hsmi|ref_src)$", re.I)
DEFAULT_PORTS = {"http": 80, "https": 443}
_SAFE_PATH = "/:@!$&'()*+,;=-._~%"
SKIP_EXTENSIONS = re.compile(
    r"\.(jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff?|pdf|zip|gz|tgz|rar|7z|mp[34]|m4a|mov|avi|wmv|webm|"
    r"woff2?|ttf|otf|eot|css|js|mjs|map|json|xml|txt|csv|xlsx?|docx?|pptx?|exe|dmg|apk)$",
    re.I,
)


class InvalidURL(ValueError):
    pass


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    trailing = path.endswith("/")
    # decode then re-encode so equivalent percent-encodings collapse
    decoded = unquote(path)
    norm = posixpath.normpath(decoded)
    if norm == ".":
        norm = "/"
    if not norm.startswith("/"):
        norm = "/" + norm
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    if trailing and not norm.endswith("/"):
        norm += "/"
    return quote(norm, safe=_SAFE_PATH)


def normalize_url(url: str, base: str | None = None, *, strip_tracking: bool = True) -> str:
    """Canonical form used for deduplication.

    - resolves relative URLs against ``base``
    - lower-cases scheme and host, IDNA-encodes host, drops default ports
    - removes fragments, dot segments, tracking parameters; sorts query params
    """
    raw = url.strip()
    if base:
        raw = urljoin(base, raw)
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise InvalidURL(f"unsupported scheme: {scheme or '(none)'}")
    if not parts.hostname:
        raise InvalidURL("missing host")
    if parts.username or parts.password:
        raise InvalidURL("credentials in URL are not allowed")
    try:
        host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise InvalidURL("invalid host") from exc
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidURL("invalid port") from exc
    netloc = host if ":" not in host else f"[{host}]"
    if port and port != DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    path = _normalize_path(parts.path)
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    if strip_tracking:
        query_items = [(k, v) for k, v in query_items if not TRACKING_PARAMS.match(k)]
    query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def url_hash(normalized: str) -> str:
    return sha256_hex(normalized)


def host_key(url: str) -> str:
    """host[:port] for a normalized URL."""
    return urlsplit(url).netloc


def registrable_host(host: str) -> str:
    """Strip a leading www. so www/apex are treated as the same site."""
    host = host.split(":")[0]
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, site_host: str) -> bool:
    netloc = host_key(url)
    if ":" in site_host or ":" in netloc:
        # explicit ports must match exactly (used by local fixtures)
        return registrable_host(netloc) == registrable_host(site_host) and netloc.split(":")[1:] == site_host.split(":")[1:]
    return registrable_host(netloc) == registrable_host(site_host)


def in_path_scope(url: str, include: list[str] | None, exclude: list[str] | None) -> bool:
    path = urlsplit(url).path or "/"
    if exclude and any(path.startswith(p) for p in exclude):
        return False
    if include:
        return any(path.startswith(p) for p in include)
    return True


def is_probably_html_url(url: str) -> bool:
    return not SKIP_EXTENSIONS.search(urlsplit(url).path)


def domain_from_input(value: str) -> tuple[str, str]:
    """Accepts 'example.com', 'https://example.com/x' etc. Returns (host[:port], base_url)."""
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    norm = normalize_url(value)
    parts = urlsplit(norm)
    return parts.netloc, f"{parts.scheme}://{parts.netloc}/"
