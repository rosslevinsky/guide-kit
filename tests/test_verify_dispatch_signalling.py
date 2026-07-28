"""The auto-baseline step REPORTS its failures — it does not just annotate them.

WHY THIS FILE EXISTS. `verify.yml` used to go red whenever the committed
reference PDF was stale, including the ordinary case where a push to the default
branch had just made it stale on purpose. That red was noise: it arrived by email
on every content push, so the signal that meant "something is actually wrong" and
the signal that meant "you edited the guide" were the same colour. The fix was to
recognise the expected case and exit 0 after dispatching the rebuild.

That fix removed a red that was ALSO, incidentally, the only thing reporting a
genuinely broken dispatch. The step's last statement was:

    if gh workflow run baseline.yml ...; then
      echo "::notice::dispatched"
    else
      echo "::error::dispatching FAILED"    # <- and nothing else
    fi

A shell `if` takes the status of the last command it ran, so the else-branch's
status is `echo`'s: zero. The STEP therefore succeeded whether or not the
dispatch did. While the staleness check still exited 1 the job was red anyway and
the hole was invisible. Take that cover away and the failure mode is total and
silent: verify reports GREEN, no baseline run is queued, `deploy.yml` keeps
skipping on a reference nothing will ever refresh, and the site serves the old
PDF indefinitely with every check on the repo passing.

An `::error::` annotation does not fail a step. That is the whole defect, and it
is invisible to every test that reads the YAML for shape rather than running it.

SO THESE TESTS RUN THE SCRIPT. The step's `run:` body is extracted from the
parsed workflow and executed with `gh` and `git` stubbed on PATH, so the branch
under test is reached hermetically and no network or repository state is
involved. What is asserted is the EXIT STATUS, because the exit status is the
entire contract between this step and GitHub.

A test that asserted the presence of the string `exit 1` would pass on a script
where that line was unreachable, and would fail on a correct rewrite that used
`set -e` or `||` instead. The status is the thing that matters, so the status is
what is measured.

AND IT RUNS UNDER THE RUNNER'S SHELL, NOT `bash -c`. This is the second lesson
here and it cost a real defect. GitHub runs `shell: bash` as
`bash --noprofile --norc -eo pipefail`; the first version of this file used plain
`bash -c`, and under that shell the lockfile guard's
`printf ... | grep -q pixi.lock` passed its test while FAILING OPEN on the
runner: `grep -q` exits at the match, `printf` takes SIGPIPE, and `pipefail`
makes the pipeline status 141 — false exactly when the lockfile WAS found. A
harness that does not reproduce the execution environment does not test the
thing that runs. See test_the_lockfile_guard_survives_a_large_push.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY = REPO_ROOT / ".github/workflows/verify.yml"

STEP_NAME = "Rebuild the reference PDF (auto-dispatch baseline)"


def _dispatch_script() -> str:
    """The `run:` body of the auto-baseline step, from the PARSED workflow.

    Parsed rather than sliced out of the raw text: a YAML block scalar's real
    content is the parser's business, and a regex over the file would silently
    pick up an indentation change."""
    doc = yaml.safe_load(VERIFY.read_text(encoding="utf-8"))
    steps = doc["jobs"]["verify"]["steps"]
    for step in steps:
        if step.get("name") == STEP_NAME:
            return step["run"]
    raise AssertionError(
        f"no step named {STEP_NAME!r} in verify.yml — if it was renamed, update "
        f"STEP_NAME here; this test is worthless if it silently matches nothing"
    )


# EXACTLY what GitHub runs for `shell: bash`, per the workflow-syntax reference.
# Not `bash -c`. The difference is not cosmetic: `-o pipefail` changes the status
# of any pipeline whose left side dies of SIGPIPE, and `-e` aborts on the first
# unchecked failure. A harness without these passes scripts the runner would fail
# and — worse, and it happened here — passes a script whose SAFETY GUARD the
# runner silently inverts. See test_the_lockfile_guard_survives_a_large_push.
RUNNER_SHELL = ["bash", "--noprofile", "--norc", "-eo", "pipefail"]


def _run(tmp_path: Path, script: str, *, gh_exit: int, baseline_yml: bool,
         changed: str = "guide.md", git_exit: int = 0) -> subprocess.CompletedProcess:
    """Execute the step body under the runner's shell, with `gh` and `git` stubbed.

    `git diff --name-only` is stubbed to report `changed`, so the pixi.lock refusal
    branch is exercised by choosing what that stub prints rather than by building a
    real repository — the branch under test is the dispatch, not git. `git_exit`
    drives the unresolved-range branch (a first push or a force-push, where the
    range genuinely cannot be diffed)."""
    work = tmp_path / "work"
    (work / ".github/workflows").mkdir(parents=True, exist_ok=True)
    if baseline_yml:
        (work / ".github/workflows/baseline.yml").write_text("name: baseline\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    # A marker file, so a test can assert `gh` was never REACHED — distinct from
    # asserting it failed. A guard that refuses must refuse before dispatching.
    gh = bin_dir / "gh"
    gh.write_text(f"#!/usr/bin/env bash\ntouch {str(tmp_path / 'gh-was-called')!r}\nexit {gh_exit}\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    # `git diff --name-only "$BEFORE" "$AFTER"` -> the changed-file list.
    #
    # The list goes through a FILE the stub `cat`s, not through an interpolated
    # literal. `repr()` of a multi-line Python string renders newlines as the two
    # characters `\` `n`, and inside bash single quotes those stay literal — so an
    # interpolated multi-line fixture reached `grep -qx` as ONE long line, matched
    # nothing, and made a fail-open look like a pass. A file has no quoting layer.
    changed_file = tmp_path / "changed.txt"
    changed_file.write_text(changed if changed.endswith("\n") else changed + "\n")
    git = bin_dir / "git"
    git.write_text(
        f"#!/usr/bin/env bash\ncat {str(changed_file)!r}\nexit {git_exit}\n")
    git.chmod(git.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["REF"] = "main"
    env["BEFORE"] = "1111111111111111111111111111111111111111"
    env["AFTER"] = "2222222222222222222222222222222222222222"
    env["GH_TOKEN"] = "stub"
    return subprocess.run(
        [*RUNNER_SHELL, "-c", script], cwd=work, env=env,
        capture_output=True, text=True,
    )


def test_a_successful_dispatch_is_green(tmp_path):
    """The whole point of the change: the expected case must NOT go red."""
    r = _run(tmp_path, _dispatch_script(), gh_exit=0, baseline_yml=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "::notice::" in r.stdout


def test_a_failed_dispatch_fails_the_step(tmp_path):
    """THE REGRESSION. `gh workflow run` fails; nothing will refresh the
    reference. An `::error::` annotation alone leaves the step green."""
    r = _run(tmp_path, _dispatch_script(), gh_exit=1, baseline_yml=True)
    assert r.returncode != 0, (
        "dispatching baseline.yml FAILED and the step still succeeded. verify "
        "will report green, no rebuild is queued, and the site keeps serving a "
        "stale PDF with every check passing.\n" + r.stdout + r.stderr
    )
    assert "::error::" in r.stdout


def test_a_stale_reference_with_no_baseline_workflow_fails_the_step(tmp_path):
    """Nothing in the repo can refresh the reference, so this needs a human. It
    reported a `::warning::` and exited 0, which is the same silence."""
    r = _run(tmp_path, _dispatch_script(), gh_exit=0, baseline_yml=False)
    assert r.returncode != 0, (
        "reference is stale and there is no baseline.yml to rebuild it, yet the "
        "step succeeded.\n" + r.stdout + r.stderr
    )


def test_a_lockfile_bump_still_refuses(tmp_path):
    """The pre-existing drift-canary guard, re-asserted here because it shares the exit
    path this file is about: it must keep FAILING, not become a notice."""
    r = _run(tmp_path, _dispatch_script(), gh_exit=0, baseline_yml=True,
             changed="pixi.lock")
    assert r.returncode != 0, r.stdout + r.stderr
    assert "pixi.lock" in r.stdout
    assert not (tmp_path / "gh-was-called").exists(), (
        "refused, but only AFTER dispatching the baseline it was refusing"
    )


def test_the_lockfile_guard_survives_a_large_push(tmp_path):
    """THE REGRESSION THIS HARNESS EXISTS TO CATCH.

    The guard was `printf '%s\\n' "$CHANGED" | grep -qx 'pixi.lock'`. Under the
    runner's `-o pipefail`, `grep -q` exits at the match, `printf` takes SIGPIPE,
    and the PIPELINE's status becomes 141 — so the condition is FALSE exactly when
    the lockfile WAS found. The guard fails open, a baseline is dispatched on a
    lockfile bump, and the dependency-driven typography change is committed into
    the deliverable alongside the content change with nothing ever reporting it.

    It needs the changed-file list to exceed the pipe buffer before the match, so
    a small fixture cannot see it — this one is ~64k paths with `pixi.lock` early.
    Under plain `bash -c` this test passes against the BROKEN script, which is
    precisely why RUNNER_SHELL is not a detail."""
    changed = "\n".join(["pixi.lock"] + [f"docs/chapter-{i:05d}.md" for i in range(64_000)])
    r = _run(tmp_path, _dispatch_script(), gh_exit=0, baseline_yml=True,
             changed=changed)
    assert r.returncode != 0, (
        "a push carrying pixi.lock plus a large file list was auto-baselined — "
        "the lockfile guard failed open.\n" + r.stdout[-2000:] + r.stderr[-2000:]
    )
    assert not (tmp_path / "gh-was-called").exists(), (
        "the baseline was dispatched despite the lockfile bump"
    )


def test_an_unresolvable_commit_range_refuses_before_dispatching(tmp_path):
    """`github.event.before` is the all-zero SHA on a branch's first push and a
    discarded commit after a force-push; `git diff` errors in both cases. The
    guard must FAIL CLOSED — continuing would auto-baseline precisely when it
    cannot show the lockfile is unchanged."""
    r = _run(tmp_path, _dispatch_script(), gh_exit=0, baseline_yml=True, git_exit=1)
    assert r.returncode != 0, r.stdout + r.stderr
    assert not (tmp_path / "gh-was-called").exists(), (
        "the range could not be resolved, yet a baseline was dispatched anyway"
    )


@pytest.mark.parametrize(
    "case,kwargs",
    [
        ("failed dispatch", dict(gh_exit=1, baseline_yml=True)),
        ("no baseline.yml", dict(gh_exit=0, baseline_yml=False)),
        ("unresolvable range", dict(gh_exit=0, baseline_yml=True, git_exit=1)),
        ("lockfile bump", dict(gh_exit=0, baseline_yml=True, changed="pixi.lock")),
    ],
)
def test_each_failure_test_can_fail(tmp_path, case, kwargs):
    """Mutation check, PER FAILURE PATH. Strip every `exit 1` from the step body
    and each refusal above must stop holding.

    Done per-case rather than in aggregate because an aggregate check is passed by
    a single sensitive path while the others are inert: removing only the `exit 1`
    after a failed `git diff` left a script that still returned nonzero through the
    `gh` branch, so the suite stayed green with that guard gone."""
    mutated = "\n".join(
        line for line in _dispatch_script().splitlines()
        if line.strip() != "exit 1"
    )
    r = _run(tmp_path, mutated, **kwargs)
    assert r.returncode == 0, (
        f"removing `exit 1` did not make the {case!r} path succeed, so that "
        f"test is not measuring the exit it claims to measure"
    )
