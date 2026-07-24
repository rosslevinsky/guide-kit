"""Dry-run is the default: sync reports drift and writes NOTHING (plan.md:107)."""
import sync


def test_dry_run_writes_nothing_even_when_drifted(sync_env, capsys):
    env = sync_env()
    # Introduce drift: the kit's build.py moves ahead of the target's.
    (env.kit / "build.py").write_text("# build.py v2\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "-A"], cwd=env.kit, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "kit v2"], cwd=env.kit, check=True, capture_output=True)

    before = (env.target / "build.py").read_bytes()
    rc = sync.run_sync(env.kit, env.target, apply=False)

    assert rc == sync.EXIT_DRIFT                       # drift => nonzero
    assert (env.target / "build.py").read_bytes() == before   # nothing written
    assert "would update" in capsys.readouterr().out


def test_dry_run_in_sync_exits_zero(sync_env, capsys):
    env = sync_env()
    rc = sync.run_sync(env.kit, env.target, apply=False)
    assert rc == sync.EXIT_OK
    assert "in sync" in capsys.readouterr().out


def test_needs_adopt_when_no_template_version(sync_env):
    env = sync_env()
    (env.target / ".template-version").unlink()
    import subprocess
    subprocess.run(["git", "add", "-A"], cwd=env.target, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "drop tv"], cwd=env.target, check=True, capture_output=True)
    assert sync.run_sync(env.kit, env.target, apply=False) == sync.EXIT_NEEDS_ADOPT
