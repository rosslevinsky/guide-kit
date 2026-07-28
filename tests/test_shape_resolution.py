"""Live manifest entries resolve from DECLARED shape, not from file presence.

The predecessor decided a guide had a web layer iff `style-screen.css` existed,
and had transforms iff `transforms.py` existed. `kit-manifest.toml`'s own header
already papered over the consequence — "a PDF-only guide has no `app/`
destinations, so the bootstrap-source entries are INERT for it" — which is a
shape enum hiding inside a boolean. A third and fourth output cannot be added
that way.

The decisive property, and the one asserted here: flipping `outputs.site`
changes the resolved entry set with NO filesystem change whatsoever.
"""
import pytest

import kitconfig
import kitmanifest


def _cfg(tmp_path, *, site="none", pdf=True):
    artifacts = {}
    if pdf:
        artifacts["pdf"] = {"date": "2026-07-26"}
    if site != "none":
        artifacts["site"] = {"date": "2026-07-26"}
    lines = [
        'TITLE = "Probe"',
        'OUTPUT_SLUG = "probe-guide"',
        'AUTHOR = "A"',
        'DESCRIPTION = "d"',
        'KEYWORDS = "k"',
        "COPYRIGHT_YEAR = 2026",
        "[outputs]",
        f"pdf = {str(pdf).lower()}",
        f'site = "{site}"',
        "slides = false",
    ]
    for name, body in artifacts.items():
        lines.append(f"[artifacts.{name}]")
        lines.append(f'date = "{body["date"]}"')
    (tmp_path / "guide.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return kitconfig.load(root=tmp_path)


def test_flipping_outputs_site_changes_resolution_with_no_filesystem_change(tmp_path, repo_root):
    manifest = kitmanifest.load(repo_root)

    pdf_only = _cfg(tmp_path, site="none")
    before = {p.dest for p in manifest.projections_for(pdf_only, slug="probe-guide")}

    # The ONLY thing that changes is one config value. No file is created,
    # deleted or touched between these two resolutions.
    with_site = _cfg(tmp_path, site="single")
    after = {p.dest for p in manifest.projections_for(with_site, slug="probe-guide")}

    assert after > before, "declaring a site did not add any destination"
    # The web-layer destinations are precisely what appears.
    assert any(d.startswith("app/") for d in after - before)
    assert not any(d.startswith("app/") for d in before)


def test_resolution_does_not_consult_the_filesystem(tmp_path, repo_root):
    # Materializing the file the predecessor used as its signal must NOT change
    # the answer — only the declaration may.
    manifest = kitmanifest.load(repo_root)
    cfg = _cfg(tmp_path, site="none")
    before = {p.dest for p in manifest.projections_for(cfg, slug="probe-guide")}

    (tmp_path / "style-screen.css").write_text("/* present */\n", encoding="utf-8")
    (tmp_path / "app").mkdir()

    after = {p.dest for p in manifest.projections_for(cfg, slug="probe-guide")}
    assert after == before, "resolution still keys on file presence"


@pytest.mark.parametrize("shape", ["single", "multipage", "app", "hub"])
def test_every_site_shape_resolves_the_web_destinations(tmp_path, repo_root, shape):
    manifest = kitmanifest.load(repo_root)
    cfg = _cfg(tmp_path, site=shape)
    dests = {p.dest for p in manifest.projections_for(cfg, slug="probe-guide")}
    assert any(d.startswith("app/") for d in dests)


def test_slug_is_resolved_in_destinations(tmp_path, repo_root):
    manifest = kitmanifest.load(repo_root)
    cfg = _cfg(tmp_path, site="none")
    dests = {p.dest for p in manifest.projections_for(cfg, slug="probe-guide")}
    assert not any("<slug>" in d for d in dests)
    assert "probe-guide.pdf" in dests


def test_projections_for_agrees_with_the_shape_primitive(tmp_path, repo_root):
    # projections_for is a config-driven wrapper over the same resolution, not a
    # second implementation that can drift from it.
    manifest = kitmanifest.load(repo_root)
    cfg = _cfg(tmp_path, site="single")
    assert (
        [p.dest for p in manifest.projections_for(cfg, slug="probe-guide")]
        == [p.dest for p in manifest.projections("web-enabled", slug="probe-guide")]
    )
