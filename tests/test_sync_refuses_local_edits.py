"""Sync refuses unreviewed local work, by name (plan.md:114) — for identical AND
templated tiers; a managed-region edit OUTSIDE the markers does NOT block; and an
existing destination absent from rendered_checksums is refused (plan.md:109)."""
import subprocess

import sync


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def test_local_edit_to_identical_file_is_refused_by_name(sync_env, capsys):
    env = sync_env()
    (env.target / "build.py").write_text("# HAND-EDITED build.py\n", encoding="utf-8")
    _commit(env.target, "local edit")
    rc = sync.run_sync(env.kit, env.target, apply=True)
    assert rc == sync.EXIT_DRIFT
    assert "build.py" in capsys.readouterr().err
    # refused before writing: the hand edit is still there.
    assert (env.target / "build.py").read_text() == "# HAND-EDITED build.py\n"


def test_local_edit_to_templated_file_is_refused(sync_env, capsys):
    env = sync_env()
    (env.target / "pixi.toml").write_text('name = "probe-guide"\n# desc\nlocal = "add"\n', encoding="utf-8")
    _commit(env.target, "local pixi edit")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    assert "pixi.toml" in capsys.readouterr().err


def test_managed_region_edit_outside_markers_does_not_block(sync_env):
    env = sync_env()
    # Edit the target's OWN section outside the markers — must not block sync.
    claude = env.target / "CLAUDE.md"
    claude.write_text(claude.read_text() + "\nAnother target-owned paragraph.\n", encoding="utf-8")
    _commit(env.target, "guide edits its own CLAUDE section")
    # Also advance the kit's managed block so there is a real update to apply.
    (env.kit / "CLAUDE.md").write_text(
        f"# Kit\n{sync.MARK_BEGIN}\nshared policy v2\n{sync.MARK_END}\nkit tail\n", encoding="utf-8"
    )
    _commit(env.kit, "kit block v2")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    out = claude.read_text()
    assert "shared policy v2" in out                     # block updated
    assert "Another target-owned paragraph." in out       # the guide's edit preserved


def test_existing_unrecorded_destination_is_refused(sync_env, capsys):
    env = sync_env()
    # Drop build.py from rendered_checksums: it exists but is unrecorded.
    import json
    tv = json.loads((env.target / ".template-version").read_text())
    del tv["rendered_checksums"]["build.py"]
    (env.target / ".template-version").write_text(json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "drop build.py from checksums")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    err = capsys.readouterr().err
    assert "build.py" in err and "adopt" in err.lower()
