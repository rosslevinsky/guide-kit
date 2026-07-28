"""What the rendered PDF ACTUALLY embedded — the output side of two guarantees.

The other font tests check inputs: the recorded binaries are the ones on disk,
and a real bold/italic face exists for every weight and style. Neither proves the
renderer reached for them. WeasyPrint synthesizes a missing weight from the
regular face; the result renders, looks roughly right, and is not the typeface
anyone chose. And a host font remains reachable however careful the CSS is,
because WeasyPrint delegates matching and fallback to Pango/Fontconfig.

So this module renders and then reads the PDF back. It is the only place in the
suite that can answer "did the thing we intended actually happen".

Skipped, not failed, where the render toolchain is unavailable: this is the kit
test suite, which must stay runnable in environments without pandoc/WeasyPrint.
"""
import shutil
import subprocess

import pytest

import buildcore

pytestmark = pytest.mark.skipif(
    shutil.which("pdffonts") is None,
    reason="pdffonts (poppler) is not available",
)

# The families the kit bundles, as the CSS renames them. Anything embedded that
# is not one of these came from somewhere other than fonts/vendor/.
_BUNDLED_PREFIXES = ("Guide-Serif", "Guide-Sans", "Guide-Mono")

def _required_real_faces():
    """Derived from the SELECTED theme, not hardcoded.

    A synthesized bold is not a separate embedded face — the renderer smears the
    regular one — so the presence of these names IS the evidence. Which names to
    expect depends on which family the theme puts in the body: naming Sans faces
    while the guide renders in Serif tests the wrong document."""
    import kitconfig
    css = (buildcore.THEMES_DIR / buildcore._cfg.theme.name / "print.css").read_text(
        encoding="utf-8")
    body = "Guide-Serif" if '"Guide Serif"' in css.split("--body-font:")[1].split(";")[0] \
        else "Guide-Sans"
    return (f"{body}-Bold", f"{body}-Italic", "Guide-Mono-Bold")


_REQUIRE_REAL = _required_real_faces()


@pytest.fixture(scope="module")
def rendered_pdf():
    """The kit's own PDF, built FRESH — never a leftover from an earlier run.

    Two failure modes are deliberately excluded. Reusing an existing
    `build/<slug>.pdf` means changed renderer or CSS code is never exercised and
    these tests pass against old bytes: the one module whose whole purpose is to
    inspect real output would be inspecting stale output. And a build that FAILS
    is a result, not a reason to skip — skipping there converts a genuine render
    regression into a green run.

    The only legitimate skip is "this environment cannot build at all", which is
    decided BEFORE building, by looking for the toolchain."""
    if shutil.which("pixi") is None:
        pytest.skip("pixi is not available; cannot build")
    pdf = buildcore.OUT_PDF
    pdf.unlink(missing_ok=True)          # never inspect a leftover render
    proc = subprocess.run(["pixi", "run", "build"], cwd=buildcore.ROOT,
                          capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, (
        f"the build failed, so the rendered output cannot be checked:\n"
        f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    )
    assert pdf.is_file(), "the build reported success but wrote no PDF"
    return pdf


def test_every_embedded_face_is_a_bundled_one(rendered_pdf):
    """The property bundling exists to buy. A host face reaching the page voids
    it silently — the PDF renders, and looks different on someone else's
    machine."""
    faces = buildcore.embedded_faces(rendered_pdf)
    assert faces, "the PDF embeds no fonts at all"
    strangers = [f for f in faces if not f.startswith(_BUNDLED_PREFIXES)]
    assert strangers == [], (
        f"non-bundled faces reached the render: {strangers}. A host font is "
        f"resolving through Fontconfig despite the bundled cascade."
    )


@pytest.mark.parametrize("face", _REQUIRE_REAL)
def test_the_weight_and_style_faces_are_really_embedded(rendered_pdf, face):
    """A SYNTHESIZED bold is not an embedded face — the renderer slants or
    smears the regular one and embeds nothing new. So a missing name here is
    exactly the signature of a synthesized weight."""
    faces = buildcore.embedded_faces(rendered_pdf)
    assert face in faces, (
        f"{face} is not embedded — its weight/style is being synthesized from "
        f"another face rather than taken from a real binary."
    )


def test_no_face_is_embedded_twice_under_different_names(rendered_pdf):
    """Two subsets of one family usually means two different binaries resolved
    for it — the cascade reaching outside fonts/vendor/ for part of the text."""
    faces = buildcore.embedded_faces(rendered_pdf)
    assert len(faces) == len(set(faces)), f"duplicate embedded faces: {faces}"


def test_the_colophon_credits_the_bundled_families(rendered_pdf):
    """The fonts are REDISTRIBUTED with every guide, not merely used to render
    it, so the families have to be identified to the reader holding the PDF."""
    text = subprocess.run(["pdftotext", str(rendered_pdf), "-"],
                          capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout
    flat = " ".join(text.split())
    assert "Typeset in" in flat, "the colophon carries no font credit"
    for family in buildcore.bundled_font_families():
        assert family in flat, f"{family} is bundled but not credited"
