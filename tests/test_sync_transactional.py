"""--apply is transactional: a failure AFTER the first real destination is
replaced rolls everything back (the journal); a dirty TEMPLATE worktree is
refused; destinations are resolved not blindly followed; .template-version is
written last (plan.md:108)."""
import json
import subprocess

import pytest

import sync


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def test_failure_after_first_write_rolls_back(sync_env, monkeypatch):
    env = sync_env()
    # Two real updates so there IS a "first destination" to replace before failing.
    (env.kit / "build.py").write_text("# build.py v2\n", encoding="utf-8")
    (env.kit / "CLAUDE.md").write_text(
        f"# Kit\n{sync.MARK_BEGIN}\nshared policy v2\n{sync.MARK_END}\nkit tail\n", encoding="utf-8"
    )
    _commit(env.kit, "kit v2 two files")

    before = {p: (env.target / p).read_bytes() for p in ("build.py", "CLAUDE.md")}
    tv_before = (env.target / ".template-version").read_bytes()

    # Inject a failure AFTER the first destination has been replaced.
    def _boom(n):
        if n == 1:
            raise RuntimeError("injected I/O failure after first write")
    monkeypatch.setattr(sync, "AFTER_WRITE_HOOK", _boom)

    with pytest.raises(RuntimeError):
        sync.run_sync(env.kit, env.target, apply=True)

    # Everything is byte-for-byte as before — the journal restored the first write.
    for p, b in before.items():
        assert (env.target / p).read_bytes() == b, f"{p} not rolled back"
    assert (env.target / ".template-version").read_bytes() == tv_before   # written last => untouched


def test_template_version_written_last(sync_env):
    env = sync_env()
    (env.kit / "build.py").write_text("# build.py v2\n", encoding="utf-8")
    _commit(env.kit, "kit v2")
    before_tv = json.loads((env.target / ".template-version").read_text())
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    after_tv = json.loads((env.target / ".template-version").read_text())
    assert after_tv["state"] == "applied"
    # the record now reflects the freshly written bytes
    assert after_tv["rendered_checksums"]["build.py"] == sync._sha256(b"# build.py v2\n")
    assert before_tv["rendered_checksums"]["build.py"] != after_tv["rendered_checksums"]["build.py"]


def test_dirty_template_worktree_refused(sync_env, capsys):
    env = sync_env()
    # Dirty the KIT worktree (uncommitted change) — apply must refuse.
    (env.kit / "build.py").write_text("# uncommitted kit change\n", encoding="utf-8")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    err = capsys.readouterr().err
    assert "KIT" in err or "template" in err


def test_destination_traversal_rejected(sync_env):
    env = sync_env()
    # A manifest whose projected dest escapes the target root must be rejected.
    with pytest.raises(sync.SyncError):
        sync._resolve_dest(env.target, "../escape.txt")


def test_atomic_write_does_not_follow_a_planted_temp_symlink(tmp_path):
    # A predictable temp pathname + symlink-follow would let an attacker redirect
    # a write outside the target. mkstemp uses a UNIQUE name, so a symlink planted
    # at the naive predictable path is never written through.
    d = tmp_path / "repo"
    d.mkdir()
    outside = tmp_path / "OUTSIDE.txt"
    outside.write_bytes(b"protected\n")
    (d / ".foo.sync-tmp").symlink_to(outside)  # the naive predictable temp name
    sync._atomic_write(d / "foo", b"safe data")
    assert outside.read_bytes() == b"protected\n"   # NOT written through the symlink
    assert (d / "foo").read_bytes() == b"safe data"


def test_failure_inside_second_write_rolls_back_first(sync_env, monkeypatch):
    env = sync_env()
    (env.kit / "build.py").write_text("# build.py v2\n", encoding="utf-8")
    (env.kit / "CLAUDE.md").write_text(
        f"# Kit\n{sync.MARK_BEGIN}\nshared policy v2\n{sync.MARK_END}\nkit tail\n", encoding="utf-8"
    )
    _commit(env.kit, "kit v2")
    before = {p: (env.target / p).read_bytes() for p in ("build.py", "CLAUDE.md")}

    real = sync._atomic_write
    calls = {"n": 0}

    def _fake(dest, data):
        calls["n"] += 1
        if calls["n"] == 2:  # fail INSIDE the second real destination write
            raise OSError("injected failure inside the second write")
        return real(dest, data)

    monkeypatch.setattr(sync, "_atomic_write", _fake)
    with pytest.raises(OSError):
        sync.run_sync(env.kit, env.target, apply=True)
    for p, b in before.items():
        assert (env.target / p).read_bytes() == b, f"{p} not rolled back"


def test_dest_symlink_is_replaced_not_followed(tmp_path):
    # If a destination is itself a symlink, sync must REPLACE it (os.replace
    # unlinks the symlink), not follow it to overwrite the referent.
    d = tmp_path / "repo"
    d.mkdir()
    (d / "bar").write_bytes(b"referent - do not touch\n")
    (d / "foo").symlink_to(d / "bar")
    dest = sync._resolve_dest(d, "foo")            # must NOT resolve to bar
    sync._atomic_write(dest, b"new foo content\n")
    assert (d / "bar").read_bytes() == b"referent - do not touch\n"  # referent untouched
    assert (d / "foo").read_bytes() == b"new foo content\n"          # the symlink was replaced
    assert not (d / "foo").is_symlink()


def test_atomic_write_preserves_destination_mode(tmp_path):
    import stat
    f = tmp_path / "file"
    f.write_bytes(b"old")
    f.chmod(0o644)
    sync._atomic_write(f, b"new")
    assert stat.S_IMODE(f.stat().st_mode) == 0o644   # not tightened to mkstemp's 0600
    g = tmp_path / "newfile"
    sync._atomic_write(g, b"x")
    assert stat.S_IMODE(g.stat().st_mode) == 0o644   # sane default for a new file


def test_metadata_write_failure_rolls_back_all_files(sync_env, monkeypatch):
    env = sync_env()
    (env.kit / "build.py").write_text("# build.py v2\n", encoding="utf-8")
    _commit(env.kit, "kit v2")
    before = (env.target / "build.py").read_bytes()
    tv_before = (env.target / ".template-version").read_bytes()

    real = sync._atomic_write

    def _fake(dest, data):
        if dest.name == sync.TEMPLATE_VERSION:
            raise OSError("injected metadata write failure")
        return real(dest, data)

    monkeypatch.setattr(sync, "_atomic_write", _fake)
    with pytest.raises(OSError):
        sync.run_sync(env.kit, env.target, apply=True)
    assert (env.target / "build.py").read_bytes() == before          # file rolled back
    assert (env.target / ".template-version").read_bytes() == tv_before  # record unchanged
