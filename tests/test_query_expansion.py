from bie.query_expansion import generate_query_variants


def test_original_query_always_first():
    variants = generate_query_variants("What is the capital of France?")
    assert variants[0] == "What is the capital of France?"


def test_respects_max_variants():
    variants = generate_query_variants("who won the latest F1 race", max_variants=1)
    assert len(variants) == 1
    assert variants == ["who won the latest F1 race"]


def test_keywords_variant_strips_filler_words():
    variants = generate_query_variants("What is the capital of France?", max_variants=3)
    assert len(variants) >= 2
    keywords_variant = variants[1]
    assert "capital" in keywords_variant.lower()
    assert "france" in keywords_variant.lower()


def test_time_sensitive_query_adds_recency_variant():
    variants = generate_query_variants("who won the latest F1 race", max_variants=3)
    assert any("latest update" in v for v in variants)


def test_non_time_sensitive_simple_query():
    variants = generate_query_variants("python list comprehension syntax", max_variants=3)
    assert variants[0] == "python list comprehension syntax"
    assert all(isinstance(v, str) and v for v in variants)


def test_no_duplicate_variants():
    variants = generate_query_variants("test", max_variants=3)
    assert len(variants) == len(set(variants))
