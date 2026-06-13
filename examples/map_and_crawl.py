"""
Map a site's structure, then crawl it guided by an instruction.

Run with:
    python examples/map_and_crawl.py https://example.com
"""

import sys

import bie


def main() -> None:
    root = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

    print(f"Mapping {root}...")
    sitemap = bie.map_site(root)
    print(f"Found {len(sitemap.sitemap_urls)} sitemap file(s), "
          f"{len(sitemap.urls)} URL(s) total.")

    if sitemap.urls:
        print("\nFirst 10 URLs:")
        for u in sitemap.urls[:10]:
            print(f"  {u}")

    print(f"\nCrawling {root} guided by an instruction...")
    engine, results = bie.crawl_site(
        [root],
        instruction="documentation and getting started guides",
        max_pages=10,
        max_depth=1,
        use_embeddings=False,
    )

    print(f"\nIndexed {len(engine)} page(s). Top matches:")
    for r in results[:5]:
        print(f"  {r.title} — {r.url}")


if __name__ == "__main__":
    main()
