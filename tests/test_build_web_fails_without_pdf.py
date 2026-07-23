"""build_web() HARD-FAILS on a missing reference PDF when the web layer is enabled
(plan.md:150) — a site must not deploy with a guaranteed-404 download link. The
check fires BEFORE rendering, so no partial site is written and no pandoc/WeasyPrint
is needed to exercise it.
"""
import pytest

import build


def test_build_web_raises_when_reference_pdf_missing(tmp_path, monkeypatch):
    style_screen = tmp_path / "style-screen.css"
    style_screen.write_text("body{}\n", encoding="utf-8")  # web layer enabled
    web_dir = tmp_path / "app" / "dist"
    missing_pdf = tmp_path / "nope.pdf"  # does not exist

    monkeypatch.setattr(build, "STYLE_SCREEN", style_screen)
    monkeypatch.setattr(build, "REFERENCE_PDF", missing_pdf)
    monkeypatch.setattr(build, "WEB_DIR", web_dir)

    with pytest.raises(SystemExit) as exc:
        build.build_web()
    assert "missing" in str(exc.value)
    # Failed fast, before rendering: no partial site written.
    assert not (web_dir / "index.html").exists()


def test_build_web_noops_when_web_layer_disabled(tmp_path, monkeypatch, capsys):
    # No style-screen.css → PDF-only fork → clean no-op (not a failure), even
    # though the reference PDF is absent.
    monkeypatch.setattr(build, "STYLE_SCREEN", tmp_path / "style-screen.css")  # absent
    monkeypatch.setattr(build, "REFERENCE_PDF", tmp_path / "nope.pdf")
    monkeypatch.setattr(build, "WEB_DIR", tmp_path / "app" / "dist")
    build.build_web()  # must not raise
    assert "not enabled" in capsys.readouterr().out
