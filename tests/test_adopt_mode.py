"""First contact requires --adopt; --adopt refuses a dirty tree, prints the
inventory, requires confirmation, and records accepted pre-sync hashes."""
import json
import subprocess

import pytest

import sync

REPO = "rosslevinsky/guide-template"


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def _unadopt(env):
    (env.target / ".template-version").unlink()
    _commit(env.target, "unadopted")
    return env


def test_first_contact_requires_adopt(sync_env):
    env = _unadopt(sync_env())
    assert sync.run_sync(env.kit, env.target, apply=False) == sync.EXIT_NEEDS_ADOPT


def test_adopt_refuses_dirty_worktree(sync_env):
    env = _unadopt(sync_env())
    (env.target / "build.py").write_text("uncommitted local edit\n", encoding="utf-8")  # dirty
    with pytest.raises(sync.SyncError):
        sync.adopt(env.kit, env.target, REPO, "v1", assume_yes=True)


def test_adopt_records_presync_hashes_and_state(sync_env, capsys):
    env = _unadopt(sync_env())
    assert sync.adopt(env.kit, env.target, REPO, "v1", assume_yes=True) == sync.EXIT_OK
    tv = json.loads((env.target / ".template-version").read_text())
    # adoption writes the COMPLETE schema (not just the fields the fixture had).
    for k in ("schema_version", "source_repo", "kit_version", "managed_digest", "state", "rendered_checksums"):
        assert k in tv, f"adopt() omitted {k}"
    assert tv["schema_version"] == sync.SCHEMA_VERSION
    assert tv["managed_digest"] == sync.compute_managed_digest(env.kit)
    assert tv["state"] == "adopted_unapplied"
    assert tv["source_repo"] == REPO
    assert tv["kit_version"] == "v1"
    # pre-sync hash equals the target's CURRENT (legacy) content, not the kit's
    assert tv["rendered_checksums"]["build.py"] == sync._sha256(
        sync._checkable_bytes("identical", (env.target / "build.py").read_bytes())
    )
    assert "will manage" in capsys.readouterr().out  # per-file inventory printed


def test_adopt_requires_confirmation(sync_env):
    env = _unadopt(sync_env())
    rc = sync.adopt(env.kit, env.target, REPO, "v1", assume_yes=False, confirm=lambda _p: "n")
    assert rc == sync.EXIT_DRIFT
    assert not (env.target / ".template-version").exists()  # nothing written on decline


def test_adopt_refuses_when_already_adopted(sync_env):
    env = sync_env()  # already has .template-version
    with pytest.raises(sync.SyncError):
        sync.adopt(env.kit, env.target, REPO, "v1", assume_yes=True)
