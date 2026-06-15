"""
Core data models for BIE.

These mirror the schemas defined in the BIE PRD (Section 7), but kept
intentionally lean for the OSS / single-process edition.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class Document(BaseModel):
    """A crawled and cleaned document, ready for indexing."""

    doc_id: str = Field(default_factory=_new_id)
    url: str
    title: str = ""
    text: str = ""
    publish_date: Optional[str] = None
    site: str = ""
    lang: str = "en"
    content_type: str = "article"
    trust_score: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)
    crawled_at: float = Field(default_factory=time.time)

    model_config = {"extra": "allow"}


class Chunk(BaseModel):
    """A paragraph/section-level chunk of a Document, used for retrieval."""

    chunk_id: str = Field(default_factory=_new_id)
    doc_id: str
    text: str
    start_offset: int = 0
    end_offset: int = 0
    embedding: Optional[list[float]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """A single ranked search result returned to the caller."""

    title: str
    url: str
    snippet: str
    source: str
    score: float
    bm25_score: float = 0.0
    vector_score: float = 0.0
    trust_score: float = 0.5
    publish_date: Optional[str] = None
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"[{self.score:.3f}] {self.title} — {self.url}"


class SearchResponse(BaseModel):
    """Full response payload for /search and the Python API."""

    query: str
    results: list[SearchResult] = Field(default_factory=list)
    took_ms: float = 0.0
    total_indexed_documents: int = 0

    answer: Optional[str] = None
    """An *extractive* "quick answer" — the most relevant passage found
    (currently the top result's snippet), trimmed to a sentence boundary.

    This is **not** LLM-generated; BIE doesn't run an LLM itself. It's the
    single best-matching passage from live web content, intended as a
    starting point for the calling LLM/agent — which reads this (and the
    full ``results`` with citations) and writes the actual final answer.
    ``None`` if no result has extracted text (e.g. discovery/crawling
    degraded, or ``deep=False``).
    """

    degraded: bool = False
    """``True`` if live discovery/crawling didn't fully succeed and
    ``results`` are bare discovered URLs without extracted content/snippets
    (rather than ranked, crawled, indexed results). See ``diagnostics``."""

    diagnostics: Optional[str] = None
    """Human-readable explanation when ``degraded`` is ``True`` — e.g.
    why discovery backends failed (network-blocked vs. rate-limited vs.
    CAPTCHA) per :func:`bie.discovery.get_last_discovery_diagnostics`, or
    why crawling produced no extractable content."""

    def to_context(self, max_results: Optional[int] = None, snippet_chars: int = 500) -> str:
        """Render this response as a compact, citation-numbered text block
        suitable for dropping straight into an LLM prompt — the format
        ChatGPT Search / Tavily-style "search tool results" typically take:
        an optional extractive answer, followed by numbered sources with
        title, URL, and snippet.

        Args:
            max_results: Cap the number of sources included (default: all
                of ``results``).
            snippet_chars: Truncate each source's snippet to roughly this
                many characters.

        Returns:
            A plain-text block. Empty results render as ``"No results
            found."`` (plus any ``diagnostics`` note) rather than an empty
            string, so it's always safe to insert directly into a prompt.
        """
        lines: list[str] = []

        if self.answer:
            lines.append(f"Answer: {self.answer}")
            lines.append("")

        if self.degraded:
            note = "Note: live web discovery/crawling was degraded for this query"
            if self.diagnostics:
                note += f" ({self.diagnostics})"
            note += (
                "; sources below may be unranked URLs without extracted "
                "content. Treat with appropriate caution."
            )
            lines.append(note)
            lines.append("")

        results = self.results[:max_results] if max_results else self.results
        if not results:
            lines.append("No results found.")
            return "\n".join(lines).strip()

        lines.append("Sources:")
        for i, result in enumerate(results, 1):
            lines.append(f"[{i}] {result.title} — {result.url}")
            if result.snippet:
                snippet = result.snippet.strip()
                if snippet_chars and len(snippet) > snippet_chars:
                    snippet = snippet[:snippet_chars].rstrip() + "…"
                lines.append(f"    {snippet}")
            lines.append("")

        return "\n".join(lines).strip()
