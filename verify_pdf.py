#!/usr/bin/env python3
"""Content-identicalness regression harness for the guide PDF.

Usage:
    python verify_pdf.py <baseline.pdf> <candidate.pdf>

Compares two PDFs with three checks at zero tolerance:
  1. Page count (pdfinfo).
  2. Text content (pdftotext -layout, byte-equal).
  3. Per-page pixel diff (pdftoppm + ImageMagick `compare -metric AE`).

Pre-step: both inputs are canonicalized via `qpdf --deterministic-id
--normalize-content=y` into temp paths first, so accidental non-determinism
in the inputs doesn't masquerade as a real diff.

On any check failure, prints an operator-readable summary to stderr and
exits 1. Per-page diff PNGs from check 3 are saved to `verify-diff/`
alongside the script so the operator can visually inspect what changed.

Exit codes:
    0 — every check passed (PDFs are content-identical)
    1 — any check failed (see stderr summary + verify-diff/ for details)
    2 — invocation / environment error (missing args, tool not on PATH)
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

HERE = Path(__file__).parent.resolve()
DIFF_DIR = HERE / "verify-diff"


# ---------------------------------------------------------------------------
# Tool checks
# ---------------------------------------------------------------------------

REQUIRED_TOOLS = ["pdfinfo", "pdftotext", "pdftoppm", "compare", "qpdf"]


def check_tools() -> None:
    missing = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
    if missing:
        sys.stderr.write(
            "verify_pdf.py: missing required tools on PATH: "
            + ", ".join(missing)
            + "\n  Install via pixi (`pixi install`) — all are pinned in pixi.toml.\n"
        )
        sys.exit(2)


# ---------------------------------------------------------------------------
# Pre-step: canonicalize via qpdf
# ---------------------------------------------------------------------------

def canonicalize(pdf: Path, tmpdir: Path, name: str) -> Path:
    out = tmpdir / f"{name}.canon.pdf"
    subprocess.run(
        [
            "qpdf",
            "--deterministic-id",
            "--normalize-content=y",
            "--object-streams=preserve",
            str(pdf),
            str(out),
        ],
        check=True,
    )
    return out


# ---------------------------------------------------------------------------
# Check 1: page count
# ---------------------------------------------------------------------------

PAGES_RE = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)


def page_count(pdf: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
    )
    m = PAGES_RE.search(result.stdout)
    if not m:
        raise RuntimeError(f"could not parse Pages from pdfinfo output for {pdf}")
    return int(m.group(1))


def check_page_count(baseline: Path, candidate: Path) -> tuple[bool, str]:
    b = page_count(baseline)
    c = page_count(candidate)
    if b == c:
        return True, f"page count: {b} (match)"
    return False, f"page count: baseline={b}, candidate={c} (MISMATCH)"


# ---------------------------------------------------------------------------
# Check 2: text content
# ---------------------------------------------------------------------------

def pdf_text(pdf: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def check_text(baseline: Path, candidate: Path) -> tuple[bool, str]:
    b = pdf_text(baseline)
    c = pdf_text(candidate)
    if b == c:
        return True, "text content: identical"
    snippet = "\n".join(
        list(
            difflib.unified_diff(
                b.splitlines(),
                c.splitlines(),
                fromfile="baseline",
                tofile="candidate",
                lineterm="",
                n=2,
            )
        )[:50]
    )
    return False, "text content: DIFFERS — first 50 lines of unified diff:\n" + snippet


# ---------------------------------------------------------------------------
# Check 3: per-page pixel diff
# ---------------------------------------------------------------------------

def rasterize(pdf: Path, prefix: Path) -> list[Path]:
    """Rasterize `pdf` to one PNG per page at 150 dpi. Returns sorted page paths."""
    subprocess.run(
        ["pdftoppm", "-r", "150", "-png", str(pdf), str(prefix)],
        check=True,
    )
    # pdftoppm names files like <prefix>-1.png, <prefix>-2.png, ...
    return sorted(prefix.parent.glob(f"{prefix.name}-*.png"))


def pixel_diff_page(a: Path, b: Path, out: Path) -> int:
    """Run `compare -metric AE -fuzz 0%` and return the absolute-error count.
    compare writes the diff image to `out` and prints the count to stderr."""
    result = subprocess.run(
        ["compare", "-metric", "AE", "-fuzz", "0%", str(a), str(b), str(out)],
        capture_output=True, text=True,
    )
    # `compare` exits 1 when images differ (even when no error occurred) — its
    # AE count goes to stderr. Don't `check=True`.
    stderr = (result.stderr or "").strip()
    try:
        return int(stderr.split()[0])
    except (ValueError, IndexError):
        # compare wrote something we couldn't parse — treat as a tool failure.
        raise RuntimeError(
            f"could not parse `compare` output for {a.name} vs {b.name}: "
            f"stderr={stderr!r}"
        )


def check_pixels(baseline: Path, candidate: Path, tmpdir: Path) -> tuple[bool, str]:
    baseline_pngs = rasterize(baseline, tmpdir / "baseline")
    candidate_pngs = rasterize(candidate, tmpdir / "candidate")
    # Page count is already verified by check 1, so lengths should match.
    n = min(len(baseline_pngs), len(candidate_pngs))
    bad_pages: list[tuple[int, int]] = []
    DIFF_DIR.mkdir(exist_ok=True)
    for i in range(n):
        page_num = i + 1
        diff_path = DIFF_DIR / f"page-{page_num:02d}.png"
        ae = pixel_diff_page(baseline_pngs[i], candidate_pngs[i], diff_path)
        if ae == 0:
            diff_path.unlink(missing_ok=True)
        else:
            bad_pages.append((page_num, ae))
    if not bad_pages:
        # Tidy up the empty diff dir we created — leaves no stale verify-diff/
        # on disk when everything passed.
        try:
            DIFF_DIR.rmdir()
        except OSError:
            pass  # directory wasn't empty (operator added files); leave alone
        return True, f"pixel diff: 0 on all {n} pages"
    detail = ", ".join(f"page {p}: AE={ae}" for p, ae in bad_pages)
    return (
        False,
        f"pixel diff: NONZERO on {len(bad_pages)} page(s) — {detail}. "
        f"Diff PNGs saved to {DIFF_DIR}/page-NN.png.",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Verify a candidate PDF matches a baseline PDF.")
    p.add_argument("baseline", type=Path)
    p.add_argument("candidate", type=Path)
    args = p.parse_args()

    if not args.baseline.exists():
        sys.stderr.write(f"verify_pdf.py: baseline not found: {args.baseline}\n")
        return 2
    if not args.candidate.exists():
        sys.stderr.write(f"verify_pdf.py: candidate not found: {args.candidate}\n")
        return 2

    check_tools()

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        baseline = canonicalize(args.baseline, tmpdir, "baseline")
        candidate = canonicalize(args.candidate, tmpdir, "candidate")

        results: list[tuple[bool, str]] = []
        ok, msg = check_page_count(baseline, candidate)
        results.append((ok, msg))
        if not ok:
            # Pixel diff is meaningless when page counts differ; stop early.
            print("FAIL  " + msg, file=sys.stderr)
            return 1

        ok, msg = check_text(baseline, candidate)
        results.append((ok, msg))

        ok, msg = check_pixels(baseline, candidate, tmpdir)
        results.append((ok, msg))

    all_ok = all(ok for ok, _ in results)
    if all_ok:
        for _, msg in results:
            print("PASS  " + msg)
        return 0

    for ok, msg in results:
        prefix = "PASS  " if ok else "FAIL  "
        print(prefix + msg, file=sys.stderr if not ok else sys.stdout)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
