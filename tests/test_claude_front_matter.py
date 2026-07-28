"""The kit's CLAUDE.md describes the KIT; a fork's describes that guide.

THE DEFECT, which is `test_readme_front_door.py`'s one file over. CLAUDE.md was
written as a fork's CLAUDE.md — `## What this is` followed by
`<DESCRIBE YOUR GUIDE>` and a sentence about `{{GUIDE_NAME}}` — and nothing
substituted them in the kit, because `bootstrap.py` fills them in a FORK. So the
public repository's project-notes file, the one that is supposed to explain what
this is, opened with an unfilled blank.

The fix is the same shape as the README's, and so is its obvious wrong version:
de-placeholdering in place would give every guide the KIT's opening, which
describes a toolkit they are not. So the block is swapped wholesale, and these
tests pin both halves.

The third assertion is the one worth writing down. A fork must not inherit
`<DESCRIBE YOUR GUIDE>`: it is in `buildcore.PLACEHOLDERS`, the sentinel that
suppresses the hygiene check is deleted at the end of the same bootstrap run, and
`--smoke` rejects a PDF containing it. A fork that kept the token would fail its
first `make`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE = REPO_ROOT / "CLAUDE.md"

_PLACEHOLDER = re.compile(r"\{\{GUIDE_(?:NAME|SLUG)\}\}")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _front(text: str) -> str:
    """Everything above the managed region — the part bootstrap rewrites."""
    import sync
    return text[: text.index(sync.MARK_BEGIN)]


def test_the_kits_own_notes_describe_the_kit():
    front = _COMMENT.sub("", _front(CLAUDE.read_text(encoding="utf-8")))
    assert "<DESCRIBE YOUR GUIDE>" not in front, (
        "the kit's CLAUDE.md still opens with the fork placeholder; this file is "
        "read by anyone browsing a public repository")
    assert not _PLACEHOLDER.search(front), (
        "the kit's CLAUDE.md front matter still carries {{GUIDE_*}} placeholders")
    assert "guide-kit" in front, "the kit's notes should say which repository this is"


def test_the_front_matter_block_is_marked_for_bootstrap():
    """The markers are the mechanism. Without them a fork inherits the KIT's
    opening — which tells a guide's author they are working on the toolkit."""
    import bootstrap

    text = CLAUDE.read_text(encoding="utf-8")
    assert text.count(bootstrap.CLAUDE_FRONT_BEGIN) == 1
    assert text.count(bootstrap.CLAUDE_FRONT_END) == 1
    assert text.index(bootstrap.CLAUDE_FRONT_BEGIN) < text.index(bootstrap.CLAUDE_FRONT_END)


def test_the_block_ends_above_the_managed_region():
    """It must not overlap `kit:begin`/`kit:end`. If it did, bootstrap's swap
    would alter the shared block and the fork's managed-region checksum would
    diverge from the kit's the moment it was created."""
    import bootstrap
    import sync

    text = CLAUDE.read_text(encoding="utf-8")
    assert text.index(bootstrap.CLAUDE_FRONT_END) < text.index(sync.MARK_BEGIN)


def test_a_fork_gets_its_own_opening():
    import bootstrap

    front = bootstrap._guide_claude_front("My Guide", "my-guide")
    assert "My Guide" in front
    assert "my-guide.pdf" in front
    assert not _PLACEHOLDER.search(front)
    assert "guide-kit" not in front, (
        "a guide's project notes describe the guide, not the toolkit")


def test_a_fork_does_not_inherit_the_hygiene_tripwire():
    """`<DESCRIBE YOUR GUIDE>` fails the build. The sentinel that suppresses that
    check is deleted at the end of the same bootstrap run, so a fork carrying the
    token cannot render at all."""
    import bootstrap
    import buildcore

    front = bootstrap._guide_claude_front("My Guide", "my-guide")
    for ph in buildcore.PLACEHOLDERS:
        assert ph not in front, f"a fork's CLAUDE.md opening would carry {ph!r}"


def test_bootstrap_substitutes_the_whole_block(tmp_path, monkeypatch):
    """End to end through the real function, because the failure mode is silent:
    a `find` returning -1 leaves the block in place and nothing complains."""
    import bootstrap

    fork = tmp_path / "fork"
    fork.mkdir()
    (fork / "CLAUDE.md").write_text(CLAUDE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ROOT", fork)
    bootstrap._sub_claude("My Guide", "my-guide")

    out = (fork / "CLAUDE.md").read_text(encoding="utf-8")
    assert out.lstrip().startswith("# Project notes for Claude"), out[:120]
    assert bootstrap.CLAUDE_FRONT_BEGIN not in out, "the marker survived into a fork"
    assert bootstrap.CLAUDE_FRONT_END not in out
    assert "My Guide" in out and "my-guide.pdf" in out
    assert not _PLACEHOLDER.search(out), "a fork's CLAUDE.md kept a placeholder"
    assert "<DESCRIBE YOUR GUIDE>" not in out


def test_bootstrap_leaves_the_managed_region_byte_identical(tmp_path, monkeypatch):
    """The whole point of the marker placement. A fork's shared block must match
    the kit's exactly, or `sync.py` reports drift on a repository that was created
    seconds ago."""
    import bootstrap
    import sync

    original = CLAUDE.read_text(encoding="utf-8")
    b = original.index(sync.MARK_BEGIN)
    e = original.index(sync.MARK_END) + len(sync.MARK_END)
    region = original[b:e]

    fork = tmp_path / "fork"
    fork.mkdir()
    (fork / "CLAUDE.md").write_text(original, encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ROOT", fork)
    bootstrap._sub_claude("My Guide", "my-guide")

    out = (fork / "CLAUDE.md").read_text(encoding="utf-8")
    ob = out.index(sync.MARK_BEGIN)
    oe = out.index(sync.MARK_END) + len(sync.MARK_END)
    assert out[ob:oe] == region, "bootstrap altered the shared managed region"


def test_the_gate_would_catch_the_shipped_defect(tmp_path, monkeypatch):
    """CLAUDE.md as it was: the kit's copy carrying the fork's placeholders.

    Invokes the REAL gate rather than re-deriving it — written the obvious way,
    this would only assert that a hard-coded string matches a hard-coded regex,
    and would stay green however weak the actual check became.
    """
    shipped = tmp_path / "CLAUDE.md"
    shipped.write_text(
        "# Project notes for Claude\n\n## What this is\n\n"
        "<DESCRIBE YOUR GUIDE>\n\n"
        "A single-document project for `{{GUIDE_NAME}}`.\n\n"
        "<!-- kit:begin -->\nshared\n<!-- kit:end -->\n",
        encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "CLAUDE", shipped)

    with pytest.raises(AssertionError, match="placeholder|public repository"):
        test_the_kits_own_notes_describe_the_kit()
