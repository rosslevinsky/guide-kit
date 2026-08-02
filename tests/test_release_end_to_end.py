"""release.py works end-to-end without scraping OUTPUT_SLUG out of build.py.

In a throwaway git repo whose build.py contains NO `OUTPUT_SLUG = "..."` literal,
release.py must still resolve the slug (from guide.toml via kitconfig), commit the
source change, promote the reference PDF, and amend it into the commit. If it
still scraped build.py, the missing literal would break it — so a green run proves
the redesign.

The render step is stubbed (monkeypatched) so the test stays fast and pixi-free;
the commit → promote → amend orchestration and the kitconfig-sourcing are all
exercised for real.
"""
import subprocess
import sys

import pytest

import release
import verify_artifacts


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
        # A complete, loadable guide.toml, so the commit/promote/amend path
        # under test actually runs rather than failing validation.
        '[outputs]\n'
        'pdf = true\n'
        'site = "none"\n'
        'slides = false\n'
        '[artifacts.pdf]\n'
        'date = "2026-07-26"\n',
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
    # The stubbed render is a fake PDF with no readable stamp; the release
    # ORCHESTRATION is what this test exercises, so stub the render validation too
    # (promotable_stamp is covered directly by the baseline/staleness tests).
    monkeypatch.setattr(verify_artifacts, "promotable_stamp", lambda w, r, a="pdf": (True, "stubbed"))
    # Same reason: this exercises the release flow against a stub PDF, so the
    # document-level check has nothing valid to read. Covered by
    # tests/test_promotion_smokes.py and tests/test_smoke_check.py.
    monkeypatch.setattr(verify_artifacts, "smoke_check",
                        lambda p, r=None, artifact="pdf": 0)
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
    # guide.toml is a SOURCE_FILES entry. Editing it must be an
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
    # The stubbed render is a fake PDF with no readable stamp; the release
    # ORCHESTRATION is what this test exercises, so stub the render validation too
    # (promotable_stamp is covered directly by the baseline/staleness tests).
    monkeypatch.setattr(verify_artifacts, "promotable_stamp", lambda w, r, a="pdf": (True, "stubbed"))
    # Same reason: this exercises the release flow against a stub PDF, so the
    # document-level check has nothing valid to read. Covered by
    # tests/test_promotion_smokes.py and tests/test_smoke_check.py.
    monkeypatch.setattr(verify_artifacts, "smoke_check",
                        lambda p, r=None, artifact="pdf": 0)
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
    # A change outside the authorable set must be refused (release only stages
    # source).
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
    original_toml = (repo / "guide.toml").read_text(encoding="utf-8")

    monkeypatch.setattr(release, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "should not run"])
    # Match the DIAGNOSTIC, and name the file. `pytest.raises(SystemExit)` alone
    # stays green when an unrelated regression makes every release exit early —
    # which is exactly what happened while the clean-state check ran last.
    with pytest.raises(SystemExit, match=r"outside the authorable set(.|\n)*README\.md"):
        release.main()

    # And the refusal mutated nothing: no date write, no transaction, no commit.
    assert (repo / "guide.toml").read_text(encoding="utf-8") == original_toml
    assert release._read_txn(release._txn_ref("pdf")) is None
    subjects = subprocess.run(
        ["git", "log", "--format=%s"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.split("\n")
    assert [s for s in subjects if s] == ["init"]
