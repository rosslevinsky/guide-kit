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


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_verify_paths_filter_covers_the_pdf_closure(event):
    import kitconfig

    paths = _trigger_paths(REPO_ROOT / ".github" / "workflows" / "verify.yml", event)
    assert paths, f"verify.yml has no {event} paths filter"
    # EVERY declared dependency, globs included, plus the config the closure
    # reads key-level.
    required = set(kitconfig.artifact_spec("pdf").file_deps) | {"guide.toml"}
    missing = sorted(d for d in required if not _covered(d, paths))
    assert not missing, (
        f"verify.yml's {event} paths filter does not cover the PDF closure: {missing}. "
        "A change to these files would render a different PDF without CI ever "
        "checking whether the committed reference went stale."
    )


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_deploy_paths_filter_covers_the_site_closure(event):
    import kitconfig

    paths = _trigger_paths(REPO_ROOT / ".github" / "workflows" / "deploy.yml.example", event)
    assert paths, f"deploy.yml.example has no {event} paths filter"
    # render_pdf.py is deliberately excluded: the site copies the committed
    # reference PDF rather than rendering one.
    required = {
        d for d in kitconfig.artifact_spec("site").file_deps if d != "render_pdf.py"
    } | {"guide.toml"}
    missing = sorted(d for d in required if not _covered(d, paths))
    assert not missing, (
        f"deploy.yml.example's {event} paths filter does not cover the site closure: {missing}"
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
    steps = doc["jobs"]["verify"]["steps"]
    rebuild = [s for s in steps if "auto-dispatch baseline" in (s.get("name") or "")]
    assert rebuild, "verify.yml no longer dispatches a rebuild at all"
    cond = str(rebuild[0].get("if", ""))
    assert "failure()" not in cond, (
        "the rebuild is gated on the run having failed, but the staleness step "
        "no longer fails on that path — the rebuild would never fire")
    assert "steps.staleness.outputs.rc == '1'" in cond, (
        "the rebuild is not keyed on the staleness verdict")


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
