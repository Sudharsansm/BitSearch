from bie import BIE, BIESettings


def test_add_text_and_search():
    engine = BIE(BIESettings(use_embeddings=False))
    engine.add_text(
        url="internal://doc1",
        title="Quarterly Report",
        text="Revenue grew 20% in Q2 2026 driven by strong cloud demand.",
        trust_score=1.0,
    )
    engine.add_text(
        url="internal://doc2",
        title="Cooking Tips",
        text="Always preheat your oven before baking bread.",
    )

    results = engine.search("cloud revenue growth", top_k=5)
    assert results
    assert results[0].url == "internal://doc1"
    assert len(engine) == 2


def test_search_full_response_metadata():
    engine = BIE(BIESettings(use_embeddings=False))
    engine.add_text(url="internal://doc1", title="Doc", text="Hello world example text.")
    response = engine.search_full("hello world")
    assert response.query == "hello world"
    assert response.total_indexed_documents == 1
    assert response.took_ms >= 0
