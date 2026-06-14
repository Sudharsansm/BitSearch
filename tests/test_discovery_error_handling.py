"""Tests for discovery error categorization, logging, and configurable
backends (bie/discovery.py)."""

import logging
from unittest.mock import patch

import httpx

from bie.discovery import (
    BackendFailure,
    _configured_backends,
    discover_urls,
    discover_urls_detailed,
)


def _http_status_error(status_code, request_url="https://example.com"):
    request = httpx.Request("GET", request_url)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_all_backends_403_categorized_as_http_error(caplog):
    def fake_403(client, query):
        raise _http_status_error(403)

    with patch("bie.discovery._fetch_ddg_html", fake_403), \
         patch("bie.discovery._fetch_ddg_lite", fake_403), \
         patch("bie.discovery._fetch_bing_html", fake_403), \
         caplog.at_level(logging.WARNING, logger="bie.discovery"):
        urls, failures = discover_urls_detailed("test query")

    assert urls == []
    assert len(failures) == 3
    assert all(f.category == "http_error" for f in failures)
    assert all("403" in f.detail for f in failures)

    # Final summary should mention rate-limiting/blocking, not "network blocked"
    summary = " ".join(r.message for r in caplog.records)
    assert "rate-limit" in summary.lower() or "blocked" in summary.lower()


def test_all_backends_connection_error_categorized_as_network_blocked(caplog):
    def fake_connect_error(client, query):
        raise httpx.ConnectError("Connection refused")

    with patch("bie.discovery._fetch_ddg_html", fake_connect_error), \
         patch("bie.discovery._fetch_ddg_lite", fake_connect_error), \
         patch("bie.discovery._fetch_bing_html", fake_connect_error), \
         caplog.at_level(logging.WARNING, logger="bie.discovery"):
        urls, failures = discover_urls_detailed("test query")

    assert urls == []
    assert len(failures) == 3
    assert all(f.category == "network_blocked" for f in failures)

    summary = " ".join(r.message for r in caplog.records)
    assert "network" in summary.lower() or "blocked" in summary.lower()


def test_host_not_allowed_style_proxy_denial_categorized_as_network_blocked():
    """Simulates a sandboxed proxy returning a connection-level denial
    (e.g. `x-deny-reason: host_not_allowed`) which httpx surfaces as a
    connect error before any HTTP response is received."""

    def fake_proxy_denial(client, query):
        raise httpx.ConnectError("[Errno 111] host_not_allowed")

    with patch("bie.discovery._fetch_ddg_html", fake_proxy_denial), \
         patch("bie.discovery._fetch_ddg_lite", fake_proxy_denial), \
         patch("bie.discovery._fetch_bing_html", fake_proxy_denial):
        urls, failures = discover_urls_detailed("test query")

    assert urls == []
    assert all(f.category == "network_blocked" for f in failures)
    assert any("host_not_allowed" in f.detail for f in failures)


def test_empty_response_categorized_distinctly_from_connection_error(caplog):
    """One backend returns 200 with unparseable content (CAPTCHA-like),
    another fails at the connection level — both contribute to failures
    but with different categories."""

    def fake_empty_200(client, query):
        return "<html><body>Please verify you are human (CAPTCHA)</body></html>"

    def fake_connect_error(client, query):
        raise httpx.ConnectError("Connection refused")

    with patch("bie.discovery._fetch_ddg_html", fake_empty_200), \
         patch("bie.discovery._fetch_ddg_lite", fake_connect_error), \
         patch("bie.discovery._fetch_bing_html", fake_connect_error), \
         caplog.at_level(logging.WARNING, logger="bie.discovery"):
        urls, failures = discover_urls_detailed("test query")

    assert urls == []
    categories = {f.backend: f.category for f in failures}
    assert categories["ddg_html"] == "empty_response"
    assert categories["ddg_lite"] == "network_blocked"
    assert categories["bing_html"] == "network_blocked"


def test_discover_urls_returns_empty_list_not_exception(caplog):
    """discover_urls() (the simple API) must never raise even if every
    backend fails -- callers (websearch) rely on this."""

    def fake_fail(client, query):
        raise httpx.ConnectError("boom")

    with patch("bie.discovery._fetch_ddg_html", fake_fail), \
         patch("bie.discovery._fetch_ddg_lite", fake_fail), \
         patch("bie.discovery._fetch_bing_html", fake_fail):
        urls = discover_urls("test query")

    assert urls == []


def test_first_backend_success_short_circuits_remaining():
    calls = []

    def fake_success(client, query):
        calls.append("ddg_html")
        return '<a class="result__a" href="https://a.example.com">A</a>'

    def fake_should_not_be_called(client, query):
        calls.append("should-not-run")
        raise AssertionError("this backend should not have been called")

    with patch("bie.discovery._fetch_ddg_html", fake_success), \
         patch("bie.discovery._fetch_ddg_lite", fake_should_not_be_called), \
         patch("bie.discovery._fetch_bing_html", fake_should_not_be_called):
        urls, failures = discover_urls_detailed("test query")

    assert urls == ["https://a.example.com"]
    assert failures == []
    assert calls == ["ddg_html"]


def test_configured_backends_default():
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("BIE_DISCOVERY_BACKENDS", None)
        assert _configured_backends() == ["ddg_html", "ddg_lite", "bing_html"]


def test_configured_backends_from_env():
    with patch.dict("os.environ", {"BIE_DISCOVERY_BACKENDS": "bing_html,ddg_html"}):
        assert _configured_backends() == ["bing_html", "ddg_html"]


def test_configured_backends_handles_whitespace_and_empty():
    with patch.dict("os.environ", {"BIE_DISCOVERY_BACKENDS": " bing_html , , ddg_lite "}):
        assert _configured_backends() == ["bing_html", "ddg_lite"]


def test_unknown_backend_in_env_is_skipped_with_warning(caplog):
    with patch.dict("os.environ", {"BIE_DISCOVERY_BACKENDS": "totally_unknown,ddg_html"}), \
         caplog.at_level(logging.WARNING, logger="bie.discovery"):

        def fake_success(client, query):
            return '<a class="result__a" href="https://a.example.com">A</a>'

        with patch("bie.discovery._fetch_ddg_html", fake_success):
            urls, failures = discover_urls_detailed("test query")

    assert urls == ["https://a.example.com"]
    assert any("totally_unknown" in r.message for r in caplog.records)


def test_searxng_backend_requires_env_var():
    with patch.dict("os.environ", {"BIE_DISCOVERY_BACKENDS": "searxng"}, clear=False):
        import os
        os.environ.pop("BIE_SEARXNG_URL", None)
        urls, failures = discover_urls_detailed("test query")

    assert urls == []
    assert len(failures) == 1
    assert failures[0].backend == "searxng"
    assert failures[0].category == "config_error"


def test_searxng_backend_used_when_configured():
    import json

    def fake_searxng(client, query):
        return json.dumps({"results": [{"url": "https://searx-result.example.com"}]})

    with patch.dict("os.environ", {
        "BIE_DISCOVERY_BACKENDS": "searxng",
        "BIE_SEARXNG_URL": "http://localhost:8080",
    }), patch("bie.discovery._fetch_searxng", fake_searxng):
        urls, failures = discover_urls_detailed("test query")

    assert urls == ["https://searx-result.example.com"]
    assert failures == []


def test_backend_failure_repr():
    f = BackendFailure(backend="ddg_html", category="http_error", detail="HTTP 403")
    assert "ddg_html" in repr(f)
    assert "http_error" in repr(f)
