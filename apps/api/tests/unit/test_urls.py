import pytest

from aseo.crawler.urls import InvalidURL, domain_from_input, in_path_scope, normalize_url, same_site


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTP://Example.COM:80/a/../b/./c?utm_source=x&b=2&a=1#frag", "http://example.com/b/c?a=1&b=2"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:443/x/", "https://example.com/x/"),
        ("https://example.com/%7Euser", "https://example.com/~user"),
        ("https://example.com//double//slash", "https://example.com/double/slash"),
        ("https://bücher.example/", "https://xn--bcher-kva.example/"),
        ("https://example.com:8443/", "https://example.com:8443/"),
    ],
)
def test_normalize(raw, expected):
    assert normalize_url(raw) == expected


def test_relative_resolution():
    assert normalize_url("../x?gclid=1", "https://a.com/b/c/") == "https://a.com/b/x"


@pytest.mark.parametrize("bad", ["ftp://a.com/", "javascript:alert(1)", "https://user:pw@a.com/", "http:///nohost"])
def test_rejects(bad):
    with pytest.raises(InvalidURL):
        normalize_url(bad)


def test_same_site_and_scope():
    assert same_site("https://www.a.com/x", "a.com")
    assert not same_site("https://evil-a.com/x", "a.com")
    assert not same_site("https://a.com.evil.com/", "a.com")
    assert same_site("http://127.0.0.1:8481/x", "127.0.0.1:8481")
    assert not same_site("http://127.0.0.1:9999/x", "127.0.0.1:8481")
    assert in_path_scope("https://a.com/blog/x", ["/blog"], None)
    assert not in_path_scope("https://a.com/shop", ["/blog"], None)
    assert not in_path_scope("https://a.com/blog/private", ["/blog"], ["/blog/private"])


def test_domain_from_input():
    assert domain_from_input("Example.com/path") == ("example.com", "https://example.com/")
