#!/usr/bin/env python3
"""The permanent drift canary: does a fresh render still match the
committed reference?

WHY THIS EXISTS. `make verify` hashes `SOURCE_FILES` and answers "did the source
change?". `pixi.lock` is not in that list, so a dependency bump that shifts how
WeasyPrint or fontconfig lays out text moves the deliverable while the staleness
check stays correctly green. The family previously named `make verify-render` as
the compensating control for that gap. It was not one, three ways over:

  1. CI never ran it — `verify.yml` runs only the build-free staleness check.
  2. It compares page count and extracted text, so a FACE-ONLY substitution with
     identical text and pagination passes it.
  3. On a stale default-branch push, `verify.yml` auto-dispatches `baseline.yml`,
     which renders and COMMITS a fresh reference without comparing it to the old
     one — absorbing any drift that rode along with a content change.

So this compares on two axes:

  * **PDF bytes.** Strictly stronger than a text diff: it sees kerning,
    justification and glyph metrics that preserve line breaks. Available because
    the render is deterministic — `SOURCE_DATE_EPOCH` comes from the artifact's
    authored date and qpdf canonicalizes the output, so two builds of identical
    committed source are byte-identical (docs/determinism-evidence.md).
  * **The `pdffonts` embedded-face list.** Not redundant with bytes: it NAMES a
    substitution rather than merely reporting that the render moved, and a
    typeface swap is the most likely drift in a font-bundling family.

WHEN IT MUST STAY SILENT, and why each case is a skip rather than a failure:

  * **The reference is stale.** Then the source really did change, a fresh render
    SHOULD differ, and that difference says nothing about the toolchain. It is
    `make verify`'s finding to report. Reporting it here too would make the
    canary red on every ordinary content edit until the baseline caught up, which
    is how a check gets ignored.
  * **There is no reference yet** (pre-first-release). Nothing to compare.

A broken staleness check (rc 2) is an ERROR, not a skip: rendering and comparing
on the strength of a check that did not work is how a wrong verdict gets
published.

**It must NEVER trigger an auto-baseline.** That is not a style preference. The
stale path auto-baselines by design; if the drift path did too, the drift would
be committed straight into the reader-facing PDF and the check that found it
would have become the mechanism that laundered it.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import kitconfig

ROOT = Path(__file__).parent.resolve()


class CanaryError(RuntimeError):
    """A comparison that could not be made. Never silently a pass."""


# ---------------------------------------------------------------------------
# The two axes
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def face_list(pdf: Path) -> list[str]:
    """The embedded font faces `pdffonts` reports, as `<name> <emb>` rows, sorted.

    Sorted rather than in document order: the axis is "which faces are in this
    PDF", and ordering that follows first-use would make an unrelated content
    reflow look like a font change.

    The name is taken by SLICING THE FIXED-WIDTH COLUMN, not by splitting on
    whitespace. `row.split()[0]` is the obvious version and it silently
    truncates: a PostScript name may legally contain a space, so `Foo Regular`
    and `Foo Bold` both reduce to `Foo` and a real substitution between them
    reports an unchanged list — the face axis going quiet in exactly the case it
    exists for. The column width is read from the header rule rather than
    hardcoded, so a poppler that widens the column does not silently re-truncate.

    The embedded flag rides along because it is a distinct failure: the same
    family name, no longer embedded, is a broken deliverable (the reader's
    machine substitutes) that a name-only comparison would call identical.
    """
    if shutil.which("pdffonts") is None:
        raise CanaryError(
            "pdffonts is not on PATH — install via pixi (`pixi install`); "
            "poppler is pinned in pixi.toml"
        )
    try:
        out = subprocess.run(
            ["pdffonts", str(pdf)],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise CanaryError(f"pdffonts failed on {pdf}: {exc.stderr.strip()}") from exc

    lines = out.splitlines()
    if len(lines) < 2 or not lines[1].startswith("---"):
        raise CanaryError(
            f"pdffonts output on {pdf} is not the expected two-line header plus "
            f"rows — refusing to guess at its shape. First lines: {lines[:2]}"
        )
    # The rule line is groups of dashes separated by single spaces, one group per
    # column. The first group's width is the name column's width; the `emb`
    # column is the 5th.
    widths = [len(g) for g in lines[1].split(" ")]
    name_w = widths[0]
    emb_start = sum(w + 1 for w in widths[:4])

    faces = []
    for row in lines[2:]:
        if not row.strip():
            continue
        name = row[:name_w].strip()
        emb = row[emb_start:emb_start + 3].strip() or "?"
        faces.append(f"{name} [embedded={emb}]")
    return sorted(faces)


@dataclass(frozen=True)
class Verdict:
    """The result of one comparison. `failures` is the operator-facing text."""
    byte_match: bool
    face_match: bool
    reference_digest: str
    fresh_digest: str
    reference_faces: list[str]
    fresh_faces: list[str]
    failures: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.byte_match and self.face_match


def compare(reference: Path, fresh: Path) -> Verdict:
    """Compare a fresh render against the committed reference on both axes.

    Both axes are evaluated even when the first already failed: an operator
    looking at drift wants to know whether the faces moved too, and stopping at
    the byte mismatch would hide the more diagnostic half.
    """
    for label, path in (("reference", reference), ("fresh render", fresh)):
        if not path.exists():
            raise CanaryError(f"drift canary: {label} not found: {path}")

    ref_digest, fresh_digest = _sha256(reference), _sha256(fresh)
    ref_faces, fresh_faces = face_list(reference), face_list(fresh)

    failures: list[str] = []
    if ref_digest != fresh_digest:
        failures.append(
            f"PDF bytes differ: reference sha256 {ref_digest[:12]}, "
            f"fresh render {fresh_digest[:12]}"
        )
    if ref_faces != fresh_faces:
        gone = [f for f in ref_faces if f not in fresh_faces]
        new = [f for f in fresh_faces if f not in ref_faces]
        failures.append(
            "embedded face list differs: "
            + (f"no longer present {gone}; " if gone else "")
            + (f"newly present {new}" if new else "")
        )

    return Verdict(
        byte_match=ref_digest == fresh_digest,
        face_match=ref_faces == fresh_faces,
        reference_digest=ref_digest,
        fresh_digest=fresh_digest,
        reference_faces=ref_faces,
        fresh_faces=fresh_faces,
        failures=failures,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Result:
    status: str          # "clean" | "drift" | "skipped" | "error"
    reason: str
    exit_code: int
    verdict: Verdict | None = None


def _staleness_rc(root: Path, artifact: str = "pdf") -> int:
    """The staleness check's verdict: 0 fresh, 1 not-fresh, 2 unusable.

    Shelled out rather than imported so this reads the SAME code path CI's
    `make verify` runs, and so a test can substitute it without a renderer.

    The mapping is deliberately NARROW, because the obvious version fails open
    in two directions:

      * `verify_artifacts.py` exits 1 for "stale" — but an unhandled exception
        also exits 1, and Python prints a traceback when it does. Returning that
        as "stale" turns a broken checker into a clean SKIP, which reads as a
        pass. A traceback on stderr therefore demotes rc 1 to UNUSABLE.
      * Any code outside {0, 1, 2} — a signal death is -9, a missing interpreter
        is 127 — is not a verdict at all. Passing it through unmapped let the
        caller's `rc == 2` / `rc == 1` tests both miss and fall through to
        "fresh", which would then render and report drift on the strength of a
        check that never ran.
    """
    proc = subprocess.run(
        [sys.executable, str(root / "verify_artifacts.py"), "--staleness",
         "--artifact", artifact],
        cwd=root, capture_output=True, text=True,
    )
    if proc.returncode == 1 and "Traceback (most recent call last)" in proc.stderr:
        return 2
    if proc.returncode not in (0, 1, 2):
        return 2
    return proc.returncode


def _reference_path(root: Path) -> Path:
    return root / f"{kitconfig.load(root).OUTPUT_SLUG}.pdf"


def _render(root: Path) -> Path:
    """Build the working render and return its path."""
    slug = kitconfig.load(root).OUTPUT_SLUG
    subprocess.run(["pixi", "run", "build"], cwd=root, check=True)
    working = root / "build" / f"{slug}.pdf"
    if not working.exists():
        raise CanaryError(f"drift canary: expected a fresh render at {working}")
    return working


def run(root: Path = ROOT, *, render=None) -> Result:
    """Decide, in the order the decisions actually gate each other.

    Staleness is consulted BEFORE rendering: on a stale tree there is nothing to
    learn from a render, and building anyway would spend a CI minute to produce a
    difference we would then have to discard.
    """
    rc = _staleness_rc(root)
    if rc != 0:
        # Everything that is not an unambiguous "fresh" is handled before the
        # render, and the DEFAULT for an unrecognised verdict is the refusal, not
        # the skip: a `rc == 2 -> error / rc == 1 -> skip / else fresh` ladder
        # treats an unmapped code as permission to proceed, which is the wrong
        # direction to fail in a check whose whole job is to notice.
        if rc != 1:
            return Result(
                "error",
                f"the staleness check returned an unusable verdict ({rc}) — "
                "refusing to judge drift on a check that did not work",
                2,
            )
        # rc 1 is broader than "stale": it also covers an unreadable stamp, a
        # reference baselined dirty, and one released-then-deleted. All four mean
        # the same thing here — freshness is NOT established, so a difference
        # carries no information about the toolchain.
        return Result(
            "skipped",
            "the committed reference is not established as fresh, so a fresh "
            "render is EXPECTED to differ — that is `make verify`'s finding, "
            "not drift",
            0,
        )

    reference = _reference_path(root)
    if not reference.exists():
        return Result(
            "skipped",
            f"pre-first-release — no reference PDF ({reference.name}) to compare against",
            0,
        )

    fresh = (render or (lambda: _render(root)))()
    verdict = compare(reference, fresh)
    if verdict.clean:
        return Result(
            "clean",
            f"fresh render is byte-identical to {reference.name} "
            f"({verdict.reference_digest[:12]}), faces unchanged",
            0,
            verdict,
        )
    return Result(
        "drift",
        "source is unchanged but the render is not — this is toolchain drift",
        1,
        verdict,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--fresh", type=Path,
        help="Compare this already-built PDF instead of running a build "
             "(CI reuses the render the build-smoke step already produced).",
    )
    args = ap.parse_args()

    try:
        result = run(ROOT, render=(lambda: args.fresh) if args.fresh else None)
    except CanaryError as exc:
        sys.stderr.write(f"ERROR {exc}\n")
        return 2

    if result.status == "skipped":
        print(f"SKIP  drift canary: {result.reason}")
    elif result.status == "clean":
        print(f"PASS  drift canary: {result.reason}")
    elif result.status == "error":
        sys.stderr.write(f"ERROR drift canary: {result.reason}\n")
    else:
        sys.stderr.write(f"FAIL  drift canary: {result.reason}\n")
        for failure in result.verdict.failures:
            sys.stderr.write(f"        {failure}\n")
        sys.stderr.write(
            "\n  The source is unchanged, so this is the environment moving under a\n"
            "  fixed input: a dependency bump, a rebuilt runner image, a font\n"
            "  package update. Do NOT re-baseline to make it green — that commits\n"
            "  the drift into the deliverable. Investigate what moved (pixi.lock,\n"
            "  the runner image), decide whether the new render is acceptable, and\n"
            "  re-baseline deliberately if it is.\n"
        )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
