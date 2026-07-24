"""adopt-web.py adds the web layer to an existing guide, two-root and safe.

Writes ONLY into --target (never kit_root); idempotent; refuses a non-identical
collision; no transforms.py without --with-transforms; and records every managed
web destination in rendered_checksums — proven by build_plan (the planner
`sync.py <guide>` uses) having NO refusals afterward.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import sync

REPO_ROOT = Path(__file__).resolve().parent.parent
_IGNORE = shutil.ignore_patterns(".git", ".pixi", "build", "__pycache__", "node_modules", "app")

# adopt-web.py has a hyphen (required by the manifest), so load it via importlib.
_spec = importlib.util.spec_from_file_location("adopt_web", REPO_ROOT / "adopt-web.py")
adopt_web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adopt_web)


def _mkkit(dst: Path) -> Path:
    # The kit's real CLAUDE.md already carries the kit:begin/end markers (Phase 9),
    # which bootstrap.py's compute_managed_digest needs — copy it faithfully.
    shutil.copytree(REPO_ROOT, dst, ignore=_IGNORE)
    return dst


def _guide_toml(slug: str) -> str:
    return (
        'TITLE = "T"\n'
        f'OUTPUT_SLUG = "{slug}"\n'
        'AUTHOR = "A"\n'
        'DESCRIPTION = "d"\n'
        'KEYWORDS = "k"\n'
        'COPYRIGHT_YEAR = 2026\n'
        'baseline_platform = "darwin"\n'
    )


def _min_target(dst: Path, slug: str = "min-guide") -> Path:
    dst.mkdir()
    (dst / "guide.toml").write_text(_guide_toml(slug), encoding="utf-8")
    (dst / ".template-version").write_text(json.dumps({
        "schema_version": 1, "source_repo": "rosslevinsky/guide-template", "kit_version": "t",
        "managed_digest": "x", "state": "applied", "rendered_checksums": {},
    }, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@e.com", "-c", "user.name=T", "commit", "-qm", "init"],
                   cwd=dst, check=True, capture_output=True)
    return dst


def _kit_files(kit: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in kit.rglob("*") if p.is_file()}


def test_writes_only_into_target_never_kit(tmp_path):
    kit = _mkkit(tmp_path / "kit")
    target = _min_target(tmp_path / "target")
    before = _kit_files(kit)
    adopt_web.adopt_web(kit, target)
    after = _kit_files(kit)
    assert before == after, "adopt-web mutated kit_root"           # kit untouched, byte-for-byte
    # bootstrap.py still exists in the kit (the two-root failure mode this prevents).
    assert (kit / "bootstrap.py").exists()
    # target got the web layer.
    assert (target / "style-screen.css").exists()
    assert (target / "app" / "wrangler.jsonc").exists()
    assert (target / ".github" / "workflows" / "deploy.yml").exists()
    assert '"name": "min-guide"' in (target / "app" / "wrangler.jsonc").read_text()
    # .gitignore gained the web entries.
    gi = (target / ".gitignore").read_text()
    assert "app/dist/" in gi and "node_modules/" in gi


def test_idempotent_second_run_is_noop(tmp_path):
    kit = _mkkit(tmp_path / "kit")
    target = _min_target(tmp_path / "target")
    assert adopt_web.adopt_web(kit, target) == 0
    tv_before = (target / ".template-version").read_bytes()
    gi_before = (target / ".gitignore").read_bytes()
    wrangler_before = (target / "app" / "wrangler.jsonc").read_bytes()
    assert adopt_web.adopt_web(kit, target) == 0        # 2nd run: no error
    assert (target / "app" / "wrangler.jsonc").read_bytes() == wrangler_before
    assert (target / ".template-version").read_bytes() == tv_before   # byte-stable
    assert (target / ".gitignore").read_bytes() == gi_before          # no duplicate entries
    gi = (target / ".gitignore").read_text()
    assert gi.count("app/dist/") == 1 and gi.count("node_modules/") == 1


def test_rollback_on_mid_write_failure_leaves_target_unchanged(tmp_path, monkeypatch):
    kit = _mkkit(tmp_path / "kit")
    target = _min_target(tmp_path / "target")
    before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}

    def _boom(n):
        if n == 2:  # fail after the second write is in place
            raise OSError("injected failure during adoption")

    monkeypatch.setattr(adopt_web, "AFTER_WRITE_HOOK", _boom)
    with pytest.raises(OSError):
        adopt_web.adopt_web(kit, target)

    # Originally-present files are byte-identical; every newly-written file rolled back.
    for p, b in before.items():
        assert p.read_bytes() == b
    assert not (target / "app" / "wrangler.jsonc").exists()
    assert not (target / "style-screen.css").exists()
    assert not (target / ".github" / "workflows" / "deploy.yml").exists()


def test_refuses_non_identical_collision(tmp_path):
    kit = _mkkit(tmp_path / "kit")
    target = _min_target(tmp_path / "target")
    (target / "style-screen.css").write_text("/* a different, hand-written screen css */\n", encoding="utf-8")
    with pytest.raises(adopt_web.AdoptError):
        adopt_web.adopt_web(kit, target)


def test_transforms_only_with_opt_in(tmp_path):
    kit = _mkkit(tmp_path / "kit")
    t1 = _min_target(tmp_path / "t1")
    adopt_web.adopt_web(kit, t1)
    assert not (t1 / "transforms.py").exists()
    t2 = _min_target(tmp_path / "t2", slug="t2-guide")
    adopt_web.adopt_web(kit, t2, with_transforms=True)
    assert (t2 / "transforms.py").exists()


def test_refuses_without_template_version(tmp_path):
    kit = _mkkit(tmp_path / "kit")
    target = tmp_path / "bare"
    target.mkdir()
    (target / "guide.toml").write_text(_guide_toml("bare-guide"), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=target, check=True, capture_output=True)
    with pytest.raises(adopt_web.AdoptError):
        adopt_web.adopt_web(kit, target)


def test_records_checksums_so_sync_does_not_refuse(tmp_path):
    # A fully-adopted PDF-only fork (via bootstrap), then adopt-web, then confirm
    # the planner sync.py uses has NO refusals — proving the web dests were recorded.
    kit = _mkkit(tmp_path / "kit")
    fork = _mkkit(tmp_path / "fork")
    r = subprocess.run(
        [sys.executable, str(fork / "bootstrap.py"), "Mac Guide", "mac-guide",
         "--baseline-platform", "darwin", "--source-repo", "rosslevinsky/guide-template", "--kit-version", "t"],
        cwd=fork, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    subprocess.run(["git", "init", "-q"], cwd=fork, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=fork, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@e.com", "-c", "user.name=T", "commit", "-qm", "init"],
                   cwd=fork, check=True, capture_output=True)

    adopt_web.adopt_web(kit, fork)

    items, _, _ = sync.build_plan(kit, fork)
    refusals = [(it.dest_rel, it.reason) for it in items if it.action == "refuse"]
    assert not refusals, refusals   # no managed web dest refused for being unrecorded
