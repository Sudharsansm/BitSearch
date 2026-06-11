from bie.chunker import chunk_document
from bie.config import BIESettings
from bie.index import HybridIndex
from bie.models import Document


def _build_index(use_embeddings: bool = False) -> HybridIndex:
    settings = BIESettings(use_embeddings=use_embeddings)
    index = HybridIndex(settings)

    docs = [
        Document(
            url="http://example.com/a",
            title="Semiconductor Supply Chains in 2026",
            text=(
                "Global semiconductor supply chains faced disruption in 2026. "
                "TSMC and Samsung announced new fabs to address chip shortages."
            ),
            trust_score=0.9,
        ),
        Document(
            url="http://example.com/b",
            title="Recipe: Chocolate Cake",
            text="Mix flour, sugar, and cocoa powder. Bake at 350F for 30 minutes.",
            trust_score=0.5,
        ),
    ]
    for doc in docs:
        chunks = chunk_document(doc, chunk_size=800, overlap=50)
        index.add_document(doc, chunks)
    return index


def test_bm25_search_returns_relevant_doc():
    index = _build_index()
    results = index.search("semiconductor chip shortage", top_k=5)
    assert results
    assert results[0].url == "http://example.com/a"


def test_search_no_match_returns_empty():
    index = _build_index()
    results = index.search("zzzzzz nonexistent term qqqqqq", top_k=5)
    assert results == []


def test_index_length():
    index = _build_index()
    assert len(index) == 2
