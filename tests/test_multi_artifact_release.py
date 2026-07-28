"""`--artifact` is wired through ALL FOUR stages, not just the predicate.

The flag was removed once, and the reason is the whole point of this file. The
predicate was artifact-aware while the build, the promotable check and the
promotion were not, so `--artifact slides` created the source commit and *then*
validated `build/<slug>.pdf` against the deck's closure. That is worse than an
unimplemented flag: it fails after mutating the tree, which is the one failure
mode a release must not have.

So these tests do not ask "does the flag parse". They ask whether each stage
resolves the same filename, and whether an artifact that cannot be released is
refused BEFORE anything is written.
"""
import subprocess
import sys
from pathlib import Path

import pytest

import kitconfig
import release

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run([sys.executable, *args], cwd=REPO_ROOT,
                          capture_output=True, text=True)


# ----- the artifact that CANNOT be released is refused up front -----------------

def test_releasing_the_site_is_refused_with_its_reason():
    """The site is deployed, not blessed into the repo — there is no committed
    byte-sequence to promote. Refusing early is what stops it being silently
    treated as the PDF, which is what the old constant did."""
    got = _run("release.py", "-m", "x", "--artifact", "site")
    assert got.returncode != 0
    assert "no committed reference" in got.stderr
    assert "deployed" in got.stderr


def test_the_refusal_happens_before_anything_is_written():
    """`git status` must be unchanged — the refusal is a preflight, not a
    rollback."""
    before = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                            capture_output=True, text=True, check=True).stdout
    _run("release.py", "-m", "x", "--artifact", "site")
    after = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                           capture_output=True, text=True, check=True).stdout
    assert before == after


# ----- one resolver, so the stages cannot disagree ------------------------------

@pytest.mark.parametrize("artifact,expected", [
    ("pdf", "probe.pdf"),
    ("slides", "probe-slides.pdf"),
])
def test_the_reference_name_resolves_per_artifact(artifact, expected, monkeypatch):
    monkeypatch.setattr(release, "ARTIFACT", artifact)
    assert release._reference_name("probe") == expected


def test_every_stage_uses_that_one_resolver():
    """A grep-level assertion on purpose. The defect was two stages computing the
    filename independently, so what matters is that only one place spells it."""
    text = (REPO_ROOT / "release.py").read_text(encoding="utf-8")
    assert 'f"{slug}.pdf"' not in text, (
        "release.py still builds a reference filename from a `{slug}.pdf` "
        "literal — that is the half-wiring the flag was once removed for")


# ----- baseline resolves the same set -------------------------------------------

def test_list_references_names_every_declared_reference():
    got = _run("baseline.py", "--list-references")
    assert got.returncode == 0, got.stderr
    names = got.stdout.split()
    cfg = kitconfig.load(REPO_ROOT)
    for artifact in cfg.outputs.declared:
        spec = kitconfig.artifact_spec(artifact)
        if spec.reference:
            assert spec.reference.replace("<slug>", cfg.OUTPUT_SLUG) in names


def test_the_deck_is_in_that_list_not_just_the_pdf():
    """The literal `$SLUG.pdf` the workflow used before would never have staged
    `<slug>-slides.pdf`, so the deck's reference would go stale uncommitted."""
    got = _run("baseline.py", "--list-references")
    assert any(n.endswith("-slides.pdf") for n in got.stdout.split())


def test_baselining_the_site_is_a_no_op_not_a_crash():
    """The CI loop runs every artifact name; one with no reference has to say so
    and exit 0, or the loop would fail on a guide that declares a site."""
    got = _run("baseline.py", "--artifact", "site")
    assert got.returncode == 0
    assert "no committed reference" in got.stdout
