from bie.chunker import chunk_document
from bie.models import Document


def test_chunk_short_document():
    doc = Document(url="http://example.com", title="Test", text="Short text.")
    chunks = chunk_document(doc, chunk_size=800, overlap=100)
    assert len(chunks) == 1
    assert chunks[0].text == "Short text."
    assert chunks[0].doc_id == doc.doc_id


def test_chunk_long_document_splits():
    paragraph = "Sentence one. Sentence two. Sentence three. " * 30
    text = "\n\n".join([paragraph] * 5)
    doc = Document(url="http://example.com", title="Long", text=text)
    chunks = chunk_document(doc, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    for c in chunks:
        assert c.doc_id == doc.doc_id
        assert len(c.text) > 0


def test_chunk_empty_document():
    doc = Document(url="http://example.com", title="Empty", text="")
    chunks = chunk_document(doc)
    assert chunks == []
