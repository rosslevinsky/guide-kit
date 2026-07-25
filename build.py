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
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from weasyprint import HTML

import kitconfig

# ----- Repo root + per-guide constants -----
# ROOT is established first so kitconfig's strict loader reads THIS repo's
# guide.toml. The seven guide-specific values now live in guide.toml and are
# read through kitconfig — build.py holds no guide-specific literal (that
# property is asserted by tests/test_guide_toml_complete.py). The four LICENSE_*
# values below are family-fixed, identical-tier constants and deliberately stay
# here (plan.md:55).
ROOT = Path(__file__).parent.resolve()
_cfg = kitconfig.load(ROOT)
TITLE = _cfg.TITLE
OUTPUT_SLUG = _cfg.OUTPUT_SLUG
AUTHOR = _cfg.AUTHOR
DESCRIPTION = _cfg.DESCRIPTION
KEYWORDS = _cfg.KEYWORDS
COPYRIGHT_YEAR = _cfg.COPYRIGHT_YEAR
BASELINE_PLATFORM = _cfg.baseline_platform

# ----- Licensing shown in the rendered output -----
# The guide CONTENT is CC BY 4.0; the build tooling (code, CSS, config) is
# Apache 2.0. The PDF colophon (last page) surfaces this so a reader of the
# PDF sees the terms, not just someone browsing the repo. COPYRIGHT is DERIVED
# from guide.toml's year + author — the year is a stored constant (never a clock
# read) so renders stay deterministic and `make verify` is stable.
COPYRIGHT = f"© {COPYRIGHT_YEAR} {AUTHOR}"
LICENSE_CONTENT_NAME = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
LICENSE_CONTENT_URL = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_CODE_NAME = "Apache License 2.0"
LICENSE_CODE_URL = "https://www.apache.org/licenses/LICENSE-2.0"

# ----- Paths -----
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
SOURCE_FILES = kitconfig.SOURCE_FILES  # canonical list (adds guide.toml, kitconfig.py) lives in kitconfig


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
    h = kitconfig.content_hash(ROOT)
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


# Kit-owned screen chrome. This is CONCATENATED BEFORE each guide's
# style-screen.css (which is target-owned — `never` in the manifest, so sync
# must not write it). Order is deliberate: kit chrome first means a guide can
# still override any of it from its own stylesheet, and putting these rules
# here instead means adding them to seven separate per-guide stylesheets that
# would then be free to drift apart.
#
# Only `--accent` and `--rule` are referenced, both with literal fallbacks, so
# this degrades gracefully in a guide that has not defined them.
WEB_CHROME_CSS = """
.site-topbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 1rem;
  margin: 0 0 2rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--rule, #e2e2e6);
}
.site-topbar .download-btn {
  display: inline-block;
  font-weight: 700;
  padding: 0.5rem 1rem;
  border: 1px solid var(--accent, #0b5394);
  border-radius: 6px;
  color: var(--accent, #0b5394);
  text-decoration: none;
  white-space: nowrap;
}
.site-topbar .download-btn:hover {
  background: var(--accent, #0b5394);
  color: #fff;
  text-decoration: none;
}
@media print {
  .site-topbar { display: none; }
}

/* ---- Wide-content breakout ----------------------------------------------
   The prose measure (--max-width, ~46rem) is CORRECT and is not touched here:
   at this font size that is roughly 75-90 characters per line, which is the
   readable measure. Widening body text past it makes the eye lose its place on
   the return sweep.

   Tables are the problem. They were `width: 100%` inside that measure with NO
   overflow escape, so a wide reference table was compressed into the prose
   column and wrapped into stacks — git-guide's widest row carries 179
   characters of text across 50 rows, and accounting's journal tables are
   similar. Code was already fine: the widest code line in the family is 90
   characters and `pre` already scrolls.

   So this is a per-element breakout, not a global widening. `.wide-block`
   centres a wider box on the prose column using the translate pattern rather
   than negative margins, and is capped against the VIEWPORT (not just a rem
   value) so it can never push the page into horizontal scrolling — the classic
   bug with breakout hacks. Inside it, `overflow-x: auto` means anything still
   too wide scrolls in its own box instead of overflowing the page.

   Emitted from the kit rather than added to each guide's style-screen.css,
   which is target-owned: all seven are byte-identical here today, and seven
   hand-copies would be free to drift from the moment they were made. */
:root {
  --wide-width: 64rem;
}
.wide-block {
  width: min(var(--wide-width), calc(100vw - 2.5rem));
  margin-left: 50%;
  transform: translateX(-50%);
  overflow-x: auto;
  /* A scroll container is a focusable region for keyboard users; without this
     they cannot reach it to scroll. tabindex is set on the element by build.py. */
  margin-block: 1.25rem;
}
.wide-block > table {
  margin: 0;
  /* min-width keeps columns from collapsing to unreadable widths inside the
     scroll container: below this the table scrolls instead of squeezing. */
  min-width: 32rem;
}
.wide-block:focus-visible {
  outline: 2px solid var(--accent, #0b5394);
  outline-offset: 2px;
}
/* Never break out in print. The PDF is rendered from style.css, not this file,
   but `make html` produces a browser-printable page from the SCREEN CSS, and a
   translated, viewport-sized box paginates badly. */
@media print {
  .wide-block {
    width: auto;
    margin-left: 0;
    transform: none;
    overflow-x: visible;
  }
}
/* Narrow viewports: the breakout is already viewport-capped, so it collapses to
   the content width on its own. Drop the centring maths to avoid sub-pixel
   drift at small sizes. */
@media (max-width: 48rem) {
  .wide-block {
    width: 100%;
    margin-left: 0;
    transform: none;
  }
}
"""


# A `<table>` that is NOT already immediately preceded by the breakout wrapper.
# The negative lookbehind makes the transform IDEMPOTENT: applying it twice
# cannot nest wrappers. That matters because the call site is one line in one
# function today, and a future `transforms.py` or a second pass would otherwise
# silently produce nested scroll containers — two focusable regions around one
# table, and a table inside a scroll box inside a scroll box.
_TABLE_OPEN_RE = re.compile(r'(?<!role="region">)<table(\s[^>]*)?>')


def _wrap_wide_blocks(html: str) -> str:
    """Wrap every `<table>` in a scrollable breakout container (screen only).

    Pandoc emits a bare `<table>` with nowhere to hang `overflow-x`, and putting
    it on the table itself requires `display: block`, which discards table layout
    and so defeats the purpose. A wrapper is the only way to get "use more width,
    and scroll if that is still not enough" while keeping real table rendering.

    `tabindex="0"` is not decoration: a horizontally scrolling region is
    unreachable by keyboard without it, so a wide table would be readable with a
    mouse and not otherwise.

    Deliberately NOT applied to `pre`: those already scroll inside the prose
    measure, the widest code line in the family is 90 characters, and pulling
    code blocks out of the text column would break the read-along flow that the
    guides depend on.
    """
    return _TABLE_OPEN_RE.sub(
        lambda m: f'<div class="wide-block" tabindex="0" role="region">{m.group(0)}',
        html,
    ).replace("</table>", "</table></div>")


def render_web_html() -> str:
    """Render the SCREEN HTML: pandoc → web transforms → wrap with
    style-screen.css. Used for the website output only."""
    body = _wrap_wide_blocks(_apply_transforms(_pandoc_body(), "web"))
    # Top chrome: the same download affordance as the footer, ABOVE the guide
    # text. Without it the only way to get the PDF is to scroll the entire
    # document — which on the longest guide in this family means ~50 pages of
    # scrolling to reach a link, so most readers never find it at all.
    #
    # `download` (on both this and the footer link) is what makes the button
    # actually download. Cloudflare serves these with `Content-Type:
    # application/pdf` and no `Content-Disposition`, so a plain link makes the
    # browser's built-in viewer take over and render the PDF in a tab instead —
    # which is not what a control labelled "Download as PDF" should do. The
    # attribute is honoured because the PDF is served same-origin with the page.
    # It is deliberately NOT done with a `Content-Disposition: attachment`
    # header, which would also force a download for someone who navigated to the
    # PDF URL directly and legitimately wanted to read it in the browser.
    body = (
        '<div class="site-topbar">'
        f'<a class="download-btn" href="{OUTPUT_SLUG}.pdf" download>'
        '⬇&nbsp;Download as PDF</a>'
        '</div>'
    ) + body
    # Footer chrome: a prominent PDF download link, the license/copyright (so
    # the website carries the same terms as the PDF), and the git-derived
    # version stamp (which commit the live site was built from).
    body += (
        '<footer class="site-footer">'
        f'<p class="download"><a href="{OUTPUT_SLUG}.pdf" download>⬇&nbsp;Download as PDF</a></p>'
        f'<p>{COPYRIGHT} · Licensed under '
        f'<a href="{LICENSE_CONTENT_URL}">{LICENSE_CONTENT_NAME}</a>; '
        f'build tooling under <a href="{LICENSE_CODE_URL}">{LICENSE_CODE_NAME}</a>.</p>'
        f'<p class="stamp">{TITLE} · {_version_stamp()}</p>'
        '</footer>'
    )
    css = WEB_CHROME_CSS + STYLE_SCREEN.read_text(encoding="utf-8")
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

    # Hard-FAIL on a missing reference PDF BEFORE rendering, so no partial site is
    # written: a site must not deploy with a guaranteed-404 download link
    # (plan.md:150). This is the compensating gate for the staleness check's
    # deliberate pass-with-notice on an absent PDF (verify_pdf.py --staleness): a
    # never-released guide passes `make verify` but cannot build its web layer
    # until its first reference PDF exists.
    if not REFERENCE_PDF.exists():
        raise SystemExit(
            f"build.py --web: reference PDF {REFERENCE_PDF.name} is missing — the site's "
            "download link would 404. Generate it on the canonical host (`make release` / "
            "`make baseline` + commit) before building or deploying the web layer."
        )

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    out_index = WEB_DIR / "index.html"
    out_index.write_text(render_web_html(), encoding="utf-8")
    print(f"  WEB   ->  {out_index}")

    # Copy the committed reference PDF (what readers download) — NOT a fresh
    # render — so the site links to the verified-by-baseline file.
    shutil.copyfile(REFERENCE_PDF, WEB_DIR / REFERENCE_PDF.name)
    print(f"  WEB   ->  {WEB_DIR / REFERENCE_PDF.name}")

    # `_headers` — Cloudflare Workers Static Assets reads this from the assets
    # directory and applies it to matching responses.
    #
    # WHY A HEADER AND NOT JUST THE `download` ATTRIBUTE. The anchor's `download`
    # attribute is enough on this guide's OWN page, where the PDF is same-origin.
    # It is silently ignored cross-origin — a deliberate browser restriction — and
    # the family hub at guides.speedytuna.com links every PDF from a DIFFERENT
    # subdomain. So on the hub the attribute does nothing and a button labelled
    # "PDF" opens the browser's viewer instead of downloading. Only a
    # server-side Content-Disposition works from there.
    #
    # THE TRADE, stated because it is a real loss: this also makes a direct
    # navigation to the PDF URL download rather than preview. That is accepted
    # deliberately — the PDF is published as a downloadable deliverable, the
    # readable version is the website itself, and a link labelled as a download
    # doing something else is the worse failure.
    #
    # Written from build.py rather than tracked as a file because app/dist/ is
    # generated and gitignored, and app/public/ is not copied into it. That makes
    # this a SOURCE_FILES change, hence a re-baseline — worth it to keep the
    # behaviour in code rather than as a Cloudflare dashboard rule. A zone-level
    # Transform Rule would also work and need no re-baseline, but this family has
    # already been bitten once this week by configuration that lived outside the
    # repo (workers.dev, which a tool silently re-enabled on every deploy).
    headers = WEB_DIR / "_headers"
    headers.write_text(
        f"/{REFERENCE_PDF.name}\n"
        f'  Content-Disposition: attachment; filename="{REFERENCE_PDF.name}"\n',
        encoding="utf-8",
    )
    print(f"  WEB   ->  {headers}")


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
    # The uninitialized-template signal is the sentinel (handled above) plus the
    # doc placeholders. The former TITLE/OUTPUT_SLUG == default comparisons were
    # dropped: they required a module-level literal equal to guide.toml's values,
    # which this phase forbids (the constants now live only in guide.toml). The
    # slug/title-default backstop is intentionally not reconstructed here; once
    # bootstrap writes guide.toml directly (Phase 7 — it does not yet), an
    # initialized fork's guide.toml no longer carries the template defaults.
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
