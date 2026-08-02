#!/usr/bin/env python3
"""Produce a DETERMINISTIC CJK subset face from a full CJK font.

    python tools/subset-cjk.py --source <full.otf> --out fonts/generated/subset-jp.otf
    python tools/subset-cjk.py --check-deterministic

WHERE THE SOURCE COMES FROM. You supply it; the kit bundles no CJK binary. Any
face you may redistribute works — Noto Sans JP/SC/TC/KR and Source Han Sans are
both SIL OFL 1.1. See the README's "CJK text" section.

THE OUTPUT FILENAME IS LOAD-BEARING. `buildcore.cjk_css()` looks for
`fonts/generated/subset-<locale>.otf`, one per locale in `[fonts] cjk`, and
writes the `@font-face` that aliases it to the CSS family `Guide CJK <LOCALE>`.
Write it anywhere else and the build stops saying which file it wanted.

THE NAME TABLE IS LEFT ALONE, deliberately (`options.name_IDs = ["*"]`). The
subset keeps calling itself whatever it was cut from, and the CSS family name is
attached by `@font-face` instead — exactly how `fontfaces.css` serves Source
Serif 4 as "Guide Serif". That is not only simpler than rewriting the binary's
name, it is the only safe option: Source Han Sans and friends carry an OFL
Reserved Font Name, and renaming a reserved name inside a redistributed file is
what that clause prohibits. A CSS alias touches no font data.

WHY SUBSET AT ALL. A full CJK face is 10-20 MB. Bundling one per guide would
dominate every repository and every PDF, when a guide needs the few hundred
codepoints it actually uses. Subsetting keeps the hermetic-font guarantee — the
glyphs still come from the repo, not the host — at a size the family can carry.

WHY DETERMINISM IS THE HARD REQUIREMENT. The output lands in `fonts/generated/`,
which is a RENDER INPUT: it feeds the version stamp's closure. A subsetter that
embeds a timestamp, or orders its tables by a hash seed, produces different bytes
from identical input — so the stamp moves, `make verify` goes red, and a
re-baseline is spent on a file whose content did not change. `--check-deterministic`
is therefore not a nicety; it is the property the tool has to hold.

WHERE THE OUTPUT GOES. `fonts/generated/` is target-owned (`generated` + `never`
in kit-manifest.toml), so sync never writes or deletes it. The kit ships the
subsetter; each guide runs it and owns the result. That is the ownership split
`fonts/vendor/` and `fonts/generated/` exist to express.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kitconfig  # noqa: E402  (after the path insert)

# The codepoints every subset carries regardless of the guide's text: ASCII plus
# the punctuation the kit itself renders (the stamp separator, the colophon).
# Without a floor, a guide whose CJK text happens to use no Latin would produce a
# face that cannot render its own filename in a fallback.
_ALWAYS = set(range(0x20, 0x7F)) | {0x00A0, 0x2018, 0x2019, 0x201C, 0x201D,
                                    0x2014, 0x2013, 0x00B7, 0x2026}


def _fonttools_version() -> str:
    import fontTools

    return fontTools.version


def codepoints_in(text: str) -> set[int]:
    return {ord(ch) for ch in text}


def subset(source: Path, out: Path, text: str) -> Path:
    """Write a subset of `source` covering `text`, deterministically.

    Every knob that could vary run-to-run is pinned here rather than left to the
    subsetter's defaults."""
    from fontTools import subset as ftsubset
    from fontTools.ttLib import TTFont

    wanted = sorted(codepoints_in(text) | _ALWAYS)

    options = ftsubset.Options()
    # Determinism knobs, each one a way the bytes could otherwise move:
    # REBOUND, not appended to. `drop_tables` is a class-level list on
    # fontTools' Options, so `+=` mutates the shared default in place and the
    # SECOND Subsetter in a process sees different options from the first. The
    # determinism check caught exactly that.
    options.drop_tables = list(options.drop_tables) + ["FFTM"]  # FontForge timestamp
    options.recalc_timestamp = False       # keep the source head.modified
    options.recalc_bounds = False
    options.canonical_order = True         # table order by tag, not by input order
    options.font_number = 0
    # Layout features are kept but not reordered by closure iteration order.
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True

    # recalcTimestamp=False is the load-bearing one, and it is a TTFont argument
    # rather than a Subsetter option: `save()` refreshes head.modified to NOW
    # unless told not to, which overwrites the pin below. The symptom is subtle —
    # two runs inside the same wall-clock second agree, so an in-process check
    # passes while output drifts second to second.
    with TTFont(str(source), fontNumber=0, recalcTimestamp=False,
                recalcBBoxes=False) as font:
        subsetter = ftsubset.Subsetter(options=options)
        subsetter.populate(unicodes=wanted)
        subsetter.subset(font)
        # Pinned explicitly as well as disabled above: the source font's own
        # modified date is still an input, and two different upstream builds of
        # the same face would otherwise produce different subsets.
        font["head"].modified = 0
        out.parent.mkdir(parents=True, exist_ok=True)
        font.save(str(out))
    return out


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _subset_in_subprocess(source: Path, out: Path, text_file: Path) -> bool:
    """Run the subsetter in a FRESH process.

    Two subsets computed inside one process share a hash seed and a wall-clock
    second, so an in-process comparison is blind to exactly the nondeterminism
    that matters."""
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()),
         "--source", str(source), "--out", str(out), "--text", str(text_file)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not out.is_file():
        print(f"subset-cjk: a subset run failed: {proc.stderr.strip()}", file=sys.stderr)
        return False
    return True


def check_deterministic(source: Path | None = None) -> int:
    """Subset the same input twice and require byte-identical output.

    Uses a bundled face when no CJK source is given: the property under test is
    the SUBSETTER's determinism, which does not depend on the script being CJK.
    That keeps the check runnable in every environment, which matters because it
    is asserted in both of the environments this repo defines."""
    import tempfile

    if source is None:
        faces = kitconfig.font_files(ROOT)
        if not faces:
            print("subset-cjk: no bundled faces to check against", file=sys.stderr)
            return 2
        source = faces[0]

    sample = "The quick brown fox — 123 · “quoted”"
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        text_file = tmpdir / "sample.txt"
        text_file.write_text(sample, encoding="utf-8")

        # BOTH runs are separate processes, BOTH use the real sample, and they are
        # separated by a second boundary. Every one of those matters, and an
        # earlier version of this check got all three wrong at once: it compared
        # two files generated back-to-back AFTER the sleep from an EMPTY input,
        # discarding the sample it had just computed. It reported "deterministic"
        # while the output still drifted second to second.
        first = tmpdir / "first.otf"
        if not _subset_in_subprocess(source, first, text_file):
            return 2
        time.sleep(1.1)
        second = tmpdir / "second.otf"
        if not _subset_in_subprocess(source, second, text_file):
            return 2
        ha, hb = _sha256(first), _sha256(second)

    print(f"subset-cjk: fontTools {_fonttools_version()}")
    print(f"  source {source.name}")
    print(f"  run 1  {ha}")
    print(f"  run 2  {hb}")
    if ha != hb:
        print("subset-cjk: NOT DETERMINISTIC — two runs on identical input differ.\n"
              "  The output is a render input, so this would move the version stamp\n"
              "  and re-stale every reference for a file whose content did not change.",
              file=sys.stderr)
        return 1
    print("subset-cjk: deterministic (byte-identical across two runs)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", type=Path, help="Full CJK face to subset.")
    p.add_argument("--out", type=Path, help="Where to write the subset.")
    p.add_argument("--text", type=Path,
                   help="File whose codepoints the subset must cover (default: guide.md).")
    p.add_argument("--check-deterministic", action="store_true",
                   help="Subset twice and require byte-identical output.")
    args = p.parse_args(argv)

    if args.check_deterministic:
        return check_deterministic(args.source)

    if not args.source or not args.out:
        p.error("--source and --out are required unless --check-deterministic is given")
    text_path = args.text or (ROOT / "guide.md")
    text = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
    out = subset(args.source, args.out, text)
    print(f"subset-cjk: wrote {out} ({out.stat().st_size} bytes, "
          f"fontTools {_fonttools_version()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
