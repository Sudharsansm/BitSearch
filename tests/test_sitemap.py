from unittest.mock import patch

from bie.sitemap import _parse_sitemap_xml, _sitemaps_from_robots, map_site

_ROBOTS_TXT = """User-agent: *
Disallow: /admin

Sitemap: https://example.com/sitemap_index.xml
"""

_SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-posts.xml</loc></sitemap>
</sitemapindex>
"""

_SITEMAP_PAGES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
</urlset>
"""

_SITEMAP_POSTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/blog/post-1</loc></url>
  <url><loc>https://example.com/blog/post-2</loc></url>
</urlset>
"""


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    def get(self, url):
        return _FakeResponse(200, _ROBOTS_TXT)


def test_sitemaps_from_robots_extracts_directive():
    sitemaps = _sitemaps_from_robots(_FakeClient(), "https://example.com")
    assert sitemaps == ["https://example.com/sitemap_index.xml"]


def test_parse_sitemap_xml_index():
    nested, pages = _parse_sitemap_xml(_SITEMAP_INDEX_XML)
    assert nested == [
        "https://example.com/sitemap-pages.xml",
        "https://example.com/sitemap-posts.xml",
    ]
    assert pages == []


def test_parse_sitemap_xml_urlset():
    nested, pages = _parse_sitemap_xml(_SITEMAP_PAGES_XML)
    assert nested == []
    assert pages == ["https://example.com/", "https://example.com/about"]


def test_map_site_expands_index_and_collects_urls():
    def fake_fetch(client, url):
        return {
            "https://example.com/robots.txt": _ROBOTS_TXT,
            "https://example.com/sitemap_index.xml": _SITEMAP_INDEX_XML,
            "https://example.com/sitemap-pages.xml": _SITEMAP_PAGES_XML,
            "https://example.com/sitemap-posts.xml": _SITEMAP_POSTS_XML,
        }.get(url)

    with patch("bie.sitemap._fetch", side_effect=fake_fetch):
        result = map_site("https://example.com/some/page")

    assert result.root == "https://example.com"
    assert "https://example.com/sitemap_index.xml" in result.sitemap_urls
    assert "https://example.com/sitemap-pages.xml" in result.sitemap_urls
    assert "https://example.com/sitemap-posts.xml" in result.sitemap_urls

    assert set(result.urls) == {
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/blog/post-1",
        "https://example.com/blog/post-2",
    }


def test_map_site_returns_empty_when_no_sitemap_found():
    with patch("bie.sitemap._fetch", return_value=None):
        result = map_site("https://example.com")

    assert result.sitemap_urls == []
    assert result.urls == []
    assert len(result) == 0


def test_sitemap_filter():
    def fake_fetch(client, url):
        return {
            "https://example.com/robots.txt": _ROBOTS_TXT,
            "https://example.com/sitemap_index.xml": _SITEMAP_INDEX_XML,
            "https://example.com/sitemap-pages.xml": _SITEMAP_PAGES_XML,
            "https://example.com/sitemap-posts.xml": _SITEMAP_POSTS_XML,
        }.get(url)

    with patch("bie.sitemap._fetch", side_effect=fake_fetch):
        result = map_site("https://example.com")

    blog_urls = result.filter(r"/blog/")
    assert blog_urls == ["https://example.com/blog/post-1", "https://example.com/blog/post-2"]
