"""
Search the live internet — no seed URLs, no API key, no subscription.

Discovers relevant URLs for your query via free public search endpoints
(DuckDuckGo, with a Bing fallback), crawls them with Bitscrape, and ranks
the content with BIE's hybrid BM25 + vector index.

Run with:
    python examples/web_search.py "your question here"
"""

import sys

import bie


def main() -> None:
    query = " ".join(sys.argv[1:]) or "who won the latest F1 race"

    print(f"Searching the web for: {query!r}\n")

    results = bie.websearch(
        query,
        top_k=5,
        use_embeddings=False,  # set True (default) for semantic re-ranking
    )

    if not results:
        print("No results found. The free search backends may be temporarily "
              "rate-limiting — try again in a moment.")
        return

    for i, r in enumerate(results, 1):
        print(f"{i}. {r.title}")
        print(f"   {r.url}")
        print(f"   score={r.score:.4f}")
        if r.snippet:
            print(f"   {r.snippet}")
        print()


if __name__ == "__main__":
    main()
