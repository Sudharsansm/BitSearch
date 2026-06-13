"""
Simple query-variant generation for fan-out web search.

This is intentionally lightweight — no LLM call, no external service.
It generates a small number of rephrasings/expansions of a query using
basic heuristics, which together with
:func:`bie.discovery.discover_urls_multi` improves recall over a single
query for ambiguous or multi-part questions.

For genuinely LLM-quality query expansion, callers can instead generate
variants themselves (e.g. with their own LLM call) and pass them directly
to :func:`bie.discovery.discover_urls_multi`.
"""

from __future__ import annotations

import re

# Words that add little to a web search query and can be dropped in a
# "stripped" variant.
_FILLER_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "what",
    "who",
    "where",
    "when",
    "why",
    "how",
    "does",
    "do",
    "did",
    "please",
    "tell",
    "me",
    "about",
    "of",
    "for",
}

_WORD_RE = re.compile(r"\w+")


def generate_query_variants(query: str, max_variants: int = 3) -> list[str]:
    """Generate up to ``max_variants`` query strings (including the
    original) to widen discovery for :func:`bie.websearch`.

    Heuristics applied:
      - The original query, unchanged (always first).
      - A "keywords only" variant with common question/filler words
        removed (helps on search engines that weight exact phrase
        matches).
      - If the query ends with a question mark or starts with a
        wh-word ("who/what/when/where/why/how"), an "current 2026"
        variant is added to bias toward recent results for
        time-sensitive questions.

    Args:
        query: The original user query.
        max_variants: Maximum number of variants to return (including the
            original).

    Returns:
        A list of 1..``max_variants`` query strings, the first of which
        is always the original ``query``.
    """
    variants = [query]

    keywords = _strip_filler_words(query)
    if keywords and keywords.lower() != query.lower() and keywords not in variants:
        variants.append(keywords)

    if _looks_time_sensitive(query) and len(variants) < max_variants:
        recency_variant = f"{query} latest update"
        if recency_variant not in variants:
            variants.append(recency_variant)

    return variants[:max_variants]


def _strip_filler_words(query: str) -> str:
    words = _WORD_RE.findall(query)
    kept = [w for w in words if w.lower() not in _FILLER_WORDS]
    return " ".join(kept) if kept else query


def _looks_time_sensitive(query: str) -> bool:
    lowered = query.lower().strip()
    time_words = ("latest", "current", "today", "now", "recent", "this week", "this year")
    return (
        lowered.endswith("?")
        or lowered.startswith(("who ", "what ", "when ", "where ", "why ", "how "))
        or any(w in lowered for w in time_words)
    )
