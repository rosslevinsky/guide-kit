"""The guards are WIRED IN — not merely correct when called.

WHY THIS FILE EXISTS. Three independent reviews of the finished kit converged on
one sentence: *guards are tested as functions, but never as wiring.* Every
serious finding was an instance of it. This is the file that closes the class,
so the next one is caught by a test rather than by a reviewer.

The measurement that motivated it, reproduced exactly:

    $ printf '\\n.smuggled { font-family: Georgia, serif; }\\n' >> style.css
    $ python build.py
    build: style.css: names 1 family/families the kit does not bundle: Georgia.
    EXIT=1                                    # correct — the guard fired

    # now replace ONE line in render_pdf.build() —
    #     buildcore.check_overrides(cascade)   ->   pass
    $ python build.py
      PDF   ->  build/guide-template.pdf
    EXIT=0                                    # the guard is gone
    $ pytest -q
    1211 passed                               # ...and the suite does not care

Five call sites were deletable that way with the suite green:
`assert_hermetic_fontconfig`, `check_font_provenance`, `check_overrides` and
`check_glyph_coverage` in `render_pdf.build`, and `_check_template_hygiene` in
`build.main`. Each guard had exhaustive unit tests. Not one of them ran the
build.

TWO KINDS OF TEST HERE, AND BOTH ARE NEEDED.

  * **Behavioural** — materialize a guide, break the thing the guard protects,
    run `build.py` as a subprocess, and require a nonzero exit. This is the real
    one: it proves the guard is reached, that its failure aborts the build, and
    that it does so BEFORE an output is written. A unit test of the guard proves
    none of the three.

  * **Structural** — read the entry points' ASTs and assert each guard is
    called. Weaker, and it earns its place by covering guards whose behavioural
    trigger is expensive or host-dependent, and by failing on the *addition* of
    an unwired guard rather than only on the deletion of a wired one.

WHAT WOULD MAKE THESE TESTS WORTHLESS: asserting on `buildcore` directly.
Every assertion below goes through `build.py`, which is the artifact whose
behaviour is in question.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run `build.py` in `root` and RETURN the result rather than raising.

    conftest's `render()` asserts success, which is the wrong shape here — every
    test in this file is about a build that must fail.
    """
    return subprocess.run(
        [sys.executable, "build.py", *args],
        cwd=root, capture_output=True, text=True,
    )


def _assert_refused(result: subprocess.CompletedProcess, expect: str, guard: str):
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"build.py exited 0 with {guard} deliberately violated.\n"
        f"The guard's own unit tests still pass — that is the point. Its CALL "
        f"has been removed from the build entry point, so nothing runs it.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert expect in combined, (
        f"build.py failed, but not for the reason {guard} exists.\n"
        f"Expected to see {expect!r}.\n--- output ---\n{combined}"
    )


# ---------------------------------------------------------------------------
# Behavioural: break the protected thing, require the BUILD to refuse
# ---------------------------------------------------------------------------

def test_an_unbundled_font_family_stops_the_build(guide_repo):
    """`check_overrides` — the reproduction in the module docstring, automated.

    A host family in the cascade renders differently on every machine, which is
    the single property bundling exists to buy.
    """
    root, _ = guide_repo
    style = root / "style.css"
    style.write_text(style.read_text(encoding="utf-8")
                     + "\n.smuggled { font-family: Georgia, serif; }\n",
                     encoding="utf-8")

    _assert_refused(_build(root, "--html-preview"), "Georgia",
                    "the unbundled-family override guard")


def test_a_font_that_does_not_match_its_recorded_hash_stops_the_build(guide_repo):
    """`check_font_provenance` — a face is a render input with no other tripwire.

    Swapping one for a different upstream build changes every page. The stamp
    moves (faces are in the closure) but says nothing about WHY, and a
    re-baseline would simply bless the new bytes.
    """
    root, _ = guide_repo
    record = root / "fonts" / "vendor" / "UPSTREAM-HASHES.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data.get("faces"), "the fixture carries no provenance record to break"
    victim = sorted(data["faces"])[0]
    data["faces"][victim] = "0" * 64
    record.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    _assert_refused(_build(root, "--html-preview"), "provenance",
                    "the font provenance guard")


def test_a_missing_fontconfig_template_stops_the_build(guide_repo):
    """`assert_hermetic_fontconfig` — it FAILS CLOSED, and that is the property.

    A tree that has the faces but lost the template would otherwise render
    against the host's font configuration, silently, under an unchanged stamp.
    Deleting the template is used rather than making it non-hermetic because it
    is deterministic on any host, including one with no system fonts at all.
    """
    root, _ = guide_repo
    (root / "fontconfig" / "fonts.conf").unlink()

    _assert_refused(_build(root, "--html-preview"), "host's font configuration",
                    "the hermetic-Fontconfig guard")


def test_a_codepoint_no_bundled_face_covers_stops_the_build(guide_repo):
    """`check_glyph_coverage` — tofu on someone else's machine, green here.

    The character renders on the author's box (the host has a face for it) and
    as a blank box elsewhere, while `make verify` stays green because the source
    genuinely did not change.
    """
    root, _ = guide_repo
    src = root / "guide.md"
    # U+1F9D1 — an emoji. No text face the kit bundles has a glyph for it.
    src.write_text(src.read_text(encoding="utf-8") + "\nA person: \U0001F9D1\n",
                   encoding="utf-8")

    _assert_refused(_build(root, "--html-preview"), "1F9D1",
                    "the glyph-coverage guard")


def test_an_uninitialized_template_stops_the_build(guide_repo):
    """`_check_template_hygiene`, called from `build.main` rather than the
    renderer — so it is a second entry point, and it was equally unwired."""
    root, _ = guide_repo
    (root / "README.md").write_text(
        "# {{GUIDE_NAME}}\n\nThe fork never ran bootstrap.\n", encoding="utf-8")

    _assert_refused(_build(root, "--html-preview"), "template not initialized",
                    "the template-hygiene guard")


def test_the_fixture_builds_when_nothing_is_broken(guide_repo):
    """The control. Without it every assertion above could be passing because
    the fixture never builds at all — which is how a gate ends up green against
    a tree it has never actually exercised."""
    root, _ = guide_repo
    result = _build(root, "--html-preview")
    assert result.returncode == 0, (
        f"the unmodified fixture does not build, so the refusals above prove "
        f"nothing:\n{result.stdout}\n{result.stderr}")


# ---------------------------------------------------------------------------
# Structural: the call sites, read out of the entry points themselves
#
# Cheaper than the behavioural tests and strictly weaker — it cannot tell a call
# that runs from one inside `if False:`. It covers a different direction: adding
# a guard to buildcore without wiring it in is caught here and by nothing else,
# because there is no failing build to observe when the guard never runs.
# ---------------------------------------------------------------------------

# The contract. A guard removed from this list has been removed from the build.
REQUIRED_CALLS: dict[tuple[str, str], tuple[str, ...]] = {
    ("render_pdf.py", "build"): (
        "assert_hermetic_fontconfig",
        "check_font_provenance",
        "check_overrides",
        "check_glyph_coverage",
        "check_rendered_families",
        "check_rendered_coverage",
    ),
    ("render_pdf.py", "render_html"): (
        "check_cjk_annotations",
    ),
    ("build.py", "main"): (
        "_check_template_hygiene",
    ),
    # The deck is a deliverable too, and it had FEWER guards than the PDF. It
    # renders from its own cascade and, with `[slides] file`, from its own
    # source — so the PDF's checks say nothing about it.
    ("render_slides.py", "build_slides"): (
        "assert_hermetic_fontconfig",
        "check_font_provenance",
        "check_overrides",
        "check_rendered_families",
        "check_rendered_coverage",
    ),
    ("render_slides.py", "render_html"): (
        "check_cjk_annotations",
    ),
}


def _called_names(module: str, func: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / module).read_text(encoding="utf-8"))
    target = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == func), None)
    assert target is not None, f"{module} has no function {func!r}"
    names = set()
    for node in ast.walk(target):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Attribute):
            names.add(callee.attr)
        elif isinstance(callee, ast.Name):
            names.add(callee.id)
    return names


@pytest.mark.parametrize(
    ("module", "func", "guard"),
    [(m, f, g) for (m, f), guards in REQUIRED_CALLS.items() for g in guards],
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_the_guard_is_called_from_the_entry_point(module, func, guard):
    assert guard in _called_names(module, func), (
        f"{module}:{func}() no longer calls {guard}(). The guard's own unit "
        f"tests will still pass — they call it directly. Nothing else runs it.")


def test_the_structural_check_can_fail():
    """A gate nobody has seen fire is a gate nobody should trust."""
    assert "check_overrides" in _called_names("render_pdf.py", "build")
    assert "no_such_guard_anywhere" not in _called_names("render_pdf.py", "build")


def test_every_buildcore_guard_is_wired_somewhere():
    """The other direction: a `check_*` in buildcore that no entry point calls.

    Nothing fails when an unwired guard is added — there is no build to observe
    refusing — so this is the only thing that would notice.
    """
    import buildcore

    defined = {n for n in dir(buildcore)
               if n.startswith("check_") or n.startswith("assert_")}
    wired = set().union(*(set(v) for v in REQUIRED_CALLS.values()))
    # Called through another guard rather than from an entry point directly.
    indirect = {"check_override", "check_svg_attributes"}
    orphans = sorted(defined - wired - indirect)
    assert not orphans, (
        f"buildcore defines guard(s) no entry point calls: {orphans}. Wire them "
        f"into render_pdf.build()/build.main() and add them to REQUIRED_CALLS, "
        f"or delete them — an unwired guard is a comment.")


def test_the_inputs_the_behavioural_tests_break_are_really_there(guide_repo):
    """Each behavioural test above breaks one file. If the fixture ever stops
    materializing one, that test would mutate nothing and pass vacuously — the
    failure mode this whole file exists to catch, reappearing inside it."""
    root, _ = guide_repo
    for rel in ("build.py", "buildcore.py", "render_pdf.py", "style.css",
                "fontfaces.css", "cascadecheck.py", "guide.md",
                "fonts/vendor/UPSTREAM-HASHES.json", "fontconfig/fonts.conf"):
        assert (root / rel).is_file(), (
            f"the fixture does not materialize {rel}, so the test that breaks "
            f"it is asserting against a file that was never there")
