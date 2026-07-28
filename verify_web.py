#!/usr/bin/env python3
"""Verify the per-output embed split actually does both jobs.

The dual-output build projects a single `<div class="embed youtube" data-id="…">`
island in guide.md two different ways:

  WEB    app/dist/index.html      contains an <iframe> for the embed (by id)
                                  and NOT a plain watch link
  PRINT  build/<slug>.html        contains a youtube.com/watch?v=<id> link
                                  and NOT an <iframe>

We assert on the print HTML (what WeasyPrint consumes), not the PDF text:
`pdftotext` extracts the visible link *label*, not the href, so it cannot see
the watch URL. The print HTML is the faithful, checkable representation of what
lands in the PDF.

This is part of the OPT-IN web layer. It skips cleanly (exit 0) when the web
layer is not enabled (no `style-screen.css`) or when `guide.md` has no embed
island to check — so it is safe to run on a PDF-only fork. The embed id is
derived from `guide.md`, never hardcoded, so this file carries no guide-specific
values.

Run via `pixi run python verify_web.py`. Exit 0 on success or clean skip;
nonzero with a diagnostic on the first failed assertion.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import kitconfig

ROOT = Path(__file__).parent.resolve()
SRC = ROOT / "guide.md"
STYLE_SCREEN = ROOT / "style-screen.css"
WEB_INDEX = ROOT / "app" / "dist" / "index.html"

# First YouTube embed island in guide.md, as authored (pandoc passes the raw
# div through). Only the data-id is needed here.
_EMBED_ID = re.compile(r'<div class="embed youtube" data-id="(?P<id>[^"]+)"')


def _output_slug() -> str:
    """Read OUTPUT_SLUG from guide.toml via kitconfig so the print-HTML path
    matches what the build writes — the validated single source of truth, same
    as the Makefile. No hardcoded fallback: a wrong slug here would check the
    wrong file."""
    return kitconfig.load(ROOT).OUTPUT_SLUG


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def _skip(msg: str) -> int:
    print(f"verify_web.py: SKIP — {msg}")
    return 0


def _fail(msg: str) -> None:
    sys.exit(f"verify_web.py: FAIL — {msg}")


def main() -> int:
    # Enablement is DECLARED, not inferred from a file. style-screen.css is
    # target-owned, so a guide that disables its site keeps the stylesheet — and
    # keying on it made this run the full web verification against a site that no
    # longer exists.
    try:
        declared = "site" in kitconfig.load(ROOT).outputs.declared
    except kitconfig.KitConfigError as exc:
        # FAIL, not skip: an unreadable config means the question could not be
        # asked, and a verifier that exits 0 on "I could not tell" is worse than
        # no verifier at all.
        _fail(f"cannot read guide.toml ({exc})")
        return 1
    if not declared:
        return _skip("web layer not declared ([outputs] site = \"none\"); nothing to verify")
    if not STYLE_SCREEN.exists():
        # Declared but not materialized: `build_web()` refuses this outright, so
        # skipping here would report a site as fine that cannot be built.
        _fail("guide.toml declares a site but style-screen.css is absent — "
              "materialize it with `adopt.py --output site --enable`")
        return 1

    m = _EMBED_ID.search(SRC.read_text(encoding="utf-8"))
    if m is None:
        return _skip("guide.md has no `embed youtube` island; no per-output embed split to verify")
    embed_id = m.group("id")
    watch_url = f"youtube.com/watch?v={embed_id}"

    print_html = ROOT / "build" / f"{_output_slug()}.html"

    # Build both representations fresh so the check reflects current source.
    _run(["python", "build.py", "--web"])            # → app/dist/index.html
    _run(["python", "build.py", "--html-preview"])   # → build/<slug>.html

    if not WEB_INDEX.exists():
        _fail(f"{WEB_INDEX} missing — `build.py --web` did not produce it")
    web = WEB_INDEX.read_text(encoding="utf-8")
    if "<iframe " not in web:
        _fail("web index.html has no <iframe> — embed→iframe transform did not run")
    if embed_id not in web:
        _fail(f"web index.html missing embed id {embed_id!r} in the iframe src")
    if watch_url in web:
        _fail("web index.html contains a plain watch link — it should be an iframe, not a link")

    if not print_html.exists():
        _fail(f"{print_html} missing — `build.py --html-preview` did not produce it")
    pr = print_html.read_text(encoding="utf-8")
    if watch_url not in pr:
        _fail(f"print HTML missing {watch_url!r} — embed→link transform did not run for PDF")
    if "<iframe" in pr:
        _fail("print HTML contains an <iframe> — the PDF path must degrade embeds to links")

    print("verify_web.py: PASS")
    print(f"  WEB    iframe with id {embed_id} present; no plain watch link")
    print(f"  PRINT  {watch_url} link present; no iframe in print HTML")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
