"""`make baseline` refuses a dirty SOURCE_FILES tree and leaves the reference PDF
byte-identical.

The dirty guard is now baseline's ONLY refusal — the platform guard it used to
sit behind is retired (see test_no_platform_guard.py). baseline refuses before
building or copying, so no renderer is needed.
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
        '[outputs]\n'
        'pdf = true\n'
        'site = "none"\n'
        'slides = false\n'
        '[artifacts.pdf]\n'
        'date = "2026-07-26"\n'
    )


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _mkrepo(tmp_path):
    (tmp_path / "guide.toml").write_text(_toml(), encoding="utf-8")
    # Seed every SOURCE_FILES entry EXCEPT transforms.py (left absent so the
    # "untracked" case has a real SOURCE_FILES file to create).
    for name in kitconfig.SOURCE_FILES:
        if name not in ("guide.toml", "transforms.py"):
            # SOURCE_FILES now contains a NESTED path (fontconfig/fonts.conf),
            # so a flat write is no longer enough.
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
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


def test_the_dirty_guard_scopes_to_the_guide_S_OWN_THEME(tmp_path, monkeypatch):
    """The guard must read the CONFIGURED theme, not the schema default.

    `kitconfig.stamp_pathspec()` with no config resolves `themes/<theme>/print.css`
    against the schema DEFAULT. `baseline.py` called it that way while the render
    read the guide's actual theme, so on any guide selecting a non-default theme —
    `guide-kit` and `git-guide` both select `editorial` — an uncommitted edit
    to its real theme file was INVISIBLE here. The tree reported
    ` M themes/editorial/print.css` and this guard saw nothing.

    It did not bless a bad reference: `buildcore._is_dirty` passes its config, so
    the render still stamped `· dirty` and promotion refused. But "refuses BEFORE
    building" is a documented property of this guard, and it was false — the
    operator paid for a build and got a late, unspecific error instead of a named
    file. The same shape bites `<slides_file>` for a deck that is not `slides.md`.
    """
    import subprocess

    import baseline
    import kitconfig

    repo = _mkrepo(tmp_path)          # seeds every stamp input and commits

    # Re-point the guide at a NON-DEFAULT theme, and give it that theme's file.
    toml = repo / "guide.toml"
    assert kitconfig.DEFAULT_THEME != "editorial", "pick a different non-default theme"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[theme]\nname = "editorial"\n',
        encoding="utf-8",
    )
    theme_file = repo / "themes" / "editorial" / "print.css"
    theme_file.parent.mkdir(parents=True, exist_ok=True)
    theme_file.write_text("/* committed */\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "theme"], cwd=repo, check=True,
                   capture_output=True)

    # Now dirty ONLY the guide's real theme file.
    theme_file.write_text("/* committed */\n/* uncommitted */\n", encoding="utf-8")

    cfg = kitconfig.load(repo)
    monkeypatch.setattr(baseline, "ROOT", repo)
    dirty = baseline._dirty_source_files(cfg)

    assert any("themes/editorial/print.css" in d for d in dirty), (
        f"the dirty guard did not see the guide's own theme file; it reported {dirty}"
    )
