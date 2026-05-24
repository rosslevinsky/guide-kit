#!/usr/bin/env python3
"""Automate the source-commit + baseline + amend dance.

Replaces the 5-step "After editing" ritual from CLAUDE.md with one command:

    pixi run python release.py -m "Your commit message"
    # or, equivalently:
    make release MSG="Your commit message"

What it does (and refuses to do):

  1. Reads OUTPUT_SLUG and SOURCE_FILES from build.py (no duplication).
  2. Refuses to run if the working tree has staged changes (would silently
     fold them into the release commit) or modifications outside the
     SOURCE_FILES list (would either be lost or unexpectedly committed).
     Use plain `git commit` for those first.
  3. Stages only the SOURCE_FILES that have working-tree changes.
  4. Creates the source commit with the supplied message.
  5. Re-renders the PDF — the version stamp is now clean because the source
     files are committed.
  6. Copies the fresh render to baseline.pdf.
  7. Stages baseline.pdf and amends it into the source commit.

If any post-commit step fails, the source commit is preserved; the operator
can investigate, then `git commit --amend baseline.pdf` once fixed.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
BUILD_PY = ROOT / "build.py"


def _parse_build_constants() -> tuple[str, list[str]]:
    """Scrape OUTPUT_SLUG and the full SOURCE_FILES list from build.py without
    importing weasyprint (which would add ~1s of import time for no good
    reason). Returns the full source list — including absent files — so that
    deleting a source file (e.g. removing transforms.py to deactivate the
    hook) is treated as an in-scope release change rather than rejected as
    "outside SOURCE_FILES."
    """
    text = BUILD_PY.read_text(encoding="utf-8")
    slug_m = re.search(r'^OUTPUT_SLUG\s*=\s*"([^"]+)"', text, re.M)
    if not slug_m:
        sys.exit("release.py: could not find OUTPUT_SLUG = \"...\" in build.py")
    slug = slug_m.group(1)
    files = re.findall(r'"(guide\.md|style\.css|build\.py|transforms\.py)"', text)
    seen: list[str] = []
    for f in files:
        if f not in seen:
            seen.append(f)
    return slug, seen


def _git(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check,
        capture_output=capture, text=capture,
        encoding="utf-8" if capture else None,
    )


def _porcelain() -> list[tuple[str, str]]:
    """Return [(status_code, path), ...] for every changed/untracked entry.
    status_code is the 2-char `git status --porcelain` prefix."""
    out = _git("status", "--porcelain", capture=True).stdout
    rows = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        rows.append((line[:2], line[3:]))
    return rows


def _ensure_clean_state(source_files: list[str]) -> list[str]:
    """Refuse to run with staged changes, untracked source-list files, or
    modifications outside the SOURCE_FILES set. Returns the subset of
    source_files that actually have working-tree changes (to stage)."""
    status = _porcelain()
    if not status:
        sys.exit("release.py: no changes to commit. Nothing to release.")

    staged = [p for code, p in status if code[0] not in (" ", "?")]
    if staged:
        sys.exit(
            "release.py: index has staged changes:\n  "
            + "\n  ".join(staged)
            + "\nUnstage them (`git reset HEAD <file>`) and re-run, or commit them\n"
            "with plain `git commit` first if they're unrelated to this release."
        )

    source_set = set(source_files)
    out_of_scope = [
        p for code, p in status
        if p not in source_set
    ]
    if out_of_scope:
        sys.exit(
            "release.py: working tree has changes outside the SOURCE_FILES set:\n  "
            + "\n  ".join(out_of_scope)
            + "\nCommit (or revert) them with plain git first. release.py only\n"
            "stages files in build.py's SOURCE_FILES list."
        )

    return [p for _, p in status if p in source_set]


def _build() -> None:
    print("  building fresh render...")
    subprocess.run(["pixi", "run", "build"], cwd=ROOT, check=True)


def _copy_baseline(slug: str) -> None:
    out_pdf = ROOT / f"{slug}.pdf"
    baseline = ROOT / "baseline.pdf"
    if not out_pdf.exists():
        sys.exit(f"release.py: expected fresh render at {out_pdf} but it's missing.")
    shutil.copyfile(out_pdf, baseline)
    print(f"  baseline.pdf <- {out_pdf.name}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Stage source + render baseline + amend, in one commit.",
    )
    p.add_argument("-m", "--message", required=True, help="Commit message")
    args = p.parse_args()

    slug, source_files = _parse_build_constants()

    to_stage = _ensure_clean_state(source_files)
    print(f"  staging: {', '.join(to_stage)}")
    _git("add", "--", *to_stage)
    _git("commit", "-m", args.message)
    print(f"  committed source: {args.message!r}")

    _build()
    _copy_baseline(slug)

    _git("add", "baseline.pdf")
    _git("commit", "--amend", "--no-edit")
    short = _git("rev-parse", "--short", "HEAD", capture=True).stdout.strip()
    print(f"  amended into {short}.")
    print("Done. `make verify` to confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
