#!/usr/bin/env python3
"""Reference-PDF verification for the guide.

Two distinct commands, deliberately not one:

    python verify_artifacts.py --staleness
        The PRIMARY gate (`make verify`). Is the committed reference PDF out of
        date with the source? Compares the content hash embedded in the PDF's
        version-stamp footer (one pdftotext call) against a freshly computed
        kitconfig.content_hash() over SOURCE_FILES. NO pandoc, NO WeasyPrint, no
        rendering, no platform sensitivity — milliseconds, correct on any
        machine, so this is what CI runs.

    python verify_artifacts.py --render <reference.pdf> <candidate.pdf>
        The LOCAL render canary (`make verify-render`). Page count +
        stamp-EXCLUDED text comparison between the committed reference and a
        fresh build. Its target is environmental drift — a `pixi update` that
        shifts layout with no source change — but being a text comparison it is
        blind to any change that preserves line breaks, including a face
        substitution. `driftcanary.py` is the stronger form of the same question
        (PDF bytes + the embedded-face list) and is what CI runs.

Absent reference PDF (staleness): a guide that has never been released has zero
root PDFs by design (bootstrap deletes the inherited template PDF; the guide's
own does not exist until its first `make release`). That state PASSES with
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
import html as html_mod
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import kitconfig

HERE = Path(__file__).parent.resolve()

# The stamp grammar has ONE definition, in kitconfig: the composer, this
# module's readers and the footer-wrap detector all resolve through it. Each
# previously held its own spelling of the format, which is exactly how a
# grammar change breaks one consumer silently — the failure a single definition
# exists to prevent. `kitconfig.parse_stamp` returns a structured result, so an unknown
# trailing segment cannot be absorbed by a permissive string match.


def _require(tools: list[str]) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        sys.stderr.write(
            "verify_artifacts.py: missing required tools on PATH: "
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
    s = kitconfig.parse_stamp(text)
    return s.hash if s else None


def extract_stamp_hash(pdf: Path) -> str | None:
    """The content hash embedded in the PDF's FOOTER stamp, or None.

    Reads the footer band, not the whole document — it claimed the footer while
    taking the first match anywhere, which a dated example in the body satisfies."""
    s = read_stamp_from_band(pdf)
    return s.hash if s else None


def read_stamp(pdf: Path) -> tuple[str | None, bool]:
    """Return (content_hash, is_dirty) from the PDF's footer stamp in one
    pdftotext call. hash is None when no dated stamp is present; is_dirty
    reflects a trailing `· dirty` segment. Used by staleness and `make baseline`."""
    s = read_stamp_from_band(pdf)
    if s is None:
        return None, False
    return s.hash, s.dirty


def promotable_stamp(working: Path, root: Path, artifact: str = "pdf") -> tuple[bool, str]:
    """Whether a freshly built PDF is safe to promote to the reference: it must
    have a readable, non-dirty stamp equal to the CURRENT source hash. Shared by
    `make baseline` and `make release` so neither blesses a no-op/stale/dirty
    render (which would immediately fail `make verify`)."""
    try:
        stamp, is_dirty = read_stamp(working)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return False, f"fresh render is unreadable ({exc})"
    expected = kitconfig.artifact_closure_hash(artifact, root=root)
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


def _changed_source_files(root: Path, reference: Path, artifact: str = "pdf") -> list[str]:
    """Best-effort diagnostic: the stamp inputs that changed since the reference
    PDF's last commit — the union of committed-since / working-tree
    modifications AND untracked new source files. Names the stale file(s).

    Scoped to `stamp_pathspec()` so a font change is NAMED rather than falling
    through to the generic "one or more SOURCE_FILES" message: the hash moved
    because of a file this list would otherwise never mention."""
    changed: list[str] = []
    ref_commit = _git(root, "log", "-1", "--format=%H", "--", reference.name).strip()
    inputs = kitconfig.stamp_pathspec(artifact, kitconfig.load(root))
    if ref_commit:
        diff = _git(root, "diff", "--name-only", ref_commit, "--", *inputs)
        changed += [line for line in diff.splitlines() if line.strip()]
    # `git diff` does not report untracked files — union in porcelain status so a
    # newly created source file (e.g. an added transforms.py) is named too.
    status = _git(root, "status", "--porcelain", "--", *inputs)
    changed += [line[3:] for line in status.splitlines() if line.strip()]
    # De-dupe, preserving order.
    seen: dict[str, None] = {}
    for f in changed:
        seen.setdefault(f, None)
    return list(seen)


def staleness_check(root: Path = HERE, artifact: str = "pdf") -> int:
    """The three-outcome contract, per artifact: stale (1) / unreadable stamp (1)
    / pre-first-release (0 with a notice), plus two outcomes that only exist once
    artifacts are plural — an output this guide does not declare, and an output
    that has no committed reference at all.

    The second of those is not a gap being waved through. `ArtifactSpec.reference`
    is None for the site precisely because a site is DEPLOYED, not blessed into
    the repository: there is no committed byte-sequence to compare a hash
    against, so staleness is not a question that can be asked of it here. The
    equivalent guarantee for a site is the released-manifest identity check,
    which belongs with the release model."""
    _require(["pdftotext"])
    cfg = kitconfig.load(root)
    spec = kitconfig.artifact_spec(artifact)

    if artifact not in cfg.outputs.declared:
        print(f"OK    {artifact}: not declared by this guide — nothing to verify")
        return 0
    if spec.reference is None:
        print(f"OK    {artifact}: no committed reference artifact — "
              f"{spec.no_reference_reason}")
        return 0

    slug = cfg.OUTPUT_SLUG
    reference = root / spec.reference.replace("<slug>", slug)

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
    current = kitconfig.artifact_closure_hash(artifact, root=root)
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
            "reference; re-render and re-release.\n"
        )
        return 1
    if embedded == current:
        print(f"OK    {reference.name} is fresh (stamp {current} matches source)")
        return 0

    stale = _changed_source_files(root, reference, artifact)
    named = ", ".join(stale) if stale else "one or more source files"
    # NAMED BY ITS OWN FILE, not "reference PDF". Every artifact reported under
    # the same noun, so a stale slide deck read as a stale PDF — and the fix
    # for the two is different (`make release ARTIFACT=slides` versus a plain
    # `make release`). The reader has to be told which one moved.
    sys.stderr.write(
        f"FAIL  {reference.name} is STALE — embedded stamp {embedded} != "
        f"source hash {current}.\n"
        f"      Changed since last release: {named}.\n"
        f"      Re-run `make release{'' if artifact == 'pdf' else f' ARTIFACT={artifact}'}` "
        f"(or `make baseline{'' if artifact == 'pdf' else f' --artifact {artifact}'}` + commit).\n"
    )
    return 1


# ---------------------------------------------------------------------------
# Render canary (make verify-render) — the local, weaker form; CI runs driftcanary
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
    it in would make verify-render red after every change. The date
    prefix is required, so a `· <hash>`-shaped example in the body is preserved."""
    return kitconfig.strip_stamp(text)


def render_canary(reference: Path, candidate: Path) -> int:
    _require(["pdfinfo", "pdftotext", "qpdf"])
    for label, p in (("reference", reference), ("candidate", candidate)):
        if not p.exists():
            sys.stderr.write(f"verify_artifacts.py: {label} not found: {p}\n")
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

# ---------------------------------------------------------------------------
# The footer-wrap detector, anchored GEOMETRICALLY
#
# The previous implementation scanned every extracted line for the stamp's
# date-time and flagged any line that carried it without the full stamp. That
# worked only because the old grammar embedded a time: `2026-07-26 14:03:11` is
# not a shape that occurs in prose. The grammar is now date-only, and a bare ISO
# date appears in real guide content — in headings, tables and fenced code — so
# a text-only scan would report a wrap on documents that render perfectly.
#
# So the check is confined to the footer band, computed per page from that
# page's own dimensions (pdftotext -bbox reports them from the MediaBox), and
# within the band the discriminator is the stamp's own SEPARATOR rather than the
# mere presence of a date. Concretely a line is a wrap iff, inside the band, it
# carries `·` together with a date or a hash-shaped token, yet does not parse as
# a complete stamp. That is what lets a bottom-margin table row holding an ISO
# date next to hash-like text pass, while both halves of a genuinely split
# footer fail — in either order.
# ---------------------------------------------------------------------------

# Fraction of page height treated as the footer band, measured from the bottom.
# The kit's @page bottom margin is ~0.75in on a 11in page (~7%); 12% gives room
# for a footer that has grown a line without reaching into body text.
_FOOTER_BAND_FRACTION = 0.12

# Words whose baselines differ by less than this (in points) are one line.
_LINE_TOLERANCE_PT = 3.0

_DATE_ONLY_RE = re.compile(r"\b\d{4}-\d\d-\d\d\b")
_HASHISH_RE = re.compile(r"\b[0-9a-f]{12}\b")
_BBOX_PAGE_RE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">')
_BBOX_WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>'
)


def _pages_with_boxes(pdf: Path) -> list[tuple[float, list[tuple[float, float, str]]]]:
    """[(page_height, [(yMin, xMin, word), ...]), ...] from `pdftotext -bbox`.

    The page element's width/height come from the MediaBox, so the band is
    computed from the page's real geometry rather than an assumed paper size."""
    xml = subprocess.run(
        ["pdftotext", "-bbox", str(pdf), "-"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    pages: list[tuple[float, list[tuple[float, float, str]]]] = []
    for chunk in xml.split("<page ")[1:]:
        m = _BBOX_PAGE_RE.search("<page " + chunk.split(">", 1)[0] + ">")
        if not m:
            continue
        height = float(m.group(2))
        words = [
            (float(w.group(2)), float(w.group(1)), html_mod.unescape(w.group(5)))
            for w in _BBOX_WORD_RE.finditer(chunk)
        ]
        pages.append((height, words))
    return pages


def footer_wrap_failures(pdf: Path) -> list[str]:
    """Pages whose footer stamp is physically SPLIT across lines (defect 8).

    The question is strictly *how many lines the stamp's own tokens occupy*. Two
    earlier attempts got this wrong in opposite directions: flagging any
    unparseable stamp-like line called the committed references' intact legacy
    `YYYY-MM-DD HH:MM:SS · hash` footers a wrap (which failed `--smoke` and
    stopped CI before the staleness check that dispatches the auto-baseline);
    while comparing "no line parses but the joined band does" missed a real wrap
    whenever page furniture interleaved — `['2026-07-26 · Page 1',
    '0123456789ab']` is a split stamp whose raw join does not parse.

    So stamp-relevant tokens are extracted in reading order carrying their line,
    and every CONTIGUOUS WINDOW of them is tested with an anchored parse. A
    window that is exactly a stamp and spans more than one line is a wrap. The
    window must be anchored, not searched: a searching parse matches a stamp
    *inside* a longer window, so an unrelated date on the line above would be
    counted as part of it and a healthy footer reported as wrapping."""
    failures: list[str] = []
    for page_no, (height, words) in enumerate(_pages_with_boxes(pdf), start=1):
        rendered = _band_lines(height, words)
        if not rendered:
            continue
        if _wrapped_span(_stamp_tokens(rendered)):
            failures.append(
                f"the footer version stamp is split across lines on page {page_no} "
                f"— the footer is wrapping. Band: {rendered!r}"
            )
    return failures


def _wrapped_span(tokens: list[tuple[str, int]]) -> bool:
    """True if some contiguous token window is exactly a stamp AND spans >1 line.

    A stamp is at most five tokens (date, sep, hash, sep, dirty), so the window
    search is bounded and cheap."""
    for i in range(len(tokens)):
        for j in range(min(i + 5, len(tokens)), i, -1):     # longest window first
            window = tokens[i:j]
            if kitconfig.parse_stamp_exact(" ".join(tok for tok, _ in window)) is None:
                continue
            if len({line_no for _, line_no in window}) > 1:
                return True
            break            # this occurrence is intact; move past it
    return False


def _stamp_tokens(rendered: list[str]) -> list[tuple[str, int]]:
    """(token, line index) for every stamp-relevant token in the band, in reading
    order: a date, the separator, a 12-hex hash, or the literal `dirty`.

    Filtering is what lets page numbers and running titles sit between the halves
    of a wrapped stamp without hiding the wrap."""
    out: list[tuple[str, int]] = []
    for line_no, line in enumerate(rendered):
        for tok in line.split():
            if (tok == kitconfig.STAMP_SEP or tok == "dirty"
                    or _DATE_ONLY_RE.fullmatch(tok) or _HASHISH_RE.fullmatch(tok)):
                out.append((tok, line_no))
    return out


def _band_lines(height: float, words: list[tuple[float, float, str]]) -> list[str]:
    """The footer band's text, one string per rendered line, left-to-right."""
    band_top = height * (1.0 - _FOOTER_BAND_FRACTION)
    band = [w for w in words if w[0] >= band_top]
    if not band:
        return []
    lines: list[list[tuple[float, float, str]]] = []
    for word in sorted(band):
        if lines and abs(word[0] - lines[-1][0][0]) <= _LINE_TOLERANCE_PT:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [" ".join(w[2] for w in sorted(line, key=lambda w: w[1])) for line in lines]


def read_stamp_from_band(pdf: Path):
    """The stamp as read from the FOOTER BAND, across ALL pages.

    Reads the band's text as RENDERED — never the filtered token stream the wrap
    detector uses. That distinction is load-bearing: filtering drops the legacy
    footer's `05:33:51`, so a retired-format stamp would reconstruct into a
    valid-looking current one and read as fresh instead of failing closed.

    It must also not return the first page's answer. The stamp is identical on
    every page, so a clean page 1 would mask a dirty page 2 and promotion would
    approve an unreproducible render. Every page's band is read; hashes that
    DISAGREE mean the document carries no one coherent stamp, which this function
    may not resolve by picking one — it returns None so the caller fails closed.
    Where the hash agrees, `dirty` is the disjunction.

    ABSENCE is treated as seriously as disagreement, which it was not: a page
    with no readable stamp was dropped from the tally, so a document that lost
    its footer on some pages still returned the stamp from the others. At most
    ONE bare page is tolerated, because several guides suppress the page-1 footer
    on purpose; beyond that this returns None rather than guess which it is."""
    stamps = []
    unstamped = 0
    for height, words in _pages_with_boxes(pdf):
        rendered = _band_lines(height, words)
        if not rendered:
            unstamped += 1
            continue
        stamp = next(
            (s for s in (kitconfig.parse_stamp(line) for line in rendered) if s),
            None,
        )
        if stamp is None:
            # A simple wrap with no interleaving still yields its hash, which is
            # what staleness wants; reporting the wrap is the detector's job.
            stamp = kitconfig.parse_stamp(" ".join(rendered))
        if stamp is not None:
            stamps.append(stamp)
        else:
            unstamped += 1
    if not stamps:
        return None
    if len({s.hash for s in stamps}) > 1 or len({s.date for s in stamps}) > 1:
        return None                        # incoherent: fail closed

    # A page whose band carries NO readable stamp used to be silently dropped, so
    # a PDF that lost its footer on half its pages still returned the coherent
    # stamp from the rest and read as fresh and promotable. Disagreement failed
    # closed; ABSENCE did not, and absence is the more likely damage.
    #
    # It cannot simply fail on any gap: several guides suppress the footer on
    # page 1 deliberately (`@page :first { @bottom-center { content: "" } }`), so
    # exactly one bare page is normal. More than one means the footer is going
    # missing somewhere it was meant to be, which this cannot distinguish from a
    # design choice — so it fails closed and lets a human look.
    if unstamped > 1:
        return None
    return kitconfig.Stamp(
        date=stamps[0].date, hash=stamps[0].hash,
        dirty=any(s.dirty for s in stamps),
    )

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

    # 5. THE FOOTER-WRAP CHECK is now geometric and needs the PDF itself, not
    #    extracted text, so smoke_check() runs it separately and merges the
    #    result. See footer_wrap_failures().

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
    # The footer-wrap check is geometric, so it reads the PDF's word boxes
    # rather than the extracted text, and is merged in here.
    try:
        failures += footer_wrap_failures(pdf)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        sys.stderr.write(f"ERROR smoke: could not read word boxes from {pdf.name} ({exc})\n")
        return 2

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

def staleness_check_all(root: Path = HERE, artifact: str = "all") -> int:
    """Run the staleness contract over one artifact or every declared one.

    Returns the WORST exit code, and never short-circuits: an operator should
    see every stale artifact in one run rather than rediscovering the next after
    each fix."""
    if artifact != "all":
        return staleness_check(root, artifact)
    worst = 0
    for name in kitconfig.load(root).outputs.declared:
        worst = max(worst, staleness_check(root, name))
    return worst


def main() -> int:
    p = argparse.ArgumentParser(description="Verify the guide's built artifacts.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--staleness", action="store_true",
        help="Primary gate: is the committed reference PDF out of date with the source? "
             "(no build, platform-independent — this is what CI runs)",
    )
    mode.add_argument(
        "--render", nargs=2, metavar=("REFERENCE", "CANDIDATE"), type=Path,
        help="Render canary: page count + stamp-excluded text (needs a build, "
             "local; CI runs the stronger driftcanary.py instead)",
    )
    mode.add_argument(
        "--smoke", nargs="?", metavar="PDF", type=Path, const=None,
        default=argparse.SUPPRESS,
        help="Smoke check a rendered PDF: page count, no blank pages, title "
             "present, no placeholders, footer stamp not wrapped. Defaults to "
             "the committed reference PDF. Platform-independent; safe in CI.",
    )
    p.add_argument(
        "--artifact", default="all", choices=(*kitconfig.ARTIFACT_NAMES, "all"),
        help="Which artifact to verify (default: every output the guide declares).",
    )
    args = p.parse_args()

    if args.staleness:
        return staleness_check_all(HERE, args.artifact)
    if hasattr(args, "smoke"):
        # `--smoke` with no argument checks the committed reference PDF, which is
        # what CI wants; an explicit path lets `make baseline` check the FRESH
        # render before it is promoted, which is the more valuable of the two.
        target = args.smoke or (HERE / f"{kitconfig.load(HERE).OUTPUT_SLUG}.pdf")
        return smoke_check(target)
    return render_canary(args.render[0], args.render[1])


if __name__ == "__main__":
    raise SystemExit(main())
