"""`release.py` must read paths git actually emits, not the pretty form.

WHY THIS EXISTS. `git status --porcelain` QUOTES any path containing a space or
a non-ASCII character, and the quotes are literal characters in the output.
`_ensure_clean_state()` compares each path against `kitconfig.is_stamp_input()`,
so a quoted path matches nothing: `make release` decides a legitimate change is
out of scope and refuses. Every bundled face in the family is plain ASCII today,
which is the only reason this had not bitten.

The rename case is the sharp edge of the fix rather than of the bug. Under `-z`
a rename emits TWO NUL-terminated fields — new path, then origin — where the
default format packs them into one line as `new -> old`. Miss that and the
origin is read back as an entry of its own.
"""
import subprocess

import pytest

import release


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "T")
    # fonts/vendor/ must already be TRACKED. Git collapses a wholly-untracked directory
    # to a single `fonts/` entry, so a new file inside one is never reported by
    # name — which would test the fixture rather than the parser.
    (tmp_path / "fonts" / "vendor").mkdir(parents=True, exist_ok=True)
    (tmp_path / "fonts" / "vendor" / "Seed.ttf").write_bytes(b"seed")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "seed")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    return tmp_path


def test_a_path_with_a_space_is_read_unquoted(repo):
    (repo / "fonts" / "vendor" / "My Font.ttf").write_bytes(b"x")
    paths = [p for _code, p in release._porcelain()]
    assert "fonts/vendor/My Font.ttf" in paths, paths
    assert not any(p.startswith('"') for p in paths), "path came back quoted"


def test_a_non_ascii_path_is_read_unquoted(repo):
    (repo / "fonts" / "vendor" / "Suisse–Bold.ttf").write_bytes(b"x")   # en dash
    paths = [p for _code, p in release._porcelain()]
    assert "fonts/vendor/Suisse–Bold.ttf" in paths, paths


def test_a_quoted_path_would_not_have_matched_a_stamp_input(repo):
    """The bug's actual consequence, pinned: the quoted form is not recognised,
    so `make release` would call a real font change out of scope."""
    import kitconfig
    assert kitconfig.is_stamp_input("fonts/vendor/My Font.ttf")
    assert not kitconfig.is_stamp_input('"fonts/vendor/My Font.ttf"')


def test_a_rename_does_not_leak_its_origin_path(repo):
    (repo / "guide.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add guide")
    _git(repo, "mv", "guide.md", "renamed.md")
    rows = release._porcelain()
    paths = [p for _code, p in rows]
    assert "renamed.md" in paths
    assert "guide.md" not in paths, f"origin path leaked as its own entry: {rows}"


def test_ordinary_paths_are_unchanged(repo):
    (repo / "guide.md").write_text("x\n", encoding="utf-8")
    (repo / "style.css").write_text("y\n", encoding="utf-8")
    paths = sorted(p for _code, p in release._porcelain())
    assert paths == ["guide.md", "style.css"]
