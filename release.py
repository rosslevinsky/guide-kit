#!/usr/bin/env python3
"""Automate the source-commit + baseline + amend dance.

Replaces the 5-step "After editing" ritual from CLAUDE.md with one command:

    pixi run python release.py -m "Your commit message"
    # or, equivalently:
    make release MSG="Your commit message"

What it does (and refuses to do):

  1. Reads OUTPUT_SLUG and SOURCE_FILES from guide.toml via kitconfig (the
     single validated source of truth — no scraping build.py).
  2. Refuses to run if the working tree has staged changes (would silently
     fold them into the release commit) or modifications outside the
     SOURCE_FILES list (would either be lost or unexpectedly committed).
     Use plain `git commit` for those first.
  3. Stages only the SOURCE_FILES that have working-tree changes.
  4. Creates the source commit with the supplied message.
  5. Re-renders the PDF — the version stamp is now clean because the source
     files are committed.
  6. Promotes build/<slug>.pdf to <slug>.pdf at the repo root (the committed
     reference that readers download from GitHub).
  7. Stages <slug>.pdf and amends it into the source commit.

If any post-commit step fails, the source commit is preserved; the operator
can investigate, then `git commit --amend <slug>.pdf` once fixed.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import kitconfig
import verify_pdf

ROOT = Path(__file__).parent.resolve()


def _load_constants() -> tuple[str, list[str]]:
    """Read OUTPUT_SLUG and the canonical SOURCE_FILES list from guide.toml via
    kitconfig — no scraping of build.py. kitconfig is dependency-light (stdlib
    only, no weasyprint), so this stays fast. The full source list is returned
    — including files that may be absent (e.g. a deactivated transforms.py) —
    so that deleting a source file is treated as an in-scope release change
    rather than rejected as "outside SOURCE_FILES."
    """
    cfg = kitconfig.load(ROOT)
    return cfg.OUTPUT_SLUG, list(kitconfig.SOURCE_FILES)


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


def _promote_to_reference(slug: str) -> str:
    """Copy build/<slug>.pdf (fresh working render) onto <slug>.pdf at the
    repo root (the committed reference that readers download from GitHub).
    Returns the reference filename for the caller to `git add`."""
    working = ROOT / "build" / f"{slug}.pdf"
    reference = ROOT / f"{slug}.pdf"
    if not working.exists():
        sys.exit(f"release.py: expected fresh render at {working} but it's missing.")
    shutil.copyfile(working, reference)
    print(f"  reference <- {working.relative_to(ROOT)}")
    return reference.name


def main() -> int:
    p = argparse.ArgumentParser(
        description="Stage source + refresh reference PDF + amend, in one commit.",
    )
    p.add_argument("-m", "--message", required=True, help="Commit message")
    p.add_argument(
        "--allow-platform-mismatch", action="store_true",
        help="Override the platform guard (loud, deliberate escape hatch).",
    )
    args = p.parse_args()

    # Platform guard — fire BEFORE any commit or reference-PDF write (plan.md:45,
    # :102). release.py renders and commits, so a Linux VM must not promote a
    # Linux-typography PDF into a family of macOS-rendered ones. Keyed on the
    # recorded baseline_platform, never hardcoded to macOS.
    ok, msg = kitconfig.baseline_platform_matches(ROOT)
    if not ok and not args.allow_platform_mismatch:
        sys.exit(
            f"make release refused: {msg}.\n"
            "  Pass --allow-platform-mismatch to force (you almost never want this)."
        )

    slug, source_files = _load_constants()

    to_stage = _ensure_clean_state(source_files)
    print(f"  staging: {', '.join(to_stage)}")
    _git("add", "--", *to_stage)
    _git("commit", "-m", args.message)
    print(f"  committed source: {args.message!r}")

    _build()

    # Don't bless a render that isn't demonstrably fresh and clean — same guard
    # `make baseline` uses, so `make release` can't promote a stale/dirty/unstamped
    # file. The source commit above is preserved for the operator to investigate.
    ok, msg = verify_pdf.promotable_stamp(ROOT / "build" / f"{slug}.pdf", ROOT)
    if not ok:
        sys.exit(
            f"release.py: not promoting — {msg}. The source commit is preserved; "
            "investigate, then `git commit --amend` the reference once fixed."
        )

    reference_name = _promote_to_reference(slug)

    _git("add", reference_name)
    _git("commit", "--amend", "--no-edit")
    short = _git("rev-parse", "--short", "HEAD", capture=True).stdout.strip()
    print(f"  amended into {short}.")
    print("Done. `make verify` to confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
