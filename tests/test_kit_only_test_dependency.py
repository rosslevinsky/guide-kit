"""pytest and the `test` task must stay kit-only.

Root [dependencies]/[tasks] template verbatim into every target's pixi.toml, so
if pytest or a `test` task lived there, all seven sync targets would inherit a
dependency and a task with no suite to run — bare pytest exits non-zero — and
would regenerate their lockfiles just because the kit gained a runner. This
asserts the structural placement the templating renderer relies on: the runner
lives under the `kit` feature, never at the root.
"""
import tomllib


def _manifest(repo_root):
    return tomllib.loads((repo_root / "pixi.toml").read_text(encoding="utf-8"))


def test_pytest_not_in_root_dependencies(repo_root):
    data = _manifest(repo_root)
    assert "pytest" not in data.get("dependencies", {})


def test_test_task_not_in_root_tasks(repo_root):
    data = _manifest(repo_root)
    assert "test" not in data.get("tasks", {})


def test_pytest_lives_in_kit_feature(repo_root):
    data = _manifest(repo_root)
    assert "pytest" in data["feature"]["kit"]["dependencies"]


def test_test_task_lives_in_kit_feature(repo_root):
    data = _manifest(repo_root)
    assert "test" in data["feature"]["kit"]["tasks"]


def _features(env):
    """`environments` accepts both a bare feature list and a table. The table
    form is what carries `solve-group`, so this reads either."""
    return env if isinstance(env, list) else env.get("features", [])


def test_kit_environment_declared(repo_root):
    data = _manifest(repo_root)
    assert "kit" in data.get("environments", {})
    assert "kit" in _features(data["environments"]["kit"])


def test_both_environments_share_one_solve_group(repo_root):
    """The suite must run on the toolchain the kit SHIPS.

    Solved independently, `pixi.lock` recorded two: `default` — behind `make`,
    `make baseline`, `make release` and the drift canary — resolved WeasyPrint
    67.0 / pandoc 3.9.0.2 / fontconfig 2.18.0 / Python 3.14.5, while `kit`, which
    runs pytest, resolved WeasyPrint 69.0 / pandoc 3.10 / fontconfig 2.18.2 /
    Python 3.14.6. Every rendering assertion in this suite — glyph coverage, the
    font audit, the rendered face set, the stamp grammar, wide blocks — was
    therefore measured against a renderer nobody ships, and it was committed, so
    CI reproduced the split faithfully.

    Asserted on the manifest rather than by comparing the two environments'
    resolved versions, because the lockfile is the artifact that has to say it:
    a joint solve is the mechanism, and two environments that merely happen to
    agree today would drift apart at the next `pixi update`.
    """
    envs = _manifest(repo_root)["environments"]
    assert isinstance(envs.get("default"), dict), (
        "the default environment must be declared explicitly to carry a "
        "solve-group; an implicit default is solved on its own"
    )
    groups = {name: env.get("solve-group") for name, env in envs.items()
              if isinstance(env, dict)}
    assert None not in groups.values(), f"an environment has no solve group: {groups}"
    assert len(set(groups.values())) == 1, (
        f"the environments are solved separately, so the suite can run on a "
        f"different renderer than `make` ships: {groups}"
    )
