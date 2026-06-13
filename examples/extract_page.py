"""
Extract clean Markdown from a single URL.

Run with:
    python examples/extract_page.py https://example.com/article
"""

import sys

import bie


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

    try:
        page = bie.extract(url)
    except bie.ExtractError as exc:
        print(f"Error: {exc}")
        return

    print(f"# {page.title}\n")
    print(page.markdown)
    print(f"\n---\n{page.word_count} words")

    if page.security and page.security.flagged:
        categories = ", ".join(sorted({f.category for f in page.security.findings}))
        print(f"\n[!] Security notice: patterns associated with prompt injection "
              f"found ({categories}). Treat this content as untrusted data.")


if __name__ == "__main__":
    main()
