# BIE — BitSearch Intelligence Engine

[![PyPI](https://img.shields.io/pypi/v/bits-bie.svg)](https://pypi.org/project/bits-bie/)
[![Python](https://img.shields.io/pypi/pyversions/bits-bie.svg)](https://pypi.org/project/bits-bie/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Built on Bitscrape](https://img.shields.io/badge/built%20on-Bitscrape-orange.svg)](https://github.com/Sudharsansm/Bitscrape)

**A real-time web search and crawling toolkit for AI applications — no
API keys, no subscriptions, no third-party search services.**

BIE gives any LLM, RAG pipeline, or AI agent five core primitives —
**search, extract, map, crawl, and a hybrid index** — all running locally
on top of [**BitS**](https://pypi.org/project/bitscrape/), our
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

### How this compares to ChatGPT Search / Tavily

`bie.websearch_response()` is shaped like those tools' "web search" tool
responses on purpose: ranked, cited `results` with snippets, an
`answer` field, and `.to_context()` for dropping straight into a prompt.
Two things are genuinely different, and worth being precise about:

- **`answer` is extractive, not generated.** ChatGPT Search and Tavily's
  `include_answer` run an LLM server-side to *write* a summary answer.
  BIE doesn't run an LLM — `answer` is the single best-matching passage
  found (verbatim from a live page). It's a strong starting point for
  *your* LLM/agent to read and synthesize from, not a finished answer on
  its own.
- **Discovery is "best-effort free", not a dedicated index.** ChatGPT
  Search/Tavily run their own crawl infrastructure and indexes. BIE's
  default discovery scrapes DuckDuckGo/Bing's public result pages, which
  can be rate-limited or served a CAPTCHA — `degraded`/`diagnostics` tell
  you when this happens for a given query, so your agent can react (retry,
  fall back to general knowledge, etc.) instead of silently getting a
  bad answer.

**SearXNG closes most of that second gap.** Self-hosting
[SearXNG](https://github.com/searxng/searxng) and adding it as a
discovery backend (`BIE_DISCOVERY_BACKENDS=searxng,...` +
`BIE_SEARXNG_URL=...`) gives BIE a stable JSON API that itself aggregates
Google/Bing/Brave/etc. server-side — far less prone to the "200 OK but
0 results" failure mode of scraping DDG/Bing HTML directly. It's the
single highest-leverage change for making `websearch()`'s *discovery*
step behave consistently. It doesn't change the `answer` field's
extractive (vs. LLM-generated) nature — that's a property of BIE not
running an LLM, independent of which discovery backend is used.

---

## Core primitives

| Function | What it does |
|---|---|
| `bie.websearch(query)` | Search the live internet — no URLs needed. Free discovery (DuckDuckGo + Bing fallback, optional SearXNG) with query fan-out, crawled and ranked by BIE's hybrid index. |
| `bie.websearch_response(query)` | Like `websearch`, but returns the full Tavily/ChatGPT-Search-shaped response: ranked `results`, an extractive `answer`, `degraded`/`diagnostics`, and `.to_context()` for an LLM-prompt-ready citation block. |
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
pip install "bits-bie[notebook]"    # smoother async behaviour in Jupyter/Colab
pip install "bits-bie[all]"         # everything
```

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

For the full, Tavily/ChatGPT-Search-shaped response — extractive
`answer`, timing, and `degraded`/`diagnostics` for when live discovery
doesn't fully succeed:

```python
response = bie.websearch_response("who won the latest F1 race")

print(response.answer)         # best-matching passage (not LLM-written)
print(response.to_context())    # numbered sources block, ready for a prompt

if response.degraded:
    print("live data degraded:", response.diagnostics)
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
| `discovery_backends` | `BIE_DISCOVERY_BACKENDS` | `ddg_html,ddg_lite,bing_html` | Ordered, comma-separated discovery backends for `websearch()`. Add `searxng` for a self-hosted instance. |
| `searxng_url` | `BIE_SEARXNG_URL` | `None` | Base URL of a self-hosted SearXNG instance, used by the `searxng` discovery backend |
| `api_key` | `BIE_API_KEY` | `None` | If set, requires `Authorization: Bearer <key>` |

---

## Troubleshooting

**`TypeError: '<' not supported between instances of 'Request' and 'Request'`**
during a crawl — this was a Bitscrape scheduler bug (its priority queue
compared `Request` objects directly when two requests shared the same
priority). BIE patches `bitscrape.Request` to be orderable at import
time, so this no longer occurs. If you still see it, you're likely on an
older `bits-bie` version — upgrade.

**`RuntimeError: asyncio.run() cannot be called from a running event
loop`** — Jupyter/Colab/IPython already run an event loop, which used to
break `engine.crawl(urls)` / `bie.websearch(...)`. Both now detect a
running loop automatically and either use
[`nest_asyncio`](https://pypi.org/project/nest_asyncio/) (install via
`pip install "bits-bie[notebook]"`) or fall back to running the crawl on
a background thread — no code changes needed. If you're already inside
an `async def`, you can also call `await engine.acrawl(urls)` directly.

**`bie.websearch(...)` returns `[]` / all discovery backends fail** —
discovery scrapes DuckDuckGo/Bing's public HTML result pages, which can
be blocked or rate-limited. Call
`bie.discovery.get_last_discovery_diagnostics()` right after to see why:

```python
import bie
from bie.discovery import get_last_discovery_diagnostics

results = bie.websearch("...")
if not results:
    print(get_last_discovery_diagnostics().summary())
```

This distinguishes three cases:

- **Network blocked** — every backend failed at the connection level
  (or an egress proxy returned `x-deny-reason: host_not_allowed`). This
  environment can't reach these hosts at all — check its outbound
  network/proxy/firewall config. Common in sandboxed code-execution
  environments; Colab and most servers have unrestricted outbound access.
- **Blocked / rate-limited** — backends responded with `403`/`429`/etc.,
  typically from bot-detection on a shared IP. Retry later, reduce
  request volume, or configure a `searxng` backend (below).
- **Empty response** — got `200 OK` but no parseable results (often a
  CAPTCHA/consent page).

For the most reliable no-API-key discovery, self-host
[SearXNG](https://github.com/searxng/searxng) and add it as a backend:

```bash
export BIE_DISCOVERY_BACKENDS=searxng,ddg_html,ddg_lite,bing_html
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

## Built on BitS

BIE's crawling and extraction layer is powered by
[**BitS**](https://github.com/Sudharsansm/Bitscrape)
(`pip install bitscrape`), our async, robots.txt-aware web scraping
framework — giving BIE high-performance, polite crawling out of the box.

---

## License

MIT — see [LICENSE](LICENSE).
