# BIE REST API

Start the server:

```bash
pip install "bie[server,embeddings]"
bie serve --port 8000
```

All endpoints are JSON over HTTP. If `BIE_API_KEY` is set, every endpoint
except `/health` requires:

```
Authorization: Bearer <BIE_API_KEY>
```

## `GET /health`

Health check, no auth required.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "indexed_documents": 12,
  "vector_search": true
}
```

## `POST /crawl/url`

Crawl one or more seed URLs (with bounded link-following) and add the
extracted pages to the index.

**Request**
```json
{
  "urls": ["https://example.com/news"],
  "allowed_domains": ["example.com"]
}
```

**Response**
```json
{
  "documents_indexed": 8,
  "total_indexed_documents": 8
}
```

## `POST /search`

Hybrid (BM25 + vector) search over the in-memory index.

**Request**
```json
{
  "query": "semiconductor supply chain 2026",
  "top_k": 5
}
```

**Response**
```json
{
  "query": "semiconductor supply chain 2026",
  "results": [
    {
      "title": "TSMC Q2 2026 Earnings",
      "url": "https://example.com/news/tsmc-q2",
      "snippet": "TSMC reported record wafer shipments in Q2 2026...",
      "source": "example.com",
      "score": 0.0421,
      "bm25_score": 8.21,
      "vector_score": 0.83,
      "trust_score": 0.5,
      "publish_date": null,
      "chunk_id": "a1b2c3d4e5f6",
      "doc_id": "0011223344aa"
    }
  ],
  "took_ms": 3.21,
  "total_indexed_documents": 8
}
```

## `POST /indices/update`

Push pre-extracted text directly into the index (no crawling).

**Request**
```json
{
  "url": "internal://doc-1",
  "title": "Internal memo",
  "text": "...",
  "trust_score": 1.0
}
```

## `GET /metrics`

Returns index size and current settings (excluding the API key).
