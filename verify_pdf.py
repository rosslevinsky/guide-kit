#!/usr/bin/env python3
"""Reference-PDF verification for the guide.

Two distinct commands, deliberately not one (plan.md:95):

    python verify_pdf.py --staleness
        The PRIMARY gate (`make verify`). Is the committed reference PDF out of
        date with the source? Compares the content hash embedded in the PDF's
        version-stamp footer (one pdftotext call) against a freshly computed
        kitconfig.content_hash() over SOURCE_FILES. NO pandoc, NO WeasyPrint, no
        rendering, no platform sensitivity — milliseconds, correct on any
        machine, so this is what CI runs.

    python verify_pdf.py --render <reference.pdf> <candidate.pdf>
        The render canary (`make verify-render`). Page count + stamp-EXCLUDED
        text comparison between the committed reference and a fresh build.
        Requires a build and is platform-sensitive (font substitution changes
        line wrapping, so page count can legitimately differ between a Linux
        build and a macOS baseline), so it runs on the canonical host ONLY and
        is NEVER wired into CI. Its one genuine catch is environmental drift — a
        `pixi update` that shifts layout with no source change.

Absent reference PDF (staleness): a guide that has never been released has zero
root PDFs by design (bootstrap deletes the inherited template PDF; the guide's
own does not exist until its first macOS `make release`). That state PASSES with
a `pre-first-release` notice. A PDF that WAS released and is now gone FAILS — the
discriminator is git history for the reference path. The missing-PDF hole for a
web-enabled guide is separately closed by build_web()'s hard failure (build.py).

Exit codes:
    0 — fresh, or pre-first-release
    1 — stale, deleted-after-release, or a render-canary mismatch
    2 — invocation / environment error (missing args, tool not on PATH, bad file)
"""
from __future__ import annotations

import argparse
import difflib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import kitconfig

HERE = Path(__file__).parent.resolve()

# The version stamp rendered into the footer: "YYYY-MM-DD HH:MM:SS · <12 hex>"
# (+ " · dirty"). Only the 12-hex content hash is needed to answer staleness.
_STAMP_HASH_RE = re.compile(r"·\s*([0-9a-f]{12})\b")
# A whole stamp line, for the render canary's stamp-exclusion and the dirty check.
_STAMP_LINE_RE = re.compile(
    r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\s*·\s*[0-9a-f]{12}(?:\s*·\s*dirty)?"
)


def _require(tools: list[str]) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        sys.stderr.write(
            "verify_pdf.py: missing required tools on PATH: "
            + ", ".join(missing)
            + "\n  Install via pixi (`pixi install`) — all are pinned in pixi.toml.\n"
        )
        sys.exit(2)


def _pdftotext(pdf: Path) -> str:
    result = subprocess.run(
        ["pdftotext", str(pdf), "-"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return result.stdout


# ---------------------------------------------------------------------------
# Staleness check (make verify) — the primary, platform-independent gate
# ---------------------------------------------------------------------------

def parse_stamp_hash(text: str) -> str | None:
    """Return the first 12-hex content hash from a version stamp in `text`, or
    None. Pure function over already-extracted text — no PDF, no tools — so the
    comparison logic is testable without a renderer."""
    m = _STAMP_HASH_RE.search(text)
    return m.group(1) if m else None


def extract_stamp_hash(pdf: Path) -> str | None:
    """The 12-hex content hash embedded in the PDF's footer stamp, or None."""
    return parse_stamp_hash(_pdftotext(pdf))


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            encoding="utf-8", check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _was_ever_released(root: Path, reference: Path) -> bool:
    """True if the reference PDF path has any commit history — i.e. it was
    released at least once and is now missing (deleted), vs. never released."""
    return bool(_git(root, "log", "-1", "--format=%H", "--", reference.name).strip())


def _changed_source_files(root: Path, reference: Path) -> list[str]:
    """Best-effort: the SOURCE_FILES entries that changed since the reference
    PDF's last commit (committed-since or in the working tree). Names the stale
    file(s) for the operator. Falls back to files with working-tree changes."""
    ref_commit = _git(root, "log", "-1", "--format=%H", "--", reference.name).strip()
    if ref_commit:
        diff = _git(root, "diff", "--name-only", ref_commit, "--", *kitconfig.SOURCE_FILES)
        changed = [line for line in diff.splitlines() if line.strip()]
        if changed:
            return changed
    # Fallback: uncommitted SOURCE_FILES modifications.
    status = _git(root, "status", "--porcelain", "--", *kitconfig.SOURCE_FILES)
    return [line[3:] for line in status.splitlines() if line.strip()]


def staleness_check(root: Path = HERE) -> int:
    _require(["pdftotext"])
    slug = kitconfig.load(root).OUTPUT_SLUG
    reference = root / f"{slug}.pdf"

    if not reference.exists():
        if _was_ever_released(root, reference):
            sys.stderr.write(
                f"FAIL  reference PDF {reference.name} was released and is now missing "
                "— restore it or re-release.\n"
            )
            return 1
        print(f"OK    no reference PDF yet — pre-first-release ({reference.name})")
        return 0

    embedded = extract_stamp_hash(reference)
    current = kitconfig.content_hash(root)
    if embedded is None:
        sys.stderr.write(
            f"FAIL  {reference.name} has no readable version stamp — cannot verify staleness.\n"
        )
        return 1
    if embedded == current:
        print(f"OK    reference PDF is fresh (stamp {current} matches source)")
        return 0

    stale = _changed_source_files(root, reference)
    named = ", ".join(stale) if stale else "one or more SOURCE_FILES"
    sys.stderr.write(
        f"FAIL  reference PDF is STALE — embedded stamp {embedded} != source hash {current}.\n"
        f"      Changed since last release: {named}.\n"
        f"      Re-run `make release` (or `make baseline` + commit) on the canonical host.\n"
    )
    return 1


# ---------------------------------------------------------------------------
# Render canary (make verify-render) — canonical-host only, never in CI
# ---------------------------------------------------------------------------

def _canonicalize(pdf: Path, tmpdir: Path, name: str) -> Path:
    out = tmpdir / f"{name}.canon.pdf"
    subprocess.run(
        ["qpdf", "--deterministic-id", "--normalize-content=y",
         "--object-streams=preserve", str(pdf), str(out)],
        check=True,
    )
    return out


_PAGES_RE = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)


def _page_count(pdf: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, encoding="utf-8", check=True,
    )
    m = _PAGES_RE.search(result.stdout)
    if not m:
        raise RuntimeError(f"could not parse Pages from pdfinfo output for {pdf}")
    return int(m.group(1))


def strip_stamp(text: str) -> str:
    """Drop version-stamp fragments so the canary's text comparison carries
    signal. The stamp moves on every edit (and can gain ` · dirty`), so leaving
    it in would make verify-render red after every change (plan.md:95)."""
    return _STAMP_LINE_RE.sub("", text)


def render_canary(reference: Path, candidate: Path) -> int:
    _require(["pdfinfo", "pdftotext", "qpdf"])
    for label, p in (("reference", reference), ("candidate", candidate)):
        if not p.exists():
            sys.stderr.write(f"verify_pdf.py: {label} not found: {p}\n")
            return 2

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        ref = _canonicalize(reference, tmp, "reference")
        cand = _canonicalize(candidate, tmp, "candidate")

        pb, pc = _page_count(ref), _page_count(cand)
        if pb != pc:
            sys.stderr.write(
                f"FAIL  page count: reference={pb}, candidate={pc} (MISMATCH)\n"
            )
            return 1

        tb = strip_stamp(_pdftotext(ref))
        tc = strip_stamp(_pdftotext(cand))
        if tb != tc:
            snippet = "\n".join(
                list(difflib.unified_diff(
                    tb.splitlines(), tc.splitlines(),
                    fromfile="reference", tofile="candidate", lineterm="", n=2,
                ))[:50]
            )
            sys.stderr.write(
                "FAIL  stamp-excluded text DIFFERS — first 50 lines of unified diff:\n"
                + snippet + "\n"
            )
            return 1

    print(f"PASS  render canary: page count {pb} and stamp-excluded text identical")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Verify the guide's reference PDF.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--staleness", action="store_true",
        help="Primary gate: is the committed reference PDF out of date with the source? "
             "(no build, platform-independent — this is what CI runs)",
    )
    mode.add_argument(
        "--render", nargs=2, metavar=("REFERENCE", "CANDIDATE"), type=Path,
        help="Render canary: page count + stamp-excluded text (needs a build, "
             "platform-sensitive, canonical host only — never in CI)",
    )
    args = p.parse_args()

    if args.staleness:
        return staleness_check(HERE)
    return render_canary(args.render[0], args.render[1])


if __name__ == "__main__":
    raise SystemExit(main())
