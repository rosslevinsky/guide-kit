"""`make baseline` refuses a dirty SOURCE_FILES tree and leaves the reference PDF
byte-identical (plan.md:101, :166).

The temp guide records baseline_platform == this host's sys.platform so the
platform guard PASSES and the dirty guard is what we exercise. baseline refuses
before building or copying, so no renderer is needed.
"""
import subprocess
import sys

import pytest

import baseline
import kitconfig

SLUG = "probe-guide"


def _toml() -> str:
    return (
        'TITLE = "Probe"\n'
        f'OUTPUT_SLUG = "{SLUG}"\n'
        'AUTHOR = "T"\n'
        'DESCRIPTION = "d"\n'
        'KEYWORDS = "k"\n'
        'COPYRIGHT_YEAR = 2026\n'
        f'baseline_platform = "{sys.platform}"\n'  # matches host → platform guard passes
    )


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _mkrepo(tmp_path):
    (tmp_path / "guide.toml").write_text(_toml(), encoding="utf-8")
    # Seed every SOURCE_FILES entry EXCEPT transforms.py (left absent so the
    # "untracked" case has a real SOURCE_FILES file to create).
    for name in kitconfig.SOURCE_FILES:
        if name not in ("guide.toml", "transforms.py"):
            (tmp_path / name).write_text(f"seed-{name}\n", encoding="utf-8")
    (tmp_path / f"{SLUG}.pdf").write_bytes(b"%PDF-reference")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "clean baseline")
    return tmp_path


@pytest.mark.parametrize("kind", ["modified", "staged", "untracked"])
def test_baseline_refuses_dirty_source_tree(tmp_path, monkeypatch, kind):
    repo = _mkrepo(tmp_path)
    reference = repo / f"{SLUG}.pdf"
    before = reference.read_bytes()

    if kind == "modified":
        (repo / "guide.md").write_text("seed-guide.md\nchanged\n", encoding="utf-8")
    elif kind == "staged":
        (repo / "guide.md").write_text("seed-guide.md\nchanged\n", encoding="utf-8")
        _git(repo, "add", "guide.md")
    elif kind == "untracked":
        (repo / "transforms.py").write_text("# new untracked source\n", encoding="utf-8")

    monkeypatch.setattr(baseline, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["baseline.py"])
    with pytest.raises(SystemExit) as exc:
        baseline.main()

    assert "dirty" in str(exc.value)
    assert reference.read_bytes() == before          # reference PDF untouched
    assert not (repo / "build").exists()             # refused before building
