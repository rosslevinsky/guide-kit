"""The per-artifact dependency closure contract.

Three founding problems motivate this file. Outputs were inferred from the
filesystem; one `SOURCE_FILES` list served six different consumers; and one
stamp covered one artifact, so adding slides would have re-staled the PDF. An
`ArtifactSpec` states, per artifact: the CONFIG KEYS it depends on (key-level,
so a `[deploy]` edit cannot reach the PDF), its file and glob dependencies, its
generated dependency edges, its stamp/date/dirty rules, where its reference
artifact lives, and what `release.py` may stage for it.

The date-isolation property is asserted **on rendered bytes, reciprocally** —
not on a closure hash. A closure hash alone would pass while the stamp moved,
which is exactly the under-specification this file exists to rule out.
"""
import pytest

import kitconfig
import verify_artifacts
from conftest import render


_MINIMAL_TOML = (
    'TITLE = "Probe"\n'
    'OUTPUT_SLUG = "probe-guide"\n'
    'AUTHOR = "A"\n'
    'DESCRIPTION = "d"\n'
    'KEYWORDS = "k"\n'
    'COPYRIGHT_YEAR = 2026\n'
    "[outputs]\n"
    "pdf = true\n"
    'site = "none"\n'
    "slides = false\n"
    "[artifacts.pdf]\n"
    'date = "2026-07-26"\n'
)


class _CfgStub:
    """Minimal stand-in for a KitConfig where only the placeholder-resolving
    fields matter, so a pathspec assertion needs no temp directory."""
    OUTPUT_SLUG = "probe-guide"
    slides = kitconfig.SlidesConfig()
    # `<theme>` is the third placeholder the resolver substitutes: the selected
    # theme's sheet is in the closure, an unselected one is not.
    theme = kitconfig.Theme()


_CFG_FOR_PATHSPEC = _CfgStub()


def _write_minimal(tmp_path):
    (tmp_path / "guide.toml").write_text(_MINIMAL_TOML, encoding="utf-8")
    return tmp_path


def test_every_declared_artifact_has_a_spec():
    for name in kitconfig.ARTIFACT_NAMES:
        spec = kitconfig.artifact_spec(name)
        assert spec.name == name
        # (a) config keys, (b) file deps, (d) stamp rule, (f) release staging
        # are meaningful for every artifact; (c) generated edges and (e) a
        # committed reference are per-artifact and may legitimately be empty.
        assert spec.config_keys, f"{name}: no config keys declared"
        assert spec.file_deps, f"{name}: no file dependencies declared"
        assert spec.stamp is not None
        assert spec.release_staging, f"{name}: no release staging policy declared"


def test_unknown_artifact_rejected():
    with pytest.raises(kitconfig.KitConfigError, match="nope"):
        kitconfig.artifact_spec("nope")


# ----- (a) config keys are KEY-LEVEL, not whole-file ------------------------

def test_deploy_and_hub_keys_are_absent_from_the_pdf_closure():
    # The whole point of key-level config dependencies: hashing all of
    # guide.toml would put [deploy] and [hub] edits into the PDF closure.
    keys = kitconfig.artifact_spec("pdf").config_keys
    assert not [k for k in keys if k.startswith(("deploy.", "hub.", "site.", "slides."))]
    # ...while the identity keys that genuinely reach the page ARE present.
    for expected in ("TITLE", "AUTHOR", "COPYRIGHT_YEAR", "theme.name"):
        assert expected in keys


def test_date_key_sits_in_exactly_one_artifact_closure():
    for name in kitconfig.ARTIFACT_NAMES:
        own = f"artifacts.{name}.date"
        assert own in kitconfig.artifact_spec(name).config_keys
        for other in kitconfig.ARTIFACT_NAMES:
            if other == name:
                continue
            assert own not in kitconfig.artifact_spec(other).config_keys, (
                f"{own} leaked into the {other} closure"
            )


def test_closure_hash_ignores_out_of_closure_config_edits(guide_repo):
    root, write_toml = guide_repo
    before = kitconfig.artifact_closure_hash("pdf", root=root)

    write_toml(deploy={"domain": "guide.example.com"})
    assert kitconfig.artifact_closure_hash("pdf", root=root) == before

    write_toml(hub={"registry": "other.toml"})
    assert kitconfig.artifact_closure_hash("pdf", root=root) == before

    # ...but an in-closure key still moves it, or the hash proves nothing.
    write_toml(TITLE="Renamed")
    assert kitconfig.artifact_closure_hash("pdf", root=root) != before


def test_closure_hash_is_insensitive_to_writing_a_default_explicitly(guide_repo):
    # The projection hashes EFFECTIVE values, so a config that omits an optional
    # key hashes identically to one that spells out the same default. Otherwise
    # a purely cosmetic config edit would re-stale a reference PDF.
    root, write_toml = guide_repo
    before = kitconfig.artifact_closure_hash("pdf", root=root)
    write_toml(theme={"name": kitconfig.DEFAULT_THEME})
    assert kitconfig.artifact_closure_hash("pdf", root=root) == before


# ----- (b)/(c)/(e)/(f) the remaining facets ---------------------------------

def test_style_screen_is_in_the_site_closure_only():
    # The predecessor excluded style-screen.css from SOURCE_FILES precisely so a
    # screen edit could not stale the PDF. That property is now expressed as
    # closure membership rather than as an omission from a single global list.
    assert "style-screen.css" in kitconfig.artifact_spec("site").file_deps
    assert "style-screen.css" not in kitconfig.artifact_spec("pdf").file_deps
    assert "style.css" in kitconfig.artifact_spec("pdf").file_deps


def test_site_declares_the_released_pdf_as_a_generated_edge():
    # "The site contains the released PDF" is a real dependency edge and is
    # declared as one, rather than being discovered when the site ships a 404.
    assert kitconfig.artifact_spec("site").generated_deps == ("<slug>.pdf",)
    assert kitconfig.artifact_spec("pdf").generated_deps == ()


def test_reference_artifact_location_is_declared():
    assert kitconfig.artifact_spec("pdf").reference == "<slug>.pdf"
    # The site has no committed reference artifact — it is deployed, not blessed.
    assert kitconfig.artifact_spec("site").reference is None


def test_authorable_sources_are_not_any_one_closure(tmp_path):
    # The union that drives release.py's staging policy is defined SEPARATELY
    # from the PDF closure; conflating them is what made one list serve six
    # consumers.
    union = set(kitconfig.AUTHORABLE_SOURCES)
    pdf_files = set(kitconfig.artifact_spec("pdf").file_deps)
    assert "guide.toml" in union
    assert "style-screen.css" in union
    assert union != pdf_files
    # Compared against the RESOLVED union for a real config, since a spec may
    # carry a config-derived placeholder (the slides source file).
    cfg = kitconfig.load(_write_minimal(tmp_path))
    resolved_union = set(kitconfig.authorable_sources(cfg))
    for name in kitconfig.ARTIFACT_NAMES:
        authorable = {
            kitconfig._resolve_pattern(f, cfg)
            for f in kitconfig.artifact_spec(name).file_deps if "*" not in f
        }
        assert authorable <= resolved_union, (
            f"{name} has file deps outside the authorable union"
        )


# ----- The date-isolation property, on rendered BYTES, reciprocally ---------

def _pdftotext(pdf) -> str:
    import subprocess
    return subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True,
                          text=True, check=True).stdout


def _stamp(pdf):
    """(hash, dirty) as the promotion path reads it."""
    return verify_artifacts.read_stamp(pdf)


def test_bumping_the_site_date_leaves_the_pdf_byte_identical(guide_repo):
    root, write_toml = guide_repo
    render(root)
    pdf = root / "build" / "probe-guide.pdf"
    before_bytes = pdf.read_bytes()
    before_stamp = _stamp(pdf)

    write_toml(artifacts={"site": {"date": "2027-01-01"}})
    render(root)

    assert pdf.read_bytes() == before_bytes, "a site-only date bump moved the PDF's bytes"
    assert _stamp(pdf) == before_stamp
    assert kitconfig.load(root).artifacts["pdf"].date == "2026-07-26"


def test_bumping_the_pdf_date_leaves_the_site_byte_identical(guide_repo):
    root, write_toml = guide_repo
    render(root)
    # build_web hard-fails without a reference PDF, so promote the working
    # render exactly as `make baseline` would.
    (root / "probe-guide.pdf").write_bytes((root / "build" / "probe-guide.pdf").read_bytes())
    render(root, "--web")
    index = root / "app" / "dist" / "index.html"
    before = index.read_bytes()

    write_toml(artifacts={"pdf": {"date": "2027-01-01"}})
    render(root, "--web")

    assert index.read_bytes() == before, "a PDF-only date bump moved the site's bytes"
    assert kitconfig.load(root).artifacts["site"].date == "2026-07-26"


def test_an_in_closure_edit_does_move_the_pdf(guide_repo):
    # The negative control for the two tests above: if nothing could move the
    # bytes, their byte-identity assertions would be vacuous.
    root, write_toml = guide_repo
    render(root)
    pdf = root / "build" / "probe-guide.pdf"
    before = pdf.read_bytes()

    write_toml(TITLE="A Different Title")
    render(root)
    assert pdf.read_bytes() != before


# ----- Defects found by cross-model review ---------------------------------

def test_font_glob_matching_is_case_insensitive(tmp_path):
    # is_stamp_input() and font_files() have always compared suffixes
    # case-folded. A case-SENSITIVE closure glob therefore accepts
    # fonts/Face.TTF as a watched stamp input while omitting its bytes from the
    # hash: a face swap that moves the render and not the stamp.
    (tmp_path / "guide.toml").write_text(_MINIMAL_TOML, encoding="utf-8")
    fonts = tmp_path / "fonts" / "vendor"
    fonts.mkdir(parents=True, exist_ok=True)
    (fonts / "Face.TTF").write_bytes(b"upper-suffix-face")

    assert kitconfig.is_stamp_input("fonts/vendor/Face.TTF")
    before = kitconfig.artifact_closure_hash("pdf", root=tmp_path)
    (fonts / "Face.TTF").write_bytes(b"upper-suffix-face-CHANGED")
    assert kitconfig.artifact_closure_hash("pdf", root=tmp_path) != before, (
        "a face with an uppercase suffix is watched but not hashed"
    )


def test_closure_hash_frames_its_records(tmp_path):
    # Unframed `name + bytes` concatenation lets two different closures present
    # the same byte stream: a file named `a.otf` containing `x.otf`, versus an
    # empty file named `a.otfx.otf`.
    (tmp_path / "guide.toml").write_text(_MINIMAL_TOML, encoding="utf-8")
    fonts = tmp_path / "fonts" / "vendor"
    fonts.mkdir(parents=True, exist_ok=True)
    (fonts / "a.otf").write_bytes(b"x.otf")
    first = kitconfig.artifact_closure_hash("pdf", root=tmp_path)

    (fonts / "a.otf").unlink()
    (fonts / "a.otfx.otf").write_bytes(b"")
    assert kitconfig.artifact_closure_hash("pdf", root=tmp_path) != first


def test_slides_closure_follows_the_configured_source_file(tmp_path):
    # With source = "file" and file = "deck.md", a hardcoded slides.md leaves
    # the real source outside the closure, so deck.md edits never re-stale it.
    toml = _MINIMAL_TOML.replace(
        "[artifacts.pdf]",
        'slides = true\n[slides]\nsource = "file"\nfile = "deck.md"\n[artifacts.slides]\n'
        'date = "2026-07-26"\n[artifacts.pdf]',
    ).replace("slides = false\n", "")
    (tmp_path / "guide.toml").write_text(toml, encoding="utf-8")
    (tmp_path / "deck.md").write_text("# deck\n", encoding="utf-8")

    assert "deck.md" in kitconfig.authorable_sources(kitconfig.load(tmp_path))
    before = kitconfig.artifact_closure_hash("slides", root=tmp_path)
    (tmp_path / "deck.md").write_text("# deck, edited\n", encoding="utf-8")
    assert kitconfig.artifact_closure_hash("slides", root=tmp_path) != before


@pytest.mark.parametrize("evil", ["../outside.md", "/etc/passwd", "a/../../b.md"])
def test_slides_file_escaping_the_repo_is_rejected(tmp_path, evil):
    toml = _MINIMAL_TOML.replace(
        "[artifacts.pdf]",
        f'slides = true\n[slides]\nsource = "file"\nfile = "{evil}"\n'
        '[artifacts.slides]\ndate = "2026-07-26"\n[artifacts.pdf]',
    ).replace("slides = false\n", "")
    (tmp_path / "guide.toml").write_text(toml, encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError, match="file"):
        kitconfig.load(tmp_path)


def test_content_pathspec_excludes_guide_toml_but_stamp_pathspec_includes_it():
    # The DATE asks "when did this artifact's content last change", and git
    # cannot scope to a config key — so including guide.toml whole would let a
    # committed [deploy]-only edit move the date of a PDF that did not change.
    assert ":(literal)guide.toml" in kitconfig.stamp_pathspec("pdf")
    assert ":(literal)guide.toml" not in kitconfig.content_pathspec("pdf")
    assert ":(literal)style.css" in kitconfig.content_pathspec("pdf")


def test_stamp_pathspec_is_per_artifact():
    assert ":(literal)style-screen.css" in kitconfig.stamp_pathspec("site")
    assert ":(literal)style-screen.css" not in kitconfig.stamp_pathspec("pdf")
    assert ":(literal)style.css" in kitconfig.stamp_pathspec("pdf")
    assert ":(literal)style.css" not in kitconfig.stamp_pathspec("site")


# ----- Defects found by cross-model RE-review ------------------------------

def test_stamp_pathspec_covers_generated_dependency_edges():
    # The site's closure hash includes the released PDF it embeds, so the guards
    # must watch it too. Scoped to file_deps alone, an uncommitted re-baseline
    # moves the site's hash while its stamp still claims clean.
    cfg_spec = kitconfig.artifact_spec("site")
    assert cfg_spec.generated_deps == ("<slug>.pdf",)
    paths = kitconfig.stamp_pathspec("site", _CFG_FOR_PATHSPEC)
    assert ":(literal)probe-guide.pdf" in paths


def test_pathspec_entries_are_literal_so_config_cannot_inject_magic(tmp_path):
    # A [slides] file of ":!guide.md" would otherwise be parsed by git as an
    # EXCLUSION, silently dropping guide.md from the date and dirty checks while
    # it stayed in the hashed closure.
    with pytest.raises(kitconfig.KitConfigError, match="pathspec magic"):
        toml = _MINIMAL_TOML.replace(
            "[artifacts.pdf]",
            'slides = true\n[slides]\nfile = ":!guide.md"\n[artifacts.slides]\n'
            'date = "2026-07-26"\n[artifacts.pdf]',
        ).replace("slides = false\n", "")
        (tmp_path / "guide.toml").write_text(toml, encoding="utf-8")
        kitconfig.load(tmp_path)

    # ...and every emitted literal is magic-proofed regardless.
    assert all(
        p.startswith((":(literal)", ":(glob,icase)"))
        for p in kitconfig.stamp_pathspec("pdf")
    )


@pytest.mark.parametrize("evil", ["..\\..\\x.md", "C:\\x.md", "\\\\server\\share\\x.md"])
def test_windows_shaped_slides_paths_are_rejected(tmp_path, evil):
    # pixi.toml declares win-64, so a POSIX-only check is not enough:
    # PurePosixPath sees no ".." part in "..\\..\\x" and C:\x is not absolute.
    toml = _MINIMAL_TOML.replace(
        "[artifacts.pdf]",
        f'slides = true\n[slides]\nfile = "{evil}"\n[artifacts.slides]\n'
        'date = "2026-07-26"\n[artifacts.pdf]',
    ).replace("slides = false\n", "")
    (tmp_path / "guide.toml").write_text(toml.replace("\\", "\\\\"), encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError, match="file"):
        kitconfig.load(tmp_path)


# ----- The stage-boundary test ----------------------------------------------
#
# The split's whole promise, asserted rather than argued: once build.py is split,
# a change belonging to a LATER stage must not move the PDF by one byte. Later
# stages are deferred, so they cannot supply these fixtures — this phase defines
# them synthetically, which is the only way the promise is checkable now rather
# than after the fact.
#
# Asserted on bytes, parsed stamp AND the authored date together. A closure-hash
# comparison alone would pass while the stamp moved — the gap this asserts shut.

def _append(path, text):
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_BOUNDARY_FIXTURES = [
    # [deploy] — a domain the PDF never renders
    ("deploy-only config edit",
     lambda root, write_toml: write_toml(deploy={"domain": "guide.example.com"})),
    # [hub] — the family index's own keys
    ("hub-only config edit",
     lambda root, write_toml: write_toml(hub={"registry": "other-registry.toml"})),
    # The site RENDERER itself — the file the build.py split created
    ("site renderer edit",
     lambda root, _: _append(root / "render_site.py", "\n# stage-boundary probe\n")),
    ("screen stylesheet edit",
     lambda root, _: _append(root / "style-screen.css", "\n/* stage-boundary probe */\n")),
    # The deck — both its stylesheet and its independent source path
    ("slides stylesheet addition",
     lambda root, _: _write(root / "style-slides.css", "/* stage-boundary probe */\n")),
    ("slides source addition",
     lambda root, _: _write(root / "slides.md", "# Deck\n\nA slide.\n")),
    # Assets — a declared directory in one output's closure only
    ("asset directory addition",
     lambda root, _: _write(root / "assets" / "diagram.svg", '<svg viewBox="0 0 1 1"></svg>\n')),
]


@pytest.mark.parametrize(
    "label,mutate", _BOUNDARY_FIXTURES, ids=[f[0] for f in _BOUNDARY_FIXTURES]
)
def test_pdf_is_frozen_under_later_stage_changes(guide_repo, label, mutate):
    root, write_toml = guide_repo
    render(root)
    pdf = root / "build" / "probe-guide.pdf"
    before_bytes = pdf.read_bytes()
    before_stamp = _stamp(pdf)
    before_date = kitconfig.load(root).artifacts["pdf"].date

    mutate(root, write_toml)
    render(root)

    assert pdf.read_bytes() == before_bytes, f"{label} moved the PDF's BYTES"
    assert _stamp(pdf) == before_stamp, f"{label} moved the PDF's parsed STAMP"
    assert kitconfig.load(root).artifacts["pdf"].date == before_date, (
        f"{label} moved [artifacts.pdf] date"
    )


def test_the_boundary_test_can_actually_fail(guide_repo):
    """The negative control. Without this, all seven cases above would pass just
    as well against a build that ignored its inputs entirely."""
    root, _ = guide_repo
    render(root)
    pdf = root / "build" / "probe-guide.pdf"
    before = pdf.read_bytes()

    _append(root / "render_pdf.py", "\n# in the PDF's closure, unlike render_site.py\n")
    render(root)
    assert pdf.read_bytes() != before, "a render_pdf.py edit must move the PDF"


# ----- Execution isolation, not just hash membership -----------------------
#
# The boundary fixtures above append a comment, which proves the CLOSURE is
# right but says nothing about whether the PDF build can be affected by the
# site's code at run time. Those are different claims: `build.py` importing
# render_site unconditionally would keep every fixture above green while a
# broken render_site.py still broke `python build.py`.

def test_a_broken_site_renderer_cannot_break_the_pdf_build(guide_repo):
    root, _ = guide_repo
    render(root)
    pdf = root / "build" / "probe-guide.pdf"
    before = pdf.read_bytes()

    # Not a comment this time — make the module genuinely unimportable.
    (root / "render_site.py").write_text(
        "raise RuntimeError('the site renderer is broken')\n", encoding="utf-8"
    )

    render(root)          # must still succeed
    assert pdf.read_bytes() == before, (
        "a broken site renderer changed the PDF; the closure claims it cannot"
    )


def test_a_broken_pdf_renderer_does_break_the_pdf_build(guide_repo):
    """The mirror image, so the test above cannot pass by the PDF build simply
    ignoring every renderer."""
    root, _ = guide_repo
    (root / "render_pdf.py").write_text(
        "raise RuntimeError('the pdf renderer is broken')\n", encoding="utf-8"
    )
    # Match the INJECTED failure, not the helper's generic "build.py … failed"
    # boilerplate — otherwise any unrelated subprocess failure occurring before
    # render_pdf is even imported would satisfy this.
    with pytest.raises(AssertionError, match="the pdf renderer is broken"):
        render(root)


def test_a_broken_pdf_renderer_cannot_break_the_site_build(guide_repo):
    """And the reciprocal: the site does not depend on the PDF renderer either.
    It embeds the committed reference PDF; it never renders one."""
    root, _ = guide_repo
    render(root)
    (root / "probe-guide.pdf").write_bytes((root / "build" / "probe-guide.pdf").read_bytes())
    render(root, "--web")
    before = (root / "app" / "dist" / "index.html").read_bytes()

    (root / "render_pdf.py").write_text(
        "raise RuntimeError('the pdf renderer is broken')\n", encoding="utf-8"
    )
    render(root, "--web")
    assert (root / "app" / "dist" / "index.html").read_bytes() == before


def test_negative_control_reaches_rendered_content_not_just_the_stamp(guide_repo):
    """A stronger negative control than appending a comment.

    Appending to render_pdf.py moves the closure hash, so the PDF's bytes change
    even if that module were never executed — which means the weaker control
    would pass against a build that ignored its own renderer. This one changes
    text the renderer PUTS ON THE PAGE, so it can only pass if render_pdf.py is
    genuinely the code doing the rendering."""
    root, _ = guide_repo
    render(root)
    pdf = root / "build" / "probe-guide.pdf"
    # A phrase render_pdf.py's colophon emits, short enough not to be split
    # across lines by pdftotext's wrapping.
    anchor, replacement = "This guide is licensed", "This manual is licensed"
    assert anchor in _pdftotext(pdf)

    src = (root / "render_pdf.py").read_text(encoding="utf-8")
    assert anchor in src, "colophon text is not where this test expects it"
    (root / "render_pdf.py").write_text(src.replace(anchor, replacement), encoding="utf-8")

    render(root)
    text = _pdftotext(pdf)
    assert replacement in text, "render_pdf.py's colophon text never reached the page"
    assert anchor not in text


def test_a_declared_but_UNIMPLEMENTED_site_shape_is_refused(tmp_path, monkeypatch):
    """`SITE_SHAPES` is a roadmap; `IMPLEMENTED_SITE_SHAPES` is today.

    `SITE_SHAPES` is deliberately wider than what `build_web()` dispatches on —
    `app` names an externally-built SPA the kit only deploys. Before the refusal
    existed, `site = "multipage"` validated and then silently rendered a SINGLE
    page. A config value that passes validation
    and means something other than what it says is exactly the failure this
    schema exists to remove, so an unimplemented shape now refuses by name.
    """
    import kitconfig
    import render_site

    assert set(kitconfig.IMPLEMENTED_SITE_SHAPES) < set(kitconfig.SITE_SHAPES), \
        "if every declared shape is implemented, this guard has become unnecessary"

    for shape in set(kitconfig.SITE_SHAPES) - set(kitconfig.IMPLEMENTED_SITE_SHAPES):
        class _Outputs:
            site = shape
            declared = ("pdf", "site")

        class _Cfg:
            outputs = _Outputs()

        monkeypatch.setattr(kitconfig, "load", lambda _root=None, _c=_Cfg: _c())
        with pytest.raises(SystemExit) as exc:
            render_site.build_web()
        assert shape in str(exc.value), f"the refusal does not name {shape!r}"
        assert "does not implement" in str(exc.value)
