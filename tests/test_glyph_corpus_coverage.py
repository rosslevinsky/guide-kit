"""Coverage is computed over the RESOLVED CASCADE, not the fonts directory.

The predecessor unioned the cmap of every file in `fonts/`, whether or not any
CSS referred to it — its own docstring called that "a deliberate false-negative".
It is worse than conservative. A face that is bundled but unreachable covers
nothing that can appear on the page, so coverage computed that way PASSES for
characters the renderer will draw as tofu.

The difference is real and per-theme, not theoretical: under `editorial` nothing
in the cascade names "Guide Sans", so its cmap is not coverage. Measured on this
repository, the union counts 42 codepoints that no reachable face provides.
"""
import pytest

import buildcore
import cascadecheck
import kitconfig


@pytest.fixture(scope="module")
def cascade():
    return buildcore.theme_css("print", buildcore.STYLE.read_text(encoding="utf-8"))


def test_reachability_is_narrower_than_the_directory_union(cascade):
    """The whole point. If these were equal the check would be the old one under
    a new name."""
    reachable = buildcore.cascade_covered_codepoints(cascade)
    union = buildcore._covered_codepoints()
    assert reachable <= union
    assert reachable != union, (
        "cascade coverage equals the directory union — either every bundled face "
        "is reachable (make this a fixture with an unreachable one) or the "
        "reachability filter is not being applied"
    )


def test_an_unreferenced_face_contributes_no_coverage(cascade):
    """A bundled face nothing names is not coverage. Stated directly, because the
    old behaviour is a natural thing to reintroduce by accident."""
    reached = cascadecheck.reachable_families(cascade)
    all_families = cascadecheck.bundled_families(cascade)
    unreachable = all_families - reached
    assert unreachable, "need a bundled-but-unreferenced family to make this meaningful"
    # The unreachable family's codepoints must not all be present via reachability.
    assert buildcore.cascade_covered_codepoints(cascade) < buildcore._covered_codepoints()


def test_a_theme_change_changes_reachability(cascade, monkeypatch):
    """Reachability is per THEME, which is what makes it a per-guide answer."""
    before = cascadecheck.reachable_families(cascade)
    other = next(n for n in ("classic-sans", "editorial", "technical")
                 if n != buildcore._cfg.theme.name)
    theme = kitconfig.Theme(name=other)
    monkeypatch.setattr(buildcore, "_cfg",
                        type(buildcore._cfg)(**{**vars(buildcore._cfg), "theme": theme}))
    after = cascadecheck.reachable_families(
        buildcore.theme_css("print", buildcore.STYLE.read_text(encoding="utf-8")))
    assert before != after, f"{buildcore._cfg.theme.name} and {other} reach the same families"


def test_the_gate_names_the_uncovered_character(tmp_path, monkeypatch, cascade):
    """A gate whose value is recall has to say WHAT is missing, not just that
    something is."""
    monkeypatch.setattr(buildcore, "SRC", tmp_path / "guide.md")
    buildcore.SRC.write_text("A page containing 字 and nothing else.\n", encoding="utf-8")
    monkeypatch.setattr(buildcore, "cascade_covered_codepoints",
                        lambda _css: set(range(0x20, 0x7F)))
    with pytest.raises(SystemExit) as exc:
        buildcore.check_glyph_coverage(cascade)
    assert "字" in str(exc.value) or "5B57" in str(exc.value).upper()


def test_the_gate_refuses_when_the_cascade_reaches_nothing(monkeypatch):
    """An empty reachable set is not "everything is fine" — it means the render
    would fall through to whatever the host has."""
    monkeypatch.setattr(buildcore, "cascade_covered_codepoints", lambda _css: set())
    with pytest.raises(SystemExit, match="reaches NO bundled face"):
        buildcore.check_glyph_coverage("/* empty cascade */")


def test_the_real_guide_is_fully_covered(cascade):
    """The shipping check: every codepoint the kit's own guide puts on the page
    is provided by a face the cascade reaches."""
    buildcore.check_glyph_coverage(cascade)   # must not raise


# ----- the rendered box tree --------------------------------------------------

def test_the_rendered_families_are_all_bundled(cascade):
    """The output-side counterpart. This reads what WeasyPrint COMPUTED — after
    the cascade, inheritance and every var() substitution — so a family that
    reached the page by a route no static check anticipated still shows up.

    STATED LIMIT: this proves a FAMILY, not a FACE."""
    pytest.importorskip("weasyprint")
    import render_pdf
    from weasyprint import HTML

    document = HTML(string=render_pdf.render_html(),
                    base_url=str(buildcore.ROOT)).render()
    buildcore.check_rendered_families(document, cascade)   # must not raise


def test_the_box_tree_check_catches_an_unbundled_family(cascade):
    """Fails for the right reason: a document that asks for Georgia resolves to
    Georgia in the box tree, whatever the stylesheets say."""
    pytest.importorskip("weasyprint")
    from weasyprint import HTML

    html = "<html><body style='font-family: Georgia'><p>x</p></body></html>"
    document = HTML(string=html, base_url=str(buildcore.ROOT)).render()
    with pytest.raises(SystemExit, match="Georgia"):
        buildcore.check_rendered_families(document, cascade)


def test_the_box_tree_check_sees_a_family_reached_only_by_inheritance(cascade):
    """The case the override guard cannot reach: no element names Georgia
    directly — a child inherits it from an ancestor."""
    pytest.importorskip("weasyprint")
    from weasyprint import HTML

    html = ("<html><body style='font-family: Georgia'>"
            "<div><section><p>inherited</p></section></div></body></html>")
    document = HTML(string=html, base_url=str(buildcore.ROOT)).render()
    with pytest.raises(SystemExit, match="Georgia"):
        buildcore.check_rendered_families(document, cascade)
