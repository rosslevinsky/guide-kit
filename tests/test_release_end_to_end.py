"""release.py works end-to-end without scraping OUTPUT_SLUG out of build.py.

In a throwaway git repo whose build.py contains NO `OUTPUT_SLUG = "..."` literal,
release.py must still resolve the slug (from guide.toml via kitconfig), commit the
source change, promote the reference PDF, and amend it into the commit. If it
still scraped build.py, the missing literal would break it — so a green run proves
the redesign (plan.md:62, :78).

The render step is stubbed (monkeypatched) so the test stays fast and pixi-free;
the commit → promote → amend orchestration and the kitconfig-sourcing are all
exercised for real.
"""
import subprocess
import sys

import pytest

import release


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _seed_repo(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    # guide.toml carries the slug; build.py deliberately has NO OUTPUT_SLUG literal.
    (repo / "guide.toml").write_text(
        'TITLE = "Probe Guide"\n'
        'OUTPUT_SLUG = "probe-guide"\n'
        'AUTHOR = "Tester"\n'
        'DESCRIPTION = "d"\n'
        'KEYWORDS = "k"\n'
        'COPYRIGHT_YEAR = 2026\n'
        # Match the host so release.py's platform guard (Phase 3) passes and the
        # commit/promote/amend path under test actually runs.
        f'baseline_platform = "{sys.platform}"\n',
        encoding="utf-8",
    )
    (repo / "guide.md").write_text("# Probe\n", encoding="utf-8")
    (repo / "style.css").write_text("body{}\n", encoding="utf-8")
    (repo / "build.py").write_text("# no OUTPUT_SLUG literal here\n", encoding="utf-8")
    (repo / "kitconfig.py").write_text("# placeholder\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")


def test_release_end_to_end(tmp_path, monkeypatch):
    repo = tmp_path
    _seed_repo(repo)

    # An in-scope source edit to release.
    (repo / "guide.md").write_text("# Probe\n\nnew paragraph\n", encoding="utf-8")

    # Point release at the throwaway repo and stub the render to write the
    # working PDF release.py expects to promote.
    monkeypatch.setattr(release, "ROOT", repo)

    def _stub_build():
        (repo / "build").mkdir(exist_ok=True)
        (repo / "build" / "probe-guide.pdf").write_bytes(b"%PDF-fake-render")

    monkeypatch.setattr(release, "_build", _stub_build)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "test release"])

    rc = release.main()
    assert rc == 0

    # The reference PDF was promoted to the repo root under the guide.toml slug
    # (proving the slug came from guide.toml, not a build.py scrape).
    reference = repo / "probe-guide.pdf"
    assert reference.exists()
    assert reference.read_bytes() == b"%PDF-fake-render"

    # It is tracked (amended into the commit), and the log shows exactly the two
    # commits — "init" plus the single amended release commit.
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.split()
    assert "probe-guide.pdf" in tracked

    subjects = subprocess.run(
        ["git", "log", "--format=%s"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.split("\n")
    subjects = [s for s in subjects if s]
    assert subjects == ["test release", "init"]


def test_release_accepts_a_guide_toml_change(tmp_path, monkeypatch):
    # guide.toml is a SOURCE_FILES entry now (Phase 1). Editing it must be an
    # IN-SCOPE release change — if release regressed to the old four-file list,
    # _ensure_clean_state would reject this as "outside SOURCE_FILES" and exit.
    repo = tmp_path
    _seed_repo(repo)
    original = (repo / "guide.toml").read_text(encoding="utf-8")
    (repo / "guide.toml").write_text(original.replace('KEYWORDS = "k"', 'KEYWORDS = "k2"'), encoding="utf-8")

    monkeypatch.setattr(release, "ROOT", repo)

    def _stub_build():
        (repo / "build").mkdir(exist_ok=True)
        (repo / "build" / "probe-guide.pdf").write_bytes(b"%PDF-x")

    monkeypatch.setattr(release, "_build", _stub_build)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "toml change"])

    assert release.main() == 0
    changed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.split()
    assert "guide.toml" in changed


def test_release_refuses_out_of_scope_changes(tmp_path, monkeypatch):
    repo = tmp_path
    _seed_repo(repo)
    # A change outside SOURCE_FILES must be refused (release only stages source).
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")

    monkeypatch.setattr(release, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "should not run"])
    with pytest.raises(SystemExit):
        release.main()
