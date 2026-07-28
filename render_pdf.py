#!/usr/bin/env python3
"""The PDF renderer.

In the PDF artifact's dependency closure; `render_site.py` is not. Reaches
shared state as `buildcore.NAME` so monkeypatching in tests is visible here.
"""
from __future__ import annotations


import os

from weasyprint import HTML

import buildcore

def _pdf_colophon() -> str:
    """License/copyright block appended to the end of the PDF (the last page).
    Styled by the `.colophon` rules in style.css."""
    return (
        '<div class="colophon">'
        f'<p class="colophon-title">{buildcore.TITLE}</p>'
        f'<p>{buildcore.COPYRIGHT}</p>'
        '<p>This guide is licensed under '
        f'<a href="{buildcore.LICENSE_CONTENT_URL}">{buildcore.LICENSE_CONTENT_NAME}</a>. '
        'The build tooling is licensed under '
        f'<a href="{buildcore.LICENSE_CODE_URL}">{buildcore.LICENSE_CODE_NAME}</a>.</p>'
        f'<p class="colophon-fonts">{_font_credit()}</p>'
        '</div>'
    )


def _font_credit() -> str:
    """Credit the bundled families by name. A COURTESY, not an obligation.

    An earlier version of this claimed the credit was "required because the fonts
    are REDISTRIBUTED with every guide". That is true of the REPOSITORY, which
    ships the actual binaries under `fonts/vendor/` beside `OFL.txt`,
    `LICENSE-DejaVu.txt` and the two per-family licences — and that is what
    discharges the obligation. It is not true of the PDF, which embeds subsets.
    OFL 1.1 settles the difference in the copy bundled here (`fonts/vendor/
    OFL.txt`, clause 5): "The requirement for fonts to remain under this license
    does not apply to any document created using the Font Software." Embedding
    needs no acknowledgement. Two of the four families are not even OFL — DejaVu
    is Bitstream Vera, with DejaVu's own changes in the public domain.

    So the line stays because a typeface colophon is a normal courtesy in a
    typeset book and a reader holding the PDF has no other way to know what they
    are looking at — not because a licence compels it. The names come from the
    binaries' own name tables, so this cannot drift from what was embedded.

    It names the LICENCES rather than a repository path. `(see fonts/vendor/)`
    pointed a reader at a location they cannot reach: seven of the eight guide
    repositories are private, and someone holding only the PDF has no way to map
    a relative path to anything at all."""
    families = buildcore.bundled_font_families()
    if not families:
        return ""
    if len(families) == 1:
        listed = families[0]
    else:
        listed = ", ".join(families[:-1]) + " and " + families[-1]
    return (
        f"Typeset in {listed}, under the Bitstream Vera and "
        f"SIL Open Font licenses."
    )


def render_html() -> str:
    """Render the PRINT HTML: pandoc → PDF transforms → colophon → wrap with style.css."""
    body = buildcore._apply_transforms(buildcore._pandoc_body(), "pdf") + _pdf_colophon()
    # On the TRANSFORMED body: a transform can inject CJK text, and the
    # question is about what actually reaches the page.
    buildcore.check_cjk_annotations(body)
    css = buildcore.theme_css("print", buildcore.STYLE.read_text(encoding="utf-8"))
    css = css.replace("__TITLE__", buildcore.TITLE).replace("__VERSION__", buildcore._version_stamp())
    return buildcore._wrap_html(body, css)


def build(want_pdf: bool, want_html: bool) -> None:
    # Pin WeasyPrint's PDF creation timestamp via the reproducible-builds
    # standard env var. WeasyPrint reads this when set.
    os.environ["SOURCE_DATE_EPOCH"] = str(buildcore._source_date_epoch("pdf"))
    # Before rendering, not after: a PDF with tofu in it should never be
    # written, or someone will ship the one that happens to look fine locally.
    # Provenance BEFORE coverage: an unexpected binary makes every downstream
    # answer — coverage, metrics, the emitted face set — about the wrong file.
    # Hermetic FIRST: it sets FONTCONFIG_FILE, and every later question — glyph
    # coverage, which faces get embedded — is only meaningful once the renderer
    # can no longer see the host's fonts.
    buildcore.assert_hermetic_fontconfig()
    buildcore.check_font_provenance()
    # The cascade is resolved ONCE and every check asks about that same
    # resolution — coverage over the families it reaches, and the override
    # guard against the faces it declares.
    cascade = buildcore.theme_css("print", buildcore.STYLE.read_text(encoding="utf-8"))
    buildcore.check_overrides(cascade)
    buildcore.check_glyph_coverage(cascade)
    buildcore.BUILD_DIR.mkdir(exist_ok=True)

    full_html = render_html()
    if want_html:
        buildcore.OUT_HTML.write_text(full_html, encoding="utf-8")
        print(f"  HTML  ->  {buildcore.OUT_HTML}")
    if want_pdf:
        # render() FIRST, then write from the same Document. The box tree is what
        # WeasyPrint actually computed — after the cascade, inheritance and every
        # var() substitution — so a family that reached the page by a route no
        # static check anticipated still shows up. Rendering twice would be both
        # slower and weaker: the tree inspected has to be the tree written.
        document = HTML(string=full_html, base_url=str(buildcore.ROOT)).render()
        buildcore.check_rendered_families(document, cascade)
        buildcore.check_rendered_coverage(document, cascade)
        document.write_pdf(str(buildcore.OUT_PDF))
        buildcore._qpdf_canonicalize(buildcore.OUT_PDF)
        print(f"  PDF   ->  {buildcore.OUT_PDF}")
