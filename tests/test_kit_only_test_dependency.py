"""pytest and the `test` task must stay kit-only.

Root [dependencies]/[tasks] template verbatim into every target's pixi.toml, so
if pytest or a `test` task lived there, all seven sync targets would inherit a
dependency and a task with no suite to run — bare pytest exits non-zero — and
would regenerate their lockfiles just because the kit gained a runner
(plan.md:89, :90). No sync/templating renderer exists yet (Phase 5), so this
asserts the structural placement the later renderer relies on: the runner lives
under the `kit` feature, never at the root.
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


def test_kit_environment_declared(repo_root):
    data = _manifest(repo_root)
    assert "kit" in data.get("environments", {})
    assert "kit" in data["environments"]["kit"]
