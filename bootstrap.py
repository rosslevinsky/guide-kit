#!/usr/bin/env python3
"""One-shot rename-your-fork script.

After `gh repo create my-new-guide --template rosslevinsky/guide-template`,
run this from the new repo's root:

    pixi run python bootstrap.py "My Guide Title" my-guide-slug
    # full form:
    pixi run python bootstrap.py "My Guide Title" my-guide-slug \\
        --author "Author Name" \\
        --description "Short description for PDF metadata + pixi.toml" \\
        --keywords "kw1, kw2, kw3"

What it does:
  * build.py:   sets TITLE, OUTPUT_SLUG, and (when provided) AUTHOR /
                DESCRIPTION / KEYWORDS.
  * pixi.toml:  sets name + description.
  * README.md:  substitutes {{GUIDE_NAME}} / {{GUIDE_SLUG}}, and removes the
                "## Getting started from this template" section (it no
                longer applies to an initialized fork).
  * CLAUDE.md:  substitutes {{GUIDE_NAME}} / {{GUIDE_SLUG}} and
                <DESCRIBE YOUR GUIDE>.
  * Deletes `.template-uninitialized` so build.py's template-hygiene check
    starts catching un-substituted placeholders going forward.
  * Deletes itself.

It refuses to run twice (it checks for the sentinel file first).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
SENTINEL = ROOT / ".template-uninitialized"


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _validate(title: str, slug: str) -> None:
    if not SENTINEL.exists():
        sys.exit(
            "bootstrap.py: this repo has already been initialized "
            "(`.template-uninitialized` is gone). Refusing to run."
        )
    if not title.strip():
        sys.exit("bootstrap.py: title cannot be empty.")
    if '"' in title:
        sys.exit("bootstrap.py: title must not contain double quotes.")
    if not SLUG_RE.match(slug):
        sys.exit(
            f"bootstrap.py: slug {slug!r} must be kebab-case "
            "(lowercase letters, digits, dashes; must start and end alphanumeric)."
        )


def _sub_build_py(
    title: str, slug: str,
    author: str | None, description: str | None, keywords: str | None,
) -> None:
    p = ROOT / "build.py"
    text = p.read_text()
    text = re.sub(r'^TITLE\s*=\s*"[^"]*"', f'TITLE = "{title}"', text, count=1, flags=re.M)
    text = re.sub(r'^OUTPUT_SLUG\s*=\s*"[^"]*"', f'OUTPUT_SLUG = "{slug}"', text, count=1, flags=re.M)
    if author is not None:
        text = re.sub(r'^AUTHOR\s*=\s*"[^"]*"', f'AUTHOR = "{author}"', text, count=1, flags=re.M)
    if description is not None:
        # DESCRIPTION is a parenthesized multi-line string in the template; replace
        # the whole assignment in one shot.
        new_block = (
            f'DESCRIPTION = (\n'
            f'    "{description} "\n'
            f'    "Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0): "\n'
            f'    "https://creativecommons.org/licenses/by/4.0/"\n'
            f')'
        )
        text = re.sub(
            r'^DESCRIPTION\s*=\s*\([^)]*\)',
            new_block,
            text, count=1, flags=re.M | re.S,
        )
    if keywords is not None:
        text = re.sub(r'^KEYWORDS\s*=\s*"[^"]*"', f'KEYWORDS = "{keywords}"', text, count=1, flags=re.M)
    p.write_text(text)
    print("  build.py        updated")


def _sub_pixi_toml(slug: str, description: str | None) -> None:
    p = ROOT / "pixi.toml"
    text = p.read_text()
    text = re.sub(r'^name\s*=\s*"[^"]*"', f'name = "{slug}"', text, count=1, flags=re.M)
    if description is not None:
        text = re.sub(
            r'^description\s*=\s*"[^"]*"',
            f'description = "{description}"',
            text, count=1, flags=re.M,
        )
    p.write_text(text)
    print("  pixi.toml       updated")


def _sub_readme(title: str, slug: str) -> None:
    p = ROOT / "README.md"
    text = p.read_text()
    text = text.replace("{{GUIDE_NAME}}", title).replace("{{GUIDE_SLUG}}", slug)
    # Strip the "Getting started from this template" section — it doesn't apply
    # post-bootstrap. The section runs from its heading to (but not including)
    # the next H2 heading.
    text = re.sub(
        r"\n## Getting started from this template\n.*?(?=\n## )",
        "\n",
        text, count=1, flags=re.S,
    )
    p.write_text(text)
    print("  README.md       updated")


def _sub_claude(title: str, slug: str) -> None:
    p = ROOT / "CLAUDE.md"
    text = p.read_text()
    text = text.replace("{{GUIDE_NAME}}", title).replace("{{GUIDE_SLUG}}", slug)
    text = text.replace("<DESCRIBE YOUR GUIDE>\n\n", "")
    p.write_text(text)
    print("  CLAUDE.md       updated")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Initialize a fork of guide-template with your own title, slug, and metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("title", help='Guide title, e.g. "A Beginner\'s Guide to Foo".')
    p.add_argument("slug", help="Kebab-case slug; drives the PDF filename and pixi project name.")
    p.add_argument("--author", help="Author name (overrides build.py AUTHOR).")
    p.add_argument("--description", help="Short description (build.py DESCRIPTION + pixi.toml description).")
    p.add_argument("--keywords", help='Comma-separated keywords (build.py KEYWORDS).')
    args = p.parse_args()

    _validate(args.title, args.slug)

    print(f"Initializing fork as {args.title!r} (slug: {args.slug})...")
    _sub_build_py(args.title, args.slug, args.author, args.description, args.keywords)
    _sub_pixi_toml(args.slug, args.description)
    _sub_readme(args.title, args.slug)
    _sub_claude(args.title, args.slug)

    SENTINEL.unlink()
    print("  .template-uninitialized  removed")

    # Self-delete LAST so a failure in any earlier step leaves bootstrap.py in
    # place for a retry.
    Path(__file__).unlink()
    print("  bootstrap.py    removed")

    print()
    print("Done. Next steps:")
    print(f"  1. Write your guide in `guide.md`.")
    print(f"  2. `make` to render, eyeball `{args.slug}.pdf`.")
    print(f"  3. `make release MSG=\"Initial content\"` to commit source + baseline.")
    print(f"  4. `git push` to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
