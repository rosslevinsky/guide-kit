#!/usr/bin/env python3
"""`make baseline`: promote a fresh render onto the committed reference PDF, with
guards that close two destructive paths in code rather than by discipline.

Refuses BEFORE mutating anything (no build, no copy, no commit):

  1. Platform mismatch — sys.platform != guide.toml's baseline_platform — unless
     --allow-platform-mismatch. Keyed on the recorded platform, never hardcoded
     to macOS (plan.md:102): a Linux forker records "linux" and baselines
     normally. This stops a Linux VM from blessing a Linux-typography PDF into a
     family of macOS-rendered ones.
  2. A dirty SOURCE_FILES tree (staged, modified, or untracked). Baselining a
     `· dirty`-stamped render makes a reference no future `make verify` can ever
     match (plan.md:101). Commit or revert first — `make release` is the normal
     promotion path.

Only then does it build, assert the fresh render's stamp carries no `dirty`
segment, and copy build/<slug>.pdf onto <slug>.pdf. Commit the reference
together with the source that changed it (see CLAUDE.md), or use `make release`.
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


def _dirty_source_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", *kitconfig.SOURCE_FILES],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # Fail CLOSED: baseline overwrites the reference PDF, so if we cannot
        # confirm the tree is clean we must refuse, not proceed.
        sys.exit(
            f"make baseline refused: cannot determine SOURCE_FILES cleanliness "
            f"(git error: {exc}). Aborting rather than risk blessing a dirty render."
        )
    return [line[3:] for line in out.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Promote a fresh render to the reference PDF.")
    ap.add_argument(
        "--allow-platform-mismatch", action="store_true",
        help="Override the platform guard (loud, deliberate escape hatch).",
    )
    args = ap.parse_args()

    cfg = kitconfig.load(ROOT)

    # Guard 1: platform — fire before anything is mutated (plan.md:45).
    ok, msg = kitconfig.baseline_platform_matches(ROOT)
    if not ok and not args.allow_platform_mismatch:
        sys.exit(
            f"make baseline refused: {msg}.\n"
            "  Baselines are rendered on the canonical host so the family shares typography.\n"
            "  Pass --allow-platform-mismatch to force (you almost never want this)."
        )

    # Guard 2: dirty SOURCE_FILES tree.
    dirty = _dirty_source_files()
    if dirty:
        sys.exit(
            "make baseline refused: SOURCE_FILES tree is dirty — a `· dirty` stamp would\n"
            "become a reference no `make verify` can match. Commit or revert first:\n  "
            + "\n  ".join(dirty)
        )

    slug = cfg.OUTPUT_SLUG
    subprocess.run(["pixi", "run", "build"], cwd=ROOT, check=True)

    working = ROOT / "build" / f"{slug}.pdf"
    if not working.exists():
        sys.exit(f"make baseline: expected fresh render at {working} but it's missing.")

    # Do not promote a render that isn't demonstrably fresh and clean (no stamp,
    # a dirty stamp, or a stamp that doesn't match current source — e.g. a stale
    # render left in build/), any of which would make the new reference fail
    # `make verify` immediately. Shared with `make release`.
    ok, msg = verify_pdf.promotable_stamp(working, ROOT)
    if not ok:
        sys.exit(f"make baseline refused: {msg} — not promoting.")

    reference = ROOT / f"{slug}.pdf"
    shutil.copyfile(working, reference)
    print(f"  reference <- {working.relative_to(ROOT)} (stamp {kitconfig.content_hash(ROOT)})")
    print(f"  commit {reference.name} together with the source that changed it (see CLAUDE.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
