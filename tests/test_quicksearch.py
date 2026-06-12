from unittest.mock import patch

from bie.quicksearch import websearch


def test_websearch_no_urls_returns_empty():
    with patch("bie.quicksearch.discover_urls", return_value=[]):
        results = websearch("anything", top_k=5)
    assert results == []


def test_websearch_non_deep_returns_discovery_order():
    urls = ["https://a.example.com", "https://b.example.com", "https://c.example.com"]
    with patch("bie.quicksearch.discover_urls", return_value=urls):
        results = websearch("anything", top_k=2, deep=False)

    assert len(results) == 2
    assert results[0].url == "https://a.example.com"
    assert results[0].source == "a.example.com"
    assert results[0].snippet == ""
    # earlier results score higher
    assert results[0].score > results[1].score


def test_websearch_deep_falls_back_when_crawl_fails():
    urls = ["https://a.example.com", "https://b.example.com"]

    with patch("bie.quicksearch.discover_urls", return_value=urls), \
         patch("bie.quicksearch.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value
        mock_engine.search_web.return_value = []  # crawl produced nothing

        results = websearch("anything", top_k=2, deep=True, use_embeddings=False)

    # falls back to discovered URLs without snippets
    assert len(results) == 2
    assert results[0].url == "https://a.example.com"
    assert results[0].snippet == ""


def test_websearch_deep_returns_crawled_results():
    from bie.models import SearchResult

    urls = ["https://a.example.com"]
    fake_result = SearchResult(
        title="A Page",
        url="https://a.example.com",
        snippet="Some relevant content",
        source="a.example.com",
        score=0.9,
    )

    with patch("bie.quicksearch.discover_urls", return_value=urls), \
         patch("bie.quicksearch.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value
        mock_engine.search_web.return_value = [fake_result]

        results = websearch("anything", top_k=5, deep=True, use_embeddings=False)

    assert results == [fake_result]
