"""Sync never deletes what it did not write: files/dirs present in a target but
absent from the manifest survive --apply.

Sync does delete, in two narrow cases — a file gone from a managed TREE, and a
destination whose LITERAL manifest entry the kit removed. Both are gated on the
destination being RECORDED in `.template-version`, i.e. on sync having written it.
This file is the standing statement of the other side of that gate, and neither
deletion path may weaken it."""
import json
import subprocess

import sync


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def test_unknown_file_and_dir_survive_apply(sync_env):
    env = sync_env()
    # Target-only content the kit knows nothing about (like git-guide/prompts/).
    (env.target / "prompts").mkdir()
    (env.target / "prompts" / "note.md").write_text("guide-only\n", encoding="utf-8")
    (env.target / "EXTRA.txt").write_text("only in the target\n", encoding="utf-8")
    _commit(env.target, "target extras")

    # Drive a real update so --apply actually writes something.
    (env.kit / "build.py").write_text("# build.py v2\n", encoding="utf-8")
    _commit(env.kit, "kit v2")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "prompts" / "note.md").read_text() == "guide-only\n"
    assert (env.target / "EXTRA.txt").read_text() == "only in the target\n"
    assert (env.target / "build.py").read_text() == "# build.py v2\n"   # the update did land


def test_an_unrecorded_file_at_a_removed_entrys_path_is_never_deleted(sync_env):
    """Sync now deletes a destination whose LITERAL manifest entry the kit has
    removed (`tests/test_sync_literal_deletion.py`). That path must not open a
    hole in this promise: an UNRECORDED file is one sync never wrote, so it is
    one a guide put there, and the removed entry says nothing about it."""
    env = sync_env()
    # build.py is recorded; drop the record so the file is target-authored as far
    # as the inventory is concerned, then remove its manifest entry upstream.
    tv = json.loads((env.target / ".template-version").read_text(encoding="utf-8"))
    del tv["rendered_checksums"]["build.py"]
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    (env.target / "build.py").write_text("# the guide's own build.py\n", encoding="utf-8")
    _commit(env.target, "an unrecorded file at the path")

    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    (env.kit / "kit-manifest.toml").write_text(
        manifest.replace(
            '[[entry]]\npath = "build.py"\nlifecycle = "retained-in-kit"\n'
            'projects_to = "build.py"\npolicy = "identical"\n', ""),
        encoding="utf-8")
    _commit(env.kit, "unclassify build.py")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "build.py").read_text() == "# the guide's own build.py\n", \
        "sync deleted a file it never wrote"
