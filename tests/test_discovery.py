from unittest.mock import patch

from bie.discovery import _parse_result_urls, _resolve_redirect, discover_urls, discover_urls_multi

# Minimal realistic snippet of DuckDuckGo HTML results page markup
_SAMPLE_HTML = """
<div class="results">
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.com%2Fpage1&rut=abc">
      Example Page One
    </a>
  </div>
  <div class="result">
    <a class="result__a" href="https://www.directlink.com/page2">
      Direct Link Page
    </a>
  </div>
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.com%2Fpage1&rut=def">
      Duplicate of page1
    </a>
  </div>
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.com%2Fpage3&rut=ghi">
      Example Page Three
    </a>
  </div>
</div>
"""

# Minimal realistic snippet of Bing's HTML results page markup
_BING_SAMPLE_HTML = """
<ol id="b_results">
  <li class="b_algo">
    <h2><a href="https://www.bing-result-one.com/article">Result One Title</a></h2>
    <div class="b_caption"><p>Some snippet text</p></div>
  </li>
  <li class="b_algo">
    <h2><a href="https://www.bing-result-two.com/page">Result Two Title</a></h2>
    <div class="b_caption"><p>Another snippet</p></div>
  </li>
</ol>
"""


def test_resolve_redirect_unwraps_uddg():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.com%2Fpage1&rut=abc"
    assert _resolve_redirect(href) == "https://www.example.com/page1"


def test_resolve_redirect_passes_through_direct_links():
    href = "https://www.directlink.com/page2"
    assert _resolve_redirect(href) == "https://www.directlink.com/page2"


def test_parse_result_urls_dedupes_and_limits():
    urls = _parse_result_urls(_SAMPLE_HTML, max_results=10)
    assert urls == [
        "https://www.example.com/page1",
        "https://www.directlink.com/page2",
        "https://www.example.com/page3",
    ]


def test_parse_result_urls_respects_max_results():
    urls = _parse_result_urls(_SAMPLE_HTML, max_results=2)
    assert len(urls) == 2
    assert urls == [
        "https://www.example.com/page1",
        "https://www.directlink.com/page2",
    ]


def test_parse_result_urls_empty_html():
    assert _parse_result_urls("<html><body>no results</body></html>", max_results=5) == []


def test_parse_result_urls_bing_fallback():
    urls = _parse_result_urls(_BING_SAMPLE_HTML, max_results=10)
    assert urls == [
        "https://www.bing-result-one.com/article",
        "https://www.bing-result-two.com/page",
    ]


def test_discover_urls_falls_back_through_backends():
    """If DDG HTML and Lite both fail/empty, Bing should be tried and used."""

    def fake_fetch_ddg_html(client, query):
        return ""  # empty -> no results

    def fake_fetch_ddg_lite(client, query):
        raise __import__("httpx").ConnectError("boom")

    def fake_fetch_bing_html(client, query):
        return _BING_SAMPLE_HTML

    with patch("bie.discovery._fetch_ddg_html", fake_fetch_ddg_html), \
         patch("bie.discovery._fetch_ddg_lite", fake_fetch_ddg_lite), \
         patch("bie.discovery._fetch_bing_html", fake_fetch_bing_html):
        urls = discover_urls("test query", max_results=5)

    assert urls == [
        "https://www.bing-result-one.com/article",
        "https://www.bing-result-two.com/page",
    ]


def test_discover_urls_all_backends_fail_returns_empty():
    def fake_fetch_fail(client, query):
        raise __import__("httpx").ConnectError("boom")

    with patch("bie.discovery._fetch_ddg_html", fake_fetch_fail), \
         patch("bie.discovery._fetch_ddg_lite", fake_fetch_fail), \
         patch("bie.discovery._fetch_bing_html", fake_fetch_fail):
        urls = discover_urls("test query", max_results=5)

    assert urls == []


def test_discover_urls_multi_merges_and_ranks_by_votes():
    def fake_discover(query, max_results=5, timeout=15.0, backends=None):
        mapping = {
            "q1": ["https://a.example.com", "https://b.example.com"],
            "q2": ["https://b.example.com", "https://c.example.com"],
        }
        return mapping.get(query, [])

    with patch("bie.discovery.discover_urls", side_effect=fake_discover):
        urls = discover_urls_multi(["q1", "q2"], max_results_per_query=5, max_total=10)

    # b.example.com appears in both queries -> ranked first
    assert urls[0] == "https://b.example.com"
    assert set(urls) == {"https://a.example.com", "https://b.example.com", "https://c.example.com"}


def test_discover_urls_multi_respects_max_total():
    def fake_discover(query, max_results=5, timeout=15.0, backends=None):
        return [f"https://{query}-{i}.example.com" for i in range(5)]

    with patch("bie.discovery.discover_urls", side_effect=fake_discover):
        urls = discover_urls_multi(["q1", "q2", "q3"], max_results_per_query=5, max_total=4)

    assert len(urls) == 4


def test_discover_urls_multi_empty_queries():
    with patch("bie.discovery.discover_urls", return_value=[]):
        urls = discover_urls_multi([], max_results_per_query=5, max_total=10)
    assert urls == []
