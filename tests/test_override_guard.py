"""No override may reach a family the kit does not bundle.

A REAL PARSER, not a substring search, because three routes each smuggle a host
family past a grep:

  * the `font` SHORTHAND — `font: italic small-caps bold 12px/1.4 Georgia, serif`
    names a family after five other components;
  * a CUSTOM PROPERTY — `--body-font: Georgia` names one in a declaration whose
    name gives no hint that it does, and the whole theme layer reaches families
    through exactly this mechanism;
  * `@font-face` — which does not name a family so much as CREATE one, pointing
    at a file the kit never vetted and that the hermetic Fontconfig environment
    cannot see.

And one route no CSS check reaches at all: `font-family` PRESENTATION ATTRIBUTES
on the inline SVG diagrams in `guide.md`. Five of the guides carry them today.
"""
from pathlib import Path

import pytest

import buildcore
import cascadecheck

ALLOWED = {"Guide Serif", "Guide Sans", "Guide Mono", "Guide Fallback"}
WORKSPACE = buildcore.ROOT.parent
def _sibling_guides():
    """Every guide repo sitting beside this one, DISCOVERED not listed.

    This was a hardcoded list of the seven repos in the author's own workspace.
    Two things were wrong with that in a public toolkit: an outside clone has
    none of them, so the parametrized cases silently reduced to nothing while
    still reporting as passed; and the kit's test suite named seven private
    repositories that no reader of it can open. Discovery keeps the check
    meaningful wherever it runs — beside a full family it covers all of them,
    beside nothing it covers nothing and says so.
    """
    workspace = buildcore.ROOT.parent
    if not workspace.is_dir():
        return []
    return sorted(d.name for d in workspace.iterdir()
                  if d.is_dir() and d.name != buildcore.ROOT.name
                  and (d / "guide.toml").is_file())


GUIDES = _sibling_guides()


def _write(tmp_path, css):
    p = tmp_path / "override.css"
    p.write_text(css, encoding="utf-8")
    return p


# ----- accepted ---------------------------------------------------------------

@pytest.mark.parametrize("css", [
    '.a { font-family: "Guide Sans", "Guide Fallback"; }',
    ".a { font-family: inherit; }",
    ".a { font-family: var(--body-font); }",
    '.a { font: 14px/1.5 "Guide Mono", monospace; }',
    ':root { --x: "Guide Serif"; }',
    ".a { font-family: serif; }",
])
def test_bundled_and_generic_families_are_accepted(tmp_path, css):
    cascadecheck.check_override(_write(tmp_path, css), ALLOWED)


# ----- rejected ---------------------------------------------------------------

def test_font_face_is_rejected_outright(tmp_path):
    """An override that DEFINES a face points at a file the kit never vetted, and
    the hermetic environment cannot see it — so it either renders nothing or
    reintroduces a host binary."""
    css = '@font-face { font-family: "Sneaky"; src: url("/usr/share/fonts/x.ttf"); }'
    with pytest.raises(cascadecheck.CascadeError, match="@font-face is not allowed"):
        cascadecheck.check_override(_write(tmp_path, css), ALLOWED)


def test_an_unbundled_family_in_a_font_shorthand_is_rejected(tmp_path):
    css = ".a { font: italic small-caps bold 12px/1.4 Georgia, serif; }"
    with pytest.raises(cascadecheck.CascadeError, match="Georgia"):
        cascadecheck.check_override(_write(tmp_path, css), ALLOWED)


def test_an_unbundled_family_in_a_custom_property_is_rejected(tmp_path):
    """The evasion a `font-family:` search cannot see — and the exact mechanism
    the theme layer uses, so it is reachable by design."""
    css = ':root { --body-font: "Helvetica Neue"; }\n.a { font-family: var(--body-font); }'
    with pytest.raises(cascadecheck.CascadeError, match="Helvetica Neue"):
        cascadecheck.check_override(_write(tmp_path, css), ALLOWED)


def test_a_family_hidden_inside_a_media_query_is_rejected(tmp_path):
    css = "@media screen { .a { font-family: Georgia; } }"
    with pytest.raises(cascadecheck.CascadeError, match="Georgia"):
        cascadecheck.check_override(_write(tmp_path, css), ALLOWED)


def test_host_resolving_generics_are_rejected(tmp_path):
    """`system-ui` IS a generic keyword, but it resolves to whatever the HOST
    considers its UI font — the dependence bundling exists to remove."""
    css = ".a { font-family: system-ui; }"
    with pytest.raises(cascadecheck.CascadeError, match="system-ui"):
        cascadecheck.check_override(_write(tmp_path, css), ALLOWED)


def test_the_font_shorthand_keywords_are_not_mistaken_for_families(tmp_path):
    """`italic small-caps bold` would be extracted as a family name by a naive
    identifier scan, and the guard would reject ordinary CSS."""
    css = '.a { font: italic small-caps bold 12px/1.4 "Guide Sans"; }'
    cascadecheck.check_override(_write(tmp_path, css), ALLOWED)   # must not raise


# ----- the inline-SVG attribute vector ----------------------------------------

def test_an_unbundled_family_in_an_svg_attribute_is_rejected(tmp_path):
    """The one route with no stylesheet involved at all: a presentation attribute
    on a diagram sets the family directly, and every CSS check stays green."""
    md = tmp_path / "guide.md"
    md.write_text('<svg><text font-family="Georgia">x</text></svg>', encoding="utf-8")
    with pytest.raises(cascadecheck.CascadeError, match="Georgia"):
        cascadecheck.check_svg_attributes(md, ALLOWED)


def test_the_real_svg_attributes_in_the_guides_are_accepted(tmp_path):
    md = tmp_path / "guide.md"
    md.write_text('<svg><text font-family="Guide Sans, Guide Fallback">x</text></svg>',
                  encoding="utf-8")
    cascadecheck.check_svg_attributes(md, ALLOWED)   # must not raise


def test_single_quoted_svg_attributes_are_seen_too(tmp_path):
    md = tmp_path / "guide.md"
    md.write_text("<svg><text font-family='Georgia'>x</text></svg>", encoding="utf-8")
    with pytest.raises(cascadecheck.CascadeError, match="Georgia"):
        cascadecheck.check_svg_attributes(md, ALLOWED)


# ----- the shipping repositories ----------------------------------------------

def test_the_kits_own_overrides_pass():
    cascade = buildcore.theme_css("print", buildcore.STYLE.read_text(encoding="utf-8"))
    allowed = cascadecheck.bundled_families(cascade)
    for sheet in ("style.css", "style-screen.css.example"):
        cascadecheck.check_override(buildcore.ROOT / sheet, allowed, label=f"kit/{sheet}")
    cascadecheck.check_svg_attributes(buildcore.SRC, allowed)


@pytest.mark.parametrize("guide", GUIDES)
def test_every_guide_passes_the_guard(guide):
    """The migration and the guard have to be consistent in ONE commit: activating
    the guard against unmigrated sheets would turn every enabled web build red."""
    root = WORKSPACE / guide
    if not root.is_dir():
        pytest.skip(f"{guide} is not checked out beside the kit")
    cascade = buildcore.theme_css("print", buildcore.STYLE.read_text(encoding="utf-8"))
    allowed = cascadecheck.bundled_families(cascade)
    for sheet in ("style.css", "style-screen.css", "style-slides.css"):
        cascadecheck.check_override(root / sheet, allowed, label=f"{guide}/{sheet}")
    cascadecheck.check_svg_attributes(root / "guide.md", allowed)


@pytest.mark.parametrize("guide", GUIDES)
def test_no_guide_still_declares_its_own_faces(guide):
    """The @font-face declarations moved to the kit-owned fontfaces.css. A guide
    that kept a copy would define the families it also consumes, which is exactly
    what makes the guard's absolute rule possible."""
    root = WORKSPACE / guide
    if not root.is_dir():
        pytest.skip(f"{guide} is not checked out beside the kit")
    # Asked of the PARSER, not of the raw text: each sheet carries a comment
    # explaining that the faces moved, and a grep matches its own documentation.
    for sheet in ("style.css", "style-screen.css"):
        p = root / sheet
        if p.is_file():
            declared = cascadecheck.font_face_rules(p.read_text(encoding="utf-8"))
            assert declared == [], f"{guide}/{sheet} still declares faces: {declared}"


def test_the_faces_are_declared_exactly_once_and_by_the_kit():
    faces = buildcore.ROOT / "fontfaces.css"
    assert faces.is_file(), "fontfaces.css is missing"
    families = cascadecheck.bundled_families(faces.read_text(encoding="utf-8"))
    assert families == ALLOWED, families
    assert cascadecheck.font_face_rules(
        (buildcore.ROOT / "style.css").read_text(encoding="utf-8")) == []


# ----- the bypasses a first cut left open -------------------------------------

def test_a_nested_font_face_is_rejected(tmp_path):
    """WeasyPrint processes `@media { @font-face { … } }` and registers the face.
    A top-level-only scan let a nested rule point at a host file while the guard
    reported nothing and the rendered-family check saw only the allowed NAME."""
    css = ('@media print { @font-face { font-family: "Guide Sans"; '
           'src: url("/usr/share/fonts/x.ttf"); } }')
    with pytest.raises(cascadecheck.CascadeError, match="@font-face is not allowed"):
        cascadecheck.check_override(_write(tmp_path, css), ALLOWED)


@pytest.mark.parametrize("css,bad", [
    (".a { font-family: var(--x, Georgia); }", "Georgia"),
    (".a { font-family: var(--x, var(--y, Menlo)); }", "Menlo"),
    (".a { font-family: var(--x, system-ui); }", "system-ui"),
])
def test_a_host_family_in_a_var_fallback_is_rejected(tmp_path, css, bad):
    """The fallback is exactly the branch that runs when the property is
    undefined, so it is reachable by construction."""
    with pytest.raises(cascadecheck.CascadeError, match=bad):
        cascadecheck.check_override(_write(tmp_path, css), ALLOWED)


def test_a_var_reference_is_not_mistaken_for_a_family(tmp_path):
    """`var(--body-font)`: the first argument is the property NAME. Reading it as
    a family rejected the kit's own stylesheet."""
    cascadecheck.check_override(
        _write(tmp_path, ".a { font-family: var(--body-font); }"), ALLOWED)


def test_family_names_are_matched_case_insensitively(tmp_path):
    """CSS family names are case-insensitive; `"guide sans"` resolves to Guide
    Sans and must not be rejected."""
    cascadecheck.check_override(
        _write(tmp_path, '.a { font-family: "guide sans"; }'), ALLOWED)


@pytest.mark.parametrize("markup", [
    '<svg><text style="font-family: Georgia">x</text></svg>',
    "<svg><style>text { font-family: Menlo; }</style></svg>",
    '<svg><text style="font: 12px/1.2 Georgia">x</text></svg>',
])
def test_svg_inline_styles_are_guarded_too(tmp_path, markup):
    """WeasyPrint renders an inline `<svg>` as ONE replaced box, so the
    rendered-family check cannot see inside it — these were the last routes by
    which a diagram could name a host family with every other check green."""
    md = tmp_path / "guide.md"
    md.write_text(markup, encoding="utf-8")
    with pytest.raises(cascadecheck.CascadeError):
        cascadecheck.check_svg_attributes(md, ALLOWED)


def test_one_binary_may_be_exposed_under_several_families():
    """Returning only the first family meant a face counted as unreachable
    whenever that one happened to be the unused name."""
    css = ('@font-face { font-family: "Alpha"; src: url("fonts/vendor/X.otf"); }\n'
           '@font-face { font-family: "Beta"; src: url("fonts/vendor/X.otf"); }')
    assert cascadecheck.families_for_source(css, "X.otf") == {"Alpha", "Beta"}


def test_the_web_build_publishes_every_font_it_references(tmp_path, monkeypatch):
    """The deployed site serves app/dist and NOTHING ELSE. The screen cascade now
    carries `url("fonts/vendor/…")`, so a dist without the faces means every one
    404s and the site falls back to host fonts — the dependence bundling removed
    from the PDF, reintroduced on the web."""
    import re
    import render_site

    monkeypatch.setattr(render_site, "WEB_DIR", tmp_path / "dist")
    render_site._publish_fonts()
    published = {p.relative_to(render_site.WEB_DIR).as_posix()
                 for p in render_site.WEB_DIR.rglob("*") if p.is_file()}
    css = buildcore.theme_css(
        "screen", (buildcore.ROOT / "style-screen.css.example").read_text(encoding="utf-8"))
    urls = set(re.findall(r'url\("([^"]+)"\)', css))
    assert urls, "the screen cascade references no fonts at all"
    assert not (urls - published), f"these would 404 on the deployed site: {sorted(urls - published)}"


def test_the_discovery_predicate_actually_finds_a_guide(tmp_path, monkeypatch):
    """A BROKEN PREDICATE AND A STANDALONE CLONE LOOK IDENTICAL, and that is the
    hole discovery opened when it replaced the hardcoded list.

    Measured: beside the full family the parametrized cases below run 8 apiece;
    in a standalone clone every one of them collapses to a single `[NOTSET]`
    skip. Both readings are correct for an empty `GUIDES` — and `GUIDES` is empty
    both when there is genuinely nothing beside the kit and when
    `_sibling_guides()` has stopped recognising a guide. Nothing distinguishes
    them, so a regression in the predicate would land as three quiet skips.

    So the predicate is exercised against a SYNTHETIC workspace, where the right
    answer is known and does not depend on what happens to be checked out.
    """
    workspace = tmp_path / "workspace"
    kit = workspace / "guide-kit"
    kit.mkdir(parents=True)
    (workspace / "a-guide").mkdir()
    (workspace / "a-guide" / "guide.toml").write_text('TITLE = "A"\n', encoding="utf-8")
    (workspace / "b-guide").mkdir()
    (workspace / "b-guide" / "guide.toml").write_text('TITLE = "B"\n', encoding="utf-8")
    # Neither of these is a guide: one has no guide.toml, the other IS the kit.
    (workspace / "edge-nginx").mkdir()
    (kit / "guide.toml").write_text('TITLE = "Kit"\n', encoding="utf-8")

    monkeypatch.setattr(buildcore, "ROOT", kit)
    assert _sibling_guides() == ["a-guide", "b-guide"]


def test_body_text_is_bound_to_the_body_token():
    """`--head-font` is Guide MONO under the `technical` theme, so binding body
    text to it renders whole pages in monospace.

    Skipped rather than looped-over-nothing when there are no siblings. It used
    to iterate an empty `GUIDES` and assert nothing, reporting a pass that had
    examined no file — the one outcome worse than a skip, because a skip says so.
    """
    if not GUIDES:
        pytest.skip("no guide repos are checked out beside the kit")
    for guide in GUIDES:
        sheet = WORKSPACE / guide / "style-screen.css"
        if not sheet.is_file():
            continue
        text = sheet.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines()):
            if line.strip().startswith("body {"):
                following = "\n".join(text.splitlines()[i:i + 4])
                assert "--head-font" not in following, \
                    f"{guide}: body text is bound to the heading token"


def test_the_guard_reads_only_the_artifact_s_own_sheet(tmp_path, monkeypatch):
    """An out-of-closure stylesheet must not be able to fail a build.

    `check_overrides` read `style.css`, `style-screen.css` AND
    `style-slides.css` on every build, whichever artifact was being made.
    Measured on a PDF-only guide: an illegal family in `style-slides.css` — a
    file in no closure that build reads, and target-owned, so every guide ships
    one — exited `build.py` with 1. That contradicts the artifact split the
    closures exist to create, and the guide cannot fix it without editing a
    stylesheet it does not use.

    Nothing is lost by narrowing: each sheet is still checked on the build that
    renders through it, against that build's own cascade, which is the stricter
    comparison since the three cascades differ.
    """
    # Built BEFORE the ROOT swap: `theme_css` reads `fontfaces.css` from ROOT,
    # and the guard refuses a cascade that declares no faces.
    cascade = buildcore.theme_css("print", buildcore.STYLE.read_text(encoding="utf-8"))
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)
    monkeypatch.setattr(buildcore, "SRC", tmp_path / "guide.md")
    (tmp_path / "guide.md").write_text("# Plain\n", encoding="utf-8")
    for sheet in buildcore._OVERRIDE_SHEET.values():
        (tmp_path / sheet).write_text("body { font-family: var(--body-font); }\n",
                                      encoding="utf-8")

    # An illegal family in the SLIDES sheet.
    (tmp_path / "style-slides.css").write_text(
        "body { font-family: Georgia, serif; }\n", encoding="utf-8")
    buildcore.check_overrides(cascade, "pdf")       # must not raise
    buildcore.check_overrides(cascade, "site")      # must not raise
    with pytest.raises(SystemExit):
        buildcore.check_overrides(cascade, "slides")

    # ...and each artifact is still guarded against its own sheet.
    (tmp_path / "style-slides.css").write_text("body { font-family: inherit; }\n",
                                               encoding="utf-8")
    (tmp_path / "style.css").write_text("body { font-family: Georgia, serif; }\n",
                                        encoding="utf-8")
    with pytest.raises(SystemExit):
        buildcore.check_overrides(cascade, "pdf")
