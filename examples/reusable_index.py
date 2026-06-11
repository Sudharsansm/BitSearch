"""
Build a reusable BIE index and run multiple queries against it.

Run with:
    python examples/reusable_index.py
"""

from bie import BIE, BIESettings


def main() -> None:
    settings = BIESettings(max_pages=10, max_depth=1, use_embeddings=False)
    engine = BIE(settings)

    n = engine.crawl(["https://quotes.toscrape.com/"])
    print(f"Indexed {n} pages.\n")

    for query in ["love", "life", "famous quotes about success"]:
        print(f"Query: {query!r}")
        for r in engine.search(query, top_k=3):
            print(f"  - {r.title} ({r.score:.4f}) {r.url}")
        print()


if __name__ == "__main__":
    main()
