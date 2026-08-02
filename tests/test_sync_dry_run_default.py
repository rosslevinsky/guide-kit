"""Dry-run is the default: sync reports drift and writes NOTHING."""
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


def test_a_bare_name_is_a_sibling_and_a_path_is_a_path(tmp_path, monkeypatch):
    """The workspace layout was an unwritten assumption in one expression.

    `sync.py` resolved its argument as `kit_root.parent / guide` and nothing
    else, so a guide checked out anywhere but beside the kit failed with a
    message naming a path the operator never typed — and no document stated the
    layout: `README.md` shows `python sync.py <guide>` and says nothing about
    where `<guide>` has to live.

    A bare name keeps meaning "sibling", because that IS this family's layout and
    every existing invocation relies on it. Anything path-shaped is taken as
    written.
    """
    kit = tmp_path / "workspace" / "guide-kit"
    kit.mkdir(parents=True)

    assert sync._resolve_target(kit, "my-guide") == tmp_path / "workspace" / "my-guide"

    elsewhere = tmp_path / "elsewhere" / "far-guide"
    elsewhere.mkdir(parents=True)
    assert sync._resolve_target(kit, str(elsewhere)) == elsewhere
    assert sync._resolve_target(kit, "../elsewhere/far-guide") != \
        tmp_path / "workspace" / "../elsewhere/far-guide"

    # A relative path with a separator resolves against the CWD, not the kit.
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert sync._resolve_target(kit, "./far-guide") == elsewhere
