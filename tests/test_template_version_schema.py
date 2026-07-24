""".template-version round-trips the full record; --apply transitions
adopted_unapplied -> applied and refreshes the managed digest."""
import json
import subprocess

import sync

_FIELDS = ("schema_version", "source_repo", "kit_version", "managed_digest", "state", "rendered_checksums")


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def test_apply_clears_adopted_unapplied_and_refreshes_digest(sync_env):
    env = sync_env()
    tv = json.loads((env.target / ".template-version").read_text())
    tv["state"] = "adopted_unapplied"
    tv["managed_digest"] = "stale-digest"
    (env.target / ".template-version").write_text(json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "adopted_unapplied")
    (env.kit / "build.py").write_text("# build.py v2\n", encoding="utf-8")
    _commit(env.kit, "kit v2")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    after = json.loads((env.target / ".template-version").read_text())
    assert all(k in after for k in _FIELDS)                 # full schema round-trips
    assert after["state"] == "applied"                       # transitioned
    assert after["managed_digest"] == sync.compute_managed_digest(env.kit)  # refreshed to current
