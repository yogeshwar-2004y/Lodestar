"""robots.txt parsing per RFC 9309 (groups, Allow/Disallow with * and $, longest match wins)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)
    crawl_delay: float | None = None


@dataclass
class Robots:
    groups: list[_Group] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    raw: str = ""
    # When robots.txt is unreachable with a 5xx we must assume full disallow (RFC 9309 2.3.1.4).
    disallow_all: bool = False

    def _group_for(self, user_agent: str) -> _Group | None:
        token = user_agent.split("/")[0].lower()
        best: _Group | None = None
        best_len = -1
        for g in self.groups:
            for a in g.agents:
                a_l = a.lower()
                if a_l != "*" and a_l in token and len(a_l) > best_len:
                    best, best_len = g, len(a_l)
        if best:
            return best
        for g in self.groups:
            if "*" in g.agents:
                return g
        return None

    def allowed(self, url: str, user_agent: str) -> bool:
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if path == "/robots.txt":
            return True
        group = self._group_for(user_agent)
        if not group:
            return True
        verdict, match_len = True, -1
        for allow, pattern in group.rules:
            if pattern == "":
                continue
            if _match(pattern, path):
                plen = len(pattern)
                if plen > match_len or (plen == match_len and allow):
                    verdict, match_len = allow, plen
        return verdict

    def crawl_delay(self, user_agent: str) -> float | None:
        group = self._group_for(user_agent)
        return group.crawl_delay if group else None


def _match(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = "^" + ".*".join(re.escape(p) for p in pattern.split("*"))
    if anchored:
        regex += "$"
    return re.match(regex, path) is not None


def parse_robots(text: str) -> Robots:
    robots = Robots(raw=text[:500_000])
    current: _Group | None = None
    last_was_agent = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = _Group()
                robots.groups.append(current)
            current.agents.append(value)
            last_was_agent = True
            continue
        last_was_agent = False
        if key == "sitemap":
            robots.sitemaps.append(value)
        elif current is None:
            continue
        elif key in ("allow", "disallow"):
            current.rules.append((key == "allow", value))
        elif key == "crawl-delay":
            try:
                current.crawl_delay = min(float(value), 30.0)
            except ValueError:
                pass
    return robots
