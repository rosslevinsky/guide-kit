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


def test_ci_runs_the_staleness_check_never_verify_render():
    """CI must gate on staleness, and must never run the render canary.

    The staleness check may be invoked EITHER as `make verify` OR as a direct
    `verify_pdf.py --staleness` call. The direct form is not a style choice: GNU
    make normalizes any recipe failure to exit 2, so through make a stale
    reference (exit 1) is indistinguishable from a broken environment (exit 2).
    verify.yml's auto-baseline step must tell those apart — dispatching a macOS
    render on the strength of a check that merely errored is how a wrong PDF
    would get blessed — so it calls the checker directly and branches on rc.
    baseline.yml does the same, for the same reason, and its comment records the
    three green-but-skipped runs that taught us.

    What must NOT change is the pair of invariants: the staleness gate is present,
    and `verify-render` (which builds and is platform-sensitive) never runs in CI.
    """
    data, _ = _load_workflow()
    runs = _run_commands(data)
    staleness = [
        r for r in runs
        if re.search(r"\bmake verify\b(?!-)", r)
        or re.search(r"verify_pdf\.py\s+--staleness\b", r)
    ]
    assert staleness, "CI must run the staleness check (`make verify` or verify_pdf.py --staleness)"
    assert not any("verify-render" in r for r in runs), "CI must NEVER run `make verify-render`"
    assert not any("--render" in r for r in runs), "CI must NEVER invoke the render canary directly"


def test_ci_smoke_checks_the_reference_pdf():
    """CI must smoke-check the committed reference PDF.

    `make verify` compares hashes — a question about bytes, not about the
    document — and `verify-render` is barred from CI. Without a smoke step
    nothing in CI ever asks whether the file readers download looks like a
    finished guide, which is how a PDF whose footer wrapped on every page shipped
    past every green gate.
    """
    data, _ = _load_workflow()
    runs = _run_commands(data)
    assert any(re.search(r"\bmake smoke\b", r) for r in runs), \
        "CI must run `make smoke` against the committed reference PDF"


def test_baseline_smoke_checks_before_committing():
    """baseline.yml must smoke-check the fresh render BEFORE it commits it.

    Ordering is the whole point. Now that verify.yml auto-dispatches baseline on a
    stale push, nothing between "edit guide.md" and "published PDF" has a human in
    it — this step is the only inspection left, and it is only an inspection if it
    can still stop the commit.
    """
    data = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/baseline.yml").read_text(encoding="utf-8")
    )
    steps = [s for job in data["jobs"].values() for s in job.get("steps", [])]
    names = [s.get("name", "") for s in steps]
    smoke_at = next(
        (i for i, s in enumerate(steps) if "make smoke" in s.get("run", "")), None
    )
    commit_at = next(
        (i for i, s in enumerate(steps) if "git commit" in s.get("run", "")), None
    )
    assert smoke_at is not None, f"baseline.yml must run `make smoke`; steps: {names}"
    assert commit_at is not None, f"baseline.yml must commit the PDF; steps: {names}"
    assert smoke_at < commit_at, (
        "baseline.yml smoke-checks the render AFTER committing it, so a bad render "
        f"is already blessed by the time it is caught (smoke at {smoke_at}, commit at {commit_at})"
    )


def test_verify_can_dispatch_baseline():
    """verify.yml needs `actions: write` to auto-dispatch baseline.yml.

    Without it the dispatch fails at runtime, the reference PDF stays stale, and
    the branch stays red — the exact manual-memory failure the auto-dispatch was
    added to remove.
    """
    data, _ = _load_workflow()
    perms = data.get("permissions") or {}
    runs = _run_commands(data)
    dispatches = any("workflow run baseline.yml" in r for r in runs)
    assert dispatches, "verify.yml must auto-dispatch baseline.yml when the reference is stale"
    assert perms.get("actions") == "write", (
        f"verify.yml dispatches a workflow but declares permissions={perms!r}; "
        "it needs `actions: write`"
    )


def test_ci_paths_filter_includes_reference_pdf():
    _, on_block = _load_workflow()
    for trigger in ("push", "pull_request"):
        paths = on_block[trigger]["paths"]
        assert "*.pdf" in paths, f"{trigger}.paths must include the root reference PDF (*.pdf)"
