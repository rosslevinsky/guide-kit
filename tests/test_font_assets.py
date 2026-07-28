"""Font provenance and the real-binary requirement.

Two properties that bundling is supposed to buy, neither of which the closure
hash alone can enforce:

* **Provenance.** A face is a render input with no other tripwire. Swap one for a
  silently different upstream build — a re-release under the same version, a
  corrupted download, a well-meant "update the fonts" commit — and every guide's
  typography changes. The stamp moves, because the faces are in the closure, but
  nothing says WHY, and a re-baseline simply blesses the new bytes.
* **No synthesized weights.** WeasyPrint will fake a bold or an italic from a
  regular face when the real one is missing. The result renders, looks roughly
  right, and is not the typeface anyone chose — so the requirement is that the
  weight/style faces exist as REAL binaries.
"""
import hashlib
import json

import pytest

import buildcore
import kitconfig

FACES = kitconfig.font_files(buildcore.ROOT)
RECORD = buildcore.ROOT / kitconfig.FONT_DIR / buildcore.UPSTREAM_HASHES


def _recorded():
    return json.loads(RECORD.read_text(encoding="utf-8"))["faces"]


def test_the_faces_live_in_the_vendor_namespace():
    """Flat in `fonts/`, a target-owned generated subset would sit inside the
    kit-managed tree. The namespaces are siblings so that cannot arise."""
    assert kitconfig.FONT_DIR == "fonts/vendor"
    assert FACES, "no bundled faces found"
    for p in FACES:
        assert p.parent.name == "vendor" and p.parent.parent.name == "fonts"


def test_every_face_on_disk_is_recorded():
    recorded = _recorded()
    assert {p.name for p in FACES} == set(recorded), \
        "the recorded face set and the faces on disk disagree"


def test_every_recorded_hash_matches_the_binary():
    recorded = _recorded()
    for p in FACES:
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        assert got == recorded[p.name], f"{p.name} is not the recorded upstream binary"


def test_the_provenance_check_passes_on_the_real_tree():
    buildcore.check_font_provenance()   # must not raise


def test_a_changed_binary_is_refused_before_rendering(tmp_path, monkeypatch):
    """The check has to FAIL for the right reason, or it is decoration. It runs
    before the renderer so a PDF built from unexpected bytes is never written."""
    fonts = tmp_path / kitconfig.FONT_DIR
    fonts.mkdir(parents=True)
    face = fonts / "Probe-Regular.otf"
    face.write_bytes(b"the recorded binary\n")
    (fonts / buildcore.UPSTREAM_HASHES).write_text(json.dumps(
        {"faces": {"Probe-Regular.otf": hashlib.sha256(b"the recorded binary\n").hexdigest()}}
    ), encoding="utf-8")
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)

    buildcore.check_font_provenance()             # matching: silent

    face.write_bytes(b"a different upstream build\n")
    with pytest.raises(SystemExit, match="provenance check FAILED"):
        buildcore.check_font_provenance()


def test_an_unrecorded_face_is_refused(tmp_path, monkeypatch):
    """Unrecorded provenance is the state the record exists to prevent — and
    admitting it would let the check be bypassed by simply adding a face."""
    fonts = tmp_path / kitconfig.FONT_DIR
    fonts.mkdir(parents=True)
    (fonts / "Sneaked-In.otf").write_bytes(b"never registered\n")
    (fonts / buildcore.UPSTREAM_HASHES).write_text(
        json.dumps({"faces": {}}), encoding="utf-8")
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="not in UPSTREAM-HASHES"):
        buildcore.check_font_provenance()


def test_a_recorded_face_missing_from_disk_is_refused(tmp_path, monkeypatch):
    fonts = tmp_path / kitconfig.FONT_DIR
    fonts.mkdir(parents=True)
    (fonts / buildcore.UPSTREAM_HASHES).write_text(json.dumps(
        {"faces": {"Vanished.otf": "0" * 64}}), encoding="utf-8")
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="missing from disk"):
        buildcore.check_font_provenance()


def test_a_fork_without_bundled_fonts_is_not_broken_by_the_check(tmp_path, monkeypatch):
    """No record, nothing to assert — a fork that never adopted bundled fonts
    must still build."""
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)
    buildcore.check_font_provenance()   # must not raise


# ----- real binaries, not synthesized weights --------------------------------

@pytest.mark.parametrize("face", [
    "SourceSerif4-Regular.otf", "SourceSerif4-Bold.otf",
    "SourceSerif4-It.otf", "SourceSerif4-BoldIt.otf",
    "SourceSans3-Regular.otf", "SourceSans3-Semibold.otf",
    "SourceSans3-It.otf", "SourceSans3-SemiboldIt.otf",
    "DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Oblique.ttf",
])
def test_each_weight_and_style_exists_as_a_real_binary(face):
    """WeasyPrint fakes a missing bold or italic from the regular face. It
    renders, it looks roughly right, and it is not the typeface anyone chose."""
    assert (buildcore.ROOT / kitconfig.FONT_DIR / face).is_file(), \
        f"{face} is missing — its weight/style would be synthesized"


def test_the_declared_font_faces_all_resolve():
    """Every `@font-face src` in style.css points at a file that exists. A
    dangling url is silent: the cascade just falls through to the next family."""
    import re
    # The declarations live in the KIT-OWNED fontfaces.css now: guides name
    # families, they do not define them.
    css = (buildcore.ROOT / "fontfaces.css").read_text(encoding="utf-8")
    urls = re.findall(r'src:\s*url\("([^"]+)"\)', css)
    assert urls, "no @font-face src urls found in style.css"
    for u in urls:
        assert u.startswith(kitconfig.FONT_DIR + "/"), \
            f"{u} does not point into the vendor namespace"
        assert (buildcore.ROOT / u).is_file(), f"{u} does not exist"


def test_the_ofl_text_ships_beside_the_binaries():
    """The criterion names `OFL.txt`; the upstream artifacts are per-family. Both
    ship — one canonical licence body, plus each family's own copyright and
    Reserved Font Name declaration, which the OFL requires be preserved."""
    d = buildcore.ROOT / kitconfig.FONT_DIR
    ofl = (d / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in ofl
    assert "Source Serif 4" in ofl and "Source Sans 3" in ofl
    # DejaVu is NOT OFL; conflating them would misstate the licence.
    assert "DejaVu" in ofl and "NOT under the OFL" in ofl
    for per_family in ("LICENSE-SourceSans3-OFL.md", "LICENSE-SourceSerif4-OFL.md",
                       "LICENSE-DejaVu.txt"):
        assert (d / per_family).is_file(), f"{per_family} was dropped"


def test_the_provenance_record_is_in_the_PDF_closure(tmp_path):
    """`UPSTREAM-HASHES.json` gates every build, so it must move the stamp.

    `buildcore._assert_font_provenance` reads this file on every render and
    refuses when a bundled face's hash disagrees with it. It was NOT in any
    artifact's closure until the boundary review found that, which meant:

      * deleting it disabled the provenance gate entirely (the function returns
        early when the record is absent — "a fork that has not adopted bundled
        fonts has nothing to assert") while `make verify` stayed green; and
      * corrupting it broke the next build with no staleness signal first.

    A check whose own input can change without moving the version stamp is not a
    check. Asserted on the hash, not on the list, because membership in
    SOURCE_FILES is a means and the hash moving is the property.
    """
    import kitconfig

    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    record = repo / "fonts" / "vendor" / "UPSTREAM-HASHES.json"
    if not record.is_file():
        import pytest
        pytest.skip("this repo has not adopted bundled fonts")

    assert "fonts/vendor/UPSTREAM-HASHES.json" in kitconfig.SOURCE_FILES

    before = kitconfig.artifact_closure_hash("pdf", root=repo)
    original = record.read_bytes()
    try:
        record.write_bytes(original + b"\n")
        after = kitconfig.artifact_closure_hash("pdf", root=repo)
    finally:
        record.write_bytes(original)
    assert after != before, (
        "editing the font provenance record does not move the PDF's closure hash "
        "— the gate's own input is outside the closure it gates"
    )
    assert kitconfig.artifact_closure_hash("pdf", root=repo) == before
