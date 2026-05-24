#!/usr/bin/env python3
"""Build the styled PDF from guide.md.

Default output (`python build.py`):
  guide-template.pdf  -- styled PDF, written to the repo root

Pipeline:
  pandoc converts guide.md to an HTML body, we wrap it in a template that
  injects style.css, then WeasyPrint renders that to PDF. Pass --html-preview
  to emit a standalone HTML (also at the repo root, gitignored) for fast
  browser iteration.

Pandoc options:
  markdown+raw_html  -- inline HTML islands (callouts, exercises, page
                        break, title block) pass through.
  -smart             -- DISABLED. Keeps dashes and quotes literal so the
                        exact characters in the source land in the PDF.

This is the phase-1 build pipeline. Determinism (SOURCE_DATE_EPOCH + qpdf),
the git-derived version stamp, and the optional transforms.py hook are added
in phases 2 and 3.
"""
import argparse
import subprocess
from pathlib import Path
from weasyprint import HTML

# ----- Document constants (edit these to rename your fork) -----
TITLE = "Guide Template"
OUTPUT_SLUG = "guide-template"
AUTHOR = "Ross Levinsky"
DESCRIPTION = (
    "Template repository for single-document beginner-guide PDF projects. "
    "Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0): "
    "https://creativecommons.org/licenses/by/4.0/"
)
KEYWORDS = "guide, template, pandoc, weasyprint, CC-BY-4.0"

# ----- Paths -----
ROOT = Path(__file__).parent.resolve()
SRC = ROOT / "guide.md"
STYLE = ROOT / "style.css"
OUT_PDF = ROOT / f"{OUTPUT_SLUG}.pdf"
OUT_HTML = ROOT / f"{OUTPUT_SLUG}.html"


def render_html() -> str:
    """Run pandoc, wrap in <html>, substitute placeholder values into the CSS."""
    pandoc = subprocess.run(
        ["pandoc", str(SRC), "-f", "markdown+raw_html-smart", "-t", "html5"],
        capture_output=True, text=True, check=True,
    )
    body = pandoc.stdout
    css = STYLE.read_text()
    css = css.replace("__TITLE__", TITLE)
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8">'
        f'<title>{TITLE}</title>'
        f'<meta name="author" content="{AUTHOR}">'
        f'<meta name="description" content="{DESCRIPTION}">'
        f'<meta name="keywords" content="{KEYWORDS}">'
        f'<style>{css}</style>'
        '</head><body>'
        f'{body}'
        '</body></html>'
    )


def build(want_pdf: bool, want_html: bool) -> None:
    full_html = render_html()
    if want_html:
        OUT_HTML.write_text(full_html)
        print(f"  HTML  ->  {OUT_HTML}")
    if want_pdf:
        HTML(string=full_html, base_url=str(ROOT)).write_pdf(str(OUT_PDF))
        print(f"  PDF   ->  {OUT_PDF}")


def main():
    p = argparse.ArgumentParser(description=f"Build {TITLE}.")
    p.add_argument("--html-preview", action="store_true",
                   help="Render only the standalone HTML for fast browser preview.")
    args = p.parse_args()
    if args.html_preview:
        build(want_pdf=False, want_html=True)
    else:
        build(want_pdf=True, want_html=False)


if __name__ == "__main__":
    main()
