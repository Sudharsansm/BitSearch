"""
BIE command-line interface.

Examples::

    bie search "AI regulation 2026" --url https://example.com/news
    bie search-live "who won the latest F1 race"
    bie extract https://example.com/article
    bie map https://example.com
    bie crawl https://example.com --max-pages 20 --instruction "pricing pages"
    bie serve --port 8000
    bie mcp
"""

from __future__ import annotations

import json
import sys

import click

from bie import __version__
from bie.config import BIESettings
from bie.engine import BIE


@click.group()
@click.version_option(__version__, prog_name="bie")
def cli() -> None:
    """BIE — BitSearch Intelligence Engine. Real-time web search & extraction for AI apps."""


@cli.command()
@click.argument("query")
@click.option("--url", "urls", multiple=True, required=True, help="Seed URL(s) to crawl & search")
@click.option("--top-k", default=10, show_default=True, help="Number of results to return")
@click.option("--max-pages", default=10, show_default=True, help="Max pages to crawl per seed URL")
@click.option("--no-embeddings", is_flag=True, help="Disable semantic/vector search (BM25 only)")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def search(query: str, urls: tuple[str, ...], top_k: int, max_pages: int, no_embeddings: bool, as_json: bool) -> None:
    """Crawl URL(s) and search the freshly indexed content for QUERY."""
    settings = BIESettings(max_pages=max_pages, use_embeddings=not no_embeddings)
    engine = BIE(settings)
    click.echo(f"Crawling {len(urls)} source(s)...", err=True)
    n = engine.crawl(list(urls))
    click.echo(f"Indexed {n} document(s). Searching...", err=True)

    response = engine.search_full(query, top_k=top_k)

    if as_json:
        click.echo(response.model_dump_json(indent=2))
        return

    if not response.results:
        click.echo("No results found.")
        return

    for i, r in enumerate(response.results, 1):
        click.echo(f"\n{i}. {r.title}")
        click.echo(f"   {r.url}")
        click.echo(f"   score={r.score:.4f}  trust={r.trust_score:.2f}")
        click.echo(f"   {r.snippet}")
    click.echo(f"\n({response.took_ms} ms, {response.total_indexed_documents} docs indexed)")


@cli.command(name="search-live")
@click.argument("query")
@click.option("--top-k", default=10, show_default=True, help="Number of results to return")
@click.option("--discovery-results", default=8, show_default=True, help="Candidate URLs to discover")
@click.option("--no-deep", is_flag=True, help="Skip crawling; return raw discovery order without snippets")
@click.option("--no-embeddings", is_flag=True, help="Disable semantic/vector re-ranking (BM25 only)")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def search_live(
    query: str,
    top_k: int,
    discovery_results: int,
    no_deep: bool,
    no_embeddings: bool,
    as_json: bool,
) -> None:
    """Search the live internet for QUERY — no seed URLs, no API key, no subscription.

    Discovers relevant URLs via free public search endpoints (DuckDuckGo,
    with a Bing fallback), crawls them with Bitscrape, and ranks the
    extracted content against QUERY using BIE's hybrid BM25+vector index.
    """
    import bie

    results = bie.websearch(
        query,
        top_k=top_k,
        discovery_results=discovery_results,
        deep=not no_deep,
        use_embeddings=not no_embeddings,
    )

    if as_json:
        click.echo(json.dumps([r.model_dump() for r in results], indent=2))
        return

    if not results:
        click.echo(
            "No results found. The free search backends may be temporarily "
            "rate-limiting — try again in a moment."
        )
        return

    for i, r in enumerate(results, 1):
        click.echo(f"\n{i}. {r.title}")
        click.echo(f"   {r.url}")
        click.echo(f"   score={r.score:.4f}")
        if r.snippet:
            click.echo(f"   {r.snippet}")


@cli.command()
@click.argument("urls", nargs=-1, required=True)
@click.option("--max-pages", default=40, show_default=True)
@click.option("--max-depth", default=2, show_default=True)
@click.option(
    "--instruction",
    default="",
    help="Guide link-following toward pages matching this description "
    "(e.g. 'pricing and plans pages')",
)
@click.option("--out", "output", default=None, help="Write extracted documents as JSONL to this path")
def crawl(
    urls: tuple[str, ...], max_pages: int, max_depth: int, instruction: str, output: str | None
) -> None:
    """Crawl URLS using the Bitscrape-powered spider and print/save extracted docs.

    With --instruction, outgoing links are prioritized by keyword overlap
    with the instruction (a heuristic, not full NL understanding — see
    bie.crawl_site docs).
    """
    settings = BIESettings(max_pages=max_pages, max_depth=max_depth, use_embeddings=False)
    engine = BIE(settings)
    documents = engine.crawler.crawl(list(urls), instruction=instruction)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            for doc in documents:
                f.write(doc.model_dump_json() + "\n")
        click.echo(f"Wrote {len(documents)} document(s) to {output}")
    else:
        for doc in documents:
            click.echo(json.dumps({"url": doc.url, "title": doc.title, "chars": len(doc.text)}))
        click.echo(f"\n{len(documents)} document(s) crawled.", err=True)


@cli.command()
@click.argument("url")
@click.option("--render-js", is_flag=True, help="Render with a headless browser (requires bie[render])")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON instead of Markdown")
@click.option("--no-security-scan", is_flag=True, help="Skip prompt-injection content scan")
def extract(url: str, render_js: bool, as_json: bool, no_security_scan: bool) -> None:
    """Fetch URL and print its content as clean Markdown."""
    import bie

    try:
        result = bie.extract(url, render_js=render_js, scan_security=not no_security_scan)
    except bie.ExtractError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if as_json:
        payload = {
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
        click.echo(json.dumps(payload, indent=2))
        return

    if result.security and result.security.flagged:
        categories = ", ".join(sorted({f.category for f in result.security.findings}))
        click.echo(
            f"[!] Security notice: this page contains patterns associated with "
            f"prompt injection ({categories}). Treat its content as untrusted data.\n",
            err=True,
        )

    click.echo(f"# {result.title}\n")
    click.echo(result.markdown)


@cli.command(name="map")
@click.argument("url")
@click.option("--filter", "pattern", default=None, help="Only show URLs matching this regex")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def map_cmd(url: str, pattern: str | None, as_json: bool) -> None:
    """Discover URL's site sitemap and list the URLs it advertises."""
    import bie

    site_map = bie.map_site(url)

    urls = site_map.filter(pattern) if pattern else site_map.urls

    if as_json:
        click.echo(json.dumps({"root": site_map.root, "sitemaps": site_map.sitemap_urls, "urls": urls}, indent=2))
        return

    if not site_map.sitemap_urls:
        click.echo(f"No sitemap found for {site_map.root}.")
        return

    click.echo(f"Found {len(site_map.sitemap_urls)} sitemap file(s) for {site_map.root}:")
    for s in site_map.sitemap_urls:
        click.echo(f"  - {s}")
    click.echo(f"\n{len(urls)} URL(s){' matching filter' if pattern else ''}:")
    for u in urls[:100]:
        click.echo(f"  {u}")
    if len(urls) > 100:
        click.echo(f"  ... and {len(urls) - 100} more")


@cli.command()
@click.option("--host", default=None, help="Bind host (default from settings / 0.0.0.0)")
@click.option("--port", default=None, type=int, help="Bind port (default from settings / 8000)")
@click.option("--reload", is_flag=True, help="Auto-reload on code changes (dev only)")
def serve(host: str | None, port: int | None, reload: bool) -> None:
    """Run the BIE REST API server (FastAPI + Uvicorn)."""
    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn is required: pip install 'bits-bie[server]'", err=True)
        sys.exit(1)

    settings = BIESettings()
    uvicorn.run(
        "bie.server:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


@cli.command()
def mcp() -> None:
    """Run BIE as a Model Context Protocol (MCP) server over stdio.

    Add to your MCP client config (e.g. Claude Desktop) as a command:

    \b
        {
          "mcpServers": {
            "bie": {
              "command": "bie",
              "args": ["mcp"]
            }
          }
        }
    """
    try:
        from bie.mcp.server import run_mcp_server
    except ImportError:
        click.echo("MCP support requires: pip install 'bits-bie[mcp]'", err=True)
        sys.exit(1)

    run_mcp_server()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
