from unittest.mock import MagicMock, patch

from bie.sitecrawl import crawl_site


def test_crawl_site_no_query_skips_ranking():
    with patch("bie.sitecrawl.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value

        engine, results = crawl_site(["https://example.com"], instruction="pricing pages", query="")

    mock_engine.crawl.assert_called_once_with(
        ["https://example.com"], allowed_domains=None, instruction="pricing pages"
    )
    mock_engine.search.assert_not_called()
    assert results == []
    assert engine is mock_engine


def test_crawl_site_defaults_query_to_instruction():
    fake_results = [MagicMock()]
    with patch("bie.sitecrawl.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value
        mock_engine.search.return_value = fake_results

        engine, results = crawl_site(["https://example.com"], instruction="pricing pages")

    mock_engine.search.assert_called_once_with("pricing pages", top_k=10)
    assert results == fake_results


def test_crawl_site_explicit_query_overrides_instruction():
    fake_results = [MagicMock()]
    with patch("bie.sitecrawl.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value
        mock_engine.search.return_value = fake_results

        engine, results = crawl_site(
            ["https://example.com"], instruction="pricing pages", query="refund policy", top_k=3
        )

    mock_engine.search.assert_called_once_with("refund policy", top_k=3)
    assert results == fake_results


def test_crawl_site_passes_allowed_domains():
    with patch("bie.sitecrawl.BIE") as mock_bie_cls:
        mock_engine = mock_bie_cls.return_value

        crawl_site(
            ["https://example.com"],
            instruction="",
            query="",
            allowed_domains=["example.com", "docs.example.com"],
        )

    mock_engine.crawl.assert_called_once_with(
        ["https://example.com"],
        allowed_domains=["example.com", "docs.example.com"],
        instruction="",
    )
