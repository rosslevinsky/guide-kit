"""The strict guide.toml loader (kitconfig.load) validates rather than trusts.

Covers every rule it enforces: required keys present, correct types, kebab-case
OUTPUT_SLUG, integer COPYRIGHT_YEAR, and slug values that would escape the repo
root. Runs on stdlib only (no pandoc/WeasyPrint).
"""
import pytest

import kitconfig

VALID = {
    "TITLE": "Guide Template",
    "OUTPUT_SLUG": "guide-template",
    "AUTHOR": "Ross Levinsky",
    "DESCRIPTION": "A description with a colon: and a url https://example.com/",
    "KEYWORDS": "guide, template, pandoc",
    "COPYRIGHT_YEAR": 2026,
    # Declared shape + the per-artifact authored edition date. Both REQUIRED:
    # outputs is what kitmanifest resolves against instead of probing the
    # filesystem, and every declared output must carry its own date.
    "outputs": {"pdf": True, "site": "none", "slides": False},
    "artifacts": {"pdf": {"date": "2026-07-26"}},
}


def _scalar(v) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_scalar(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _dump(d: dict) -> str:
    """Serialize a nested dict to TOML: scalars first, then [table] and
    [table.sub] sections, so the result parses regardless of dict order."""
    lines = [f"{k} = {_scalar(v)}" for k, v in d.items() if not isinstance(v, dict)]
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        scalars = {kk: vv for kk, vv in v.items() if not isinstance(vv, dict)}
        subs = {kk: vv for kk, vv in v.items() if isinstance(vv, dict)}
        if scalars or not subs:
            lines.append(f"[{k}]")
            lines += [f"{kk} = {_scalar(vv)}" for kk, vv in scalars.items()]
        for kk, vv in subs.items():
            lines.append(f"[{k}.{kk}]")
            lines += [f"{k2} = {_scalar(v2)}" for k2, v2 in vv.items()]
    return "\n".join(lines) + "\n"


def _write(tmp_path, d: dict):
    (tmp_path / "guide.toml").write_text(_dump(d), encoding="utf-8")
    return tmp_path


def test_valid_config_loads(tmp_path):
    c = kitconfig.load(root=_write(tmp_path, VALID))
    assert c.TITLE == "Guide Template"
    assert c.OUTPUT_SLUG == "guide-template"
    assert c.AUTHOR == "Ross Levinsky"
    assert c.KEYWORDS == "guide, template, pandoc"
    assert c.COPYRIGHT_YEAR == 2026


def test_missing_guide_toml_rejected(tmp_path):
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=tmp_path)


@pytest.mark.parametrize("missing", list(VALID))
def test_missing_key_rejected(tmp_path, missing):
    d = dict(VALID)
    d.pop(missing)
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


def test_year_must_be_integer(tmp_path):
    d = dict(VALID)
    d["COPYRIGHT_YEAR"] = "2026"  # string, not int
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


def test_year_bool_rejected(tmp_path):
    d = dict(VALID)
    d["COPYRIGHT_YEAR"] = True  # bool is an int subclass — must be rejected
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


def test_title_must_be_string(tmp_path):
    d = dict(VALID)
    d["TITLE"] = 5
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


@pytest.mark.parametrize("bad", ["Guide_Template", "-guide", "guide-", "UPPER", "has space", "under_score"])
def test_non_kebab_slug_rejected(tmp_path, bad):
    d = dict(VALID)
    d["OUTPUT_SLUG"] = bad
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


@pytest.mark.parametrize("ok", ["a1", "guide-template", "g2g", "windows-cmd-guide"])
def test_valid_slugs_accepted(tmp_path, ok):
    d = dict(VALID)
    d["OUTPUT_SLUG"] = ok
    assert kitconfig.load(root=_write(tmp_path, d)).OUTPUT_SLUG == ok


@pytest.mark.parametrize("evil", ["../../x", "../escape", "a/../../b"])
def test_slug_escaping_repo_root_rejected(tmp_path, evil):
    d = dict(VALID)
    d["OUTPUT_SLUG"] = evil
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


def test_slug_with_trailing_newline_rejected(tmp_path):
    # A TOML escaped `\n` decodes to a real newline; regex `$` (with .match())
    # matches just before a trailing newline, so this must be rejected by the
    # .fullmatch() anchor — else OUTPUT_SLUG yields a filename with an embedded
    # newline. Write the raw TOML so tomllib decodes the escape (the _dump helper
    # would instead emit an invalid multi-line basic string).
    rest = _dump({k: v for k, v in VALID.items() if k != "OUTPUT_SLUG"})
    text = 'OUTPUT_SLUG = "guide-template\\n"\n' + rest
    (tmp_path / "guide.toml").write_text(text, encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=tmp_path)


def test_source_files_exact_contract():
    # Pin the exact SET. Order is no longer part of the contract: the closure
    # hash sorts its inputs by repo-relative path rather than concatenating in
    # list order, so a reorder is not a change to the hash input. Membership
    # still is, and this fails by name if an entry appears or disappears.
    assert kitconfig.SOURCE_FILES == sorted([
        "build.py",
        "buildcore.py",
        # The cascade guard: buildcore imports it during rendering, and a change
        # to what it accepts changes what can reach the page.
        "cascadecheck.py",
        # A render input like any other: it decides which font each family
        # resolves to, so editing or deleting it changes the rendered bytes.
        "fontconfig/fonts.conf",
        # The bundled @font-face declarations — kit-owned, and a render input for
        # every artifact.
        "fontfaces.css",
        # The font provenance record. `buildcore._assert_font_provenance` reads
        # it on every build and REFUSES to render on a hash mismatch, so it gates
        # the render as surely as any stylesheet. It was outside the closure
        # until the boundary review found that: deleting it silently disabled the
        # gate (the check returns early when the record is absent) while
        # `make verify` stayed green.
        "fonts/vendor/UPSTREAM-HASHES.json",
        "guide.md",
        "guide.toml",
        "kitconfig.py",
        "render_pdf.py",
        "style.css",
        # The SELECTED theme's print tokens. Resolved from `[theme] name`, so an
        # unselected theme is not here and cannot stale the reference.
        f"themes/{kitconfig.DEFAULT_THEME}/print.css",
        "transforms.py",
    ])
    # render_site.py and render_slides.py are deliberately ABSENT: they are the
    # whole point of the split, and if either appeared here a website or slides
    # edit would re-stale every reference PDF again.
    assert "render_site.py" not in kitconfig.SOURCE_FILES
    assert "render_slides.py" not in kitconfig.SOURCE_FILES
    # ...and it is exactly the PDF closure's authorable half, derived rather
    # than hand-maintained alongside it.
    # Placeholders resolved on BOTH sides, exactly as SOURCE_FILES derives itself:
    # the spec holds `themes/<theme>/print.css` and the derived list holds the
    # selected theme, so comparing raw against resolved would always differ.
    assert set(kitconfig.SOURCE_FILES) == (
        {kitconfig._with_defaults(f)
         for f in kitconfig.artifact_spec("pdf").file_deps if "*" not in f}
        | {"guide.toml"}
    )


def test_content_hash_covers_every_source_file(tmp_path):
    # Every file in the PDF's closure must feed the hash. guide.toml is excluded
    # from the byte loop and exercised separately below, because it now reaches
    # the hash key-level: it is parsed, and appended bytes are simply invalid
    # TOML rather than a different input.
    (tmp_path / "guide.toml").write_text(_dump(VALID), encoding="utf-8")
    byte_deps = [n for n in kitconfig.SOURCE_FILES if n != "guide.toml"]
    for name in byte_deps:
        # SOURCE_FILES contains a nested path (fontconfig/fonts.conf).
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(f"init-{name}", encoding="utf-8")

    baseline = kitconfig.content_hash(root=tmp_path)
    assert len(baseline) == 12
    assert kitconfig.content_hash(root=tmp_path) == baseline  # deterministic

    for name in byte_deps:
        p = tmp_path / name
        original = p.read_text(encoding="utf-8")
        p.write_text(original + "X", encoding="utf-8")
        assert kitconfig.content_hash(root=tmp_path) != baseline, f"{name} not covered by hash"
        p.write_text(original, encoding="utf-8")  # restore
        assert kitconfig.content_hash(root=tmp_path) == baseline

    # guide.toml, key-level: an in-closure key moves it, an out-of-closure one
    # does not. Both directions, or the projection proves nothing.
    (tmp_path / "guide.toml").write_text(_dump({**VALID, "TITLE": "Renamed"}), encoding="utf-8")
    assert kitconfig.content_hash(root=tmp_path) != baseline

    (tmp_path / "guide.toml").write_text(
        _dump({**VALID, "deploy": {"domain": "x.example.com"}}), encoding="utf-8"
    )
    assert kitconfig.content_hash(root=tmp_path) == baseline


# ---------------------------------------------------------------------------
# Stage 0 — declared shape: [outputs] / [theme] / [site] / [slides] / [fonts] /
# [deploy] / [hub] / [artifacts.*] / [kit].
#
# The loader VALIDATES rather than trusts, so every table below is checked for
# unknown keys and out-of-enum values with a NAMED error — a stale key must fail
# loudly rather than silently do nothing.
# ---------------------------------------------------------------------------

def _load(tmp_path, d):
    return kitconfig.load(root=_write(tmp_path, d))


def test_declared_shape_defaults(tmp_path):
    c = _load(tmp_path, VALID)
    assert c.outputs.pdf is True
    assert c.outputs.site == "none"
    assert c.outputs.slides is False
    # Every optional table has a default, so a minimal config is legal.
    assert c.theme.name == kitconfig.DEFAULT_THEME
    assert c.site.chapter_level == 1
    assert c.slides.source == "auto"
    assert c.fonts.cjk == ()
    assert c.deploy.domain == ""
    assert c.kit.min_version == ""


def test_unknown_top_level_key_rejected(tmp_path):
    d = dict(VALID)
    d["NOT_A_KEY"] = "x"
    with pytest.raises(kitconfig.KitConfigError, match="NOT_A_KEY"):
        _load(tmp_path, d)


def test_release_table_rejected_as_unknown(tmp_path):
    # Publication always happens in the guide's own repository, so nothing
    # about it is user-configurable. [release] is absent from the schema
    # ENTIRELY, so a stale config cannot silently do nothing.
    d = dict(VALID)
    d["release"] = {"mode": "split", "mirror": "owner/public"}
    with pytest.raises(kitconfig.KitConfigError, match="release"):
        _load(tmp_path, d)


@pytest.mark.parametrize("table", ["outputs", "theme", "site", "slides", "fonts", "deploy", "hub", "kit"])
def test_unknown_key_inside_table_rejected(tmp_path, table):
    d = dict(VALID)
    d[table] = dict(d.get(table, {}))
    d[table]["bogus_key"] = "x"
    with pytest.raises(kitconfig.KitConfigError, match="bogus_key"):
        _load(tmp_path, d)


@pytest.mark.parametrize("bad", ["yes", "web", "single-page", "MULTIPAGE", ""])
def test_outputs_site_out_of_enum_rejected(tmp_path, bad):
    d = dict(VALID)
    d["outputs"] = {**VALID["outputs"], "site": bad}
    with pytest.raises(kitconfig.KitConfigError, match="site"):
        _load(tmp_path, d)


@pytest.mark.parametrize("ok", ["none", "single", "multipage", "app", "hub"])
def test_outputs_site_enum_accepted(tmp_path, ok):
    d = dict(VALID)
    d["outputs"] = {**VALID["outputs"], "site": ok}
    if ok != "none":
        # Declaring the output obliges the matching artifact table.
        d["artifacts"] = {"pdf": {"date": "2026-07-26"}, "site": {"date": "2026-07-26"}}
    assert _load(tmp_path, d).outputs.site == ok


def test_outputs_pdf_must_be_bool(tmp_path):
    d = dict(VALID)
    d["outputs"] = {**VALID["outputs"], "pdf": "true"}
    with pytest.raises(kitconfig.KitConfigError, match="pdf"):
        _load(tmp_path, d)


@pytest.mark.parametrize("bad", ["ja", "JP", "cn", "zh"])
def test_fonts_cjk_out_of_enum_rejected(tmp_path, bad):
    d = dict(VALID)
    d["fonts"] = {"cjk": [bad]}
    with pytest.raises(kitconfig.KitConfigError, match="cjk"):
        _load(tmp_path, d)


def test_fonts_cjk_accepts_a_list_of_locales(tmp_path):
    # Han unification means the same codepoint must select a different face per
    # locale, so this is an ordered list of language selectors, not a boolean.
    d = dict(VALID)
    d["fonts"] = {"cjk": ["jp", "tc"]}
    assert _load(tmp_path, d).fonts.cjk == ("jp", "tc")


def test_fonts_cjk_rejects_a_bare_boolean(tmp_path):
    d = dict(VALID)
    d["fonts"] = {"cjk": True}
    with pytest.raises(kitconfig.KitConfigError, match="cjk"):
        _load(tmp_path, d)


@pytest.mark.parametrize("bad", ["file", "markdown", "GUIDE", ""])
def test_slides_source_out_of_enum_rejected(tmp_path, bad):
    d = dict(VALID)
    d["outputs"] = {**VALID["outputs"], "slides": True}
    d["artifacts"] = {"pdf": {"date": "2026-07-26"}, "slides": {"date": "2026-07-26"}}
    d["slides"] = {"source": bad} if bad != "file" else {"source": bad, "file": ""}
    with pytest.raises(kitconfig.KitConfigError, match="slides"):
        _load(tmp_path, d)


@pytest.mark.parametrize("bad", [0, 7, -1])
def test_site_chapter_level_out_of_range_rejected(tmp_path, bad):
    d = dict(VALID)
    d["site"] = {"chapter_level": bad}
    with pytest.raises(kitconfig.KitConfigError, match="chapter_level"):
        _load(tmp_path, d)


def test_deploy_workers_dev_is_derived_not_authored(tmp_path):
    # Criterion: workers_dev is DERIVED from config (true when no domain, false
    # when one is set) so no deploy can re-assert Cloudflare's default. Authoring
    # it must therefore be rejected as unknown.
    d = dict(VALID)
    d["deploy"] = {"workers_dev": True}
    with pytest.raises(kitconfig.KitConfigError, match="workers_dev"):
        _load(tmp_path, d)

    assert _load(tmp_path, VALID).deploy.workers_dev is True
    d2 = dict(VALID)
    d2["deploy"] = {"domain": "guide.example.com"}
    assert _load(tmp_path, d2).deploy.workers_dev is False


# ----- [artifacts.<name>] and the authored edition date --------------------

def test_artifact_date_parsed(tmp_path):
    c = _load(tmp_path, VALID)
    assert c.artifacts["pdf"].date == "2026-07-26"


@pytest.mark.parametrize("bad", ["26-07-2026", "2026-7-26", "2026/07/26", "20260726", "", "today"])
def test_malformed_artifact_date_rejected(tmp_path, bad):
    d = dict(VALID)
    d["artifacts"] = {"pdf": {"date": bad}}
    with pytest.raises(kitconfig.KitConfigError, match="date"):
        _load(tmp_path, d)


@pytest.mark.parametrize("impossible", ["2026-02-30", "2026-13-01", "2026-00-10"])
def test_impossible_artifact_date_rejected(tmp_path, impossible):
    # ISO-8601 CALENDAR date: shape alone is not enough, the day must exist.
    d = dict(VALID)
    d["artifacts"] = {"pdf": {"date": impossible}}
    with pytest.raises(kitconfig.KitConfigError, match="date"):
        _load(tmp_path, d)


def test_artifact_table_for_undeclared_output_rejected(tmp_path):
    d = dict(VALID)
    d["artifacts"] = {"pdf": {"date": "2026-07-26"}, "slides": {"date": "2026-07-26"}}
    with pytest.raises(kitconfig.KitConfigError, match="slides"):
        _load(tmp_path, d)


def test_missing_artifact_table_for_declared_output_rejected(tmp_path):
    d = dict(VALID)
    d["outputs"] = {**VALID["outputs"], "site": "multipage"}
    # site is declared but has no [artifacts.site] table.
    with pytest.raises(kitconfig.KitConfigError, match="site"):
        _load(tmp_path, d)


def test_declared_site_with_its_artifact_table_accepted(tmp_path):
    d = dict(VALID)
    d["outputs"] = {**VALID["outputs"], "site": "multipage"}
    d["artifacts"] = {"pdf": {"date": "2026-07-26"}, "site": {"date": "2026-07-01"}}
    c = _load(tmp_path, d)
    assert sorted(c.artifacts) == ["pdf", "site"]
    assert c.artifacts["site"].date == "2026-07-01"


def test_artifact_unknown_key_rejected(tmp_path):
    d = dict(VALID)
    d["artifacts"] = {"pdf": {"date": "2026-07-26", "stamp": "x"}}
    with pytest.raises(kitconfig.KitConfigError, match="stamp"):
        _load(tmp_path, d)


def test_pdf_disabled_needs_no_pdf_artifact_table(tmp_path):
    # An app-shaped target (romance-languages) declares no PDF and skips every
    # PDF gate, so requiring [artifacts.pdf] there would be wrong.
    d = dict(VALID)
    d["outputs"] = {"pdf": False, "site": "app", "slides": False}
    d["artifacts"] = {"site": {"date": "2026-07-26"}}
    c = _load(tmp_path, d)
    assert c.outputs.pdf is False
    assert "pdf" not in c.artifacts
