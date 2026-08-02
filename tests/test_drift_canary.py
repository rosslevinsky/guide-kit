"""The permanent drift canary: a MEASUREMENT that a fresh render still
matches the committed reference, on two axes a text comparison cannot cover.

WHY IT EXISTS. `make verify` hashes `SOURCE_FILES`. `pixi.lock` is not in that
list, so a dependency bump that shifts layout leaves the staleness check
correctly green while the deliverable has quietly changed. Nothing in CI closed
that gap. The compensating control the family USED to claim — `make verify-render`
— is false three ways, all of which these tests pin:

  * CI never runs it (`verify.yml` runs only the build-free staleness check);
  * it compares page count and extracted text, so a FACE-ONLY substitution with
    identical text and pagination passes it; and
  * on a stale default-branch push `verify.yml` auto-dispatches `baseline.yml`,
    which renders and COMMITS a new reference without comparing it to the old
    one — silently absorbing any drift riding along with a content change.

So the canary compares PDF **bytes** (strictly stronger than a text diff) plus
the `pdffonts` embedded-face list (which names a face substitution rather than
merely reporting different bytes), and it must NEVER auto-baseline.

The fixtures below are hand-built minimal PDFs rather than real renders: the
canary's logic is about comparison and refusal, and a WeasyPrint render per case
would make this file too slow to run on every commit. The face-only fixture pair
is the important one — identical text, identical page count, different
`/BaseFont` — because it is exactly the case `verify-render` is blind to, and
`test_face_only_change_is_invisible_to_the_render_canary` asserts that blindness
directly rather than taking the canary's claim on trust.
"""
from pathlib import Path

import pytest
import yaml

import driftcanary
import kitconfig
import verify_artifacts

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Minimal PDF fixtures with a controllable font table
# ---------------------------------------------------------------------------

def _minipdf(font: str = "Helvetica", text: str = "Hello world") -> bytes:
    """A valid one-page PDF whose only interesting property is its font table.

    Written by hand because the point is to vary /BaseFont independently of the
    text and page count, which no real render lets you do.
    """
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{font} >>".encode(),
    ]
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1) + b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    return bytes(out)


@pytest.fixture
def pdfs(tmp_path):
    def make(name: str, **kw) -> Path:
        p = tmp_path / f"{name}.pdf"
        p.write_bytes(_minipdf(**kw))
        return p
    return make


# ---------------------------------------------------------------------------
# The comparison itself
# ---------------------------------------------------------------------------

def test_identical_renders_are_clean(pdfs):
    verdict = driftcanary.compare(pdfs("ref"), pdfs("fresh"))
    assert verdict.clean
    assert verdict.byte_match and verdict.face_match
    assert not verdict.failures


def test_a_perturbed_toolchain_is_red_on_BYTES(pdfs):
    """The general case: the render moved, for whatever reason."""
    verdict = driftcanary.compare(
        pdfs("ref", text="Hello world"),
        pdfs("fresh", text="Hello  world"),   # a metric/layout change
    )
    assert not verdict.clean
    assert not verdict.byte_match
    assert any("bytes" in f.lower() for f in verdict.failures), verdict.failures


def test_a_face_substitution_is_red_on_the_FACE_LIST(pdfs):
    """Identical text, identical page count, different embedded face.

    Reported on the face axis specifically — not merely as "bytes differ" —
    because the whole reason the face list is a second axis is that it NAMES
    what changed. A byte-only report would say the render moved without saying
    that the typeface was substituted, which is the single most likely form of
    toolchain drift in a font-bundling family.
    """
    ref, fresh = pdfs("ref", font="Helvetica"), pdfs("fresh", font="Courier")
    verdict = driftcanary.compare(ref, fresh)

    assert not verdict.clean
    assert not verdict.face_match
    assert any("face" in f.lower() for f in verdict.failures), verdict.failures
    assert any(f.startswith("Helvetica") for f in verdict.reference_faces), verdict.reference_faces
    assert any(f.startswith("Courier") for f in verdict.fresh_faces), verdict.fresh_faces


def test_face_only_change_is_invisible_to_the_render_canary(pdfs, capsys):
    """The canary's central claim, asserted rather than cited.

    `make verify-render` compares page count and stamp-excluded text. On the
    face-substitution pair above it returns 0 — PASS. That is the gap the face
    axis exists to close, and if a future `render_canary` ever starts catching
    it, this test fails and the second axis can be reconsidered.
    """
    ref, fresh = pdfs("ref", font="Helvetica"), pdfs("fresh", font="Courier")

    assert verify_artifacts.render_canary(ref, fresh) == 0, (
        "render_canary now catches a face-only substitution — re-derive whether "
        "the canary still needs a separate face axis"
    )
    assert not driftcanary.compare(ref, fresh).clean


def test_a_face_name_containing_a_SPACE_is_not_truncated(pdfs):
    """A shipped-and-caught defect: `row.split()[0]` truncated at the space.

    A PostScript name may legally contain a space, so `Foo Regular` and
    `Foo Bold` both reduced to `Foo` — and a substitution between two such faces
    reported an UNCHANGED list, silencing the face axis in exactly the case it
    exists for. The parser slices the fixed-width column instead.
    """
    ref = pdfs("ref", font="Foo#20Regular")
    fresh = pdfs("fresh", font="Foo#20Bold")

    ref_faces = driftcanary.face_list(ref)
    assert any(" " in f.split(" [")[0] for f in ref_faces), ref_faces

    verdict = driftcanary.compare(ref, fresh)
    assert not verdict.face_match, (verdict.reference_faces, verdict.fresh_faces)


def test_a_face_that_stops_being_EMBEDDED_is_caught(pdfs):
    """Same family name, no longer embedded, is a broken deliverable — the
    reader's machine substitutes — and a name-only comparison calls it
    identical. The `emb` column rides along for that reason."""
    faces = driftcanary.face_list(pdfs("ref", font="Helvetica"))
    assert all("embedded=" in f for f in faces), faces
    # The hand-built fixture uses a base-14 font, which is NOT embedded.
    assert faces == ["Helvetica [embedded=no]"], faces


def test_unexpected_pdffonts_output_is_an_ERROR_not_an_empty_list(monkeypatch, pdfs):
    """Fail closed on a shape we do not recognise. Returning [] would make two
    unparseable PDFs compare EQUAL on the face axis — the check going quiet
    precisely when it cannot do its job."""
    import subprocess as sp

    class FakeProc:
        stdout = "something entirely unexpected\n"

    monkeypatch.setattr(driftcanary.subprocess, "run", lambda *a, **k: FakeProc())
    with pytest.raises(driftcanary.CanaryError):
        driftcanary.face_list(pdfs("ref"))


# ---------------------------------------------------------------------------
# The staleness verdict must not fail OPEN
# ---------------------------------------------------------------------------

def test_a_crashing_staleness_check_is_an_ERROR_not_a_skip(tmp_path, monkeypatch):
    """`verify_artifacts.py` exits 1 for "stale" — and Python also exits 1 on an
    unhandled exception. Reading a traceback as "stale" turned a broken checker
    into a clean SKIP, which reads as a pass."""
    class FakeProc:
        returncode = 1
        stderr = 'Traceback (most recent call last):\n  File "x", line 1\nKeyError: 1\n'

    monkeypatch.setattr(driftcanary.subprocess, "run", lambda *a, **k: FakeProc())
    assert driftcanary._staleness_rc(tmp_path) == 2


@pytest.mark.parametrize("rc", [-9, 127, 3])
def test_an_UNRECOGNISED_staleness_code_is_an_ERROR(tmp_path, monkeypatch, rc):
    """A signal death (-9) or a missing interpreter (127) is not a verdict.

    Passed through unmapped, it matched neither the `== 2` nor the `== 1` branch
    and fell through to "fresh" — so the canary would render and judge drift on
    the strength of a check that never ran. The default is now the refusal.
    """
    class FakeProc:
        returncode = rc
        stderr = ""

    monkeypatch.setattr(driftcanary.subprocess, "run", lambda *a, **k: FakeProc())
    assert driftcanary._staleness_rc(tmp_path) == 2

    monkeypatch.setattr(driftcanary, "_staleness_rc", lambda root, artifact="pdf": rc)
    result = driftcanary.run(tmp_path, render=lambda: pytest.fail("must not render"))
    assert result.status == "error" and result.exit_code == 2


def test_missing_reference_is_an_ERROR_not_a_pass(pdfs, tmp_path):
    """Fail closed. A comparison that cannot be made has not been passed."""
    with pytest.raises(driftcanary.CanaryError):
        driftcanary.compare(tmp_path / "absent.pdf", pdfs("fresh"))


# ---------------------------------------------------------------------------
# When the canary must stay SILENT
# ---------------------------------------------------------------------------

def test_a_stale_reference_SKIPS_rather_than_fails(tmp_path, monkeypatch, pdfs):
    """A stale reference is `make verify`'s finding, not the canary's.

    If the source changed, a fresh render SHOULD differ from the committed
    reference — that is not drift, and reporting it as drift would make the
    canary red on every ordinary content edit until the baseline caught up,
    which is how a check gets ignored.
    """
    monkeypatch.setattr(driftcanary, "_staleness_rc", lambda root, artifact="pdf": 1)
    result = driftcanary.run(tmp_path, render=lambda: pytest.fail("must not render"))
    assert result.status == "skipped"
    assert "not established as fresh" in result.reason
    assert result.exit_code == 0


def test_a_broken_staleness_check_is_an_ERROR(tmp_path, monkeypatch):
    """rc == 2 is "the check itself is broken". Rendering and comparing on the
    strength of a broken check is how a wrong verdict gets published."""
    monkeypatch.setattr(driftcanary, "_staleness_rc", lambda root, artifact="pdf": 2)
    result = driftcanary.run(tmp_path, render=lambda: pytest.fail("must not render"))
    assert result.status == "error"
    assert result.exit_code == 2


def test_pre_first_release_skips(tmp_path, monkeypatch):
    """No reference PDF yet — nothing to compare against."""
    monkeypatch.setattr(driftcanary, "_staleness_rc", lambda root, artifact="pdf": 0)
    monkeypatch.setattr(driftcanary, "_reference_path", lambda root, artifact="pdf": tmp_path / "absent.pdf")
    result = driftcanary.run(tmp_path, render=lambda: pytest.fail("must not render"))
    assert result.status == "skipped"
    assert result.exit_code == 0


def test_drift_on_a_FRESH_reference_is_reported_as_drift(tmp_path, monkeypatch, pdfs):
    """The one combination that means toolchain drift: staleness passes (the
    source is unchanged) and the render still differs."""
    ref = pdfs("ref", font="Helvetica")
    fresh = pdfs("fresh", font="Courier")
    monkeypatch.setattr(driftcanary, "_staleness_rc", lambda root, artifact="pdf": 0)
    monkeypatch.setattr(driftcanary, "_reference_path", lambda root, artifact="pdf": ref)

    result = driftcanary.run(tmp_path, render=lambda: fresh)

    assert result.status == "drift"
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# The workflow wiring — the "never auto-baseline" rule
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def verify_workflow():
    return yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    )


def _steps(workflow):
    return workflow["jobs"]["verify"]["steps"]


def _all_steps(workflow):
    """Every step in every job. The auto-baseline dispatch moved into its own
    `dispatch-baseline` job so `actions: write` would stop existing on the
    pull-request path, so a lookup scoped to `verify` no longer finds it."""
    return [s for job in workflow["jobs"].values() for s in (job.get("steps") or [])]


def _dispatch_job(workflow):
    """The job holding the auto-baseline dispatch, and its own `if:` — which is
    now where the staleness gate lives."""
    for job in workflow["jobs"].values():
        for step in job.get("steps") or []:
            if "workflow run baseline.yml" in yaml.dump(step):
                return job
    raise AssertionError("no job dispatches baseline.yml")


def _canary_step(workflow):
    hits = [s for s in _steps(workflow) if "driftcanary.py" in yaml.dump(s)]
    assert len(hits) == 1, f"expected exactly one canary step, found {len(hits)}"
    return hits[0]


def test_the_canary_is_wired_into_ci(verify_workflow):
    """It exists AND it reuses the render the build-smoke step already made.

    A second build would be the obvious implementation and is what the design argues
    against: the decision calls the canary cheap precisely because CI already
    has a fresh PDF in the workspace.
    """
    step = _canary_step(verify_workflow)
    assert "--fresh" in step["run"]
    assert "build/$SLUG.pdf" in step["run"]


def test_the_canary_runs_only_when_STALENESS_PASSED(verify_workflow):
    """Drift is "source unchanged AND the render moved". On a stale reference a
    difference is expected and means nothing about the toolchain."""
    cond = str(_canary_step(verify_workflow).get("if", ""))

    # The staleness step FAILS the job on a stale tree, so a bare `if:` would skip
    # the canary — it needs an explicit status check. `!cancelled()` and not
    # `always()`: this workflow sets cancel-in-progress, and a canary on a
    # superseded commit teaches nothing while still paying for a build.
    assert "!cancelled()" in cond, cond
    assert "always()" not in cond, "always() also runs on a cancelled run — use !cancelled()"

    # It must prove the staleness step RAN, not just what it reported. An earlier
    # step failing skips staleness, and a skipped step's outputs are unset.
    assert "steps.staleness.outcome == 'success'" in cond, cond
    assert "steps.staleness.outputs.state == 'fresh'" in cond, cond


def test_the_canary_gate_is_not_vulnerable_to_numeric_COERCION(verify_workflow):
    """A shipped bug, caught on a real runner — do not "simplify" this back.

    The obvious gate is `steps.staleness.outputs.rc == '0'`. It is WRONG.
    GitHub's `==` is loose: when the operand types differ it casts both to
    numbers, an unset output is the empty string, and the empty string casts to
    0 — so `rc == '0'` evaluates TRUE for a step that never ran. On the kit's
    first real CI run the test-suite step failed, `make` and the staleness check
    were skipped, and the canary fired anyway: it compared a leftover `build/`
    artifact against the reference and reported toolchain drift that did not
    exist.

    The lesson generalises past this one gate, which is why the assertion is
    about the SHAPE and not about one spelling: never compare a possibly-unset
    step output against a numeric-looking string literal.
    """
    cond = str(_canary_step(verify_workflow).get("if", ""))
    assert "outputs.rc" not in cond, (
        "the canary gate compares a numeric-looking output; an unset output "
        "coerces to 0 and the gate opens when the step never ran"
    )
    for numeric_literal in ("== '0'", '== "0"', "== 0"):
        assert numeric_literal not in cond, (
            f"{numeric_literal!r} in the canary gate is coercion-vulnerable: an "
            "unset output is '' which GitHub casts to 0"
        )


def test_the_staleness_step_publishes_a_NON_NUMERIC_verdict(verify_workflow):
    """The other half of the fix: there has to be something safe to compare to.

    `rc` is kept — it is what the auto-baseline dispatch reads, and there the
    coercion is harmless because that gate wants rc == 1 and an unset output
    casts to 0, which is correctly false. `state` exists so the canary has a
    string that cannot be cast to a number.
    """
    staleness = next(s for s in _steps(verify_workflow) if s.get("id") == "staleness")
    run = staleness["run"]
    assert "state=fresh" in run and "state=broken" in run, run
    assert 'echo "state=$state" >> "$GITHUB_OUTPUT"' in run, run


def test_the_canary_step_NEVER_dispatches_a_baseline(verify_workflow):
    """The refusal the design names explicitly.

    Auto-baselining a drift difference would commit the drift into the
    deliverable and turn the check that found it into the mechanism that
    laundered it.
    """
    step = yaml.dump(_canary_step(verify_workflow))
    assert "baseline.yml" not in step, "the drift canary must never dispatch a baseline"
    assert "workflow run" not in step


def test_auto_baseline_stays_gated_on_STALENESS_only(verify_workflow):
    """The separation that keeps drift out of the deliverable.

    The canary and the auto-baseline are in different jobs now — split so
    `actions: write` never exists on the pull-request path — but the separation
    that matters here is the CONDITION, not the boundary: nothing structural
    stops someone widening the dispatch to cover a red canary. This assertion is
    that guard, and it moves with the condition, which is now the job's.
    """
    job = _dispatch_job(verify_workflow)
    cond = str(job.get("if", ""))
    assert "needs.verify.outputs.staleness_rc == '1'" in cond, cond
    assert "canary" not in cond.lower(), cond
    # The verdict has to reach the job, or the condition compares against "".
    assert verify_workflow["jobs"]["verify"]["outputs"]["staleness_rc"] == \
        "${{ steps.staleness.outputs.rc }}"


def test_the_canary_runs_after_the_staleness_check(verify_workflow):
    """Ordering is load-bearing: `steps.staleness.outputs.rc` is unset until the
    staleness step has run, so a canary placed above it would silently never
    execute — a check that is always skipped looks exactly like a check that
    always passes."""
    names = [s.get("name", "") for s in _steps(verify_workflow)]
    staleness = next(i for i, s in enumerate(_steps(verify_workflow))
                     if s.get("id") == "staleness")
    canary = next(i for i, s in enumerate(_steps(verify_workflow))
                  if "driftcanary.py" in yaml.dump(s))
    assert canary > staleness, names


def test_the_canary_runs_weekly_and_on_lock_or_workflow_changes(verify_workflow):
    """The canary's triggers. The schedule is not optional: a rebuilt runner image or a
    refreshed environment produces no push event of its own, so a push-only
    canary can never see the drift class it exists for."""
    # PyYAML parses a bare `on:` key as the boolean True.
    triggers = verify_workflow.get("on") or verify_workflow.get(True)
    assert "schedule" in triggers, "no weekly schedule — the canary cannot see runner drift"

    watched = set(triggers["push"]["paths"]) | set(triggers["pull_request"]["paths"])
    assert "pixi.lock" in watched
    assert any(p.startswith(".github/workflows/") for p in watched)


# ---------------------------------------------------------------------------
# The auto-baseline's pixi.lock refusal — the laundering path
# ---------------------------------------------------------------------------
#
# The canary correctly SKIPS on a stale reference, which leaves one hole: a push
# that changes both content and `pixi.lock`. The reference is legitimately stale,
# so the canary says nothing, and `baseline.yml` would then render and commit the
# dependency-driven typography change folded into the content change — with the
# next canary comparing against the new reference and passing. Nothing would ever
# report it.
#
# CI cannot separate the two causes with one toolchain, so the auto-baseline
# dispatch refuses instead. These tests run the workflow's REAL shell block —
# extracted from verify.yml, not retyped — against a temp repo.

def _dispatch_step_script(workflow) -> str:
    step = next(s for s in _all_steps(workflow)
                if "baseline.yml" in yaml.dump(s) and "driftcanary" not in yaml.dump(s))
    return step["run"]


def _run_dispatch_script(script, repo, before, after, env_extra=None):
    import os
    import subprocess
    env = {**os.environ, "REF": "main", "GH_TOKEN": "x",
           "BEFORE": before, "AFTER": after, **(env_extra or {})}
    return subprocess.run(["bash", "-c", script], cwd=repo, env=env,
                          capture_output=True, text=True)


@pytest.fixture
def repo_with_history(tmp_path):
    import subprocess

    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "baseline.yml").write_text("name: baseline\n")
    (tmp_path / "guide.md").write_text("one\n")
    (tmp_path / "pixi.lock").write_text("lock v1\n")
    git("add", "-A")
    git("commit", "-q", "-m", "first")
    first = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                           capture_output=True, text=True).stdout.strip()
    return tmp_path, first, git


def test_a_lock_change_in_the_same_push_REFUSES_to_auto_baseline(
        verify_workflow, repo_with_history):
    """The laundering path, closed."""
    import subprocess

    repo, first, git = repo_with_history
    (repo / "guide.md").write_text("one\ntwo\n")
    (repo / "pixi.lock").write_text("lock v2\n")
    git("add", "-A")
    git("commit", "-q", "-m", "content + lock")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()

    r = _run_dispatch_script(_dispatch_step_script(verify_workflow), repo, first, head)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "pixi.lock" in (r.stdout + r.stderr)


def test_a_content_only_push_still_auto_baselines(verify_workflow, repo_with_history):
    """The refusal must be narrow. An ordinary content edit is the case the
    auto-baseline exists for, and breaking it would return the family to the
    hand-dispatch era this workflow's comments describe."""
    import subprocess

    repo, first, git = repo_with_history
    (repo / "guide.md").write_text("one\ntwo\n")
    git("add", "-A")
    git("commit", "-q", "-m", "content only")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()

    r = _run_dispatch_script(_dispatch_step_script(verify_workflow), repo, first, head)
    # `gh` is absent here, so the dispatch itself fails and the script says so —
    # what matters is that it REACHED the dispatch instead of refusing early.
    assert "pixi.lock" not in (r.stdout + r.stderr), r.stdout + r.stderr


@pytest.mark.parametrize("before", [
    "0" * 40,                                    # a branch's first push
    "deadbeef" * 5,                              # a discarded commit after force-push
])
def test_an_UNRESOLVABLE_range_refuses_rather_than_proceeding(
        verify_workflow, repo_with_history, before):
    """FAIL CLOSED — this is the bug the first version of the guard had.

    `git diff` errors on both of these, and the original swallowed the error with
    `2>/dev/null`. grep then matched nothing, so the guard concluded "the lock did
    not change" and auto-baselined — inverting itself in exactly the case where it
    cannot establish the answer.
    """
    import subprocess

    repo, _, git = repo_with_history
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()

    r = _run_dispatch_script(_dispatch_step_script(verify_workflow), repo, before, head)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "cannot be resolved" in (r.stdout + r.stderr)


def test_every_committed_reference_is_watched_not_just_the_pdf(repo_root):
    """The deck has committed bytes and was never drift-checked.

    `run()` hardcoded the pdf staleness call and `_reference_path` returned
    `<slug>.pdf`, so the one class of change this module exists for — a
    dependency bump that moves typography with NO source change — was caught for
    the guide and invisible for the deck. It is not a hypothetical gap for the
    deck specifically: it shares `_COMMON_FILES` with the PDF, and `make verify`
    cannot see the cause either, because `pixi.lock` is deliberately outside
    SOURCE_FILES.

    Asserted through `_watched`, against the artifact table rather than a
    literal, so declaring a fourth artifact with a reference cannot quietly leave
    it unwatched.
    """
    watched = set(driftcanary._watched(repo_root))
    cfg = kitconfig.load(repo_root)
    expected = {a for a in cfg.outputs.declared
                if kitconfig.artifact_spec(a).reference is not None}
    assert watched == expected and "slides" in watched, watched
    # The site is excluded by construction, not by omission: it is deployed
    # rather than blessed into the repo, so there are no committed bytes to diff.
    assert "site" not in watched
    for artifact in watched:
        assert driftcanary._reference_path(repo_root, artifact).name.endswith(".pdf")
    assert (driftcanary._reference_path(repo_root, "pdf")
            != driftcanary._reference_path(repo_root, "slides"))
