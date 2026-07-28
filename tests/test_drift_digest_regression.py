"""The computed managed-content digest closes the silent-staleness hole: an
upstream managed-byte change WITHOUT a kit_version bump still reports drift. Also:
adopted_unapplied reads as behind, and a local edit reads as drift."""
import json
import subprocess

import sync


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def _set_tv(env, **over):
    tv = json.loads((env.target / ".template-version").read_text())
    tv.update(over)
    (env.target / ".template-version").write_text(json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "tv")


def test_upstream_change_without_version_bump_still_drifts(sync_env):
    env = sync_env()
    _set_tv(env, state="applied", kit_version="v1", managed_digest=sync.compute_managed_digest(env.kit))
    drifted, _ = sync.drift_report(env.kit, env.target)
    assert not drifted  # baseline: in sync

    # Change a MANAGED kit file but do NOT bump kit_version.
    (env.kit / "build.py").write_text("# upstream change, no version bump\n", encoding="utf-8")
    _commit(env.kit, "kit managed change")
    drifted, msgs = sync.drift_report(env.kit, env.target)
    assert drifted, "computed digest must catch the change despite an unchanged kit_version"
    assert any("upstream" in m for m in msgs)


def test_adopted_unapplied_reads_as_behind(sync_env):
    env = sync_env()
    _set_tv(env, state="adopted_unapplied", managed_digest=sync.compute_managed_digest(env.kit))
    drifted, msgs = sync.drift_report(env.kit, env.target)
    assert drifted
    assert any("adopted_unapplied" in m or "behind" in m for m in msgs)


def test_digest_sensitive_to_each_input_class(sync_env):
    env = sync_env(shape="web-enabled")
    base = sync.compute_managed_digest(env.kit)
    assert sync.compute_managed_digest(env.kit) == base  # deterministic

    def _moves(path, mutate):
        orig = path.read_text()
        path.write_text(mutate(orig), encoding="utf-8")
        moved = sync.compute_managed_digest(env.kit) != base
        path.write_text(orig, encoding="utf-8")
        assert sync.compute_managed_digest(env.kit) == base  # restored
        return moved

    # identical source, templated source, and the managed-region BLOCK all move it
    assert _moves(env.kit / "build.py", lambda s: s + "# more\n")
    assert _moves(env.kit / "pixi.toml", lambda s: s + "# more\n")
    assert _moves(env.kit / "CLAUDE.md", lambda s: s.replace("shared policy v1", "shared policy vX"))
    # a substitution ANCHOR (kit guide.toml) moves it
    assert _moves(env.kit / "guide.toml", lambda s: s.replace('"guide-template"', '"guide-kit"'))
    # a POLICY change (identical -> templated in the manifest) moves it
    assert _moves(env.kit / "kit-manifest.toml",
                  lambda s: s.replace('policy = "identical"', 'policy = "templated"', 1))
    # ...but a change OUTSIDE the managed-region markers does NOT (only the block counts)
    assert not _moves(env.kit / "CLAUDE.md", lambda s: s.replace("kit-only tail", "tail CHANGED"))


def test_local_edit_to_managed_file_reads_as_drift(sync_env):
    env = sync_env()
    _set_tv(env, state="applied", managed_digest=sync.compute_managed_digest(env.kit))
    (env.target / "build.py").write_text("# hand-edited away from recorded\n", encoding="utf-8")
    _commit(env.target, "local edit")
    drifted, msgs = sync.drift_report(env.kit, env.target)
    assert drifted
    assert any("local edit" in m for m in msgs)
