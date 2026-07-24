"""Sync never deletes: files/dirs present in a target but absent from the
manifest survive --apply (plan.md:81)."""
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
