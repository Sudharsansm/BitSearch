from unittest.mock import patch

from bie.discovery import (
    _decode_bing_redirect,
    _parse_result_urls,
    _resolve_redirect,
    discover_urls,
    discover_urls_multi,
)

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


# ---------------------------------------------------------------------------
# Real-world markup robustness: multi-class attributes, nested <li>, ck/a
# redirects. These reproduce "200 OK but 0 results parsed" failures caused
# by overly-strict patterns that only matched a single, exact class name.
# ---------------------------------------------------------------------------

_MULTI_CLASS_DDG_HTML = """
<div class="result">
  <a class="result__a js-result-title-link" href="https://www.example.com/multi-class-ddg">
    Title
  </a>
</div>
"""

_MULTI_CLASS_DDG_LITE_HTML = """
<table>
  <tr><td><a rel="nofollow" class="result-link js-lite-link" href="https://www.example.com/multi-class-lite">Title</a></td></tr>
</table>
"""

# Bing markup with extra classes on <li>/<h2>, and a nested <li> (sitelinks)
# inside the organic result -- this breaks a non-greedy `<li ...>.*?</li>`
# block extraction, since it matches up to the *inner* </li>.
_NESTED_LI_BING_HTML = """
<ol id="b_results">
  <li class="b_algo b_algoBig">
    <h2 class="title"><a target="_blank" href="https://www.example.com/nested-li-result">Outer Result</a></h2>
    <div class="b_caption">
      <ul class="b_vlist2col">
        <li><a href="https://www.example.com/sitelink-one">Sitelink One</a></li>
        <li><a href="https://www.example.com/sitelink-two">Sitelink Two</a></li>
      </ul>
    </div>
  </li>
</ol>
"""

_BING_CK_A_HTML = (
    '<ol id="b_results"><li class="b_algo"><h2><a href='
    '"https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1aHR0cHM6Ly93d3cuZXhhbXBsZS5jb20vYXJ0aWNsZQ&amp;ntb=1">'
    "Title</a></h2></li></ol>"
)


def test_parse_result_urls_handles_multi_class_ddg_html():
    """A `class="result__a js-result-title-link"` attribute (extra CSS
    classes alongside `result__a`) must still match."""
    urls = _parse_result_urls(_MULTI_CLASS_DDG_HTML, max_results=5)
    assert urls == ["https://www.example.com/multi-class-ddg"]


def test_parse_result_urls_handles_multi_class_ddg_lite_html():
    urls = _parse_result_urls(_MULTI_CLASS_DDG_LITE_HTML, max_results=5)
    assert urls == ["https://www.example.com/multi-class-lite"]


def test_parse_result_urls_bing_with_nested_li_sitelinks():
    """The organic result's <h2><a> link must be found even when the
    <li class="b_algo"> block contains nested <li> sitelinks, which would
    truncate a naive non-greedy `.*?</li>` block match."""
    urls = _parse_result_urls(_NESTED_LI_BING_HTML, max_results=5)
    assert "https://www.example.com/nested-li-result" in urls


def test_decode_bing_redirect_extracts_target_url():
    href = (
        "https://www.bing.com/ck/a?!&&p=abc"
        "&u=a1aHR0cHM6Ly93d3cuZXhhbXBsZS5jb20vYXJ0aWNsZQ"
        "&ntb=1"
    )
    assert _decode_bing_redirect(href) == "https://www.example.com/article"


def test_decode_bing_redirect_returns_none_for_missing_u_param():
    assert _decode_bing_redirect("https://www.bing.com/ck/a?!&&p=abc") is None


def test_decode_bing_redirect_returns_none_for_undecodable_u_param():
    assert _decode_bing_redirect("https://www.bing.com/ck/a?u=not-valid-base64!!!") is None


def test_resolve_redirect_unwraps_bing_ck_a():
    href = (
        "https://www.bing.com/ck/a?!&&p=abc"
        "&u=a1aHR0cHM6Ly93d3cuZXhhbXBsZS5jb20vYXJ0aWNsZQ"
        "&ntb=1"
    )
    assert _resolve_redirect(href) == "https://www.example.com/article"


def test_parse_result_urls_unwraps_bing_ck_a_redirects():
    urls = _parse_result_urls(_BING_CK_A_HTML, max_results=5)
    assert urls == ["https://www.example.com/article"]
