"""`BREAKING.md`, and the guard that makes anyone actually write in it.

THE GAP IT COVERS is a seam in the sync model rather than a bug in it. Sync
overwrites kit-owned files and never touches target-owned ones — `guide.toml` is
the guide's. So a sync can deliver a stricter `kitconfig.py` while leaving in
place the `guide.toml` it now rejects: the sync succeeds and says so, the next
`make` dies on `unknown key`, and the error names a file the sync did not write.
Every step is correct. Nothing inside sync can detect it. So it is written down,
and sync prints it before it writes.

THE FILE ALONE WOULD DECAY, which is why the vocabulary pin below exists. A note
that depends on remembering to write it is the same failure it was built to
prevent — this repository has already shipped a `re.sub` whose pattern stopped
matching and reported that by doing nothing. `test_the_accepted_config_vocabulary_is_pinned`
is the forcing function: removing or renaming a setting fails a test whose
message says to write the entry.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import kitconfig
import sync

REPO_ROOT = Path(__file__).resolve().parent.parent


def _has_history() -> bool:
    """Is this checkout a git repository with readable history?

    Several assertions below are ABOUT git ranges, so without history they fail
    for a reason that has nothing to do with what they check — which is the
    failure mode this whole file exists to complain about. Found by running the
    suite over an exported tree with no `.git`: two tests went red and neither
    was reporting a real defect.
    """
    return bool(sync._head_sha(REPO_ROOT))


needs_history = pytest.mark.skipif(
    not _has_history(), reason="no git history in this checkout — range tests are moot")


# --------------------------------------------------------------------------
# The forcing function
# --------------------------------------------------------------------------
#
# ASKED OF THE LOADER, not read out of the source. `kitconfig` names its accepted
# keys in the very error it raises for an unknown one, so provoking that error
# reports what the loader really accepts — which is the thing a guide's
# `guide.toml` is measured against. Parsing `kitconfig.py` instead would pin how
# the code is spelled, and could pass while the behaviour moved.

_MINIMAL = {
    "TITLE": "T", "OUTPUT_SLUG": "probe-guide", "AUTHOR": "A",
    "DESCRIPTION": "d", "KEYWORDS": "k", "COPYRIGHT_YEAR": 2026,
    "outputs": {"pdf": True}, "artifacts": {"pdf": {"date": "2026-01-01"}},
}

# Every table and top-level key the kit accepts today. A REMOVAL here is a
# breaking change for every guide that used the key.
EXPECTED_TOP = {
    "AUTHOR", "COPYRIGHT_YEAR", "DESCRIPTION", "KEYWORDS", "OUTPUT_SLUG", "TITLE",
    "artifacts", "deploy", "fonts", "hub", "outputs", "site", "slides", "theme",
}
EXPECTED_TABLES = {
    "outputs": {"pdf", "site", "slides"},
    "theme": {"name", "tokens"},
    "slides": {"source", "file"},
    "fonts": {"cjk"},
    "deploy": {"domain", "preview_urls"},
    "hub": {"registry", "snapshot"},
}

_HOWTO = (
    "\n\nIf you REMOVED or RENAMED a setting, that is a breaking change for every "
    "guide whose guide.toml still uses it: add an entry to BREAKING.md naming the "
    "commit and what to do, then update this list. If you ADDED one, just update "
    "this list — additions break nobody."
)


def _known_from_error(tmp_path, data, table=None) -> set[str]:
    """Provoke the unknown-key refusal and read the accepted set out of it."""
    d = {k: (dict(v) if isinstance(v, dict) else v) for k, v in data.items()}
    if table is None:
        d["a_key_that_is_not_real"] = "x"
    else:
        d.setdefault(table, {})["a_key_that_is_not_real"] = "x"
    p = tmp_path / "guide.toml"
    p.write_text(_toml(d), encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError) as exc:
        kitconfig.load(tmp_path)
    m = re.search(r"known: \[([^\]]*)\]", str(exc.value))
    assert m, f"the refusal no longer lists its accepted keys: {exc.value}"
    return {s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()}


def _toml(d: dict) -> str:
    """Minimal writer — enough for the shapes above, no dependency needed."""
    def scalar(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "[" + ", ".join(scalar(x) for x in v) + "]"
        return '"' + str(v).replace('"', '\\"') + '"'

    lines, tables = [], []
    for k, v in d.items():
        if isinstance(v, dict):
            tables.append((k, v))
        else:
            lines.append(f"{k} = {scalar(v)}")
    for name, tbl in tables:
        nested = {k: v for k, v in tbl.items() if isinstance(v, dict)}
        flat = {k: v for k, v in tbl.items() if not isinstance(v, dict)}
        lines.append(f"[{name}]")
        lines += [f"{k} = {scalar(v)}" for k, v in flat.items()]
        for sub, subtbl in nested.items():
            lines.append(f"[{name}.{sub}]")
            lines += [f"{k} = {scalar(v)}" for k, v in subtbl.items()]
    return "\n".join(lines) + "\n"


def test_the_accepted_config_vocabulary_is_pinned(tmp_path):
    """Remove a setting and this fails, telling you to write the entry.

    This is the whole reason `BREAKING.md` is more than a good intention. The
    change that prompted it — `[kit] min_version` — passed every test in the
    suite on its way out.
    """
    assert _known_from_error(tmp_path, _MINIMAL) == EXPECTED_TOP, (
        "the set of top-level guide.toml keys has changed." + _HOWTO)


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_each_tables_accepted_keys_are_pinned(tmp_path, table):
    assert _known_from_error(tmp_path, _MINIMAL, table) == EXPECTED_TABLES[table], (
        f"the accepted keys of [{table}] have changed." + _HOWTO)


# --------------------------------------------------------------------------
# The file itself
# --------------------------------------------------------------------------

def test_breaking_md_exists_and_parses():
    entries = sync.parse_breaking(REPO_ROOT)
    assert entries, "BREAKING.md parsed to zero entries — check the heading format"


@needs_history
def test_every_entry_names_a_real_commit():
    """A SHA that resolves nowhere makes the range computation silently wrong:
    `git rev-list` would never match it, so the entry would never be shown."""
    for e in sync.parse_breaking(REPO_ROOT):
        got = subprocess.run(["git", "cat-file", "-e", f"{e['sha']}^{{commit}}"],
                             cwd=REPO_ROOT, capture_output=True)
        assert got.returncode == 0, (
            f"BREAKING.md entry {e['sha'][:8]} is not a commit in this repository")


def test_every_entry_has_a_summary_and_a_remedy():
    for e in sync.parse_breaking(REPO_ROOT):
        assert e["summary"], f"{e['sha'][:8]} has no summary line"
        assert len(e["body"]) > len(e["summary"]) + 20, (
            f"{e['sha'][:8]} says what changed but not what to do about it")


def test_a_missing_file_is_not_an_error(tmp_path):
    """A kit predating this file, or a fork that dropped it, must still sync."""
    assert sync.parse_breaking(tmp_path) == []
    assert sync.breaking_since(tmp_path, "0" * 40) == ([], None)


# --------------------------------------------------------------------------
# Which entries a given guide is shown
# --------------------------------------------------------------------------

@needs_history
def test_a_guide_already_past_an_entry_is_not_shown_it():
    """HEAD..HEAD is empty, so a guide on the current kit sees nothing."""
    head = sync._head_sha(REPO_ROOT)
    entries, caveat = sync.breaking_since(REPO_ROOT, head)
    assert entries == [] and caveat is None


@needs_history
def test_a_guide_behind_an_entry_is_shown_it():
    entries = sync.parse_breaking(REPO_ROOT)
    oldest = entries[-1]["sha"]
    parent = subprocess.run(["git", "rev-parse", f"{oldest}^"], cwd=REPO_ROOT,
                            capture_output=True, text=True)
    if parent.returncode != 0:
        pytest.skip("oldest entry is the root commit — no 'before' to stand at")
    shown, caveat = sync.breaking_since(REPO_ROOT, parent.stdout.strip())
    assert oldest in [e["sha"] for e in shown]
    assert caveat is None


def test_an_unusable_recorded_version_shows_everything_with_a_caveat():
    """Under-reporting reproduces the exact failure the file exists to prevent,
    so an unanswerable range fails toward saying too much."""
    for bad in ("", "unknown", "bcdb317e"):          # empty, label, short sha
        shown, caveat = sync.breaking_since(REPO_ROOT, bad)
        assert shown == sync.parse_breaking(REPO_ROOT)
        assert caveat and "every entry is listed" in caveat


@needs_history
def test_a_recorded_version_absent_from_history_shows_everything_with_a_caveat():
    shown, caveat = sync.breaking_since(REPO_ROOT, "0" * 40)
    assert shown == sync.parse_breaking(REPO_ROOT)
    assert caveat and "not in this checkout" in caveat


def test_the_notice_prints_before_anything_is_written():
    """Printed after `_apply`, this would be a post-mortem — and worse, empty:
    `_apply` advances `kit_version`, so the range would close to nothing every
    time and the notice would never appear at all."""
    src = (REPO_ROOT / "sync.py").read_text(encoding="utf-8")
    apply_call = src.index("_apply(kit_root, target, updates, tv, kit_digest)")
    notice = src.rindex("report_breaking(kit_root, tv)", 0, apply_call)
    assert notice < apply_call


def test_the_notice_does_not_prompt():
    """`--apply` is already the deliberate act, and an unattended caller — a
    family sweep, a scheduled run — must not hang on a question."""
    src = (REPO_ROOT / "sync.py").read_text(encoding="utf-8")
    body = src[src.index("def report_breaking"):src.index("def build_plan")]
    assert "input(" not in body
