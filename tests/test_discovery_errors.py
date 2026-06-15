"""Tests for bie.discovery's error-handling and configurability additions:

- Per-backend failures are categorized (network-blocked vs.
  blocked/rate-limited vs. empty/unparseable response vs. unknown
  backend / not configured) and logged with the specific reason.
- A clear, actionable summary is produced when *all* backends fail,
  distinguishing "network blocked" from "got a response but no usable
  results".
- BIE_DISCOVERY_BACKENDS / the `backends=` argument control which
  backends are tried, in what order, including the optional `searxng`
  backend (which requires BIE_SEARXNG_URL).
- get_last_discovery_diagnostics() exposes structured per-call results.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx

from bie.discovery import (
    BLOCKED_OR_RATE_LIMITED,
    EMPTY_RESPONSE,
    NETWORK_BLOCKED,
    NOT_CONFIGURED,
    UNKNOWN_BACKEND,
    discover_urls,
    get_last_discovery_diagnostics,
)

_BING_SAMPLE_HTML = """
<ol id="b_results">
  <li class="b_algo">
    <h2><a href="https://www.bing-result-one.com/article">Result One Title</a></h2>
  </li>
</ol>
"""

_SEARXNG_SAMPLE_JSON = (
    '{"results": [{"url": "https://www.searxng-result.example.com/page", "title": "Title"}]}'
)


def _connect_error(*_args, **_kwargs):
    raise httpx.ConnectError("Connection refused")


def _status_error(status_code: int, headers: dict | None = None):
    def _raiser(*_args, **_kwargs):
        request = httpx.Request("GET", "https://example.com")
        response = httpx.Response(status_code, request=request, headers=headers or {})
        raise httpx.HTTPStatusError("error", request=request, response=response)

    return _raiser


def _returns(html: str):
    def _fetch(*_args, **_kwargs):
        return html

    return _fetch


# ---------------------------------------------------------------------------
# Connection-level failures -> NETWORK_BLOCKED
# ---------------------------------------------------------------------------


def test_connection_errors_categorized_as_network_blocked():
    with patch("bie.discovery._fetch_ddg_html", _connect_error), \
         patch("bie.discovery._fetch_ddg_lite", _connect_error), \
         patch("bie.discovery._fetch_bing_html", _connect_error):
        urls = discover_urls("test query", max_results=5)

    assert urls == []
    diag = get_last_discovery_diagnostics()
    assert diag.all_failed
    assert {f.category for f in diag.failures} == {NETWORK_BLOCKED}
    assert "network/connection level" in diag.summary()
    assert "environment issue, not a BIE bug" in diag.summary()


# ---------------------------------------------------------------------------
# HTTP 403 with x-deny-reason header (egress proxy denial) -> NETWORK_BLOCKED
# ---------------------------------------------------------------------------


def test_proxy_deny_reason_categorized_as_network_blocked():
    deny = _status_error(403, headers={"x-deny-reason": "host_not_allowed"})

    with patch("bie.discovery._fetch_ddg_html", deny), \
         patch("bie.discovery._fetch_ddg_lite", deny), \
         patch("bie.discovery._fetch_bing_html", deny):
        urls = discover_urls("test query", max_results=5)

    assert urls == []
    diag = get_last_discovery_diagnostics()
    assert {f.category for f in diag.failures} == {NETWORK_BLOCKED}
    assert all("host_not_allowed" in f.detail for f in diag.failures)


# ---------------------------------------------------------------------------
# Plain HTTP 403 (no deny-reason header) -> BLOCKED_OR_RATE_LIMITED
# ---------------------------------------------------------------------------


def test_plain_403_categorized_as_blocked_or_rate_limited():
    forbidden = _status_error(403)

    with patch("bie.discovery._fetch_ddg_html", forbidden), \
         patch("bie.discovery._fetch_ddg_lite", forbidden), \
         patch("bie.discovery._fetch_bing_html", forbidden):
        urls = discover_urls("test query", max_results=5)

    assert urls == []
    diag = get_last_discovery_diagnostics()
    assert {f.category for f in diag.failures} == {BLOCKED_OR_RATE_LIMITED}
    assert "rate-limiting or bot-blocking" in diag.summary()


# ---------------------------------------------------------------------------
# 200 OK but no parseable results -> EMPTY_RESPONSE
# ---------------------------------------------------------------------------


def test_unparseable_response_categorized_as_empty_response():
    empty = _returns("<html><body>captcha, please verify you're human</body></html>")

    with patch("bie.discovery._fetch_ddg_html", empty), \
         patch("bie.discovery._fetch_ddg_lite", empty), \
         patch("bie.discovery._fetch_bing_html", empty):
        urls = discover_urls("test query", max_results=5)

    assert urls == []
    diag = get_last_discovery_diagnostics()
    assert {f.category for f in diag.failures} == {EMPTY_RESPONSE}
    assert "CAPTCHA" in diag.summary()


def test_empty_response_detail_includes_page_title_for_diagnosis():
    """The failure detail should surface the served page's <title> so a
    CAPTCHA/consent page (vs. a genuine layout change on a real results
    page) is identifiable directly from the log/error message."""
    captcha_page = _returns(
        "<html><head><title>DuckDuckGo - About Your Search</title></head>"
        "<body>Please verify you are not a robot.</body></html>"
    )

    with patch("bie.discovery._fetch_ddg_html", captcha_page), \
         patch("bie.discovery._fetch_ddg_lite", captcha_page), \
         patch("bie.discovery._fetch_bing_html", captcha_page):
        urls = discover_urls("test query", max_results=5)

    assert urls == []
    diag = get_last_discovery_diagnostics()
    for f in diag.failures:
        assert "DuckDuckGo - About Your Search" in f.detail
        assert "body_len=" in f.detail


# ---------------------------------------------------------------------------
# Mixed failure categories -> mixed summary
# ---------------------------------------------------------------------------


def test_mixed_failures_produce_mixed_summary():
    with patch("bie.discovery._fetch_ddg_html", _connect_error), \
         patch("bie.discovery._fetch_ddg_lite", _status_error(429)), \
         patch("bie.discovery._fetch_bing_html", _returns("<html></html>")):
        urls = discover_urls("test query", max_results=5)

    assert urls == []
    diag = get_last_discovery_diagnostics()
    categories = {f.category for f in diag.failures}
    assert categories == {NETWORK_BLOCKED, BLOCKED_OR_RATE_LIMITED, EMPTY_RESPONSE}
    assert "mixed errors" in diag.summary()


# ---------------------------------------------------------------------------
# Success after earlier categorized failures
# ---------------------------------------------------------------------------


def test_success_after_failures_records_succeeded_backend():
    with patch("bie.discovery._fetch_ddg_html", _connect_error), \
         patch("bie.discovery._fetch_ddg_lite", _status_error(403)), \
         patch("bie.discovery._fetch_bing_html", _returns(_BING_SAMPLE_HTML)):
        urls = discover_urls("test query", max_results=5)

    assert urls == ["https://www.bing-result-one.com/article"]
    diag = get_last_discovery_diagnostics()
    assert diag.succeeded_backend == "bing_html"
    assert not diag.all_failed
    # Earlier failures are still recorded for diagnostics
    assert {f.backend for f in diag.failures} == {"ddg_html", "ddg_lite"}


# ---------------------------------------------------------------------------
# Configurable backends: explicit `backends=` argument
# ---------------------------------------------------------------------------


def test_backends_argument_restricts_and_orders_attempts():
    """Only the backends listed in `backends=` are tried, in that order."""
    calls = []

    def tracking_fetch(name):
        def _fetch(*_args, **_kwargs):
            calls.append(name)
            return _BING_SAMPLE_HTML if name == "bing_html" else ""

        return _fetch

    with patch("bie.discovery._fetch_ddg_html", tracking_fetch("ddg_html")), \
         patch("bie.discovery._fetch_ddg_lite", tracking_fetch("ddg_lite")), \
         patch("bie.discovery._fetch_bing_html", tracking_fetch("bing_html")):
        urls = discover_urls("test query", max_results=5, backends=["bing_html", "ddg_html"])

    assert urls == ["https://www.bing-result-one.com/article"]
    # ddg_html is configured second but bing_html succeeds first, so
    # ddg_html should never be called.
    assert calls == ["bing_html"]


# ---------------------------------------------------------------------------
# Unknown backend names
# ---------------------------------------------------------------------------


def test_unknown_backend_name_is_skipped_with_diagnostic():
    with patch("bie.discovery._fetch_bing_html", _returns(_BING_SAMPLE_HTML)):
        urls = discover_urls("test query", max_results=5, backends=["totally_made_up", "bing_html"])

    assert urls == ["https://www.bing-result-one.com/article"]
    diag = get_last_discovery_diagnostics()
    unknown = [f for f in diag.failures if f.backend == "totally_made_up"]
    assert len(unknown) == 1
    assert unknown[0].category == UNKNOWN_BACKEND


# ---------------------------------------------------------------------------
# BIE_DISCOVERY_BACKENDS environment variable
# ---------------------------------------------------------------------------


def test_discovery_backends_env_var_controls_default_order(monkeypatch):
    monkeypatch.setenv("BIE_DISCOVERY_BACKENDS", "bing_html,ddg_html")
    calls = []

    def tracking_fetch(name, html=""):
        def _fetch(*_args, **_kwargs):
            calls.append(name)
            return html

        return _fetch

    with patch("bie.discovery._fetch_bing_html", tracking_fetch("bing_html", _BING_SAMPLE_HTML)), \
         patch("bie.discovery._fetch_ddg_html", tracking_fetch("ddg_html")), \
         patch("bie.discovery._fetch_ddg_lite", tracking_fetch("ddg_lite")):
        urls = discover_urls("test query", max_results=5)

    assert urls == ["https://www.bing-result-one.com/article"]
    assert calls == ["bing_html"]


# ---------------------------------------------------------------------------
# SearXNG backend
# ---------------------------------------------------------------------------


def test_searxng_backend_skipped_without_searxng_url(monkeypatch):
    monkeypatch.delenv("BIE_SEARXNG_URL", raising=False)

    with patch("bie.discovery._fetch_bing_html", _returns(_BING_SAMPLE_HTML)):
        urls = discover_urls("test query", max_results=5, backends=["searxng", "bing_html"])

    assert urls == ["https://www.bing-result-one.com/article"]
    diag = get_last_discovery_diagnostics()
    searxng_failures = [f for f in diag.failures if f.backend == "searxng"]
    assert len(searxng_failures) == 1
    assert searxng_failures[0].category == NOT_CONFIGURED


def test_searxng_backend_used_when_configured(monkeypatch):
    monkeypatch.setenv("BIE_SEARXNG_URL", "http://localhost:8080")

    with patch("bie.discovery._fetch_searxng", _returns(_SEARXNG_SAMPLE_JSON)):
        urls = discover_urls("test query", max_results=5, backends=["searxng"])

    assert urls == ["https://www.searxng-result.example.com/page"]
    diag = get_last_discovery_diagnostics()
    assert diag.succeeded_backend == "searxng"


def test_searxng_json_extraction_parses_results():
    from bie.discovery import _parse_searxng_json

    urls = _parse_searxng_json(_SEARXNG_SAMPLE_JSON, max_results=5)
    assert urls == ["https://www.searxng-result.example.com/page"]


def test_searxng_json_extraction_handles_malformed_body():
    from bie.discovery import _parse_searxng_json

    assert _parse_searxng_json("not json", max_results=5) == []
    assert _parse_searxng_json("[]", max_results=5) == []
    assert _parse_searxng_json('{"results": "oops"}', max_results=5) == []


# ---------------------------------------------------------------------------
# get_last_discovery_diagnostics()
# ---------------------------------------------------------------------------


def test_diagnostics_summary_when_nothing_attempted():
    with patch("bie.discovery._get_configured_backends", return_value=[]):
        urls = discover_urls("test query", max_results=5, backends=[])

    assert urls == []
    diag = get_last_discovery_diagnostics()
    assert diag.all_failed
    assert diag.summary() == "no backends were attempted"
