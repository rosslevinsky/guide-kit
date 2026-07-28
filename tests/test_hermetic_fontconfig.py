"""The render must not be able to see the host's fonts.

Bundling the faces and writing a careful CSS cascade does NOT achieve this on its
own, which is the whole reason this exists. WeasyPrint delegates font matching
and fallback to Pango/Fontconfig, and Fontconfig answers from whatever the host
has installed. Measured on an ordinary Linux box before the hermetic config
existed:

    fc-match 'Source Serif 4'  ->  /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
    fc-match 'Helvetica'       ->  /usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf

A host font standing in for a family the repository ships. Any glyph the cascade
does not nail down, and every fallback, came from the machine rather than the
repo — so two people running `make` got different PDFs from identical source,
which is precisely the failure bundling exists to remove.
"""
import re
import shutil
import subprocess

import pytest

import buildcore
import kitconfig

pytestmark = pytest.mark.skipif(
    shutil.which("fc-match") is None, reason="fc-match is not available")


@pytest.fixture(autouse=True)
def _no_env_leak():
    """Restore FONTCONFIG_* after every test in this module.

    Without it these tests leave the variables pointing at a config under a
    tmp_path that pytest then deletes, and the next test that RENDERS hands Pango
    a configuration whose font directory no longer exists — which segfaults the
    interpreter rather than raising."""
    import os
    before = {k: os.environ.get(k) for k in ("FONTCONFIG_FILE", "FONTCONFIG_PATH")}
    yield
    for k, v in before.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="module")
def resolved():
    p = buildcore.hermetic_fontconfig()
    if p is None:
        pytest.skip("no fontconfig template in this fork")
    return p


def _match(resolved, family, fmt="%{file}"):
    return subprocess.run(
        ["fc-match", "-f", fmt, family], capture_output=True, text=True,
        encoding="utf-8", env={"FONTCONFIG_FILE": str(resolved), "PATH": "/usr/bin:/bin"},
    ).stdout.strip()


def test_the_template_is_tracked_and_the_resolved_copy_is_not(resolved):
    """The template is the reviewable, synced artifact; the resolved copy carries
    absolute paths that are wrong on every other machine."""
    assert buildcore.FONTCONFIG_TEMPLATE.is_file()
    assert "__FONT_DIR__" in buildcore.FONTCONFIG_TEMPLATE.read_text(encoding="utf-8"), \
        "the template has been resolved in place — it would be machine-specific"
    assert resolved.is_relative_to(buildcore.BUILD_DIR), \
        "the resolved config is not under build/, so it would be committed"


def _without_comments(text: str) -> str:
    """XML comments stripped. The file's prose legitimately MENTIONS `<include>`
    and /etc/fonts — to record that neither is used — so a test that greps the
    raw text is testing the documentation, not the configuration."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def test_the_resolved_config_scans_only_the_vendor_directory(resolved):
    text = _without_comments(resolved.read_text(encoding="utf-8"))
    font_dir = str((buildcore.ROOT / kitconfig.FONT_DIR).resolve())
    generated = str((buildcore.ROOT / kitconfig.GENERATED_FONT_DIR).resolve())
    assert f"<dir>{font_dir}</dir>" in text
    # TWO directories, both bundled: the vendored faces and the target's own
    # generated subsets. Any third would be a host directory.
    assert f"<dir>{generated}</dir>" in text
    assert text.count("<dir>") == 2, "an unexpected font directory is scanned"
    # An <include> ELEMENT, not the string anywhere: the file's own comments
    # mention /etc/fonts precisely to record that it is never included.
    assert "<include" not in text, "the config includes another configuration"


def test_the_cache_is_isolated(resolved):
    """Sharing ~/.cache/fontconfig would let a cache built against the host's
    fonts answer queries here — the same leak by a slower route."""
    text = resolved.read_text(encoding="utf-8")
    assert f"<cachedir>{buildcore.BUILD_DIR}" in text


@pytest.mark.parametrize("family", [
    "Source Serif 4", "Source Sans 3", "DejaVu Sans", "DejaVu Sans Mono",
])
def test_a_bundled_family_resolves_to_the_bundled_binary(resolved, family):
    got = _match(resolved, family)
    assert got.startswith(str((buildcore.ROOT / kitconfig.FONT_DIR).resolve())), \
        f"{family} resolved to {got}, outside {kitconfig.FONT_DIR}"


@pytest.mark.parametrize("family", [
    "Helvetica", "Georgia", "Times New Roman", "Arial", "Hiragino Sans",
    "Menlo", "serif", "sans-serif", "monospace", "NoSuchFamilyAnywhere",
])
def test_no_query_can_reach_a_host_font(resolved, family):
    """The load-bearing property. Every one of these resolved to a system file
    before the hermetic config existed — including the generics, and including a
    family that does not exist at all, which is the fallback path."""
    got = _match(resolved, family)
    assert got.startswith(str((buildcore.ROOT / kitconfig.FONT_DIR).resolve())), \
        f"{family} escaped to {got}"


def test_the_assertion_passes_on_the_real_tree():
    buildcore.assert_hermetic_fontconfig(set_env=False)   # must not raise


def test_the_assertion_fails_when_a_query_escapes(monkeypatch, tmp_path):
    """The guard has to FAIL for the right reason, or it is decoration. Pointing
    it at a font dir that contains nothing forces every query out to the host."""
    empty = tmp_path / "fonts" / "vendor"
    empty.mkdir(parents=True)
    (tmp_path / "fontconfig").mkdir()
    (tmp_path / "fontconfig" / "fonts.conf").write_text(
        buildcore.FONTCONFIG_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(buildcore, "ROOT", tmp_path)
    monkeypatch.setattr(buildcore, "FONTCONFIG_TEMPLATE", tmp_path / "fontconfig" / "fonts.conf")
    monkeypatch.setattr(buildcore, "FONTCONFIG_DIR", tmp_path / "build" / "fontconfig")
    # With nothing in the bundled directories the assertion now fails on the
    # stronger of its two checks — Fontconfig can see no fonts at all — which is
    # a better failure than "a query escaped": it says the scan is broken.
    with pytest.raises(SystemExit, match="NOT hermetic|NO fonts at all"):
        buildcore.assert_hermetic_fontconfig(set_env=False)
