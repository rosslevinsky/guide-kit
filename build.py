#!/usr/bin/env python3
"""Build the styled PDF from guide.md.

Default output (`python build.py`):
  {OUTPUT_SLUG}.pdf  -- styled PDF, written to the repo root

Pipeline:
  pandoc → HTML body → wrap in <html> template → WeasyPrint → qpdf canonicalize
  Pass --html-preview to emit a standalone HTML for fast browser iteration.

Determinism:
  SOURCE_DATE_EPOCH is set from the most-recent source commit so WeasyPrint's
  PDF creation timestamp moves only when source moves. The rendered PDF is
  then piped through `qpdf --deterministic-id --normalize-content=y` so the
  PDF document ID is content-derived, not random. Two consecutive builds of
  unchanged source produce content-identical PDFs (same text, same layout;
  font subset prefixes can still differ at the byte level, but `verify_pdf.py`
  doesn't care about those).

Version stamp:
  Footer carries "YYYY-MM-DD · <sha256[:12]>" of the most recent commit
  touching the SOURCE_FILES list, plus " · dirty" when the working tree has
  uncommitted changes to any of those files. Substituted into style.css via
  the __VERSION__ placeholder.

Transforms hook:
  If `transforms.py` exists next to build.py, it's imported and
  `transforms.post_pandoc_html(html: str) -> str` is called exactly once,
  between the pandoc step and WeasyPrint. The hook receives the raw HTML body
  emitted by pandoc and returns a transformed HTML body. Activating the hook
  also adds transforms.py to the version-stamp input list, so the rendered
  footer changes — refresh `baseline.pdf` (`make baseline`) after activating
  or deactivating.

Pandoc options:
  markdown+raw_html  -- inline HTML islands (callouts, exercises, page
                        break, title block) pass through.
  -smart             -- DISABLED. Keeps dashes and quotes literal so the
                        exact characters in the source land in the PDF.
"""
import argparse
import hashlib
import importlib.util
import os
import subprocess
import tempfile
from datetime import datetime
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

# Files whose changes invalidate the version stamp and the deterministic-render
# timestamp. transforms.py is included unconditionally — git silently ignores
# nonexistent paths in `log` / `status` queries, and `_content_hash` guards
# with `p.exists()`, so the same list works whether or not the hook is
# activated. (Activating the hook does still bump the footer hash, because
# the new file's bytes become part of the content. That gotcha is intrinsic
# to a content-derived stamp and is called out in CLAUDE.md.)
SOURCE_FILES = ["guide.md", "style.css", "build.py", "transforms.py"]


# ---------------------------------------------------------------------------
# Version stamp + determinism helpers
# ---------------------------------------------------------------------------

def _git_last_source_change_date() -> str:
    """Return YYYY-MM-DD of the most recent commit touching any SOURCE_FILES
    entry. Empty string when git is unavailable or the repo has no relevant
    commits."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=short", "--"]
            + SOURCE_FILES,
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _content_hash() -> str:
    """Return the 12-char prefix of the sha256 over the concatenated bytes of
    every SOURCE_FILES entry that exists on disk, taken in the fixed
    SOURCE_FILES order."""
    h = hashlib.sha256()
    for name in SOURCE_FILES:
        p = ROOT / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _is_dirty() -> bool:
    """Return True if `git status --porcelain` reports any modified or
    untracked file in SOURCE_FILES. The `--` scope is load-bearing: it
    constrains the dirty check to the version-stamp file list so transient
    build artifacts (notably the just-rendered PDF) don't trigger a false
    dirty."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--"] + SOURCE_FILES,
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _version_stamp() -> str:
    """Compose 'YYYY-MM-DD · <hash>' (+ ' · dirty' when the working tree has
    uncommitted source changes)."""
    date = _git_last_source_change_date()
    h = _content_hash()
    stamp = f"{date} · {h}" if date else h
    if _is_dirty():
        stamp += " · dirty"
    return stamp


def _source_date_epoch() -> int:
    """Return the unix-seconds equivalent of the most-recent source commit
    date, suitable for `SOURCE_DATE_EPOCH`. Returns 0 when git is unavailable
    or there are no relevant commits."""
    date = _git_last_source_change_date()
    if not date:
        return 0
    return int(datetime.fromisoformat(date).timestamp())


def _qpdf_canonicalize(pdf_path: Path) -> None:
    """Rewrite `pdf_path` in place via `qpdf --deterministic-id
    --normalize-content=y --object-streams=preserve`. Strips per-run document
    IDs and normalizes content streams so two builds of identical source
    produce content-identical PDFs."""
    with tempfile.NamedTemporaryFile(
        suffix=".pdf", delete=False, dir=pdf_path.parent
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            [
                "qpdf",
                "--deterministic-id",
                "--normalize-content=y",
                "--object-streams=preserve",
                str(pdf_path),
                str(tmp_path),
            ],
            check=True,
        )
        os.replace(tmp_path, pdf_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _apply_transforms_hook(html_body: str) -> str:
    """If `transforms.py` exists next to build.py, import it and call
    `post_pandoc_html`. Otherwise return the body unchanged."""
    hook_path = ROOT / "transforms.py"
    if not hook_path.exists():
        return html_body
    spec = importlib.util.spec_from_file_location("transforms", hook_path)
    if spec is None or spec.loader is None:
        return html_body
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.post_pandoc_html(html_body)


def render_html() -> str:
    """Run pandoc, optionally pipe through the transforms hook, wrap in
    <html>, substitute placeholder values into the CSS."""
    pandoc = subprocess.run(
        ["pandoc", str(SRC), "-f", "markdown+raw_html-smart", "-t", "html5"],
        capture_output=True, text=True, check=True,
    )
    body = _apply_transforms_hook(pandoc.stdout)
    css = STYLE.read_text()
    css = css.replace("__TITLE__", TITLE).replace("__VERSION__", _version_stamp())
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
    # Pin WeasyPrint's PDF creation timestamp via the reproducible-builds
    # standard env var. WeasyPrint reads this when set.
    os.environ["SOURCE_DATE_EPOCH"] = str(_source_date_epoch())

    full_html = render_html()
    if want_html:
        OUT_HTML.write_text(full_html)
        print(f"  HTML  ->  {OUT_HTML}")
    if want_pdf:
        HTML(string=full_html, base_url=str(ROOT)).write_pdf(str(OUT_PDF))
        _qpdf_canonicalize(OUT_PDF)
        print(f"  PDF   ->  {OUT_PDF}")


# ---------------------------------------------------------------------------
# Template hygiene
# ---------------------------------------------------------------------------

# Sentinel file shipped with the template repo. bootstrap.py deletes it after
# it substitutes placeholders for the fork's own values. Its presence means
# "the user is building the unrenamed template" and suppresses the hygiene
# check below.
TEMPLATE_SENTINEL = ROOT / ".template-uninitialized"

# Placeholders the template ships with in its docs (README.md, CLAUDE.md).
# If a forked guide still contains any of these, the fork forgot to
# initialize. The hygiene check refuses to build until they're gone.
PLACEHOLDERS = ("{{GUIDE_NAME}}", "{{GUIDE_SLUG}}", "<DESCRIBE YOUR GUIDE>")
DEFAULT_TITLE = "Guide Template"
DEFAULT_SLUG = "guide-template"


def _check_template_hygiene() -> None:
    if TEMPLATE_SENTINEL.exists():
        return
    issues = []
    for name in ("README.md", "CLAUDE.md"):
        p = ROOT / name
        if not p.exists():
            continue
        body = p.read_text()
        for ph in PLACEHOLDERS:
            if ph in body:
                issues.append(f"{name}: still contains '{ph}'")
    if TITLE == DEFAULT_TITLE:
        issues.append("build.py: TITLE is still the template default 'Guide Template'")
    if OUTPUT_SLUG == DEFAULT_SLUG:
        issues.append("build.py: OUTPUT_SLUG is still the template default 'guide-template'")
    if not issues:
        return
    bullet = "\n  ".join(issues)
    raise SystemExit(
        "build.py: template not initialized. Run\n"
        "  pixi run python bootstrap.py \"My Guide Title\" my-guide-slug\n"
        "to substitute placeholders, or delete `.template-uninitialized` to silence\n"
        "this check after handling them manually.\n\n"
        f"Issues:\n  {bullet}"
    )


def main():
    p = argparse.ArgumentParser(description=f"Build {TITLE}.")
    p.add_argument("--html-preview", action="store_true",
                   help="Render only the standalone HTML for fast browser preview.")
    args = p.parse_args()
    _check_template_hygiene()
    if args.html_preview:
        build(want_pdf=False, want_html=True)
    else:
        build(want_pdf=True, want_html=False)


if __name__ == "__main__":
    main()
