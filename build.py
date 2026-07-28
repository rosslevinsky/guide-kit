#!/usr/bin/env python3
"""Build entry point: parse the flags, dispatch to a renderer.

Default output (`python build.py`):
  {OUTPUT_SLUG}.pdf  -- styled PDF, written to build/

  Pass --html-preview to emit a standalone HTML for fast browser iteration.
  Pass --web to build the deployable website into app/dist/ (opt-in web layer;
  no-ops cleanly when the web layer is not enabled — see render_site.build_web).

This file used to be the whole pipeline — 1391 lines covering the PDF, the
website's chrome, its navigation script and its HTML post-processing. That was a
problem with a name: `build.py` is a PDF stamp input, so **every website change
re-staled all eight reference PDFs** and forced a re-baseline of documents whose
content had not moved. Splitting it is what makes a screen-only edit free.

Where the code went:

  buildcore.py     artifact-neutral: config and paths, the version stamp and
                   determinism helpers, the transforms hook, the glyph-coverage
                   gate, pandoc, the shared HTML wrapper, template hygiene
  render_pdf.py    the PDF renderer               (in the PDF's closure)
  render_site.py   the website renderer           (NOT in the PDF's closure)
  render_slides.py the slides seam                (NOT in the PDF's closure)

Each artifact's dependency closure is declared in `kitconfig.ArtifactSpec`, so
which module belongs to which artifact is asserted by tests rather than implied
by import structure.

Pandoc options and the inline-HTML island vocabulary are documented in
buildcore.py, next to the code that implements them.
"""
from __future__ import annotations

import argparse

import buildcore


def main():
    p = argparse.ArgumentParser(description=f"Build {buildcore.TITLE}.")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--html-preview", action="store_true",
                       help="Render only the standalone print HTML for fast browser preview.")
    group.add_argument("--web", action="store_true",
                       help="Build the deployable website into app/dist/ (opt-in web layer).")
    group.add_argument("--slides", action="store_true",
                       help="Build the slides deck into build/<slug>-slides.pdf (opt-in).")
    group.add_argument("--slides-coverage", action="store_true",
                       help="Report which chapters have no slide. A REPORT — always exits 0.")
    args = p.parse_args()
    buildcore._check_template_hygiene()
    # Renderers are imported LAZILY, per branch, and this is load-bearing rather
    # than a micro-optimization. `render_site.py` is deliberately absent from the
    # PDF's dependency closure — the claim being that a website change cannot
    # affect the PDF. An unconditional module-level import would make that claim
    # false in the direction that matters: a syntax error, a missing dependency
    # or a module-level side effect in render_site.py would break or alter a
    # plain `python build.py`, for a file the PDF's closure says is irrelevant to
    # it. Importing only the renderer a branch actually uses makes the declared
    # isolation real at run time, not just in the hash.
    if args.web:
        import render_site
        render_site.build_web()
    elif args.slides:
        import render_slides
        render_slides.build_slides()
    elif args.slides_coverage:
        import kitconfig
        import render_slides
        report = render_slides.coverage(kitconfig.load(buildcore.ROOT))
        for slug in report["uncovered"]:
            print(f"  uncovered: {slug}")
        print(f"  slides coverage: {len(report['covered'])}/{report['total']} "
              f"chapter unit(s) have at least one slide")
        # Deliberately NO nonzero exit. A deck is a selection, not a mirror of
        # the guide, so an uncovered chapter is information rather than a fault —
        # and a report that failed the build would just be turned off.
    elif args.html_preview:
        import render_pdf
        render_pdf.build(want_pdf=False, want_html=True)
    else:
        import render_pdf
        render_pdf.build(want_pdf=True, want_html=False)


if __name__ == "__main__":
    main()
