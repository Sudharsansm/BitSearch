"""Tests for bie.quicksearch.websearch_response and the new
Tavily/ChatGPT-Search-style SearchResponse fields:
``answer`` (extractive), ``degraded``/``diagnostics``, and
``SearchResponse.to_context()``.
"""

from __future__ import annotations

from unittest.mock import patch

from bie.discovery import DiscoveryDiagnostics
from bie.models import SearchResponse, SearchResult
from bie.quicksearch import _extract_answer, websearch, websearch_response


def _result(title="Title", url="https://a.example.com", snippet="", score=0.9, chunk_id=None):
    return SearchResult(
        title=title, url=url, snippet=snippet, source="a.example.com", score=score, chunk_id=chunk_id
    )


# ---------------------------------------------------------------------------
# websearch_response: discovery failure
# ---------------------------------------------------------------------------


def test_websearch_response_no_urls_is_degraded_with_diagnostics():
    diag = DiscoveryDiagnostics(query="anything")
    diag.failures = []  # summary() for no-failures-attempted case below

    with patch("bie.quicksearch.discover_urls_multi", return_value=[]), \
         patch("bie.quicksearch.get_last_discovery_diagnostics", return_value=diag):
        response = websearch_response("anything", top_k=5)

    assert response.results == []
    assert response.degraded is True
    assert response.diagnostics == diag.summary()
    assert response.answer is None
    assert response.took_ms >= 0


# ---------------------------------------------------------------------------
# websearch_response: deep search with results -> answer extraction
# ---------------------------------------------------------------------------


def test_websearch_response_deep_sets_answer_from_top_result():
    urls = ["https://a.example.com"]
    fake_result = _result(
        title="A Page",
        snippet="The 2026 Miami Grand Prix was won by the home favorite. "
        "It was a thrilling race from start to finish.",
        score=0.9,
    )

    with patch("bie.quicksearch.discover_urls_multi", return_value=urls), \
         patch("bie.quicksearch.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value
        mock_engine.search_web.return_value = [fake_result]
        mock_engine.index.chunks = {}

        response = websearch_response("who won the race", top_k=5, use_embeddings=False)

    assert response.results == [fake_result]
    assert response.degraded is False
    assert response.diagnostics is None
    assert response.answer == fake_result.snippet
    assert response.total_indexed_documents == len(mock_engine)


def test_websearch_response_deep_no_snippet_has_no_answer():
    urls = ["https://a.example.com"]
    fake_result = _result(snippet="")  # bare-URL-style result

    with patch("bie.quicksearch.discover_urls_multi", return_value=urls), \
         patch("bie.quicksearch.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value
        mock_engine.search_web.return_value = [fake_result]
        mock_engine.index.chunks = {}

        response = websearch_response("anything", top_k=5, use_embeddings=False)

    assert response.answer is None


# ---------------------------------------------------------------------------
# websearch_response: crawl produced nothing -> degraded fallback
# ---------------------------------------------------------------------------


def test_websearch_response_crawl_fallback_is_degraded():
    urls = ["https://a.example.com", "https://b.example.com"]

    with patch("bie.quicksearch.discover_urls_multi", return_value=urls), \
         patch("bie.quicksearch.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value
        mock_engine.search_web.return_value = []

        response = websearch_response("anything", top_k=2, use_embeddings=False)

    assert len(response.results) == 2
    assert response.results[0].url == "https://a.example.com"
    assert response.results[0].snippet == ""
    assert response.degraded is True
    assert response.diagnostics is not None
    assert "crawl" in response.diagnostics.lower()
    assert response.answer is None


# ---------------------------------------------------------------------------
# websearch_response: deep=False
# ---------------------------------------------------------------------------


def test_websearch_response_non_deep_not_degraded_no_answer():
    urls = ["https://a.example.com", "https://b.example.com"]

    with patch("bie.quicksearch.discover_urls_multi", return_value=urls):
        response = websearch_response("anything", top_k=2, deep=False)

    assert len(response.results) == 2
    assert response.degraded is False
    assert response.diagnostics is None
    assert response.answer is None


# ---------------------------------------------------------------------------
# websearch() == websearch_response().results
# ---------------------------------------------------------------------------


def test_websearch_returns_just_the_results_list():
    urls = ["https://a.example.com"]
    fake_result = _result(snippet="Some content")

    with patch("bie.quicksearch.discover_urls_multi", return_value=urls), \
         patch("bie.quicksearch.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value
        mock_engine.search_web.return_value = [fake_result]
        mock_engine.index.chunks = {}

        results = websearch("anything", top_k=5, use_embeddings=False)

    assert results == [fake_result]


# ---------------------------------------------------------------------------
# _extract_answer
# ---------------------------------------------------------------------------


def test_extract_answer_returns_none_for_no_results():
    assert _extract_answer([]) is None


def test_extract_answer_returns_none_for_empty_snippet():
    assert _extract_answer([_result(snippet="")]) is None


def test_extract_answer_returns_short_snippet_unchanged():
    short = "A short snippet."
    assert _extract_answer([_result(snippet=short)]) == short


def test_extract_answer_truncates_long_snippet_at_sentence_boundary():
    sentence = "This is a sentence about the topic. "
    long_snippet = sentence * 20  # well over 400 chars

    answer = _extract_answer([_result(snippet=long_snippet)], max_chars=100)

    assert len(answer) <= 100
    assert answer.endswith(".")


def test_extract_answer_falls_back_to_ellipsis_without_sentence_boundary():
    long_snippet = "x" * 500  # no sentence breaks at all
    answer = _extract_answer([_result(snippet=long_snippet)], max_chars=100)
    assert answer.endswith("…")
    assert len(answer) <= 101


# ---------------------------------------------------------------------------
# SearchResponse.to_context()
# ---------------------------------------------------------------------------


def test_to_context_includes_answer_and_numbered_sources():
    response = SearchResponse(
        query="who won the race",
        answer="Driver X won the race.",
        results=[
            _result(title="Race report", url="https://a.example.com", snippet="Driver X won."),
            _result(title="Standings", url="https://b.example.com", snippet="Updated standings."),
        ],
    )

    context = response.to_context()

    assert context.startswith("Answer: Driver X won the race.")
    assert "[1] Race report — https://a.example.com" in context
    assert "Driver X won." in context
    assert "[2] Standings — https://b.example.com" in context


def test_to_context_no_results_message():
    response = SearchResponse(query="anything", results=[])
    assert response.to_context() == "No results found."


def test_to_context_degraded_includes_diagnostics_note():
    response = SearchResponse(
        query="anything",
        degraded=True,
        diagnostics="network blocked",
        results=[_result(snippet="")],
    )

    context = response.to_context()

    assert "degraded" in context.lower()
    assert "network blocked" in context
    assert "[1]" in context


def test_to_context_respects_max_results_and_snippet_chars():
    response = SearchResponse(
        query="anything",
        results=[
            _result(title="One", url="https://a.example.com", snippet="a" * 1000),
            _result(title="Two", url="https://b.example.com", snippet="b" * 1000),
        ],
    )

    context = response.to_context(max_results=1, snippet_chars=10)

    assert "[1] One" in context
    assert "[2]" not in context
    assert "a" * 10 + "…" in context
