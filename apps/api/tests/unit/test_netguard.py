import ipaddress

import pytest

from aseo.crawler import netguard
from aseo.crawler.netguard import BlockedDestination, ip_is_forbidden, resolve_safe, validate_url


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.1.1",
     "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:169.254.169.254", "224.0.0.1", "2002:7f00:1::"],
)
def test_forbidden_ips(ip):
    assert ip_is_forbidden(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", ["93.184.216.34", "2606:4700:4700::1111", "8.8.8.8"])
def test_public_ips(ip):
    assert not ip_is_forbidden(ipaddress.ip_address(ip))


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "gopher://a.com/", "http://localhost/", "http://metadata.google.internal/",
     "http://a.com:22/", "http://user:pw@a.com/", "http://foo.localhost/"],
)
def test_validate_url_blocks(url):
    with pytest.raises(BlockedDestination):
        validate_url(url)


def test_resolve_blocks_private_literal_and_dns(monkeypatch):
    with pytest.raises(BlockedDestination):
        resolve_safe("127.0.0.1", 80)

    def fake_getaddrinfo(host, port, type=0):  # noqa: A002
        # mixed answer — one public, one internal (rebinding style)
        return [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("10.0.0.1", port))]

    monkeypatch.setattr(netguard.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(BlockedDestination):
        resolve_safe("rebind.example", 80)


def test_allowlist_only_for_listed_host(monkeypatch):
    from aseo.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "crawler_allowed_private_hosts", ["127.0.0.1:8481"])
    assert resolve_safe("127.0.0.1", 8481) == "127.0.0.1"
    validate_url("http://127.0.0.1:8481/")
    with pytest.raises(BlockedDestination):
        resolve_safe("127.0.0.1", 8482)
    with pytest.raises(BlockedDestination):
        validate_url("http://127.0.0.1:6379/")
