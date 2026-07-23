"""`make baseline` / `make release` refuse a platform mismatch before mutating
anything, keyed on guide.toml's baseline_platform, with a loud override
(plan.md:102, :172). Keyed on the recorded platform — never hardcoded to macOS.
"""
import subprocess
import sys
from pathlib import Path

import pytest

import baseline
import kitconfig
import release

REPO_ROOT = Path(__file__).resolve().parent.parent
SLUG = "probe-guide"


def _toml(platform: str) -> str:
    return (
        'TITLE = "Probe"\n'
        f'OUTPUT_SLUG = "{SLUG}"\n'
        'AUTHOR = "T"\n'
        'DESCRIPTION = "d"\n'
        'KEYWORDS = "k"\n'
        'COPYRIGHT_YEAR = 2026\n'
        f'baseline_platform = "{platform}"\n'
    )


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _mkrepo(tmp_path, platform, dirty=False):
    (tmp_path / "guide.toml").write_text(_toml(platform), encoding="utf-8")
    for name in kitconfig.SOURCE_FILES:
        if name not in ("guide.toml", "transforms.py"):
            (tmp_path / name).write_text(f"seed-{name}\n", encoding="utf-8")
    (tmp_path / f"{SLUG}.pdf").write_bytes(b"%PDF-reference")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "clean")
    if dirty:
        (tmp_path / "guide.md").write_text("seed-guide.md\ndirtied\n", encoding="utf-8")
    return tmp_path


def _other_platform() -> str:
    # A platform value guaranteed to differ from this host's sys.platform.
    return "darwin" if sys.platform != "darwin" else "linux"


# ----- unit: the matcher itself -----

def test_matcher_true_when_equal(tmp_path):
    repo = _mkrepo(tmp_path, sys.platform)
    ok, _ = kitconfig.baseline_platform_matches(repo)
    assert ok


def test_matcher_false_when_different(tmp_path):
    repo = _mkrepo(tmp_path, _other_platform())
    ok, msg = kitconfig.baseline_platform_matches(repo)
    assert not ok
    assert sys.platform in msg and _other_platform() in msg


# ----- baseline -----

def test_baseline_refuses_platform_mismatch_and_leaves_pdf(tmp_path, monkeypatch):
    repo = _mkrepo(tmp_path, _other_platform())
    reference = repo / f"{SLUG}.pdf"
    before = reference.read_bytes()
    monkeypatch.setattr(baseline, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["baseline.py"])
    with pytest.raises(SystemExit) as exc:
        baseline.main()
    msg = str(exc.value)
    assert sys.platform in msg and _other_platform() in msg
    assert reference.read_bytes() == before
    assert not (repo / "build").exists()  # refused before building


def test_baseline_override_bypasses_platform_guard(tmp_path, monkeypatch):
    # With the override, the platform guard is skipped — proven by reaching the
    # dirty guard (a dirty tree) and failing THERE, not on platform.
    repo = _mkrepo(tmp_path, _other_platform(), dirty=True)
    monkeypatch.setattr(baseline, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["baseline.py", "--allow-platform-mismatch"])
    with pytest.raises(SystemExit) as exc:
        baseline.main()
    msg = str(exc.value)
    assert "dirty" in msg
    assert "platform mismatch" not in msg


# ----- release -----

def test_release_refuses_platform_mismatch_before_commit(tmp_path, monkeypatch):
    repo = _mkrepo(tmp_path, _other_platform())
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(release, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "should not commit"])
    with pytest.raises(SystemExit) as exc:
        release.main()
    assert sys.platform in str(exc.value) and _other_platform() in str(exc.value)
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before  # no commit


# ----- wiring -----

def test_makefile_wires_baseline_to_baseline_py():
    out = subprocess.run(
        ["make", "-n", "baseline"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout
    assert "baseline.py" in out
