"""
BIE REST API server — implements the core endpoints from PRD Section 6.

Run with::

    bie serve --port 8000

or::

    uvicorn bie.server:app --reload
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from bie import __version__
from bie.config import BIESettings
from bie.engine import BIE
from bie.models import SearchResponse

logger = logging.getLogger("bie.server")

settings = BIESettings()
engine = BIE(settings)

app = FastAPI(
    title="BitSearch Intelligence Engine (BIE)",
    description=(
        "AI-native, real-time web search & extraction API. "
        "Built on the Bitscrape crawling framework. "
        "https://github.com/Sudharsansm/BIE"
    ),
    version=__version__,
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def require_api_key(authorization: Optional[str] = Header(default=None)) -> None:
    if not settings.api_key:
        return
    expected = f"Bearer {settings.api_key}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(..., description="The search query")
    top_k: int = Field(10, ge=1, le=100)


class SearchLiveRequest(BaseModel):
    query: str = Field(..., description="The search query")
    top_k: int = Field(10, ge=1, le=100)
    discovery_results: int = Field(8, ge=1, le=20)
    deep: bool = Field(
        True,
        description="If true (default), crawl discovered URLs with Bitscrape and "
        "rank via BIE's hybrid index. If false, return raw discovery order "
        "without snippets.",
    )


class CrawlRequest(BaseModel):
    urls: list[str] = Field(..., description="Seed URLs to crawl and index")
    allowed_domains: list[str] | None = Field(
        default=None, description="Restrict link-following to these domains"
    )
    instruction: str = Field(
        default="",
        description="Optional description of what to look for (e.g. 'pricing "
        "and plans pages'). Outgoing links are prioritized by keyword overlap "
        "with this instruction.",
    )


class ExtractRequest(BaseModel):
    url: str = Field(..., description="The URL to fetch")
    render_js: bool = Field(
        default=False,
        description="Render with a headless browser (requires the 'render' extra "
        "to be installed on the server).",
    )


class MapRequest(BaseModel):
    url: str = Field(..., description="Any URL on the target site")
    filter_pattern: str | None = Field(
        default=None, description="Optional regex to filter returned URLs"
    )


class CrawlResponse(BaseModel):
    documents_indexed: int
    total_indexed_documents: int


class IndexTextRequest(BaseModel):
    url: str
    title: str = ""
    text: str
    trust_score: float = 0.5


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__
    indexed_documents: int
    vector_search: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    return HealthResponse(
        indexed_documents=len(engine),
        vector_search=engine.index.vector_enabled,
    )


@app.post("/search", response_model=SearchResponse, tags=["search"], dependencies=[Depends(require_api_key)])
async def search(req: SearchRequest) -> SearchResponse:
    """Hybrid (BM25 + vector) search over the in-memory index."""
    return engine.search_full(req.query, top_k=req.top_k)


@app.post("/search/live", tags=["search"], dependencies=[Depends(require_api_key)])
async def search_live(req: SearchLiveRequest) -> dict:
    """Search the live internet for `query` — no seed URLs, no API key,
    no subscription required.

    Discovers relevant URLs via free public search endpoints (DuckDuckGo,
    with a Bing fallback), crawls them with Bitscrape, and ranks the
    extracted content via BIE's hybrid index.
    """
    import bie

    results = bie.websearch(
        req.query,
        top_k=req.top_k,
        discovery_results=req.discovery_results,
        deep=req.deep,
        use_embeddings=False,
    )

    return {"query": req.query, "results": [r.model_dump() for r in results]}


@app.post("/crawl/url", response_model=CrawlResponse, tags=["ingest"], dependencies=[Depends(require_api_key)])
async def crawl(req: CrawlRequest) -> CrawlResponse:
    """Trigger an on-demand crawl of one or more URLs and add to the index.

    If `instruction` is set, outgoing links are prioritized by keyword
    overlap with it (a heuristic, not full NL understanding).
    """
    n = await _async_crawl(req.urls, req.allowed_domains, req.instruction)
    return CrawlResponse(documents_indexed=n, total_indexed_documents=len(engine))


@app.post("/extract", tags=["extract"], dependencies=[Depends(require_api_key)])
async def extract_endpoint(req: ExtractRequest) -> dict:
    """Fetch a URL and return its content as clean Markdown.

    If the page appears to require JavaScript and `render_js=false`,
    returns a 422 with a message suggesting `render_js=true` (requires the
    server to have the `render` extra installed).
    """
    import bie

    try:
        result = bie.extract(req.url, render_js=req.render_js)
    except bie.ExtractError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    payload: dict = {
        "url": result.url,
        "title": result.title,
        "markdown": result.markdown,
        "word_count": result.word_count,
        "rendered_with_js": result.rendered_with_js,
    }
    if result.security:
        payload["security"] = {
            "flagged": result.security.flagged,
            "categories": sorted({f.category for f in result.security.findings}),
        }
    return payload


@app.post("/map", tags=["extract"], dependencies=[Depends(require_api_key)])
async def map_endpoint(req: MapRequest) -> dict:
    """Discover a website's sitemap and return the URLs it advertises."""
    import bie

    site_map = bie.map_site(req.url)
    urls = site_map.filter(req.filter_pattern) if req.filter_pattern else site_map.urls

    return {
        "root": site_map.root,
        "sitemap_files": site_map.sitemap_urls,
        "url_count": len(urls),
        "urls": urls[:500],
    }


@app.post("/indices/update", tags=["ingest"], dependencies=[Depends(require_api_key)])
async def index_text(req: IndexTextRequest) -> dict:
    """Push a pre-extracted document directly into the index."""
    engine.add_text(req.url, req.text, title=req.title, trust_score=req.trust_score)
    return {"status": "indexed", "total_indexed_documents": len(engine)}


@app.get("/metrics", tags=["meta"], dependencies=[Depends(require_api_key)])
async def metrics() -> dict:
    return {
        "indexed_documents": len(engine),
        "indexed_chunks": len(engine.index.chunks),
        "vector_search_enabled": engine.index.vector_enabled,
        "settings": settings.model_dump(exclude={"api_key"}),
    }


async def _async_crawl(
    urls: list[str], allowed_domains: list[str] | None, instruction: str = ""
) -> int:
    documents = await engine.crawler.acrawl(
        urls, allowed_domains=allowed_domains, instruction=instruction
    )
    for doc in documents:
        engine.add_document(doc)
    return len(documents)
