"""kit-manifest.toml classifies every tracked file, on two independent axes.

Enumerates `git ls-files` and asserts: every path carries exactly one source
lifecycle; a destination policy is present iff the path has a projected
destination; the `.example` -> live and templates/web -> app mappings project
correctly; both PDF-only and web-enabled shapes resolve; and deploy.yml IS
sync-managed at its live destination — the regression the collapsed single-axis
model caused.
"""
import subprocess
from pathlib import Path

import pytest

import kitmanifest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def manifest():
    return kitmanifest.load(REPO_ROOT)


def test_manifest_loads(manifest):
    assert manifest.entries


def test_every_tracked_file_is_classified(manifest):
    unclassified = [p for p in _tracked_files() if manifest.classify(p) is None]
    assert not unclassified, f"unclassified tracked files: {unclassified}"


def test_each_file_has_exactly_one_valid_lifecycle(manifest):
    for p in _tracked_files():
        e = manifest.classify(p)
        assert e is not None
        assert e.lifecycle in kitmanifest.LIFECYCLES, f"{p}: bad lifecycle {e.lifecycle}"


def test_destination_policy_iff_projected(manifest):
    # load() already enforces projects_to <=> policy; assert it holds for every
    # classified tracked file, and that a present policy is valid.
    for p in _tracked_files():
        e = manifest.classify(p)
        assert (e.projects_to is None) == (e.policy is None), f"{p}: half a destination"
        if e.policy is not None:
            assert e.policy in kitmanifest.POLICIES, f"{p}: bad policy {e.policy}"


def test_no_duplicate_entries():
    # A tracked file must not be governed by two EXACT entries. (load() rejects
    # duplicate paths; this guards the classify precedence too.)
    m = kitmanifest.load(REPO_ROOT)
    exact = [e.path for e in m.entries if not e.is_glob]
    assert len(exact) == len(set(exact))


@pytest.mark.parametrize("src,dest,policy", [
    (".github/workflows/deploy.yml.example", ".github/workflows/deploy.yml", "identical"),
    ("style-screen.css.example", "style-screen.css", "never"),
    ("transforms.py.example", "transforms.py", "never"),
    # `never`: generated per-target from guide.toml by cfadapter.py, because the
    # routes block is conditional structure that substitution cannot express.
    ("templates/web/wrangler.jsonc", "app/wrangler.jsonc", "never"),
    ("templates/web/package.json", "app/package.json", "identical"),
])
def test_bootstrap_source_mappings(manifest, src, dest, policy):
    e = manifest.classify(src)
    assert e is not None, f"{src} unclassified"
    assert e.lifecycle == "bootstrap-source"
    assert e.projects_to == dest
    assert e.policy == policy


def test_guide_toml_is_never_and_readable_not_writable(manifest):
    e = manifest.classify("guide.toml")
    assert e.policy == "never"           # sync reads it, never writes it
    assert e.lifecycle == "retained-in-kit"


def test_bootstrap_py_has_no_destination(manifest):
    e = manifest.classify("bootstrap.py")
    assert e.lifecycle == "retained-in-kit"
    assert e.projects_to is None and e.policy is None


def test_both_target_shapes_resolve(manifest):
    web = manifest.projections("web-enabled")
    pdf = manifest.projections("pdf-only")
    assert web and pdf
    web_dests = {p.dest for p in web}
    pdf_dests = {p.dest for p in pdf}
    # web-layer destinations are present for web, inert (absent) for pdf-only.
    assert ".github/workflows/deploy.yml" in web_dests
    assert ".github/workflows/deploy.yml" not in pdf_dests
    assert "app/wrangler.jsonc" in web_dests
    assert not any(d.startswith("app/") for d in pdf_dests)
    # identical/templated/never kit files project in BOTH shapes.
    assert "build.py" in pdf_dests and "build.py" in web_dests


def test_deploy_yml_is_sync_managed_at_its_live_destination(manifest):
    # The regression the collapsed single-axis model caused: deploy.yml must be
    # sync-managed (identical) at .github/workflows/deploy.yml for web targets.
    web = manifest.projections("web-enabled")
    deploy = [p for p in web if p.dest == ".github/workflows/deploy.yml"]
    assert len(deploy) == 1
    assert deploy[0].policy == "identical"
    assert deploy[0].source == ".github/workflows/deploy.yml.example"


def test_unknown_shape_rejected(manifest):
    with pytest.raises(kitmanifest.ManifestError):
        manifest.projections("nonsense")


# The paired-fields invariant is satisfied by deleting BOTH fields, which would
# silently drop a required file from sync. Pin the core identical-tier set so
# that regression fails by name.
CORE_IDENTICAL = [
    "build.py", "release.py", "verify_artifacts.py", "verify_web.py", "kitconfig.py",
    "baseline.py", "Makefile", "LICENSE", "LICENSE-CONTENT",
    ".github/workflows/baseline.yml",
]


@pytest.mark.parametrize("path", CORE_IDENTICAL)
def test_core_files_sync_identical_to_themselves(manifest, path, ):
    e = manifest.classify(path)
    assert e is not None, f"{path} unclassified"
    assert e.policy == "identical", f"{path} must be identical-tier, got {e.policy}"
    assert e.projects_to == path, f"{path} must project to itself, got {e.projects_to}"
    # ...and it must actually appear in BOTH shapes' projections (not dropped).
    for shape in ("pdf-only", "web-enabled"):
        dests = {p.dest for p in manifest.projections(shape)}
        assert path in dests, f"{path} missing from {shape} projections"


def test_reference_pdf_slug_is_resolved(manifest):
    # projections leaves the <slug> placeholder without a slug, and resolves it
    # to a concrete path when given one (as sync does from the target guide.toml).
    unresolved = {p.dest for p in manifest.projections("pdf-only")}
    assert "<slug>.pdf" in unresolved
    resolved = {p.dest for p in manifest.projections("pdf-only", slug="probe-guide")}
    assert "probe-guide.pdf" in resolved
    assert "<slug>.pdf" not in resolved


def test_glob_matches_nested_but_not_siblings(manifest):
    # tests/** matches a nested file, but a delimiter-aware prefix must NOT match
    # a sibling directory like `tests-foo/` (raw startswith would over-match).
    assert manifest.classify("tests/test_manifest_roles.py") is not None
    assert manifest.classify("tests/deep/nested/thing.py") is not None
    assert manifest.classify("tests-foo/x.py") is None
    assert manifest.classify("plans-archive/old.md") is None


def test_exact_entry_wins_over_a_covering_glob():
    # Precedence: an exact entry beneath a matching glob must win. Build a tiny
    # manifest to prove classify() checks exact before glob (reversing it breaks).
    m = kitmanifest.Manifest([
        kitmanifest.Entry(path="tests/**", lifecycle="retained-in-kit"),
        kitmanifest.Entry(
            path="tests/special.py", lifecycle="retained-in-kit",
            projects_to="tests/special.py", policy="identical",
        ),
    ])
    e = m.classify("tests/special.py")
    assert e.policy == "identical"           # the exact entry, not the glob
    assert m.classify("tests/other.py").policy is None  # falls through to the glob
