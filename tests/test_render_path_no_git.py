"""The render path reads no git history.

The stamp's date used to come from `git log -1 --format=%ad` over a pathspec.
That made the rendered bytes depend on commit history, and — because git cannot
scope to a key inside a file — a `[deploy]`-only commit moved the PDF's
displayed date even though the PDF renders nothing from `[deploy]`. The date is
now the artifact's authored `[artifacts.<name>] date`.

Two consequences are asserted here: no renderer invokes `git log` at all, and a
`[deploy]`-only edit leaves the PDF's bytes, its parsed stamp and its resolved
`SOURCE_DATE_EPOCH` all unchanged — the three together, because a closure hash
alone would pass while the stamp moved.
"""
import ast
import pathlib
import subprocess

import pytest

import buildcore
import kitconfig
import verify_artifacts
from conftest import render

RENDER_PATH_MODULES = ("buildcore.py", "render_pdf.py", "render_site.py",
                       "render_slides.py", "build.py")


def _git_argv_lists(src: str) -> list[list[str]]:
    """Every list literal in `src` whose first element is the string "git".

    Read from the AST rather than by grepping the text, so the prose explaining
    why git history is gone — which necessarily says "git log" — cannot be
    mistaken for a call that makes one.
    """
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.List) and node.elts:
            head = node.elts[0]
            if isinstance(head, ast.Constant) and head.value == "git":
                out.append([e.value for e in node.elts if isinstance(e, ast.Constant)])
    return out


def test_no_renderer_reads_git_history(repo_root):
    offenders = []
    for name in RENDER_PATH_MODULES:
        for argv in _git_argv_lists((repo_root / name).read_text(encoding="utf-8")):
            if any(sub in argv for sub in ("log", "show", "rev-list", "blame")):
                offenders.append((name, argv))
    assert not offenders, f"a renderer still reads git history: {offenders}"


def test_the_only_surviving_git_call_is_the_dirty_check(repo_root):
    src = (repo_root / "buildcore.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    git_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List):
            head = node.elts[0] if node.elts else None
            if isinstance(head, ast.Constant) and head.value == "git":
                git_calls.append([
                    e.value for e in node.elts if isinstance(e, ast.Constant)
                ])
    assert git_calls, "expected the dirty check's git invocation to be present"
    for call in git_calls:
        assert call[:2] == ["git", "status"], f"unexpected git call in the render path: {call}"


def test_the_stamp_date_is_the_authored_edition_date(guide_repo):
    root, write_toml = guide_repo
    write_toml(artifacts={"pdf": {"date": "2031-03-04"}})
    render(root)
    stamp = kitconfig.parse_stamp(
        subprocess.run(["pdftotext", str(root / "build" / "probe-guide.pdf"), "-"],
                       capture_output=True, text=True, check=True).stdout
    )
    assert stamp is not None, "no parseable stamp in the render"
    assert stamp.date == "2031-03-04"


def test_source_date_epoch_is_midnight_utc_of_the_authored_date(guide_repo, monkeypatch):
    root, write_toml = guide_repo
    write_toml(artifacts={"pdf": {"date": "2031-03-04"}})
    monkeypatch.setattr(buildcore, "ROOT", root)
    # 2031-03-04T00:00:00Z
    assert buildcore._source_date_epoch("pdf") == 1930348800


def test_a_deploy_only_edit_changes_nothing_about_the_pdf(guide_repo, monkeypatch):
    """The criterion, asserted on all three of bytes, stamp and SOURCE_DATE_EPOCH."""
    root, write_toml = guide_repo
    render(root)
    pdf = root / "build" / "probe-guide.pdf"
    before_bytes = pdf.read_bytes()
    before_stamp = verify_artifacts.read_stamp(pdf)
    monkeypatch.setattr(buildcore, "ROOT", root)
    before_epoch = buildcore._source_date_epoch("pdf")

    write_toml(deploy={"domain": "guide.example.com"})
    render(root)

    assert pdf.read_bytes() == before_bytes
    assert verify_artifacts.read_stamp(pdf) == before_stamp
    assert buildcore._source_date_epoch("pdf") == before_epoch


def test_two_builds_of_identical_content_are_byte_identical(guide_repo):
    """No `SOURCE_DATE_EPOCH` special case for unreleased builds: the authored
    date makes this hold across hosts and across time, not just within one run."""
    root, _ = guide_repo
    render(root)
    first = (root / "build" / "probe-guide.pdf").read_bytes()
    (root / "build" / "probe-guide.pdf").unlink()
    render(root)
    assert (root / "build" / "probe-guide.pdf").read_bytes() == first


def test_a_guide_with_no_artifact_table_for_the_output_fails_loudly(guide_repo, monkeypatch):
    root, write_toml = guide_repo
    monkeypatch.setattr(buildcore, "ROOT", root)
    with pytest.raises(SystemExit, match="slides"):
        buildcore.artifact_date("slides")
