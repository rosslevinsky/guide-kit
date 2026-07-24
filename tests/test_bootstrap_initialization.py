"""bootstrap.py initializes a fork into a correct, honest, ZERO-DRIFT state.

Two checkpoints (plan.md:276): immediately after bootstrap there are ZERO root
reference PDFs; after a (simulated) macOS release there is exactly one. Also:
--baseline-platform is required non-interactively and recorded; the fork emits
guide.toml + .template-version; transforms.py is absent without --with-transforms;
and the freshly bootstrapped fork reports zero drift against a pristine kit (its
templated files carry the fork's identity, not the kit's).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import kitconfig
import sync

REPO_ROOT = Path(__file__).resolve().parent.parent
_IGNORE = shutil.ignore_patterns(".git", ".pixi", "build", "__pycache__", "node_modules", "app")


def _mkcopy(dst: Path) -> Path:
    """A --template-style copy of the kit. The kit's real CLAUDE.md already carries
    the kit:begin/end markers (Phase 9), which compute_managed_digest needs — so the
    copy is faithful with no synthetic marker injection."""
    shutil.copytree(REPO_ROOT, dst, ignore=_IGNORE)
    # Guard: the fixture is only valid while the kit ships exactly one marker pair.
    claude = (dst / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.count(sync.MARK_BEGIN) == 1 and claude.count(sync.MARK_END) == 1, \
        "kit CLAUDE.md must carry exactly one managed-region marker pair"
    return dst


def _run_bootstrap(fork: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(fork / "bootstrap.py"), "Fork Guide", "fork-guide", *extra],
        cwd=fork, capture_output=True, text=True,
    )


def test_bootstrap_requires_baseline_platform_noninteractively(tmp_path):
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork)  # no --baseline-platform, no TTY
    assert r.returncode != 0
    assert "baseline-platform" in (r.stderr + r.stdout)
    # refused before writing: guide.toml is still the kit's, sentinel still present
    assert kitconfig.load(fork).OUTPUT_SLUG == "guide-template"
    assert (fork / ".template-uninitialized").exists()


def test_bootstrap_full_initialization_zero_drift(tmp_path):
    pristine = _mkcopy(tmp_path / "kit")        # stands in for source_repo at check time
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork, "--baseline-platform", "darwin",
                       "--source-repo", "rosslevinsky/guide-template", "--kit-version", "test")
    assert r.returncode == 0, r.stderr

    # guide.toml written with the fork's identity + the recorded platform.
    cfg = kitconfig.load(fork)
    assert cfg.OUTPUT_SLUG == "fork-guide"
    assert cfg.TITLE == "Fork Guide"
    assert cfg.baseline_platform == "darwin"

    # CHECKPOINT 1: zero root reference PDFs (inherited guide-template.pdf deleted).
    assert list(fork.glob("*.pdf")) == []

    # transforms.py NOT activated (no --with-transforms), and no web layer.
    assert not (fork / "transforms.py").exists()
    assert not (fork / "style-screen.css").exists()

    # templated files carry the FORK's identity (pixi project name), not the kit's.
    assert 'name = "fork-guide"' in (fork / "pixi.toml").read_text()

    # .template-version: full record, state applied.
    tv = json.loads((fork / ".template-version").read_text())
    for k in ("schema_version", "source_repo", "kit_version", "managed_digest", "state", "rendered_checksums"):
        assert k in tv
    assert tv["state"] == "applied"
    assert tv["source_repo"] == "rosslevinsky/guide-template"

    # bootstrap self-deleted and removed the sentinel.
    assert not (fork / "bootstrap.py").exists()
    assert not (fork / ".template-uninitialized").exists()

    # ZERO DRIFT against the pristine kit — the fork is genuinely in sync.
    drifted, msgs = sync.drift_report(pristine, fork)
    assert not drifted, msgs
    # The genuine cross-check: the real planner `sync.py <fork>` uses. This proves
    # bootstrap rendered every file BYTE-IDENTICALLY to what sync would produce
    # (drift_report's local loop is self-referential against bootstrap's own record).
    items, _, _ = sync.build_plan(pristine, fork)
    assert all(it.action == "in-sync" for it in items), [(i.dest_rel, i.action) for i in items if i.action != "in-sync"]

    # CHECKPOINT 2 (simulated macOS release): after the first baseline there is
    # exactly one root reference PDF.
    (fork / "fork-guide.pdf").write_bytes(b"%PDF-fork-baseline")
    assert [p.name for p in fork.glob("*.pdf")] == ["fork-guide.pdf"]


def test_bootstrap_with_web_but_no_transforms(tmp_path):
    pristine = _mkcopy(tmp_path / "kit")
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork, "--baseline-platform", "linux", "--with-web")
    assert r.returncode == 0, r.stderr
    # web layer materialized, but transforms.py stays absent (the terminal-guide case).
    assert (fork / "style-screen.css").exists()
    assert (fork / "app" / "wrangler.jsonc").exists()
    assert (fork / ".github" / "workflows" / "deploy.yml").exists()
    assert not (fork / "transforms.py").exists()
    # the worker name is the fork's slug, rendered by value-substitution (matches sync).
    assert '"name": "fork-guide"' in (fork / "app" / "wrangler.jsonc").read_text()
    assert "{{GUIDE_SLUG}}" not in (fork / "app" / "wrangler.jsonc").read_text()
    # a fresh web fork also reports ZERO drift (incl. app/wrangler.jsonc).
    drifted, msgs = sync.drift_report(pristine, fork)
    assert not drifted, msgs
    items, _, _ = sync.build_plan(pristine, fork)
    assert all(it.action == "in-sync" for it in items), [(i.dest_rel, i.action) for i in items if i.action != "in-sync"]
