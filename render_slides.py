#!/usr/bin/env python3
"""The slides renderer — the seam, not yet the implementation.

This module exists now, empty of rendering logic, because its **absence** is what
the split is trying to prevent. `kitconfig`'s `ArtifactSpec` already declares a
`slides` artifact whose closure includes this file and `style-slides.css`; with
nowhere for slides code to live, the first person to add it would reach for
`buildcore.py` or `build.py`, both of which are PDF stamp inputs — and adding
slides would re-stale all eight reference PDFs. That is precisely the coupling
the split exists to remove: editing `slides.css` would re-stale the PDF and
force a pointless re-render of a document that did not change.

So the seam is established and asserted (the stage-boundary test in
`tests/test_artifact_spec.py` renders a slides-stylesheet edit and a slides
source edit and requires the PDF's bytes, stamp and date to be unchanged), while
the rendering itself lands with the slides stage.

Deliberately raises rather than no-ops: a silent no-op would let `make slides`
report success and write nothing.
"""
from __future__ import annotations

import os
from pathlib import Path

from weasyprint import HTML

import buildcore
import chapters
import kitconfig

# The slides stylesheet, target-owned like the other override files and in
# exactly one artifact's closure — membership there is what creates the
# separation, not the filename.
STYLE_SLIDES = buildcore.ROOT / "style-slides.css"


# EXACTLY 16:9, and the arithmetic is written out because getting it almost
# right is the failure mode. 254 × 9/16 = 142.875mm. The 143mm that reads like
# the obvious value gives 1.7762, not 1.7778 — visibly wrong on a projector and
# invisible in a code review. The test asserts the COMPUTED RATIO, never this
# string, so a future edit cannot satisfy it by matching the text.
SLIDE_WIDTH_MM = 254.0
SLIDE_HEIGHT_MM = SLIDE_WIDTH_MM * 9.0 / 16.0     # 142.875

# THE DECK'S STRUCTURAL FLOOR — emitted by the kit, not left to
# `style-slides.css`. Two things live here, and both were missing.
#
# ONE SLIDE, ONE PAGE. The deck shipped 16:9, stamped, reproducible and
# byte-identical across runs, and unpaginated: three marked regions came out as
# two pages, with slides sharing a sheet and bullet lists orphaning across the
# break. Nothing caught it because every assertion was about the page's SIZE and
# the stamp on it, and no test asked how many pages there were.
#
#   * `break-after: page` ends the sheet after each slide.
#   * `break-inside: avoid` stops a tall slide fragmenting — without it the page
#     COUNT can be right while a slide's bullets orphan onto the next sheet, so
#     counting pages alone is not enough.
#   * `break-after: auto` on the last slide, so the deck does not trail an empty
#     sheet. `:last-child` rather than `:last-of-type`: the slides sit among
#     whatever else the wrapper emits, and `:last-of-type` asks about the last
#     `div`, which is not necessarily the last `.slide`.
#
# A BUNDLED FAMILY. `style-slides.css`'s absence is tolerated (see
# `render_html`), so a guide that deleted or emptied it rendered a deck whose
# boxes resolved to the generic `serif` — no bundled family named anywhere in
# the deck's cascade. Fontconfig is hermetic, so it still landed on a bundled
# face and the deck LOOKED right while the cascade guaranteed nothing, which is
# the exact state the bundled-font machinery exists to prevent. Surfaced by
# wiring `check_rendered_coverage` into `build_slides`.
#
# WHY NOT IN THE STYLESHEET. `style-slides.css` is `policy = "never"` —
# target-owned, never written by sync — so a rule there is absent from every new
# guide and from any guide whose author did not copy it, which is how this
# family shipped unstyled site chrome to seven repos. And neither of these is a
# style a guide might reasonably override: one is what the word "slide" means,
# the other is the determinism the whole font stack exists for. They are a
# FLOOR: `style-slides.css` is concatenated after and overrides every rule here.
_SLIDE_STRUCTURE_CSS = (
    ".slide {\n"
    "  break-after: page;\n"
    "  break-inside: avoid;\n"
    "  font-family: var(--body-font);\n"
    "}\n"
    ".slide:last-child {\n"
    "  break-after: auto;\n"
    "}\n"
    ".slide h1, .slide h2, .slide h3 {\n"
    "  font-family: var(--head-font);\n"
    "}\n"
    ".slide code, .slide pre {\n"
    "  font-family: var(--mono-font);\n"
    "}\n"
)


# The deck carries the family's version stamp, like every other artifact. Its
# ArtifactSpec declares `stamp=_STAMPED`, and a reference with no readable stamp
# fails `verify --staleness` CLOSED — correctly, since freshness cannot be
# established from a file that does not say what built it.
#
# A margin box is the only place to put it, which is why the page is not
# `margin: 0`: WeasyPrint drops every `@bottom-*` box when the margin is zero, so
# a full-bleed page silently has nowhere for a stamp to live. The reserved strip
# is small and the text muted, so a projected slide is not disfigured by it.
def _page_css(stamp: str) -> str:
    return (
        f"@page {{\n"
        f"  size: {SLIDE_WIDTH_MM:g}mm {SLIDE_HEIGHT_MM:g}mm;\n"
        f"  margin: 0 0 6mm 0;\n"
        f"  @bottom-right {{\n"
        f"    content: \"{stamp}\";\n"
        f"    font-family: var(--mono-font, monospace);\n"
        f"    font-size: 6pt; color: #9aa4b1; padding-right: 6mm;\n"
        f"  }}\n"
        f"}}\n"
    ) + _SLIDE_STRUCTURE_CSS


# Kept for the geometry tests, which are about the page SIZE and must not depend
# on a stamp value.
SLIDE_PAGE_CSS = (
    f"@page {{ size: {SLIDE_WIDTH_MM:g}mm {SLIDE_HEIGHT_MM:g}mm; margin: 0 0 6mm 0; }}\n"
)


class SlidesError(Exception):
    """The deck's source cannot be resolved, or there is nothing to render."""


def resolve_source(cfg, root: Path | None = None) -> tuple[str, Path | None]:
    """Which source this deck renders from: `("file", path)` or `("guide", None)`.

    RETURNED, not inferred silently. `auto` is a convenience that has to be able
    to say what it chose — a build that resolves a source without recording it
    leaves nobody able to answer "which one did that deck come from" after the
    fact, which is the question you ask precisely when the deck is wrong.

    `file` configured but missing is a named refusal, NOT a quiet fall back to
    projection: the guide asked for a specific deck, and rendering a different
    one under its name is worse than stopping."""
    base = root or buildcore.ROOT
    wanted = base / cfg.slides.file
    if cfg.slides.source == "guide":
        return "guide", None
    if cfg.slides.source == "file":
        if not wanted.is_file():
            raise SlidesError(
                f"[slides] source = \"file\" names {cfg.slides.file!r}, which does "
                f"not exist. Create it, or switch to source = \"auto\" to project "
                f"from guide.md — the kit will not silently render a different deck."
            )
        return "file", wanted
    return ("file", wanted) if wanted.is_file() else ("guide", None)


def project_from_guide(md_path: Path) -> list:
    """The `::: slide` regions of `guide.md`, in document order.

    A fenced Div, so a slide is a real `Div` node in the AST rather than a
    comment or a raw-HTML island a parser has to guess at. Nothing outside a
    marked region reaches the deck: projection is opt-in per region, which is
    what keeps a 40-chapter guide from becoming a 400-slide deck by default."""
    doc = chapters.document(md_path)
    out: list = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Div" and "slide" in (node["c"][0][1] or []):
                out.append(node)
                return                      # no nested slides
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc.get("blocks", []))
    return out


def _as_slide(blocks: list) -> dict:
    """Wrap blocks in the `.slide` Div the deck's CSS and guards key on."""
    return {"t": "Div", "c": [["", ["slide"], []], blocks]}


def split_into_slides(blocks: list) -> list:
    """A standalone deck file's blocks, grouped into `.slide` Divs.

    WHY THIS EXISTS. A file deck's blocks were returned RAW, so nothing carried
    the `slide` class — and everything keyed on that class silently did nothing:
    the whole deck ran together on one continuous page, and its text matched no
    `.slide` font rule, so it resolved to the generic `serif` with no bundled
    family behind it. The 16:9 geometry and the stamp were correct throughout,
    which is why it looked fine.

    The grouping rule, in order:

      * If the file already uses `::: slide` fences, those ARE the slides —
        identical to how a projected deck works, so one convention covers both
        sources and a deck can be moved between them unchanged.
      * Otherwise each top-level heading starts a slide, which is what a
        hand-written deck file looks like. Content before the first heading
        becomes a leading slide rather than being dropped.
    """
    def _is_fence(b) -> bool:
        return (isinstance(b, dict) and b.get("t") == "Div"
                and "slide" in (b["c"][0][1] or []))

    # NOTHING IS DROPPED. Returning only the fenced Divs — which is what this
    # did — silently discarded every block outside them, so a deck file with a
    # title page or an introduction before its first `::: slide` lost that
    # content with no error and no notice.
    #
    # It is the same reasoning as projection, applied to a different question.
    # In `guide.md`, unmarked content is the GUIDE and must not become slides.
    # In a deck FILE, every block is the deck by definition — the file exists
    # only to be projected — so unfenced runs are grouped by heading and kept.
    groups: list[list] = []          # each entry is one slide's blocks
    run: list = []

    def _flush_run() -> None:
        """Group a run of unfenced blocks into slides, one per top heading."""
        if not run:
            return
        levels = [b["c"][0] for b in run
                  if isinstance(b, dict) and b.get("t") == "Header"]
        if not levels:
            groups.append(list(run))
            return
        top = min(levels)
        current: list = []
        for block in run:
            if isinstance(block, dict) and block.get("t") == "Header" \
                    and block["c"][0] == top and current:
                groups.append(current)
                current = []
            current.append(block)
        if current:
            groups.append(current)

    for block in blocks:
        if _is_fence(block):
            _flush_run()
            run = []
            groups.append([block])       # already a slide; kept as authored
        else:
            run.append(block)
    _flush_run()

    return [g[0] if len(g) == 1 and _is_fence(g[0]) else _as_slide(g)
            for g in groups if g]


def slide_blocks(cfg, root: Path | None = None) -> tuple[str, list]:
    """`(resolved_source, blocks)` for the deck."""
    base = root or buildcore.ROOT
    kind, path = resolve_source(cfg, base)
    if kind == "file":
        doc = chapters.document(path)
        blocks = split_into_slides(doc.get("blocks", []))
        if not blocks:
            raise SlidesError(
                f"{path.name} has no content, so the deck would be empty.")
        return kind, blocks
    blocks = project_from_guide(base / "guide.md")
    if not blocks:
        raise SlidesError(
            "no `::: slide` regions found in guide.md, so the deck would be "
            "empty. Mark the regions to project, or point [slides] file at a "
            "deck of its own."
        )
    return kind, blocks


def coverage(cfg, root: Path | None = None) -> dict:
    """Which AST chapter units contain at least one slide.

    A REPORT, never a gate — it exits 0 with uncovered chapters, because a deck
    is a selection and "every chapter has a slide" was never the goal. Units come
    from `chapters.py`, not from literal `##` headings, which are ZERO for
    git-guide: a report saying "0 of 0 units covered" for a 34-chapter guide
    would be worse than none.

    Membership is by DOCUMENT POSITION — which chapter's span the marked region
    falls in — not by matching slug text against the slide's contents. Text
    matching looked simpler and was wrong twice over: a heading is tokenised into
    separate `Str` nodes so the phrase never appears intact, and a slug that
    happens to be a substring of unrelated prose would count as coverage.

    A deck from a separate FILE has no positional relationship to the guide at
    all, so coverage is reported as unknown rather than invented."""
    base = root or buildcore.ROOT
    cfg_level = cfg.site.chapter_level
    chs = chapters.split(base / "guide.md", chapter_level=cfg_level)
    kind, _ = resolve_source(cfg, base)
    if kind == "file":
        return {"total": len(chs), "covered": [],
                "uncovered": [c.slug for c in chs], "source": "file",
                "note": "the deck is a separate file, so per-chapter coverage "
                        "cannot be derived from position"}

    doc = chapters.document(base / "guide.md")
    covered: list[str] = []
    current: str | None = None
    for block in doc.get("blocks", []):
        if not isinstance(block, dict):
            continue
        if block.get("t") == "Header" and block["c"][0] <= cfg_level:
            level = block["c"][0]
            current = None
            if level == cfg_level:
                title = chapters._inline_text(block["c"][2])
                ident = block["c"][1][0]
                authored = chapters._authored_ids(base / "guide.md")
                current = ident if ident in authored else chapters.derive_slug(title)
            continue
        if current and _contains_slide(block) and current not in covered:
            covered.append(current)
    return {"total": len(chs), "covered": sorted(covered), "source": "guide",
            "uncovered": [c.slug for c in chs if c.slug not in covered]}


def _contains_slide(node) -> bool:
    if isinstance(node, dict):
        if node.get("t") == "Div" and "slide" in (node["c"][0][1] or []):
            return True
        return any(_contains_slide(v) for v in node.values())
    if isinstance(node, list):
        return any(_contains_slide(v) for v in node)
    return False


def render_html(cfg, root: Path | None = None) -> str:
    """The deck's HTML: marked blocks → pandoc → the slides cascade at 16:9."""
    base = root or buildcore.ROOT
    _, blocks = slide_blocks(cfg, base)
    body = chapters.blocks_to_html(blocks, chapters.document(base / "guide.md")
                                   .get("pandoc-api-version"))
    body = buildcore._apply_transforms(body, "pdf")
    buildcore.check_cjk_annotations(body)
    stamp = buildcore._version_stamp("slides")
    css = _page_css(stamp) + buildcore.theme_css(
        "slides", STYLE_SLIDES.read_text(encoding="utf-8")
        if STYLE_SLIDES.is_file() else "")
    css = css.replace("__TITLE__", buildcore.TITLE).replace("__VERSION__", stamp)
    return buildcore._wrap_html(body, css)


def build_slides() -> None:
    """Render the deck to `build/<slug>-slides.pdf`."""
    cfg = kitconfig.load(buildcore.ROOT)
    if not cfg.outputs.slides:
        print("  SLIDES -> [outputs] slides = false — nothing to build.")
        return
    os.environ["SOURCE_DATE_EPOCH"] = str(buildcore._source_date_epoch("slides"))
    buildcore.assert_hermetic_fontconfig()
    buildcore.check_font_provenance()

    source, _ = resolve_source(cfg)
    print(f"  SLIDES -> source resolved to {source!r}")
    full_html = render_html(cfg)
    cascade = _page_css(buildcore._version_stamp("slides")) + buildcore.theme_css(
        "slides", STYLE_SLIDES.read_text(encoding="utf-8")
        if STYLE_SLIDES.is_file() else "")
    buildcore.check_overrides(cascade, "slides")

    buildcore.BUILD_DIR.mkdir(exist_ok=True)
    out = buildcore.BUILD_DIR / f"{buildcore.OUTPUT_SLUG}-slides.pdf"
    document = HTML(string=full_html, base_url=str(buildcore.ROOT)).render()
    # THE SAME TWO CHECKS THE PDF RUNS, and they were missing here. The deck is a
    # deliverable rendered from its own cascade and — with `[slides] file` — from
    # its own source, so the PDF's checks say nothing about it. Asking the
    # rendered box tree rather than the source is what makes them work for a
    # deck whose text `check_glyph_coverage` never scans: it inspects what
    # actually reached the page, by whatever route.
    buildcore.check_rendered_families(document, cascade)
    buildcore.check_rendered_coverage(document, cascade)
    document.write_pdf(str(out))
    buildcore._qpdf_canonicalize(out)
    print(f"  SLIDES -> {out}")
    return out
