"""Anchor the verify / verify-render split (plan.md:95, :161).

`make verify` performs no build and imports no renderer; `make verify-render`
builds and compares page count + stamp-excluded text; and verify.yml invokes
`make verify` ONLY (never verify-render) with the reference PDF in its paths filter.
"""
import re
import subprocess
from pathlib import Path

import yaml

import verify_pdf

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_strip_stamp_removes_dated_footer_but_preserves_body_lookalike():
    text = "body with example · deadbeefcafe\n2026-01-02 03:04:05 · abcdef123456\ntail"
    stripped = verify_pdf.strip_stamp(text)
    assert "abcdef123456" not in stripped   # dated footer stamp removed
    assert "deadbeefcafe" in stripped        # undated body lookalike preserved


def _make_n(target: str) -> str:
    return subprocess.run(
        ["make", "-n", target], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


def test_verify_target_does_no_build_and_runs_staleness():
    out = _make_n("verify")
    assert "--staleness" in out
    # No build in the recipe: `make` builds via `pixi run build`; verify must not.
    assert "pixi run build" not in out


def test_verify_render_builds_and_runs_render():
    out = _make_n("verify-render")
    assert "--render" in out
    assert "pixi run build" in out  # has the build prerequisite


def test_verify_pdf_imports_no_renderer():
    # An IMPORT of the renderer, not a mere mention: the docstring legitimately
    # says "no WeasyPrint" in prose. Check for actual import statements.
    src = (REPO_ROOT / "verify_pdf.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+weasyprint\b", src, re.MULTILINE)
    assert not re.search(r"^\s*(import|from)\s+build\b", src, re.MULTILINE)


def _load_workflow():
    # GitHub's `on:` key parses as the YAML boolean True — handle both.
    data = yaml.safe_load((REPO_ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8"))
    on_block = data.get("on", data.get(True))
    return data, on_block


def _run_commands(data) -> list[str]:
    runs = []
    for job in data["jobs"].values():
        for step in job.get("steps", []):
            if "run" in step:
                runs.append(step["run"])
    return runs


def test_ci_runs_make_verify_never_verify_render():
    data, _ = _load_workflow()
    runs = _run_commands(data)
    assert any(re.search(r"\bmake verify\b(?!-)", r) for r in runs), "CI must run `make verify`"
    assert not any("verify-render" in r for r in runs), "CI must NEVER run `make verify-render`"


def test_ci_paths_filter_includes_reference_pdf():
    _, on_block = _load_workflow()
    for trigger in ("push", "pull_request"):
        paths = on_block[trigger]["paths"]
        assert "*.pdf" in paths, f"{trigger}.paths must include the root reference PDF (*.pdf)"
