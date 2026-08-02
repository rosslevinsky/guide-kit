"""Every `${{ ... }}` in a workflow VALUE must be a valid expression.

WHY THIS EXISTS. GitHub evaluates expression syntax anywhere in a workflow
*value*, and does not care that a given position is a shell comment inside a
`run:` block. A note reading "passed via env rather than <delimiters>
interpolation", written with the real delimiters inside a `run:` body, is
therefore not a comment: it is an EMPTY EXPRESSION, and it invalidates the entire
workflow file. GitHub reports that as a run named after the file path, with no
jobs and no annotations — a long way from pointing at the line.

It shipped exactly that way to eight repos, so this is a regression test.

THE DISTINCTION THAT MAKES THIS TEST CORRECT. A `#` comment at YAML level is
stripped by the YAML parser before GitHub ever sees it, so the same prose is
perfectly safe there — `deploy.yml.example` and `baseline.yml` both carry it and
have always run fine. Only text that survives into a parsed VALUE is
interpolated. So this walks the parsed document rather than the raw file: a
raw-text scan flags the harmless YAML comments and would have to be suppressed,
and a suppressed check is worth nothing.

`yaml.safe_load` succeeding proves nothing on its own here — the offending text
is a perfectly valid YAML string.

The same trap in a different costume has now bitten this repo three times: prose
containing a literal managed-region marker unbalanced the sync parser twice, and
this. The rule generalises — never write a live delimiter in prose that lives
inside the thing that parses it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WF_DIR = REPO_ROOT / ".github/workflows"
WORKFLOWS = sorted(WF_DIR.glob("*.yml")) + sorted(WF_DIR.glob("*.yml.example"))

_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)

# Contexts and expression functions GitHub actually provides.
_KNOWN = frozenset({
    "github", "env", "vars", "job", "jobs", "steps", "runner", "secrets",
    "strategy", "matrix", "needs", "inputs",
    "always", "success", "failure", "cancelled", "contains", "startsWith",
    "endsWith", "format", "join", "toJSON", "toJson", "fromJSON", "fromJson",
    "hashFiles",
})


def _strings(node, path="") -> list[tuple[str, str]]:
    """Every string VALUE in the parsed document, with a path for the message.

    Keys are walked as well as values: a mapping key is also a value GitHub
    interpolates (e.g. an `env:` name built from an expression)."""
    out: list[tuple[str, str]] = []
    if isinstance(node, str):
        out.append((path or "<root>", node))
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str):
                out.append((f"{path}.<key>", k))
            out += _strings(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _strings(v, f"{path}[{i}]")
    return out


def _load(wf: Path):
    return yaml.safe_load(wf.read_text(encoding="utf-8"))


def test_there_are_workflows_to_check():
    """Guard against the glob matching nothing, which would make every
    assertion below vacuously true."""
    assert WORKFLOWS, f"no workflow files found under {WF_DIR}"
    # The two that carry the auto-baseline wiring must be among them.
    names = {w.name for w in WORKFLOWS}
    assert {"verify.yml", "baseline.yml"} <= names, names


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_no_empty_expressions_in_values(wf: Path):
    empties = [
        (path, value.strip()[:90])
        for path, value in _strings(_load(wf))
        for body in _EXPR.findall(value)
        if not body.strip()
    ]
    assert not empties, (
        f"{wf.name} has an EMPTY expression inside a VALUE, which invalidates the "
        f"whole workflow file. GitHub interpolates expression syntax even inside a "
        f"shell comment in a run: block — move the note to a YAML comment, or "
        f"reword it. Offenders: {empties}"
    )


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_expression_delimiters_balanced_in_values(wf: Path):
    bad = [
        (path, value.strip()[:90])
        for path, value in _strings(_load(wf))
        if value.count("${{") != value.count("}}")
    ]
    assert not bad, (
        f"{wf.name} has an unterminated expression in a value, which invalidates "
        f"the workflow file: {bad}"
    )


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_expressions_reference_a_known_context(wf: Path):
    """A typo'd context (`secret.FOO`, `step.x.outputs.y`) resolves to empty at
    runtime instead of failing — a silent wrong value, which is the failure mode
    this family keeps rediscovering."""
    bad = []
    for path, value in _strings(_load(wf)):
        for body in _EXPR.findall(value):
            body = body.strip()
            if not body:
                continue  # covered above
            head = re.match(r"[A-Za-z_][A-Za-z0-9_]*", body)
            if head and head.group(0) not in _KNOWN:
                bad.append((path, body[:90]))
    assert not bad, f"{wf.name} references unknown context(s): {bad}"


# ---------------------------------------------------------------------------
# CI trigger coverage: the paths filter must cover the declared closures.
#
# Found by splitting build.py — verify.yml listed `build.py` and nothing else,
# so once the pipeline moved into buildcore.py and render_*.py a change to the
# code that actually renders the PDF would not have triggered the staleness
# check at all. A hand-maintained list beside a declared closure drifts exactly
# once and then stays wrong, so it is asserted rather than remembered.
# ---------------------------------------------------------------------------

def _trigger_paths(wf: Path, event: str) -> set[str]:
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    # `on` is parsed by YAML 1.1 as the boolean True.
    trigger = doc.get("on", doc.get(True, {})) or {}
    return set((trigger.get(event) or {}).get("paths", []) or [])


def _covered(dep: str, paths: set[str]) -> bool:
    """Whether a filter entry covers a closure dependency.

    Glob deps must be handled, not skipped: `fonts/*.otf` is a real PDF input,
    and an entry of `fonts/**` covers it. Dropping globs was how the first
    version of this test passed while a font swap triggered no CI at all.
    """
    if dep in paths:
        return True
    directory = dep.rsplit("/", 1)[0] if "/" in dep else ""
    while directory:
        if f"{directory}/**" in paths:
            return True
        directory = directory.rsplit("/", 1)[0] if "/" in directory else ""
    return False


# Which workflow gates which artifact, and what it legitimately does not carry.
#   verify.yml  — the staleness gate, so EVERY artifact with a committed
#                 reference. It covered only the PDF's closure, and the deck's
#                 `<slides_file>` was consequently absent from the filter: an
#                 edit to it triggered nothing at all, while staleness IS asked
#                 of the deck. Silent by construction — an unlisted path produces
#                 no run, so there is no check to be red.
#   deploy.yml  — the site, which COPIES the committed reference rather than
#                 rendering one, so `render_pdf.py` is correctly absent.
_FILTER_SCOPE = [
    ("verify.yml", "pdf", set()),
    ("verify.yml", "slides", set()),
    ("deploy.yml.example", "site", {"render_pdf.py"}),
]


@pytest.mark.parametrize("event", ["push", "pull_request"])
@pytest.mark.parametrize("workflow, artifact, exempt", _FILTER_SCOPE,
                         ids=lambda v: v if isinstance(v, str) else "")
def test_a_paths_filter_covers_the_closure_it_gates(event, workflow, artifact, exempt):
    import kitconfig

    paths = _trigger_paths(WF_DIR / workflow, event)
    assert paths, f"{workflow} has no {event} paths filter"
    # EVERY declared dependency, globs included, plus the config the closure
    # reads key-level.
    # Placeholders RESOLVED, the same way `AUTHORABLE_SOURCES` derives itself.
    # `<theme>` happens to be covered by the `themes/**` glob, but
    # `<slides_file>` is a bare filename with no directory to be caught by one —
    # so comparing the raw spec silently exempted the very entry that was missing.
    required = ({kitconfig._with_defaults(d)
                 for d in kitconfig.artifact_spec(artifact).file_deps} - exempt) | {"guide.toml"}
    missing = sorted(d for d in required if not _covered(d, paths))
    assert not missing, (
        f"{workflow}'s {event} paths filter does not cover the {artifact} "
        f"closure: {missing}. A change to these renders a different artifact "
        f"while CI never runs at all — no red check, because an unlisted path "
        f"creates no run."
    )


# ---------------------------------------------------------------------------
# The loose-`==` numeric coercion trap
#
# GitHub casts BOTH operands to a number when their types differ. An unset
# output — which is what a SKIPPED step yields — is `''`, and `''` casts to `0`.
# So `steps.x.outputs.rc == '0'` is TRUE for a step that never ran, and the
# condition reads as "the command succeeded" while meaning "the command may not
# have happened".
#
# This bit the family once, with the local tests green throughout; it
# took a real runner to show the check firing on a tree that had never been
# rendered.
#
# THE GATE IS NARROWED TO THE ACTUAL DEFECT, and the narrowing is the interesting
# part. Only a ZERO-VALUED literal is dangerous, because only `0` is what `''`
# casts to. `rc == '1'` is *safe*: a skipped step yields `''` -> 0, and 0 != 1, so
# the condition is correctly false. `verify.yml` relies on exactly that to decide
# whether to auto-dispatch a baseline, and flagging it would either force churn on
# a correct condition or — worse — invite a "fix" that breaks the auto-baseline.
#
# A non-numeric comparison ('true', 'hub', a branch name) is safe for a different
# reason: the string casts to NaN, and NaN equals nothing at all, including the
# empty string a skipped step produces.
# ---------------------------------------------------------------------------

# Zero in any spelling GitHub would coerce to 0.
_ZERO_COMPARE = re.compile(
    r"(needs|steps|env|inputs|jobs)\.[A-Za-z0-9_.\-]+\s*==\s*'(-?0+(?:\.0*)?)'")


def _conditions(node, path=""):
    """Every `if:` value in the parsed document."""
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if key == "if" and isinstance(value, (str, bool)):
                out.append((here, str(value)))
            out += _conditions(value, here)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            out += _conditions(item, f"{path}[{i}]")
    return out


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_no_condition_compares_an_output_to_a_numeric_string(wf):
    """The unset-output-casts-to-zero trap, gated statically."""
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    bad = [(where, cond) for where, cond in _conditions(doc)
           if _ZERO_COMPARE.search(cond)]
    assert not bad, (
        f"{wf.name}: a condition compares a context value to zero. An unset "
        f"output is '' and casts to 0, so this is TRUE for a step that never "
        f"ran — invert it, or use a non-numeric sentinel like 'true'. Found: {bad}"
    )


def test_the_trap_would_actually_be_caught():
    """A gate nobody has seen fire is a gate nobody should trust."""
    assert _ZERO_COMPARE.search("steps.build.outputs.rc == '0'")
    assert _ZERO_COMPARE.search("steps.build.outputs.rc == '-0'")
    assert _ZERO_COMPARE.search("steps.build.outputs.rc == '0.0'")


def test_the_gate_does_not_flag_the_safe_comparisons():
    """Narrowed deliberately — see the note above. `rc == '1'` is correct and
    load-bearing in verify.yml's auto-baseline dispatch."""
    assert not _ZERO_COMPARE.search("steps.staleness.outputs.rc == '1'")
    assert not _ZERO_COMPARE.search("steps.shape.outputs.pdf == 'true'")
    assert not _ZERO_COMPARE.search("github.ref == 'refs/heads/main'")


# ---------------------------------------------------------------------------
# Expression interpolation inside a `run:` body
#
# GitHub pastes `${{ ... }}` into the script as TEXT before any shell sees it, so
# quoting at the call site is not a defence: the value can close the quote
# itself. `git check-ref-format` accepts a single quote in a tag name, and a tag
# is chosen by whoever pushes it — so `--tag '${{ steps.tag.outputs.tag }}'` in a
# step whose environment holds GH_TOKEN and the Cloudflare secrets makes
# tag-push permission equivalent to secret exfiltration.
#
# The rule is mechanical and therefore testable: a `run:` body takes its values
# from `env:`. This is a static gate on the whole family's workflows, not a note
# asking people to remember.
# ---------------------------------------------------------------------------

def _run_bodies(doc):
    """Every `run:` script in the document, with a path for the message."""
    out = []
    for job_name, job in (doc.get("jobs") or {}).items():
        for i, step in enumerate(job.get("steps") or []):
            body = step.get("run")
            if isinstance(body, str):
                label = step.get("name") or step.get("id") or f"step {i}"
                out.append((f"jobs.{job_name}.steps[{i}] ({label})", body))
    return out


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_no_expression_is_interpolated_into_a_run_body(wf: Path):
    bad = [
        (where, f"${{{{{body.strip()}}}}}")
        for where, script in _run_bodies(_load(wf))
        for body in _EXPR.findall(script)
    ]
    assert not bad, (
        f"{wf.name}: an expression is interpolated directly into a shell script. "
        f"GitHub pastes the value in as text before the shell parses it, so "
        f"quoting does not contain it — a value carrying a quote breaks out and "
        f"runs commands with whatever secrets the step has in scope. Pass it "
        f"through `env:` and reference it as a shell variable instead. "
        f"Offenders: {bad}"
    )




# ---------------------------------------------------------------------------
# Credentials and pull-request-controlled code must not share a job
#
# Fork PRs never receive repository secrets, but SAME-REPOSITORY ones do. A job
# that runs `npm ci` (postinstall scripts) or `make` (the repo's own Python) and
# then hands the Cloudflare token to a later step has made "can push a branch"
# equivalent to "can use the account", with no review and without touching
# protected main.
#
# Stated as a property over the parsed workflow rather than as a comment,
# because the previous version of this file explained the split in prose while
# the preview step sat in the build job regardless.
# ---------------------------------------------------------------------------

_CREDENTIALED = re.compile(r"secrets\.(CLOUDFLARE_API_TOKEN|CLOUDFLARE_ACCOUNT_ID)")
# Anything that executes code the pull request supplied.
_RUNS_REPO_CODE = re.compile(r"\bnpm (ci|install)\b|\bmake\b|\bpixi run\b")


def _excludes_pull_request(condition: str) -> bool:
    """Whether a condition restricts the run to events that are not a PR.

    Deliberately conservative — reachable UNLESS the condition both names
    `github.event_name` and omits `pull_request`. Assuming a job is unreachable
    because its condition happens not to mention pull requests is how the first
    version of this test passed against the very defect it was written for.
    """
    if "github.event_name" not in condition:
        return False
    return "pull_request" not in condition


def test_the_pull_request_path_never_holds_cloudflare_credentials():
    """The deploy job builds; the preview job publishes. Not one job doing both.

    A job may legitimately do both when a pull request cannot reach it — the
    production deploy runs `make web` and then deploys, and is gated on
    `push`/`workflow_dispatch` to `main`. What must never happen is a
    credential-bearing step reachable from a pull request in a job that also
    executes the pull request's own code.
    """
    doc = _load(WF_DIR / "deploy.yml.example")
    findings = []
    for job_name, job in (doc.get("jobs") or {}).items():
        steps = job.get("steps") or []
        executes = [s.get("name") or s.get("id") or "?" for s in steps
                    if isinstance(s.get("run"), str)
                    and _RUNS_REPO_CODE.search(s["run"])]
        if not executes:
            continue
        job_if = str(job.get("if", ""))
        for step in steps:
            if not _CREDENTIALED.search(str(step)):
                continue
            if _excludes_pull_request(str(step.get("if", ""))) or \
                    _excludes_pull_request(job_if):
                continue
            findings.append((job_name, step.get("name") or step.get("id"), executes))
    assert not findings, (
        f"deploy.yml.example: a credential-bearing step is reachable from a pull "
        f"request in a job that also runs pull-request-controlled code. A "
        f"same-repository PR receives repository secrets, so this makes "
        f"branch-push permission equivalent to account access. Split the build "
        f"from the publish and hand over an artifact. Findings: {findings}")


def test_the_credential_gate_would_actually_fire():
    """The shape of the defect this repo shipped, asserted directly — the first
    version of the gate above passed against it."""
    assert not _excludes_pull_request("github.event_name == 'pull_request'")
    assert not _excludes_pull_request("")
    assert not _excludes_pull_request("needs.guard.outputs.has_pdf == 'true'")
    assert _excludes_pull_request(
        "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
        " && github.ref == 'refs/heads/main'")


def test_no_job_gives_a_pull_request_the_cloudflare_token():
    """The stronger form of the rule above, and the one that actually holds.

    Splitting build from publish is not enough, and neither is validating the
    PR's `wrangler.jsonc` in the credentialed job. For `pull_request`, GitHub
    runs the workflow file from the MERGE COMMIT — the pull request's own
    version — so a PR can delete any check this file adds in the same commit
    that adds the payload. `pull_request_target` reads the workflow from the
    base branch and is not usable for a preview, because it would build the
    base tree.

    There is therefore no arrangement of jobs, artifacts or validation inside
    this file that makes a same-repository PR safe to hand the token to. The
    only property that holds is the absence of the token on that path.
    """
    doc = _load(WF_DIR / "deploy.yml.example")
    reachable = []
    for job_name, job in (doc.get("jobs") or {}).items():
        job_if = str(job.get("if", ""))
        if _excludes_pull_request(job_if):
            continue
        for step in job.get("steps") or []:
            if not _CREDENTIALED.search(str(step)):
                continue
            if _excludes_pull_request(str(step.get("if", ""))):
                continue
            reachable.append((job_name, step.get("name") or step.get("id")))
    assert not reachable, (
        f"a pull request can reach a step holding Cloudflare credentials: "
        f"{reachable}. A same-repository PR receives repository secrets AND "
        f"controls the workflow file the run uses, so nothing here can contain "
        f"it. Gate the step on push/workflow_dispatch.")


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_a_production_deploy_still_fires_on_workflow_dispatch(wf):
    """A dispatched run matches neither `push` nor `pull_request`. Omitting it
    from the production condition produces a green check with nothing deployed
    and the site serving the old PDF — the recorded worst case, and how
    baseline.yml redeploys after refreshing the reference."""
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    steps = [s for job in (doc.get("jobs") or {}).values()
             for s in (job.get("steps") or [])]
    prod = [s for s in steps if s.get("id") == "deploy_prod"]
    for step in prod:
        assert "workflow_dispatch" in str(step.get("if", "")), (
            f"{wf.name}: the production deploy does not fire on workflow_dispatch — "
            f"baseline.yml's redeploy would silently do nothing")


# ---------------------------------------------------------------------------
# An EXPECTED state must not be reported as a failure
#
# The reference PDF is a build artifact committed to the repo and stamped with a
# hash of its own sources, so any source push makes it stale BY CONSTRUCTION.
# Reporting that as a failed run emailed the maintainer on every content edit
# about a condition the next step was already repairing.
#
# The family's own record names the cost: "a red check that means nothing
# teaches people to ignore it just as thoroughly as one that passes without
# looking." These tests pin the two halves of the fix, and the second is the one
# that would have failed silently.
# ---------------------------------------------------------------------------

def _step(wf: str, job: str, ident: str):
    doc = _load(WF_DIR / wf)
    for s in doc["jobs"][job]["steps"]:
        if s.get("id") == ident:
            return s
    raise AssertionError(f"{wf}: no step with id {ident!r} in job {job!r}")


def test_a_stale_reference_after_a_push_does_not_fail_verify():
    """Green on the expected state; the rebuild is what reports a real problem."""
    body = _step("verify.yml", "verify", "staleness")["run"]
    assert "EXPECTED_STALE" in body, (
        "the staleness step exits on rc alone, so a push that changed source — "
        "which is stale by construction — still fails the run and emails")
    assert 'exit 0' in body, "there is no green path for the expected state"


def test_it_still_fails_where_nothing_can_repair_it():
    """A pull request cannot be auto-committed to, and a scheduled run has no
    push to repair — so staleness there is a standing defect, not a phase."""
    step = _step("verify.yml", "verify", "staleness")
    guard = str(step.get("env", {}).get("EXPECTED_STALE", ""))
    assert "github.event_name == 'push'" in guard, (
        "the green path is not restricted to a push")
    assert "default_branch" in guard, (
        "the green path is not restricted to the default branch")


def test_the_rebuild_is_not_gated_on_the_run_having_failed():
    """THE COUPLING THAT WOULD HAVE BROKEN SILENTLY.

    The auto-baseline dispatch used to be `if: failure() && rc == '1'`, because
    a stale reference failed the step above. The moment that step stops failing,
    `failure()` is false and the rebuild is never dispatched — so the workflow
    goes green while the reference stays stale forever. A green check that
    verified nothing, produced by removing a red check that meant nothing.
    """
    doc = _load(WF_DIR / "verify.yml")
    # The dispatch is its own JOB now — split out so `actions: write` never
    # exists on the pull-request path — so the condition under test is the job's,
    # not the step's, and the verdict crosses the boundary as a job output.
    jobs = doc["jobs"]
    rebuild = [j for j in jobs.values()
               if any("auto-dispatch baseline" in (s.get("name") or "")
                      for s in (j.get("steps") or []))]
    assert rebuild, "verify.yml no longer dispatches a rebuild at all"
    cond = str(rebuild[0].get("if", ""))
    assert "failure()" not in cond, (
        "the rebuild is gated on the run having failed, but the staleness step "
        "no longer fails on that path — the rebuild would never fire")
    assert "needs.verify.outputs.staleness_rc == '1'" in cond, (
        "the rebuild is not keyed on the staleness verdict")
    assert jobs["verify"]["outputs"]["staleness_rc"] == \
        "${{ steps.staleness.outputs.rc }}", (
        "the verdict is no longer published from the verify job, so the "
        "condition above can only ever compare against an empty string")


def test_the_paths_filter_covers_every_tracked_file_that_is_not_prose():
    """AN ALLOW-LIST FAILS SILENTLY, which is the whole reason to test it.

    A path absent from `verify.yml`'s `paths:` runs no CI at all — the push is
    simply not a trigger, so there is no red check and nothing to notice. 31
    tracked files were in that position, including `cfadapter.py`, `hub.py`,
    `adopt.py`, `guidekit.py`, `verify_web.py`, `tools/**`, `templates/**` and
    the root `package-lock.json`, which decides what `tests/test_nav_dom.py`
    executes in jsdom. Each has tests; none of those tests ran when it changed.

    The exemption list below is the deliberate half — prose and maintainer
    material that changes no rendered output — and it is stated as an explicit
    allow-list of EXCLUSIONS so that adding a file to it is a visible decision
    rather than an omission.
    """
    import fnmatch
    import subprocess

    exempt = (
        ".gitignore", "README.md", "CLAUDE.md", "CONTRIBUTING.md",
        "LICENSE", "LICENSE-CONTENT", "docs/*", "plans/*",
    )
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout.split()
    assert tracked, "git ls-files returned nothing; the check has gone blind"

    for trigger in ("push", "pull_request"):
        # `_trigger_paths` and `_covered` are the helpers the closure-coverage
        # test above already uses; this asks the same question of a wider set.
        patterns = _trigger_paths(WF_DIR / "verify.yml", trigger)
        uncovered = [f for f in tracked
                     if not any(fnmatch.fnmatch(f, e) for e in exempt)
                     and not _covered(f, patterns)
                     and not any(fnmatch.fnmatch(f, p) for p in patterns)]
        assert not uncovered, (
            f"verify.yml's {trigger} paths filter does not cover: {uncovered}. "
            f"A push touching only these runs NO CI and reports nothing — add "
            f"them to the filter, or to this test's `exempt` list if they really "
            f"are prose."
        )


def test_no_workflow_hardcodes_the_default_branch_name():
    """`main` is this repo's default branch, not every fork's.

    `deploy.yml.example` gated both deploy steps on `github.ref ==
    'refs/heads/main'` while `verify.yml` correctly derived it. A fork on
    `master` or `trunk` therefore got a GREEN deploy run that skipped both steps
    and shipped nothing — the exact silent-success shape the surrounding comments
    in that file spend paragraphs guarding against.
    """
    offenders = [f"{wf.name}{path}" for wf in WORKFLOWS
                 for path, value in _strings(_load(wf)) if "refs/heads/main" in value]
    assert not offenders, (
        f"these lines hardcode the default branch: {offenders}. Use "
        f"format('refs/heads/{{0}}', github.event.repository.default_branch)."
    )


def test_every_action_is_pinned_to_a_commit_sha():
    """`@v4` is a MUTABLE tag: whoever controls the action repository decides
    what it points at, and can re-point it after review.

    That is not theoretical for this family's workflows. `setup-pixi` runs in
    `baseline.yml`, which holds `contents: write` and pushes to the default
    branch; `wrangler-action` runs with the Cloudflare API token in scope. A
    moved tag on either is arbitrary code inside those grants.

    The readable version stays as a trailing comment — the point is to know what
    the SHA is, not to give up on knowing, and walking the PARSED document is
    what lets that comment exist: a raw-line scan would flag the prose explaining
    this convention, which is this file's own documented trap.
    """
    sha = re.compile(r"^[0-9a-f]{40}$")
    unpinned = [f"{wf.name}{path} -> {ref}" for wf in WORKFLOWS
                for path, ref in _strings(_load(wf))
                if path.endswith(".uses")
                and not ref.startswith(("./", "docker://"))
                and not sha.fullmatch(ref.split("@")[-1])]
    assert not unpinned, (
        f"these actions are pinned to a mutable ref: {unpinned}. Resolve the tag "
        f"to a commit SHA (`gh api repos/<owner>/<repo>/git/ref/tags/<tag>`) and "
        f"keep the tag as a trailing comment."
    )


def test_write_permissions_never_reach_the_pull_request_path():
    """A permission is granted for a whole TRIGGER unless a job boundary narrows it.

    `verify.yml` declared `actions: write` at workflow level. Its one consumer —
    the auto-baseline dispatch — was already gated to pushes on the default
    branch, but the grant was not: the `pull_request` trigger runs the same job,
    and that job executes PR-authored code (`npm ci`, `pytest`, `make`) while
    holding a token that can start any workflow in the repository.

    Nothing arranged inside the workflow file closes that, for the same reason
    the PR preview deploy was removed: for `pull_request` GitHub runs the
    workflow file from the MERGE commit, so a pull request can edit the guard in
    the same commit that adds a payload. The only durable answer is not to hold
    the permission on that path at all.

    Asserted across every workflow, and on the WORKFLOW level specifically —
    which is the level a trigger reaches. A job may hold whatever its own
    condition justifies.
    """
    offenders = {}
    for wf in WORKFLOWS:
        doc = _load(wf)
        if not isinstance(doc, dict):
            continue
        triggers = doc.get(True) or doc.get("on") or {}
        if "pull_request" not in (triggers if isinstance(triggers, dict) else [triggers]):
            continue
        perms = doc.get("permissions") or {}
        writes = sorted(k for k, v in perms.items() if v == "write")
        if writes:
            offenders[wf.name] = writes
    assert not offenders, (
        f"workflow-level write permissions apply to the pull_request trigger, "
        f"whose job runs PR-authored code: {offenders}. Move the grant onto the "
        f"job that needs it, gated on the event."
    )


def test_a_stale_reference_stops_the_deploy_without_failing_it():
    """The gate's job is keeping a stale PDF off the site. It must still do that
    — going green is only acceptable because the deploy is SKIPPED."""
    doc = _load(WF_DIR / "deploy.yml.example")
    steps = doc["jobs"]["deploy"]["steps"]
    gate = [s for s in steps if s.get("id") == "stale_gate"]
    assert gate, "deploy.yml.example has no identified staleness gate"
    assert "exit 0" in gate[0]["run"], "the gate still fails the run on stale"

    prod = [s for s in steps if s.get("id") == "deploy_prod"]
    assert prod, "no production deploy step"
    cond = str(prod[0].get("if", ""))
    assert "steps.stale_gate.outputs.rc != '1'" in cond, (
        "the gate no longer fails, and the deploy is not gated on its verdict — "
        "so a stale PDF would now ship, which is the one thing the gate exists "
        "to prevent")


def test_the_deploy_guard_survives_a_skipped_gate():
    """A shape with no PDF skips the gate, and a skipped step's output is ''.
    GitHub's loose `==` casts '' to 0, so `== '0'` would read as "fresh" for a
    gate that never ran — and `!= '1'` is correct for both. Asserted because the
    two spellings look interchangeable and are not."""
    doc = _load(WF_DIR / "deploy.yml.example")
    prod = [s for s in doc["jobs"]["deploy"]["steps"] if s.get("id") == "deploy_prod"]
    cond = str(prod[0].get("if", ""))
    assert "stale_gate.outputs.rc == '0'" not in cond, (
        "`== '0'` is TRUE for a skipped gate — use `!= '1'`")
