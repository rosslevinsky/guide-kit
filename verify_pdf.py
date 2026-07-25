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

# The full version stamp rendered into the footer:
#   "YYYY-MM-DD HH:MM:SS · <12 hex>" (+ " · dirty").
# The DATE PREFIX is REQUIRED (\s* absorbs any pdftotext line break between the
# date and the hash), so a `· <12-hex>`-shaped fragment in the guide BODY can
# never be mistaken for the footer stamp. Group 1 is the content hash; group 2
# is the literal "dirty" when present. This one regex serves staleness, the
# render canary's stamp-exclusion, and the baseline dirty check.
_STAMP_RE = re.compile(
    r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\s*·\s*([0-9a-f]{12})(?:\s*·\s*(dirty))?"
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
    """Return the content hash from a full dated version stamp in `text`, or
    None. Pure function over already-extracted text — no PDF, no tools — so the
    comparison logic is testable without a renderer. Requires the date prefix,
    so a `· <hash>`-shaped fragment in the guide body is never mistaken for it."""
    m = _STAMP_RE.search(text)
    return m.group(1) if m else None


def extract_stamp_hash(pdf: Path) -> str | None:
    """The content hash embedded in the PDF's footer stamp, or None."""
    return parse_stamp_hash(_pdftotext(pdf))


def read_stamp(pdf: Path) -> tuple[str | None, bool]:
    """Return (content_hash, is_dirty) from the PDF's footer stamp in one
    pdftotext call. hash is None when no dated stamp is present; is_dirty
    reflects a trailing `· dirty` segment. Used by staleness and `make baseline`."""
    m = _STAMP_RE.search(_pdftotext(pdf))
    if m is None:
        return None, False
    return m.group(1), m.group(2) == "dirty"


def promotable_stamp(working: Path, root: Path) -> tuple[bool, str]:
    """Whether a freshly built PDF is safe to promote to the reference: it must
    have a readable, non-dirty stamp equal to the CURRENT source hash. Shared by
    `make baseline` and `make release` so neither blesses a no-op/stale/dirty
    render (which would immediately fail `make verify`)."""
    try:
        stamp, is_dirty = read_stamp(working)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return False, f"fresh render is unreadable ({exc})"
    expected = kitconfig.content_hash(root)
    if stamp is None:
        return False, "fresh render has no readable version stamp"
    if is_dirty:
        return False, "rendered stamp carries a `· dirty` segment"
    if stamp != expected:
        return False, f"fresh render's stamp {stamp} != source hash {expected}"
    return True, f"promotable (stamp {stamp})"


def _git(root: Path, *args: str) -> str:
    """Lenient git — returns "" on any error. For DIAGNOSTIC use only (naming
    stale files); never for a decision that must fail closed."""
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            encoding="utf-8", check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _git_strict(root: Path, *args: str) -> str:
    """Strict git — raises on failure. For decisions that must NOT fail open."""
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


def _was_ever_released(root: Path, reference: Path) -> bool:
    """True if the reference PDF path has any commit history — i.e. it was
    released at least once and is now missing (deleted), vs. never released.
    Strict: raises on git failure so the caller can fail CLOSED rather than
    treat a deleted deliverable as pre-first-release (CI checks out full
    history, so a real query never comes back empty by accident)."""
    return bool(_git_strict(root, "log", "-1", "--format=%H", "--", reference.name).strip())


def _changed_source_files(root: Path, reference: Path) -> list[str]:
    """Best-effort diagnostic: the SOURCE_FILES entries that changed since the
    reference PDF's last commit — the union of committed-since / working-tree
    modifications AND untracked new source files. Names the stale file(s)."""
    changed: list[str] = []
    ref_commit = _git(root, "log", "-1", "--format=%H", "--", reference.name).strip()
    if ref_commit:
        diff = _git(root, "diff", "--name-only", ref_commit, "--", *kitconfig.SOURCE_FILES)
        changed += [line for line in diff.splitlines() if line.strip()]
    # `git diff` does not report untracked files — union in porcelain status so a
    # newly created source file (e.g. an added transforms.py) is named too.
    status = _git(root, "status", "--porcelain", "--", *kitconfig.SOURCE_FILES)
    changed += [line[3:] for line in status.splitlines() if line.strip()]
    # De-dupe, preserving order.
    seen: dict[str, None] = {}
    for f in changed:
        seen.setdefault(f, None)
    return list(seen)


def staleness_check(root: Path = HERE) -> int:
    _require(["pdftotext"])
    slug = kitconfig.load(root).OUTPUT_SLUG
    reference = root / f"{slug}.pdf"

    if not reference.exists():
        try:
            released = _was_ever_released(root, reference)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            # Fail CLOSED: if git history can't be queried we cannot tell a
            # deleted deliverable from a never-released one, so error rather than
            # silently pass a missing reference PDF.
            sys.stderr.write(
                f"ERROR cannot query git history for {reference.name} "
                f"(is git available with full history?): {exc}\n"
            )
            return 2
        if released:
            sys.stderr.write(
                f"FAIL  reference PDF {reference.name} was released and is now missing "
                "— restore it or re-release.\n"
            )
            return 1
        print(f"OK    no reference PDF yet — pre-first-release ({reference.name})")
        return 0

    try:
        embedded, embedded_dirty = read_stamp(reference)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # A corrupt/unreadable PDF is an environment/invocation error (exit 2),
        # not a staleness verdict — honour the documented exit-code contract
        # instead of leaking a traceback.
        sys.stderr.write(f"ERROR could not read {reference.name} (corrupt PDF?): {exc}\n")
        return 2
    current = kitconfig.content_hash(root)
    if embedded is None:
        sys.stderr.write(
            f"FAIL  {reference.name} has no readable version stamp — cannot verify staleness.\n"
        )
        return 1
    if embedded_dirty:
        # A reference stamped `· dirty` is not a valid deliverable even if its
        # hash matches — it was baselined from an uncommitted tree.
        sys.stderr.write(
            f"FAIL  {reference.name} was baselined DIRTY (`· dirty` stamp) — not a valid "
            "reference; re-release on the canonical host.\n"
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
    """Drop full dated version stamps so the canary's text comparison carries
    signal. The stamp moves on every edit (and can gain ` · dirty`), so leaving
    it in would make verify-render red after every change (plan.md:95). The date
    prefix is required, so a `· <hash>`-shaped example in the body is preserved."""
    return _STAMP_RE.sub("", text)


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
# Render smoke check (make smoke)
# ---------------------------------------------------------------------------
#
# WHAT GAP THIS CLOSES. `make verify` answers "does the stamp match the source",
# which is a question about bytes, not about the document. `make verify-render`
# compares a fresh render against the reference, so it is useless on an
# intentional content edit (the text is SUPPOSED to differ). Between them,
# nothing ever asked "does this PDF look like a finished guide?" — and the
# family has already shipped a PDF where it did not: the page footer wrapped on
# EVERY page of three guides, splitting the version stamp at its middle dot and
# orphaning the hash. Every automated gate was green. It was found by a human
# opening the file.
#
# That matters more now that baselining is automatic: the loop from "edit
# guide.md" to "published PDF" has no human in it at all, so the only inspection
# left is whatever is written down here.
#
# These assertions are deliberately coarse. A smoke check that tries to judge
# typography will produce false alarms on every legitimate edit and be switched
# off within a month; one that only catches catastrophes keeps its credibility.

# The date-time half of the footer stamp. If THIS appears on a line but the
# full stamp does not, the footer wrapped mid-stamp — which is exactly the
# defect described above.
_STAMP_DATE_RE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")

# Placeholders that must never survive into a rendered guide. Sourced from the
# template's own substitution vocabulary (bootstrap.py) plus build.py's CSS
# tokens. build.py's hygiene check scans README.md and CLAUDE.md only, so a
# placeholder left in guide.md or style.css reaches the PDF unchallenged —
# this is the backstop for that (outstanding item: "guide.md hygiene check has
# a blind spot").
_PLACEHOLDERS = (
    "{{GUIDE_NAME}}", "{{GUIDE_SLUG}}", "{{GUIDE_TITLE}}", "{{AUTHOR}}",
    "<DESCRIBE YOUR GUIDE>", "__TITLE__", "__VERSION__", "TODO:", "FIXME:",
    "Lorem ipsum",
)

MIN_PAGES = 2


def _pdftotext_layout(pdf: Path) -> str:
    """Extract text preserving physical layout. `-layout` is REQUIRED for the
    footer-wrap check: without it pdftotext reflows, and a stamp that is broken
    across two physical lines can be rejoined into one, hiding the very defect
    this looks for."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return result.stdout


def smoke_failures(text: str, pages: int, title: str) -> list[str]:
    """Every smoke assertion, as a PURE function over already-extracted text.

    Split out from smoke_check so the assertions are testable without a
    renderer — otherwise the only way to prove the footer-wrap detector works
    would be to produce a PDF with a wrapped footer, and a check that has never
    been shown to fail is not evidence of anything."""
    failures: list[str] = []

    # 1. A guide that renders to one page means the pipeline dropped the body.
    if pages < MIN_PAGES:
        failures.append(f"only {pages} page(s) — the body did not render")

    # 2. Any page with no extractable text is a blank or image-only page.
    #    pdftotext separates pages with \f, so an empty chunk is an empty page.
    blank = [i for i, chunk in enumerate(text.split("\f")[:pages], start=1)
             if not chunk.strip()]
    if blank:
        failures.append(
            f"page(s) {', '.join(map(str, blank))} contain no extractable text"
        )

    # 3. The guide's own title must appear. Catches a render of the wrong
    #    source, or a title-block that silently failed to render. Whitespace is
    #    collapsed first: `-layout` pads with runs of spaces, and a title that
    #    legitimately wraps in the rendered title-block would otherwise look
    #    absent.
    if title not in " ".join(text.split()):
        failures.append(f"the guide title ({title!r}) does not appear in the text")

    # 4. Un-substituted placeholders.
    for marker in _PLACEHOLDERS:
        if marker in text:
            failures.append(f"unsubstituted placeholder {marker!r} is in the rendered text")

    # 5. THE FOOTER-WRAP CHECK — the one that would have caught defect 8. On any
    #    line carrying the stamp's date-time, the COMPLETE stamp must also be on
    #    that line. When the footer wraps, the date lands on one line and the
    #    hash on the next: the date matches, the full stamp does not.
    #
    #    Note this cannot be done with _STAMP_RE alone. That regex has `\s*`
    #    around its separators precisely so it can span a pdftotext line break
    #    (staleness wants the hash whether or not the footer wrapped), so
    #    searching the whole text would happily match a wrapped stamp. The
    #    detection has to be per-line.
    wrapped = [
        line.strip()
        for line in text.splitlines()
        if _STAMP_DATE_RE.search(line) and not _STAMP_RE.search(line)
    ]
    if wrapped:
        failures.append(
            f"the footer version stamp is split across lines on {len(wrapped)} line(s) "
            f"— the footer is wrapping. First: {wrapped[0]!r}"
        )

    return failures


def smoke_check(pdf: Path, root: Path = HERE) -> int:
    """Assert a rendered PDF looks like a finished guide. Exit codes match the
    rest of this module: 0 pass, 1 the PDF is bad, 2 environment/invocation
    error (so a caller can tell "this render is wrong" from "I could not
    tell")."""
    _require(["pdfinfo", "pdftotext"])

    try:
        title = kitconfig.load(root).TITLE
    except kitconfig.KitConfigError as exc:
        sys.stderr.write(f"ERROR smoke: could not read guide.toml ({exc})\n")
        return 2

    if not pdf.exists():
        sys.stderr.write(f"ERROR smoke: {pdf.name} does not exist\n")
        return 2
    if pdf.stat().st_size == 0:
        sys.stderr.write(f"FAIL  smoke: {pdf.name} is zero bytes\n")
        return 1

    try:
        pages = _page_count(pdf)
        text = _pdftotext_layout(pdf)
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        sys.stderr.write(f"ERROR smoke: could not read {pdf.name} ({exc})\n")
        return 2

    failures = smoke_failures(text, pages, title)

    if failures:
        sys.stderr.write(f"FAIL  smoke: {pdf.name} does not look like a finished guide\n")
        for f in failures:
            sys.stderr.write(f"        - {f}\n")
        return 1

    print(f"PASS  smoke: {pdf.name} — {pages} pages, title present, stamp intact, no placeholders")
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
    mode.add_argument(
        "--smoke", nargs="?", metavar="PDF", type=Path, const=None,
        default=argparse.SUPPRESS,
        help="Smoke check a rendered PDF: page count, no blank pages, title "
             "present, no placeholders, footer stamp not wrapped. Defaults to "
             "the committed reference PDF. Platform-independent; safe in CI.",
    )
    args = p.parse_args()

    if args.staleness:
        return staleness_check(HERE)
    if hasattr(args, "smoke"):
        # `--smoke` with no argument checks the committed reference PDF, which is
        # what CI wants; an explicit path lets `make baseline` check the FRESH
        # render before it is promoted, which is the more valuable of the two.
        target = args.smoke or (HERE / f"{kitconfig.load(HERE).OUTPUT_SLUG}.pdf")
        return smoke_check(target)
    return render_canary(args.render[0], args.render[1])


if __name__ == "__main__":
    raise SystemExit(main())
