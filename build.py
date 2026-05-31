#!/usr/bin/env python3
"""Build the styled PDF from guide.md.

Default output (`python build.py`):
  {OUTPUT_SLUG}.pdf  -- styled PDF, written to the repo root

Pipeline:
  pandoc → HTML body → wrap in <html> template → WeasyPrint → qpdf canonicalize
  Pass --html-preview to emit a standalone HTML for fast browser iteration.
  Pass --web to build the deployable website into app/dist/ (opt-in web layer;
  no-ops cleanly when the web layer is not enabled — see build_web).

Determinism:
  SOURCE_DATE_EPOCH is set from the most-recent source commit so WeasyPrint's
  PDF creation timestamp moves only when source moves. The rendered PDF is
  then piped through `qpdf --deterministic-id --normalize-content=y` so the
  PDF document ID is content-derived, not random. Two consecutive builds of
  unchanged source produce content-identical PDFs (same text, same layout;
  font subset prefixes can still differ at the byte level, but `verify_pdf.py`
  doesn't care about those).

Version stamp:
  Footer carries "YYYY-MM-DD HH:MM:SS · <sha256[:12]>" of the most recent
  commit touching the SOURCE_FILES list, plus " · dirty" when the working
  tree has uncommitted changes to any of those files. Substituted into
  style.css via the __VERSION__ placeholder.

Transforms hook (per-output):
  If `transforms.py` exists next to build.py, it's imported and called once
  between the pandoc step and the renderer. The contract has two entry points,
  one per output target:
    post_pandoc_html_for_pdf(html: str) -> str   # PDF pipeline (WeasyPrint)
    post_pandoc_html_for_web(html: str) -> str    # website pipeline (app/dist)
  A single-entry `post_pandoc_html(html)` is accepted as a fallback for forks
  that don't differentiate; when neither is defined the body passes through
  unchanged. Activating the hook also adds transforms.py to the version-stamp
  input list, so the rendered footer changes — refresh the committed reference
  PDF (`make baseline`) after activating or deactivating.

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
import shutil
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

# ----- Licensing shown in the rendered output -----
# The guide CONTENT is CC BY 4.0; the build tooling (code, CSS, config) is
# Apache 2.0. The PDF colophon (last page) surfaces this so a reader of the
# PDF sees the terms, not just someone browsing the repo. Forks: update
# COPYRIGHT's year/holder to your own. The year is a constant (not derived
# from the clock) so renders stay deterministic and `make verify` is stable.
COPYRIGHT = f"© 2026 {AUTHOR}"
LICENSE_CONTENT_NAME = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
LICENSE_CONTENT_URL = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_CODE_NAME = "Apache License 2.0"
LICENSE_CODE_URL = "https://www.apache.org/licenses/LICENSE-2.0"

# ----- Paths -----
ROOT = Path(__file__).parent.resolve()
SRC = ROOT / "guide.md"
STYLE = ROOT / "style.css"
# Screen-only stylesheet for the website output. NOT in SOURCE_FILES — it
# affects only the web build, never the PDF, so editing it must not bump the
# PDF version stamp or break `make verify`. Ships opt-in: the template has only
# `style-screen.css.example`; `bootstrap.py --with-web` copies it into place.
# Its presence is also the signal that the web layer is enabled (see build_web).
STYLE_SCREEN = ROOT / "style-screen.css"
# The build/ directory holds the WORKING render (gitignored). `make` writes
# here; `make verify` compares this to the committed reference at the repo
# root. `make baseline` (and `make release`) copies build/<slug>.pdf onto
# the root <slug>.pdf, which is the file readers download from GitHub.
BUILD_DIR = ROOT / "build"
OUT_PDF = BUILD_DIR / f"{OUTPUT_SLUG}.pdf"
OUT_HTML = BUILD_DIR / f"{OUTPUT_SLUG}.html"
# The website build output (gitignored). `make web` writes the deployable
# site here; Cloudflare Workers Static Assets serves this directory.
WEB_DIR = ROOT / "app" / "dist"
# The committed reference PDF at the repo root. Named for the guide so it
# downloads cleanly from GitHub (no anonymous "baseline.pdf"). Override
# REFERENCE_PDF if you want the old `baseline.pdf` convention.
REFERENCE_PDF = ROOT / f"{OUTPUT_SLUG}.pdf"

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
    """Return "YYYY-MM-DD HH:MM:SS" of the most recent commit touching any
    SOURCE_FILES entry, in the author's local time at commit. Uses %ad
    (author date), not %cd (committer date), so `git commit --amend`
    inside release.py doesn't perturb the stamp by ~1s and break the
    verify cycle. Empty string when git is unavailable or the repo has
    no relevant commits."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ad", "--date=format:%Y-%m-%d %H:%M:%S", "--"]
            + SOURCE_FILES,
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
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
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _version_stamp() -> str:
    """Compose 'YYYY-MM-DD HH:MM:SS · <hash>' (+ ' · dirty' when the working
    tree has uncommitted source changes)."""
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

def _load_transforms():
    """Import `transforms.py` if it exists next to build.py, else return None."""
    hook_path = ROOT / "transforms.py"
    if not hook_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("transforms", hook_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_transforms(html_body: str, target: str) -> str:
    """Pipe `html_body` through the transforms hook for the given target
    ("pdf" or "web"). Prefers the per-output entry point
    (`post_pandoc_html_for_<target>`); falls back to the single-entry
    `post_pandoc_html` for forks that don't differentiate; returns the body
    unchanged when no hook is present."""
    module = _load_transforms()
    if module is None:
        return html_body
    per_output = getattr(module, f"post_pandoc_html_for_{target}", None)
    if callable(per_output):
        return per_output(html_body)
    single = getattr(module, "post_pandoc_html", None)
    if callable(single):
        return single(html_body)
    return html_body


def _pandoc_body() -> str:
    """Run pandoc on guide.md and return the raw HTML body (pre-transform)."""
    pandoc = subprocess.run(
        ["pandoc", str(SRC), "-f", "markdown+raw_html-smart", "-t", "html5"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return pandoc.stdout


def _wrap_html(body: str, css: str) -> str:
    """Wrap a transformed HTML body in the document shell with inlined CSS."""
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{TITLE}</title>'
        f'<meta name="author" content="{AUTHOR}">'
        f'<meta name="description" content="{DESCRIPTION}">'
        f'<meta name="keywords" content="{KEYWORDS}">'
        f'<style>{css}</style>'
        '</head><body>'
        f'{body}'
        '</body></html>'
    )


def _pdf_colophon() -> str:
    """License/copyright block appended to the end of the PDF (the last page).
    Styled by the `.colophon` rules in style.css."""
    return (
        '<div class="colophon">'
        f'<p class="colophon-title">{TITLE}</p>'
        f'<p>{COPYRIGHT}</p>'
        '<p>This guide is licensed under '
        f'<a href="{LICENSE_CONTENT_URL}">{LICENSE_CONTENT_NAME}</a>. '
        'The build tooling is licensed under '
        f'<a href="{LICENSE_CODE_URL}">{LICENSE_CODE_NAME}</a>.</p>'
        '</div>'
    )


def render_html() -> str:
    """Render the PRINT HTML: pandoc → PDF transforms → colophon → wrap with style.css."""
    body = _apply_transforms(_pandoc_body(), "pdf") + _pdf_colophon()
    css = STYLE.read_text(encoding="utf-8")
    css = css.replace("__TITLE__", TITLE).replace("__VERSION__", _version_stamp())
    return _wrap_html(body, css)


def render_web_html() -> str:
    """Render the SCREEN HTML: pandoc → web transforms → wrap with
    style-screen.css. Used for the website output only."""
    body = _apply_transforms(_pandoc_body(), "web")
    # Footer chrome: a prominent PDF download link, the license/copyright (so
    # the website carries the same terms as the PDF), and the git-derived
    # version stamp (which commit the live site was built from).
    body += (
        '<footer class="site-footer">'
        f'<p class="download"><a href="{OUTPUT_SLUG}.pdf">⬇&nbsp;Download as PDF</a></p>'
        f'<p>{COPYRIGHT} · Licensed under '
        f'<a href="{LICENSE_CONTENT_URL}">{LICENSE_CONTENT_NAME}</a>; '
        f'build tooling under <a href="{LICENSE_CODE_URL}">{LICENSE_CODE_NAME}</a>.</p>'
        f'<p class="stamp">{TITLE} · {_version_stamp()}</p>'
        '</footer>'
    )
    css = STYLE_SCREEN.read_text(encoding="utf-8")
    css = css.replace("__TITLE__", TITLE).replace("__VERSION__", _version_stamp())
    return _wrap_html(body, css)


def build(want_pdf: bool, want_html: bool) -> None:
    # Pin WeasyPrint's PDF creation timestamp via the reproducible-builds
    # standard env var. WeasyPrint reads this when set.
    os.environ["SOURCE_DATE_EPOCH"] = str(_source_date_epoch())
    BUILD_DIR.mkdir(exist_ok=True)

    full_html = render_html()
    if want_html:
        OUT_HTML.write_text(full_html, encoding="utf-8")
        print(f"  HTML  ->  {OUT_HTML}")
    if want_pdf:
        HTML(string=full_html, base_url=str(ROOT)).write_pdf(str(OUT_PDF))
        _qpdf_canonicalize(OUT_PDF)
        print(f"  PDF   ->  {OUT_PDF}")


def build_web() -> None:
    """Build the website into app/dist/: the screen HTML as index.html and a
    copy of the committed reference PDF for download.

    The web layer is opt-in. When `style-screen.css` is absent (a PDF-only
    template or fork that never ran `bootstrap.py --with-web`), this no-ops
    cleanly — it prints a hint, creates nothing, and exits 0 so `make web` is
    safe on every fork."""
    if not STYLE_SCREEN.exists():
        print("  web layer not enabled — run `bootstrap.py --with-web` to enable it")
        return

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    out_index = WEB_DIR / "index.html"
    out_index.write_text(render_web_html(), encoding="utf-8")
    print(f"  WEB   ->  {out_index}")

    # Copy the committed reference PDF (what readers download) — NOT a fresh
    # render — so the site links to the verified-by-baseline file.
    if REFERENCE_PDF.exists():
        shutil.copyfile(REFERENCE_PDF, WEB_DIR / REFERENCE_PDF.name)
        print(f"  WEB   ->  {WEB_DIR / REFERENCE_PDF.name}")
    else:
        print(f"  WARN  reference PDF {REFERENCE_PDF.name} missing; site will 404 the download link")


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
        body = p.read_text(encoding="utf-8")
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
    group = p.add_mutually_exclusive_group()
    group.add_argument("--html-preview", action="store_true",
                       help="Render only the standalone print HTML for fast browser preview.")
    group.add_argument("--web", action="store_true",
                       help="Build the deployable website into app/dist/ (opt-in web layer).")
    args = p.parse_args()
    _check_template_hygiene()
    if args.web:
        build_web()
    elif args.html_preview:
        build(want_pdf=False, want_html=True)
    else:
        build(want_pdf=True, want_html=False)


if __name__ == "__main__":
    main()
