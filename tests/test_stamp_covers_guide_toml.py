"""guide.toml reaches the version stamp KEY-LEVEL, not as a whole file.

This previously asserted that mutating guide.toml at all moved the stamp, which
was the right property while one hash covered one artifact over a fixed file
list. It is now wrong in one direction and too weak in the other: hashing the
whole file puts `[deploy]` and `[hub]` edits into the PDF's closure, so a domain
change would re-stale all eight reference PDFs for a value the PDF never
renders.

The property therefore splits in two, and both halves are asserted here — an
in-closure key still moves the stamp (or the config would not be build input at
all), and an out-of-closure table does not.
"""
import buildcore
import kitconfig

BASE = (
    'TITLE = "Probe"\n'
    'OUTPUT_SLUG = "probe-guide"\n'
    'AUTHOR = "T"\n'
    'DESCRIPTION = "d"\n'
    'KEYWORDS = "k"\n'
    'COPYRIGHT_YEAR = 2026\n'
    "[outputs]\n"
    "pdf = true\n"
    'site = "single"\n'
    "slides = false\n"
    "[artifacts.pdf]\n"
    'date = "2026-07-26"\n'
    "[artifacts.site]\n"
    'date = "2026-07-26"\n'
)


def _seed(tmp_path, toml=BASE):
    for name in kitconfig.SOURCE_FILES:
        if name != "guide.toml":
            # SOURCE_FILES now contains a NESTED path (fontconfig/fonts.conf),
            # so a flat write is no longer enough.
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text(f"seed-{name}", encoding="utf-8")
    (tmp_path / "guide.toml").write_text(toml, encoding="utf-8")
    return tmp_path


def test_in_closure_key_change_moves_the_stamp(tmp_path, monkeypatch):
    # In a non-git tmp dir the date/dirty halves of the stamp are empty, so the
    # stamp is the closure hash alone — exactly what we want to observe moving.
    _seed(tmp_path)
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)
    first = buildcore._version_stamp()

    _seed(tmp_path, BASE.replace('TITLE = "Probe"', 'TITLE = "Renamed"'))
    assert buildcore._version_stamp() != first


def test_out_of_closure_table_does_not_move_the_pdf_stamp(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)
    first = buildcore._version_stamp()

    # A [deploy] table the PDF never renders must not re-stale it.
    _seed(tmp_path, BASE + '[deploy]\ndomain = "guide.example.com"\n')
    assert buildcore._version_stamp() == first


def test_each_artifact_stamps_from_its_own_closure(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)
    assert buildcore._version_stamp("pdf") != buildcore._version_stamp("site")


def test_guide_toml_and_kitconfig_are_authorable_sources():
    assert "guide.toml" in kitconfig.AUTHORABLE_SOURCES
    assert "kitconfig.py" in kitconfig.AUTHORABLE_SOURCES
    # kitconfig.py is genuine render input (it resolves the config the renderer
    # reads); guide.toml reaches the render key-level, via the projection.
    assert "kitconfig.py" in kitconfig.artifact_spec("pdf").file_deps
