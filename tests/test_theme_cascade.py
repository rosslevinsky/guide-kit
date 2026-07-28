"""The cascade: theme tokens -> [theme.tokens] -> the guide's own override.

A THEME IS A TOKEN SET. That is what makes `[theme] name` a real choice rather
than a label: the guide's stylesheet supplies structure and reads values through
`var()`, so switching themes restyles a render without either side knowing about
the other.

CONCATENATION ORDER, NOT `@layer`. Plain source order means "later wins", which
is what every contributor already expects from CSS; `@layer` inverts that
intuition and WeasyPrint's support for it is not something a family of eight
repositories should bet its typography on.

The closure half matters as much as the render half: the PDF must depend on the
SELECTED theme's `print.css` and nothing else, or a screen-only palette tweak —
or an entirely unselected theme — would re-stale eight reference PDFs.
"""
import subprocess

import pytest

import buildcore
import kitconfig

THEMES_DIR = buildcore.ROOT / "themes"
OUTPUTS = ("print", "screen", "slides")


def _themes():
    return sorted(p.name for p in THEMES_DIR.iterdir() if p.is_dir())


# ----- the themes themselves --------------------------------------------------

def test_at_least_three_themes_exist():
    names = _themes()
    assert len(names) >= 3, f"only {names}"
    # The two the family committed to by name: its current appearance, and the
    # serif alternative. Serif-vs-sans is a THEME choice, not a family decision.
    assert "classic-sans" in names and "editorial" in names


@pytest.mark.parametrize("output", OUTPUTS)
def test_every_theme_supplies_every_output(output):
    for name in _themes():
        assert (THEMES_DIR / name / f"{output}.css").is_file(), \
            f"theme {name} has no {output}.css"


def test_a_theme_defines_tokens_and_nothing_else():
    """Structure belongs to the guide. A theme that shipped selectors would
    override the guide's own sheet from the wrong end of the cascade."""
    import re
    for name in _themes():
        for output in OUTPUTS:
            css = (THEMES_DIR / name / f"{output}.css").read_text(encoding="utf-8")
            body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            selectors = [b.split("{")[0].strip() for b in body.split("}") if "{" in b]
            assert all(s == ":root" for s in selectors), \
                f"{name}/{output}.css declares non-token rules: {selectors}"


def test_font_stacks_name_only_bundled_families():
    """A host family in a token would reintroduce exactly the dependence the
    bundled faces and the hermetic Fontconfig exist to remove."""
    for name in _themes():
        css = (THEMES_DIR / name / "print.css").read_text(encoding="utf-8")
        for line in css.splitlines():
            if "-font:" not in line:
                continue
            assert "Guide " in line, f"{name}: {line.strip()} names no bundled family"
            for stranger in ("-apple-system", "Helvetica", "Georgia", "Arial",
                             "Hiragino", "Menlo", "system-ui"):
                assert stranger not in line, f"{name}: host family {stranger} in {line.strip()}"


# ----- cascade ORDER ----------------------------------------------------------

def test_the_override_comes_last(monkeypatch):
    """Later wins, so the guide's own sheet is the final word."""
    css = buildcore.theme_css("print", "/* OVERRIDE MARKER */")
    assert css.index("theme:") < css.index("OVERRIDE MARKER")


def test_guide_toml_tokens_sit_between_the_theme_and_the_override(tmp_path, monkeypatch):
    """The middle layer: one guide retinting a value without forking a sheet."""
    theme = kitconfig.Theme(name=buildcore._cfg.theme.name,
                            tokens=(("--accent", "rebeccapurple"),))
    monkeypatch.setattr(buildcore, "_cfg",
                        type(buildcore._cfg)(**{**vars(buildcore._cfg), "theme": theme}))
    css = buildcore.theme_css("print", "/* OVERRIDE MARKER */")
    assert css.index("theme:") < css.index("rebeccapurple") < css.index("OVERRIDE MARKER")


@pytest.mark.parametrize("output", ("screen", "slides"))
def test_non_print_outputs_layer_over_print(output):
    """Only what genuinely differs belongs in screen.css or slides.css, so a
    palette change is made once."""
    css = buildcore.theme_css(output, "")
    assert css.index("print.css") < css.index(f"{output}.css")


def test_a_missing_theme_is_a_hard_failure(monkeypatch):
    """Falling back silently would render with every var() unresolved — which
    does not look like an error, it looks like a slightly wrong design."""
    theme = kitconfig.Theme(name="no-such-theme")
    monkeypatch.setattr(buildcore, "_cfg",
                        type(buildcore._cfg)(**{**vars(buildcore._cfg), "theme": theme}))
    with pytest.raises(SystemExit, match="has no print.css"):
        buildcore.theme_css("print", "")


# ----- the CLOSURE half -------------------------------------------------------

def test_the_pdf_closure_contains_only_the_selected_themes_print_sheet():
    cfg = kitconfig.load(buildcore.ROOT)
    deps = [kitconfig._resolve_pattern(f, cfg)
            for f in kitconfig.artifact_spec("pdf").file_deps]
    theme_deps = [d for d in deps if d.startswith("themes/")]
    assert theme_deps == [f"themes/{cfg.theme.name}/print.css"], theme_deps


def test_an_unselected_theme_does_not_stale_the_pdf(tmp_path):
    """Eight reference PDFs must not go stale because a theme nobody selected
    changed."""
    cfg = kitconfig.load(buildcore.ROOT)
    before = kitconfig.artifact_closure_hash("pdf", root=buildcore.ROOT)
    others = [n for n in _themes() if n != cfg.theme.name]
    assert others, "need a second theme to make this meaningful"
    victim = THEMES_DIR / others[0] / "print.css"
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"\n:root { --accent: red; }\n")
        after = kitconfig.artifact_closure_hash("pdf", root=buildcore.ROOT)
    finally:
        victim.write_bytes(original)
    assert before == after, "an unselected theme moved the PDF's closure hash"


def test_the_selected_themes_screen_sheet_does_not_stale_the_pdf():
    cfg = kitconfig.load(buildcore.ROOT)
    before = kitconfig.artifact_closure_hash("pdf", root=buildcore.ROOT)
    victim = THEMES_DIR / cfg.theme.name / "screen.css"
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"\n:root { --measure: 1px; }\n")
        after = kitconfig.artifact_closure_hash("pdf", root=buildcore.ROOT)
    finally:
        victim.write_bytes(original)
    assert before == after, "the theme's screen sheet is in the PDF closure"


def test_changing_the_selected_theme_moves_the_pdf_closure():
    """The other direction — the closure has to NOTICE a real change, or the
    reference would never be re-rendered when the appearance moved."""
    cfg = kitconfig.load(buildcore.ROOT)
    before = kitconfig.artifact_closure_hash("pdf", root=buildcore.ROOT)
    victim = THEMES_DIR / cfg.theme.name / "print.css"
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"\n:root { --accent: red; }\n")
        after = kitconfig.artifact_closure_hash("pdf", root=buildcore.ROOT)
    finally:
        victim.write_bytes(original)
    assert before != after, "editing the SELECTED theme did not move the closure"


# ----- overrides keep their names, one closure each ---------------------------

def test_each_override_is_in_exactly_one_closure():
    """The names are unchanged, and each belongs to one artifact — the split
    that stopped a slides stylesheet from re-staling every PDF."""
    cfg = kitconfig.load(buildcore.ROOT)
    where = {}
    for artifact in ("pdf", "site", "slides"):
        for dep in kitconfig.artifact_spec(artifact).file_deps:
            resolved = kitconfig._resolve_pattern(dep, cfg)
            if resolved.startswith("style"):
                where.setdefault(resolved, []).append(artifact)
    assert where.get("style.css") == ["pdf"]
    assert where.get("style-screen.css") == ["site"]
    assert where.get("style-slides.css") == ["slides"]


def test_the_theme_name_is_validated_as_a_path_component(tmp_path):
    """`theme.name` becomes `themes/<name>/print.css`. Unconstrained, a value
    like `../../etc` would read a file outside the repository into every render."""
    base = (buildcore.ROOT / "guide.toml").read_text(encoding="utf-8")
    bad = base.replace(f'name = "{buildcore._cfg.theme.name}"', 'name = "../../etc"')
    (tmp_path / "guide.toml").write_text(bad, encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError, match="kebab-case"):
        kitconfig.load(tmp_path)


@pytest.mark.parametrize("value", [
    "red; } body { display: none }",
    "url(http://x)@import",
    # A COMMENT OPENER is as dangerous as a brace and far less obvious: `red/*`
    # comments out the generated semicolon, the closing brace, and every layer
    # that follows — the CJK rules and the guide's whole stylesheet — producing a
    # silently unstyled render rather than an error.
    "red/*",
    "*/ body { display: none } /*",
])
def test_a_token_value_that_could_escape_the_block_is_rejected(tmp_path, value):
    """`[theme.tokens]` values are emitted verbatim into `:root {}`. An unchecked
    value is a stylesheet-injection hole reachable from a config file."""
    base = (buildcore.ROOT / "guide.toml").read_text(encoding="utf-8")
    hacked = base.replace("[artifacts.pdf]",
                          f'[theme.tokens]\n"--accent" = "{value}"\n\n[artifacts.pdf]')
    (tmp_path / "guide.toml").write_text(hacked, encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError, match="plain CSS value"):
        kitconfig.load(tmp_path)


# ----- box drawing ------------------------------------------------------------

def test_box_drawing_panels_use_unit_leading():
    """At any leading above 1 the vertical bars render as short segments with
    visible gaps between rows, whatever the face: the glyph is drawn to the em box
    and extra leading inserts blank space it cannot bridge."""
    import re
    css = (buildcore.ROOT / "style.css").read_text(encoding="utf-8")
    block = re.search(r"pre\.diagram\s*\{[^}]*\}", css, re.S)
    assert block, "pre.diagram rule is gone"
    assert re.search(r"line-height:\s*1\s*;", block.group(0)), \
        f"box-drawing joins need line-height: 1 — got {block.group(0)}"


# ----- the non-print outputs depend on print.css too --------------------------

@pytest.mark.parametrize("artifact", ["site", "slides"])
def test_the_non_print_closures_include_the_theme_print_sheet(artifact):
    """`theme_css("screen", …)` LAYERS screen.css over print.css, so print.css is
    genuinely an input to the site. Left out of the closure, editing it would
    change the rendered site while its stamp claimed nothing had moved."""
    cfg = kitconfig.load(buildcore.ROOT)
    deps = [kitconfig._resolve_pattern(f, cfg)
            for f in kitconfig.artifact_spec(artifact).file_deps]
    assert f"themes/{cfg.theme.name}/print.css" in deps


def test_editing_the_theme_print_sheet_moves_the_site_hash():
    cfg = kitconfig.load(buildcore.ROOT)
    before = kitconfig.artifact_closure_hash("site", root=buildcore.ROOT)
    victim = THEMES_DIR / cfg.theme.name / "print.css"
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"\n:root { --accent: red; }\n")
        after = kitconfig.artifact_closure_hash("site", root=buildcore.ROOT)
    finally:
        victim.write_bytes(original)
    assert before != after, "the site does not notice its own theme changing"


def test_bootstrap_seeds_an_explicit_theme():
    """No guide inherits an appearance by defaulting — a guide that omits
    `[theme] name` would change the day the kit's default moves."""
    src = (buildcore.ROOT / "bootstrap.py").read_text(encoding="utf-8")
    assert "[theme]" in src and "DEFAULT_THEME" in src
