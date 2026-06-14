# BIE — BitSearch Intelligence Engine

[![PyPI](https://img.shields.io/pypi/v/bits-bie.svg)](https://pypi.org/project/bits-bie/)
[![Python](https://img.shields.io/pypi/pyversions/bits-bie.svg)](https://pypi.org/project/bits-bie/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Built on Bitscrape](https://img.shields.io/badge/built%20on-Bitscrape-orange.svg)](https://github.com/Sudharsansm/Bitscrape)

**A real-time web search and crawling toolkit for AI applications — no
API keys, no subscriptions, no third-party search services.**

BIE gives any LLM, RAG pipeline, or AI agent five core primitives —
**search, extract, map, crawl, and a hybrid index** — all running locally
on top of [**Bitscrape**](https://pypi.org/project/bitscrape/), our
async crawling framework. Use it as a Python library, REST API, CLI, or
[MCP](https://modelcontextprotocol.io) server.

```python
import bie

# Search the live internet — no URLs, no API key, no subscription
results = bie.websearch("latest semiconductor export rules 2026")
for r in results:
    print(r.title, "—", r.url, f"(score={r.score:.3f})")
    print(r.snippet)

# Get clean markdown from a specific page
page = bie.extract("https://example.com/article")
print(page.markdown)
```

---

## Honest scope

BIE is built to be a genuinely useful, self-hosted web search/extraction
toolkit — and we'd rather be upfront about what that means than oversell
it:

- **What's real**: working search (free public discovery + Bitscrape
  crawl + hybrid BM25/vector ranking with query fan-out), Markdown
  extraction with JS-rendering fallback, sitemap-based site mapping,
  instruction-guided crawling, a prompt-injection heuristic scanner, and
  REST/CLI/MCP/LangChain integrations — all of it runs today, with no
  paid dependencies.
- **What it isn't**: a replacement for web-scale search infrastructure.
  BIE doesn't have its own crawled index of the internet — discovery
  relies on free public search endpoints (which can rate-limit), and
  relevance ranking is BM25+embeddings, not a model tuned on years of
  query logs. "Crawl guided by natural language" means *keyword-relevance
  link prioritization*, not an LLM reading every page. The
  prompt-injection scanner is a pattern-matching heuristic, not a
  guarantee.

If your use case needs guaranteed uptime, massive scale, or
state-of-the-art ranking, a commercial search API may still be the right
choice for that piece. BIE is for teams that want a capable, free,
self-hosted starting point — and full control over the code.

---

## Core primitives

| Function | What it does |
|---|---|
| `bie.websearch(query)` | Search the live internet — no URLs needed. Free discovery (DuckDuckGo + Bing fallback) with query fan-out, crawled and ranked by BIE's hybrid index. |
| `bie.extract(url)` | Fetch a URL and return clean Markdown, with nav/ads/scripts stripped. Optional JS rendering via Playwright. |
| `bie.map_site(url)` | Discover a site's sitemap(s) and the URLs they list, before crawling. |
| `bie.crawl_site(urls, instruction=...)` | Crawl a site, prioritizing links by keyword-relevance to your instruction. Returns an index + ranked results. |
| `bie.search(query, urls=...)` | Crawl specific URLs and rank their content against a query. |
| `bie.BIE()` | Build a persistent, queryable hybrid index across multiple crawls. |
| `bie.scan_for_prompt_injection(text)` | Heuristic scan for prompt-injection patterns in crawled content. |

---

## Install

```bash
pip install bits-bie
```

> Note: the PyPI **distribution** is named `bits-bie` (since `bie` was
> too similar to an existing PyPI project), but you still `import bie`
> and run the `bie` CLI command — same API as shown below.

Optional extras:

```bash
pip install "bits-bie[embeddings]"  # semantic/vector search (sentence-transformers)
pip install "bits-bie[server]"      # FastAPI + Uvicorn REST server
pip install "bits-bie[mcp]"         # Model Context Protocol server
pip install "bits-bie[render]"      # JS rendering for extract() via Playwright
pip install "bits-bie[langchain]"   # LangChain tool adapters
pip install "bits-bie[notebook]"    # smoother Jupyter/Colab support (nest_asyncio)
pip install "bits-bie[all]"         # everything
```

> **Using BIE in Jupyter / Google Colab?** All sync entry points
> (`engine.crawl(...)`, `bie.websearch(...)`, `bie.extract(..., render_js=True)`)
> work inside notebooks out of the box — BIE detects the notebook's
> already-running event loop and handles it automatically. Installing
> `bits-bie[notebook]` (adds `nest_asyncio`) makes this slightly more
> efficient, but is not required.

> BIE depends on [`bitscrape`](https://pypi.org/project/bitscrape/), our
> proprietary async crawling & extraction framework, which is installed
> automatically.

---

## Usage

### 1. Search the live internet — no URLs, no API key, no subscription

```python
import bie

results = bie.websearch("who won the latest F1 race")
for r in results:
    print(r.title, "—", r.url)
    print(r.snippet)
```

`websearch` pipeline:

1. **Discovery** — free, public, no-key search endpoints (DuckDuckGo,
   with an automatic Bing fallback). By default, several phrasings of
   your query are searched and merged (`fanout=True`) for better recall.
2. **Crawl** — discovered URLs are crawled with Bitscrape.
3. **Rank** — extracted content is chunked and ranked against your query
   with BIE's hybrid BM25 + vector index.
4. **Security filter** — results whose matched text trips the
   prompt-injection heuristic (`bie.security`) are dropped by default.

Useful options: `top_k`, `discovery_results`, `fanout`,
`max_query_variants`, `deep`, `scan_security`, `use_embeddings`.

### 2. Extract — clean Markdown from a specific URL

```python
page = bie.extract("https://example.com/article")
print(page.title)
print(page.markdown)
print(page.word_count)

# For JS-rendered (SPA) pages:
page = bie.extract("https://app.example.com", render_js=True)  # requires bie[render]
```

If a static fetch returns suspiciously little text, `extract` raises
`ExtractError` suggesting `render_js=True` rather than silently returning
near-empty content.

Every result includes `page.security` — a `SecurityReport` flagging
prompt-injection-like patterns in the extracted text (see
[Security](#security) below).

### 3. Map — discover a site's structure before crawling

```python
sitemap = bie.map_site("https://example.com")
print(sitemap.sitemap_urls)        # which sitemap files were found
print(len(sitemap.urls))           # how many pages they list
print(sitemap.filter(r"/blog/"))   # just the blog URLs
```

Based on the sitemaps.org protocol: reads `robots.txt` for `Sitemap:`
directives, falls back to `/sitemap.xml`, and recursively expands sitemap
indexes.

### 4. Crawl — guided by a natural-language instruction

```python
engine, results = bie.crawl_site(
    ["https://docs.example.com"],
    instruction="authentication and rate limits",
    max_pages=30,
    max_depth=2,
)
for r in results:
    print(r.title, r.url)

# Re-query the same crawled index without re-crawling:
more = engine.search("error codes")
```

Outgoing links are ranked by keyword overlap between your instruction and
each link's anchor text + URL path — a fast heuristic that biases the
crawl toward relevant pages without an LLM call per page.

### 5. Search specific sites (no live-web discovery)

```python
results = bie.search("AI regulation news", urls=["https://example.com/news"], top_k=5)
for r in results:
    print(r)
```

### 6. Build a reusable index

```python
from bie import BIE

engine = BIE()
engine.crawl(["https://example.com/blog", "https://another-site.com"])

print(engine.search("quarterly earnings"))
print(engine.search("product launch"))  # reuses the same index

# Index your own text (no crawling):
engine.add_text(url="internal://doc-1", title="Q2 Memo", text="...", trust_score=1.0)
```

### 7. CLI

```bash
# Search the live internet — no URLs needed
bie search-live "who won the latest F1 race"

# Clean markdown from a URL
bie extract https://example.com/article

# Discover a site's sitemap
bie map https://example.com --filter "/blog/"

# Crawl, guided by an instruction
bie crawl https://docs.example.com --instruction "authentication and rate limits" --max-pages 30

# Crawl + search specific sites in one command
bie search "global markets today" --url https://www.bbc.com/news --top-k 5

# Run the REST API
bie serve --port 8000

# Run as an MCP server (stdio)
bie mcp
```

### 8. REST API

```bash
bie serve --port 8000
```

```bash
curl -X POST http://localhost:8000/search/live \
  -H "Content-Type: application/json" \
  -d '{"query": "who won the latest F1 race", "top_k": 5}'

curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article"}'

curl -X POST http://localhost:8000/map \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

curl -X POST http://localhost:8000/crawl/url \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://example.com/news"], "instruction": "pricing pages"}'

curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "latest news", "top_k": 5}'
```

See the full endpoint contract in [`docs/API.md`](docs/API.md).

### 9. MCP (Model Context Protocol)

Add BIE as a tool in your MCP client (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bie": {
      "command": "bie",
      "args": ["mcp"]
    }
  }
}
```

This exposes six tools to your AI assistant:

- `bie_web_search(query, top_k, deep)` — search the live internet, no URLs needed
- `bie_extract(url, render_js)` — fetch a URL as clean Markdown
- `bie_map(url, filter_pattern)` — discover a site's sitemap
- `bie_search(query, urls, top_k, max_pages)` — crawl + search specific URLs
- `bie_crawl(urls, max_pages, instruction)` — crawl & index into a session-persistent store
- `bie_index_search(query, top_k)` — search the session index

### 10. LangChain

```python
from bie.integrations.langchain import get_tools

tools = get_tools()  # [bie_websearch, bie_extract, bie_crawl_site]
# pass `tools` to your LangChain/LangGraph agent
```

Requires `pip install "bits-bie[langchain]"`.

---

## Security

BIE includes `bie.scan_for_prompt_injection(text)` — a pattern-based
heuristic that flags text likely to contain instructions aimed at an LLM
(e.g. "ignore previous instructions...", fake `SYSTEM:` blocks, requests
to reveal a system prompt).

- `bie.extract()` attaches a `SecurityReport` to every result
  (`result.security`).
- `bie.websearch()` drops results whose matched chunk trips the
  heuristic by default (`scan_security=True`).

**This is a signal, not a guarantee.** It catches common, unobfuscated
injection phrasing in crawled web content — it will not catch everything,
and legitimate pages *discussing* prompt injection may occasionally be
flagged. Treat `flagged=True` as "review before feeding this directly
into a high-privilege agent context," not as "this content is dangerous"
or "unflagged content is safe." See `bie/security.py` for the full pattern
list and caveats.

---

## Configuration

All settings can be set via environment variables prefixed with `BIE_`,
or passed directly:

```python
from bie import BIE, BIESettings

engine = BIE(BIESettings(
    max_pages=20,
    max_depth=1,
    use_embeddings=True,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    bm25_weight=0.6,
    vector_weight=0.4,
))
```

| Setting | Env var | Default | Description |
|---|---|---|---|
| `max_pages` | `BIE_MAX_PAGES` | `40` | Max pages crawled per seed URL |
| `max_depth` | `BIE_MAX_DEPTH` | `2` | Max link-follow depth |
| `concurrent_requests` | `BIE_CONCURRENT_REQUESTS` | `16` | Crawl concurrency |
| `robotstxt_obey` | `BIE_ROBOTSTXT_OBEY` | `true` | Respect robots.txt |
| `use_embeddings` | `BIE_USE_EMBEDDINGS` | `true` | Enable semantic search |
| `chunk_size` | `BIE_CHUNK_SIZE` | `800` | Chars per chunk |
| `bm25_weight` / `vector_weight` | `BIE_BM25_WEIGHT` / `BIE_VECTOR_WEIGHT` | `0.5` / `0.5` | Fusion weights |
| `api_key` | `BIE_API_KEY` | `None` | If set, requires `Authorization: Bearer <key>` |
| — | `BIE_DISCOVERY_BACKENDS` | `ddg_html,ddg_lite,bing_html` | Comma-separated list and order of `websearch()` discovery backends. Known names: `ddg_html`, `ddg_lite`, `bing_html`, `searxng`. |
| — | `BIE_SEARXNG_URL` | `None` | Base URL of a self-hosted [SearXNG](https://docs.searxng.org/) instance, used when `searxng` is included in `BIE_DISCOVERY_BACKENDS`. |

### Discovery backends & troubleshooting empty `websearch()` results

`websearch()` discovers candidate URLs by scraping public search-engine
result pages (DuckDuckGo HTML, DuckDuckGo Lite, Bing HTML, in that order
by default). This is inherently fragile — these are not official APIs,
and shared/cloud IPs (CI runners, some notebook hosts, restrictive
sandboxes) can be rate-limited or blocked entirely.

If `websearch()` returns `[]`, BIE logs a `WARNING` that distinguishes
two failure categories:

- **"network blocked"** — every backend failed at the connection level
  (timeouts, connection refused, or a sandbox/proxy denial). This means
  the environment itself can't reach these hosts — re-run in an
  environment with normal internet access (a local machine, server, or
  Colab) rather than a locked-down sandbox.
- **"reachable but no results"** — connections succeeded but responses
  were empty, a CAPTCHA/consent page, or rate-limited (HTTP 403/429).
  This means the IP is likely being rate-limited; try again later, reduce
  request frequency, or switch to a self-hosted backend (below).

For a durable fix to rate-limiting, run a self-hosted
[SearXNG](https://docs.searxng.org/) instance and point BIE at it:

```bash
export BIE_DISCOVERY_BACKENDS=searxng
export BIE_SEARXNG_URL=http://localhost:8080
```

You can also combine backends and reorder them, e.g. to prefer your
SearXNG instance but fall back to DuckDuckGo:

```bash
export BIE_DISCOVERY_BACKENDS=searxng,ddg_html,ddg_lite
export BIE_SEARXNG_URL=http://localhost:8080
```

---

## Architecture

```
              ┌─────────────────────────────────────────────────┐
              │                       bie                        │
              │                                                   │
   query ──▶  │  discovery (DuckDuckGo/Bing) ──▶ query fan-out    │
              │           │                                       │
   urls ──▶   │           ▼                                       │
              │  Crawler (Bitscrape) ──▶ Document ──▶ Chunker      │
              │           │                            │          │
              │           │                            ▼          │
              │           │                      HybridIndex      │
              │           │                     BM25 + Vector      │
              │           │                       (RRF fusion)     │
              │           ▼                            │          │
              │     extract()/map()         Ranked SearchResults   │
              │      (standalone)                      │          │
              │                                security scan       │
              └─────────────────────────────────────────────────┘
                     │            │            │            │
                  Python API   REST API    MCP Server   LangChain
```

This OSS edition implements the core of the BIE PRD's **Module 1
(Crawler)**, **Module 2 (Indexes)**, **Module 3 (Hybrid Retriever)**, and
**Module 11 (Agent API)** as a single lightweight package — no external
services required. Larger deployments can swap `BM25Index`/`VectorIndex`
for Elasticsearch/Milvus-backed implementations behind the same
`HybridIndex` interface.

---

## Built on Bitscrape

BIE's crawling and extraction layer is powered by
[**Bitscrape**](https://github.com/Sudharsansm/Bitscrape)
(`pip install bitscrape`), our async, robots.txt-aware web scraping
framework — giving BIE high-performance, polite crawling out of the box.

---

## License

MIT — see [LICENSE](LICENSE).
