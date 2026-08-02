"""Sync refuses unreviewed local work, by name — for identical AND
templated tiers; a managed-region edit OUTSIDE the markers does NOT block; and an
existing destination absent from rendered_checksums is refused."""
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


def test_an_edit_INSIDE_the_markers_is_overwritten_not_refused(sync_env, capsys):
    """The one thing every guide's CLAUDE.md tells its reader about this block.

    Both `CLAUDE.md` files say editing inside `kit:begin`/`kit:end` is "wasted
    work — the next sync overwrites it". Sync refused the file instead — and
    because one refusal aborts the whole run, an edited heading in the shared
    block stopped every OTHER file's update from landing too. Measured: one
    stray line inside the region blocked an unrelated `build.py` update.

    Overwriting is the designed behaviour rather than a concession:
    `_checkable_bytes` scopes the comparison to the marked block, which is
    kit-owned, and `_render_managed` rebuilds it from the kit while preserving
    every byte outside the markers. So this asserts BOTH — the region is reset,
    and the guide's own sections are not touched.
    """
    env = sync_env()
    p = env.target / "CLAUDE.md"
    text = p.read_text(encoding="utf-8")
    p.write_text(text.replace(sync.MARK_BEGIN,
                              sync.MARK_BEGIN + "\nAN EDIT INSIDE THE SHARED BLOCK.\n"),
                 encoding="utf-8")
    # ...and an unrelated kit change, to prove the run is not aborted.
    (env.kit / "build.py").write_text("# build.py v2\n", encoding="utf-8")
    _commit(env.kit, "kit moves on")
    _commit(env.target, "edit inside the managed region")

    items, _, _ = sync.build_plan(env.kit, env.target)
    by_dest = {it.dest_rel: it for it in items}
    assert by_dest["CLAUDE.md"].action == "update", by_dest["CLAUDE.md"].action
    assert "reset from the kit" in by_dest["CLAUDE.md"].reason, "the reset is silent"
    assert by_dest["build.py"].action == "update", (
        "one edited managed region still blocks an unrelated file's update")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    after = p.read_text(encoding="utf-8")
    assert "AN EDIT INSIDE THE SHARED BLOCK." not in after
    assert "TARGET-OWNED section the guide maintains." in after, (
        "the guide's own text outside the markers was destroyed")
    assert (env.target / "build.py").read_text(encoding="utf-8") == "# build.py v2\n"
