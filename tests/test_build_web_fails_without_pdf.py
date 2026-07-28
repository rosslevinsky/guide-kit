"""build_web() HARD-FAILS on a missing reference PDF when the web layer is enabled:
a site must not deploy with a guaranteed-404 download link. The check fires BEFORE
rendering, so no partial site is written and no pandoc/WeasyPrint is needed to
exercise it.

Enablement is DECLARED (`[outputs] site`), not inferred from `style-screen.css`
existing. The stylesheet is target-owned, so a guide that disables its site keeps
the file — and the old file-presence gate then rendered a site the guide had just
switched off.
"""
import pytest

import buildcore
import kitconfig

import render_site


class _Outputs:
    # `site` is not optional on the real Outputs, so the stub must carry it.
    # It was absent here, and `build_web`'s new implemented-shape check read it
    # and raised AttributeError — a stub that models the object loosely turns a
    # correct new guard into a test failure. Defaulting to "single" keeps these
    # tests aimed at what they are about (a missing reference PDF, a missing
    # stylesheet) rather than at the shape check.
    def __init__(self, declared, site="single"):
        self.declared = declared
        self.site = site


class _Cfg:
    def __init__(self, declared):
        self.outputs = _Outputs(declared)


def _declare(monkeypatch, *outputs):
    monkeypatch.setattr(render_site.kitconfig, "load", lambda root=None: _Cfg(tuple(outputs)))


def test_build_web_raises_when_reference_pdf_missing(tmp_path, monkeypatch):
    style_screen = tmp_path / "style-screen.css"
    style_screen.write_text("body{}\n", encoding="utf-8")
    web_dir = tmp_path / "app" / "dist"
    missing_pdf = tmp_path / "nope.pdf"  # does not exist

    _declare(monkeypatch, "pdf", "site")           # the site is declared
    monkeypatch.setattr(render_site, "STYLE_SCREEN", style_screen)
    monkeypatch.setattr(buildcore, "REFERENCE_PDF", missing_pdf)
    monkeypatch.setattr(render_site, "WEB_DIR", web_dir)

    with pytest.raises(SystemExit) as exc:
        render_site.build_web()
    assert "missing" in str(exc.value)
    # Failed fast, before rendering: no partial site written.
    assert not (web_dir / "index.html").exists()


def test_build_web_noops_when_the_site_is_not_declared(tmp_path, monkeypatch, capsys):
    # A PDF-only guide → clean no-op (not a failure), even though the reference
    # PDF is absent AND — the case that matters — even if style-screen.css is
    # still lying around from a site that was disabled.
    (tmp_path / "style-screen.css").write_text("body{}\n", encoding="utf-8")
    _declare(monkeypatch, "pdf")
    monkeypatch.setattr(render_site, "STYLE_SCREEN", tmp_path / "style-screen.css")
    monkeypatch.setattr(buildcore, "REFERENCE_PDF", tmp_path / "nope.pdf")
    monkeypatch.setattr(render_site, "WEB_DIR", tmp_path / "app" / "dist")
    render_site.build_web()  # must not raise
    assert "not declared" in capsys.readouterr().out


def test_build_web_refuses_a_declared_site_with_no_stylesheet(tmp_path, monkeypatch):
    """Declared but not materialized is a real, nameable state — the one
    `adopt.py --output site --enable` exists to resolve. Silently rendering an
    unstyled site would be worse than saying so."""
    _declare(monkeypatch, "pdf", "site")
    monkeypatch.setattr(render_site, "STYLE_SCREEN", tmp_path / "absent.css")
    monkeypatch.setattr(buildcore, "REFERENCE_PDF", tmp_path / "nope.pdf")
    monkeypatch.setattr(render_site, "WEB_DIR", tmp_path / "app" / "dist")
    with pytest.raises(SystemExit, match="style-screen.css"):
        render_site.build_web()
