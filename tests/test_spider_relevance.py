from bie.spiders.generic import _relevance_score


def test_relevance_score_counts_keyword_overlap_in_anchor_text():
    keywords = {"pricing", "plans"}
    score = _relevance_score("https://example.com/pricing", "Pricing & Plans", keywords)
    assert score == 2


def test_relevance_score_counts_keyword_overlap_in_url_path():
    keywords = {"docs", "api"}
    score = _relevance_score("https://example.com/docs/api/reference", "Reference", keywords)
    assert score == 2


def test_relevance_score_zero_for_no_overlap():
    keywords = {"pricing"}
    score = _relevance_score("https://example.com/about", "About Us", keywords)
    assert score == 0


def test_relevance_score_empty_keywords():
    score = _relevance_score("https://example.com/pricing", "Pricing", set())
    assert score == 0
