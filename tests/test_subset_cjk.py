"""`tools/subset-cjk.py` must produce byte-identical output from identical input.

The output lands in `fonts/generated/`, which is a RENDER INPUT: it feeds the
version stamp's closure. A subsetter that embeds a timestamp, or orders tables by
a hash seed, produces different bytes from the same source — so the stamp moves,
`make verify` goes red, and a re-baseline is spent on a file whose content did
not change.

TWO REAL DEFECTS WERE FOUND BY THIS CHECK, and both are the reason the tests
below are shaped the way they are:

1. `options.drop_tables += [...]` mutated fontTools' class-level default list in
   place, so the SECOND Subsetter in a process saw different options from the
   first. An in-process comparison caught this one.
2. `TTFont(...)` defaults `recalcTimestamp=True`, so `save()` refreshed
   `head.modified` to NOW — after the code had pinned it. An in-process
   comparison did NOT catch this: both runs fell inside the same wall-clock
   second and agreed. Output drifted second to second, which only showed up when
   the runs were separated in time and across processes.

So determinism is asserted ACROSS PROCESSES and ACROSS A SECOND BOUNDARY. A
same-process, same-second comparison is the version of this test that passes
while the property is false.
"""
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

import kitconfig

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "subset-cjk.py"

pytestmark = pytest.mark.skipif(not TOOL.is_file(), reason="subset-cjk.py is absent")


def _load():
    spec = importlib.util.spec_from_file_location("subset_cjk", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def source():
    faces = kitconfig.font_files(ROOT)
    if not faces:
        pytest.skip("no bundled faces to subset")
    return faces[0]


def _run(source: Path, out: Path, text_file: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(TOOL), "--source", str(source), "--out", str(out),
         "--text", str(text_file)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr
    assert out.is_file(), r.stderr


def test_two_runs_in_separate_processes_are_byte_identical(source, tmp_path):
    text = tmp_path / "sample.txt"
    text.write_text("The quick brown fox — 123 · “quoted”\n", encoding="utf-8")
    a, b = tmp_path / "a.otf", tmp_path / "b.otf"
    _run(source, a, text)
    _run(source, b, text)
    assert _sha256(a) == _sha256(b)


def test_output_does_not_drift_across_a_second_boundary(source, tmp_path):
    """The defect an in-process check cannot see. `head.modified` refreshed to
    the current time on save, so two subsets agreed inside one second and
    disagreed across one."""
    text = tmp_path / "sample.txt"
    text.write_text("timestamp drift probe\n", encoding="utf-8")
    a, b = tmp_path / "a.otf", tmp_path / "b.otf"
    _run(source, a, text)
    time.sleep(1.1)
    _run(source, b, text)
    assert _sha256(a) == _sha256(b), \
        "the subset changed across a second boundary — a timestamp is in the output"


def test_the_head_timestamp_is_pinned(source, tmp_path):
    """Directly, rather than only through the hash: a refreshed `head.modified`
    is the MECHANISM behind the drift, and naming it makes a regression legible.

    Asserted as "the same fixed value across runs separated in time", not as a
    literal constant: the tool writes 0 and fontTools normalises that into the
    font's 1904 epoch, so hardcoding the resulting number would pin an
    implementation detail of the library instead of the property."""
    from fontTools.ttLib import TTFont

    text = tmp_path / "t.txt"
    text.write_text("probe\n", encoding="utf-8")
    stamps = []
    for name in ("s1.otf", "s2.otf"):
        out = tmp_path / name
        _run(source, out, text)
        with TTFont(str(out), lazy=True) as font:
            stamps.append(font["head"].modified)
        time.sleep(1.1)
    assert stamps[0] == stamps[1], \
        f"head.modified moved between runs ({stamps}) — it is being refreshed on save"


def test_the_subsetter_options_are_not_shared_between_runs(source, tmp_path):
    """`options.drop_tables += [...]` mutated a class-level default in place, so
    the second Subsetter in a process saw different options from the first."""
    mod = _load()
    text = "same input both times"
    a = mod.subset(source, tmp_path / "a.otf", text)
    b = mod.subset(source, tmp_path / "b.otf", text)
    assert _sha256(a) == _sha256(b), \
        "two subsets in one process differ — shared mutable options"


def test_the_subset_covers_the_requested_codepoints(source, tmp_path):
    """Determinism is worthless if the subset is wrong. Everything asked for, plus
    the ASCII floor, must be present."""
    from fontTools.ttLib import TTFont

    mod = _load()
    text = "Hello — ok"
    out = mod.subset(source, tmp_path / "s.otf", text)
    with TTFont(str(out), lazy=True) as font:
        cmap = set(font.getBestCmap())
    for ch in text:
        if ord(ch) in cmap or ch == " ":
            continue
        pytest.fail(f"{ch!r} (U+{ord(ch):04X}) was requested but is not in the subset")
    assert ord("A") in cmap, "the ASCII floor is missing"


def test_the_check_deterministic_entrypoint_passes():
    """The command the phase's verification runs, in this environment."""
    r = subprocess.run([sys.executable, str(TOOL), "--check-deterministic"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "deterministic" in r.stdout
