"""
``bie.crawl_site()`` — crawl a website guided by a natural-language
instruction.

This is BIE's "Crawl" primitive: given one or more seed URLs and a short
description of what you're looking for (e.g. "pricing and plans pages",
"blog posts about machine learning"), crawl the site while prioritizing
links that look relevant to that description, and return the indexed
documents plus an optional ranked search over them.

**Honest scope**: relevance is determined by keyword overlap between your
instruction and each link's anchor text + URL path (see
:mod:`bie.spiders.generic`). This is a fast, zero-dependency heuristic —
it is not an LLM reading and deciding on each page. For true
natural-language-driven navigation (e.g. "find the page that explains
their refund policy" when no link obviously says "refund"), pair
:func:`crawl_site` with your own LLM call: crawl broadly first
(``instruction=""``), then have your LLM pick which extracted documents
to read in full.
"""

from __future__ import annotations

from bie.config import BIESettings
from bie.engine import BIE
from bie.models import SearchResult


def crawl_site(
    urls: list[str],
    instruction: str = "",
    query: str | None = None,
    top_k: int = 10,
    allowed_domains: list[str] | None = None,
    **settings_kwargs,
) -> tuple[BIE, list[SearchResult]]:
    """Crawl a site (or sites) guided by ``instruction``, optionally
    ranking the results against ``query``.

    Args:
        urls: Seed URLs to start crawling from.
        instruction: Short description of what to look for, used to
            prioritize which links get followed (e.g. "documentation and
            API reference pages"). Pass ``""`` for unguided crawling
            (first-N-links order, the previous default behaviour).
        query: If given, rank the crawled content against this query
            using BIE's hybrid index and return the top ``top_k`` results
            as the second return value. If ``None`` (default), ``query``
            falls back to ``instruction`` so a single call both guides the
            crawl *and* ranks the results for the same topic. Pass an
            explicit empty string ``""`` to skip ranking entirely (the
            second return value will then be ``[]``).
        top_k: Number of ranked results to return (only relevant if
            ``query`` is non-empty).
        allowed_domains: Restrict link-following to these domains
            (defaults to the domains of ``urls``).
        **settings_kwargs: Forwarded to :class:`bie.config.BIESettings`
            (e.g. ``max_pages=50``, ``max_depth=3``).

    Returns:
        A tuple ``(engine, results)``:
          - ``engine``: the :class:`bie.BIE` instance, with all crawled
            pages indexed — inspect ``engine.index.documents`` for the
            full set, or call ``engine.search(...)`` again with a
            different query.
          - ``results``: ranked :class:`~bie.models.SearchResult` list
            for ``query`` (or ``instruction`` if ``query`` is ``None``),
            or ``[]`` if no query was given.

    Example::

        import bie

        engine, results = bie.crawl_site(
            ["https://docs.example.com"],
            instruction="API authentication and rate limits",
            max_pages=30,
            max_depth=2,
        )
        for r in results:
            print(r.title, r.url)

        # Re-query the same crawled index without re-crawling:
        more = engine.search("error codes")
    """
    engine = BIE(BIESettings(**settings_kwargs))
    engine.crawl(urls, allowed_domains=allowed_domains, instruction=instruction)

    effective_query = instruction if query is None else query
    if not effective_query:
        return engine, []

    return engine, engine.search(effective_query, top_k=top_k)
