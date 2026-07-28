"""The sidebar as a BROWSER builds it, not as the source text reads.

WHY THIS FILE EXISTS, and it is worth being blunt about it. Everything else
asserting `WEB_NAV_JS` searches the script SOURCE for literals. That catches
deletion and renaming, which is most of what happens to it — and it caught
nothing at all when the script's `aria-current` handling was wrong, because the
literal each assertion looked for was present and the logic around it was not.
The defect was found by a cross-model reviewer reading the code, which is not a
gate. This runs the script.

WHAT IT COVERS AND WHAT IT CANNOT. jsdom does no layout: `getBoundingClientRect`
returns zeros, so the scroll-spy's 96px threshold, the drawer's live header
bottom, and the `display: none` on a collapsed sub-list are invisible here. Those
are checked by driving a real browser by hand. What this covers is the half that
broke — the heading walk, the nesting, which entry is expanded, and the
attributes each entry carries.

The zero-height quirk is not merely a limitation here, it is the thing that makes
the `aria-current` case reachable: with every rect at the origin, `mark()` selects
the LAST paired heading, so on a chapter with no sub-headings the section in view
IS the chapter's own entry — precisely the collision that shipped.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import materialize_guide, render  # noqa: PLC0415 — the suite's own helpers

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(__file__).resolve().parent / "nav_dom.js"


def _harness_missing() -> str | None:
    """Why the DOM harness cannot run, or None if it can.

    Keyed on the KIT'S OWN `node_modules`, deliberately. Node resolves `require`
    by walking up the tree, so a jsdom installed anywhere above the repo would
    satisfy the import and let this pass on a machine where `npm ci` had never
    run — which is exactly the "gate that quietly stops covering its subject"
    this repo keeps designing against.
    """
    if not shutil.which("node"):
        return "node is not on PATH"
    if not (REPO_ROOT / "node_modules" / "jsdom").is_dir():
        return "jsdom is not installed — run `npm ci` in the kit"
    return None


def _require_harness() -> None:
    """Skip locally, FAIL in CI.

    A skip is the right answer on a contributor's machine that has no node, and
    the wrong one in CI: a silent skip there means the only test that executes
    the navigation script stops running and nothing says so. `verify.yml` runs
    `npm ci`, so in CI a missing harness is a broken workflow, not an absent
    optional tool.
    """
    why = _harness_missing()
    if not why:
        return
    if os.environ.get("CI"):
        pytest.fail(
            f"the DOM harness is unavailable in CI ({why}). This is the only "
            f"test that RUNS WEB_NAV_JS rather than grepping it; skipping it "
            f"here would silently retire that coverage."
        )
    pytest.skip(f"DOM harness unavailable: {why}")


# A part, a chapter WITH sub-headings, a chapter WITHOUT any, and a second part.
# The chapter with none is not filler: it is the shape that made the aria-current
# collision reachable, and it is the shape of 34 of git-guide's chapters and 43
# of accounting-guide's.
_MD = """\
Front matter prose.

# Part I — The Basics {.part}

The part's blurb.

# 1. First Chapter

Body of the first.

## A subsection

Nested.

## Constructor

Named to collide with `Object.prototype`. See the nesting test.

## Another subsection

Also nested.

# 2. Second Chapter

Body of the second, with no sub-headings at all.

# Part II — Going Further {.part}

# 3. Third Chapter

Body of the third.
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """ONE real multipage render, shared by every case in this module.

    Module-scoped on purpose: each case below reads the same built bytes, so a
    per-test render would add about a minute to the suite and buy nothing."""
    _require_harness()
    root = tmp_path_factory.mktemp("navdom") / "guide"
    write_toml = materialize_guide(root)
    (root / "guide.md").write_text(_MD, encoding="utf-8")
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    return root / "app" / "dist"


def _run(page: Path, mode: str = "desktop") -> dict:
    proc = subprocess.run(
        ["node", str(DRIVER), str(page), mode],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, f"harness failed:\n{proc.stdout}\n{proc.stderr}"
    out = json.loads(proc.stdout)
    assert out["errors"] == [], (
        f"the navigation script raised while building the sidebar: {out['errors']}\n"
        f"A partial DOM can look entirely healthy — the first version of this "
        f"harness threw part way through and still produced a plausible tree.")
    assert out["sidebar"] is not None, "no sidebar was built at all"
    return out


# ---------------------------------------------------------------------------
# One list
# ---------------------------------------------------------------------------

def test_the_sidebar_is_one_list(built):
    out = _run(built / "index.html")
    assert out["sidebar"]["listCount"] == 1, (
        "the sidebar holds more than one list container again — the arrangement "
        "this replaced stacked the chapter list above a heading-derived one")
    assert out["sidebar"]["headingDerivedTopLevel"] == 0, (
        "a heading-derived top level was built beside the chapter list")


def test_the_chapter_list_is_moved_out_of_the_body_not_copied(built):
    """Move-never-recreate, observed rather than grepped: a copy left behind in
    the body would mean the sidebar's list was built rather than relocated."""
    assert _run(built / "index.html")["chapterListStillInBody"] is False


def test_the_top_level_is_parts_and_chapters_in_document_order(built):
    kinds = [(e["kind"], e["label"]) for e in _run(built / "index.html")["sidebar"]["entries"]]
    assert kinds == [
        ("part", "Part I — The Basics"),
        ("chapter", "1. First Chapter"),
        ("chapter", "2. Second Chapter"),
        ("part", "Part II — Going Further"),
        ("chapter", "3. Third Chapter"),
    ], kinds


def test_sub_headings_nest_under_their_own_chapter(built):
    """The property a top level seeded from the chapter set alone would lose —
    measured at 14 of mac-terminal-guide's 21 entries.

    "Constructor" is in the fixture on purpose. The script indexes headings by id
    in an object, and on a PLAIN object `'constructor' in owners` is true through
    `Object.prototype` — so a sub-heading with that name would be mistaken for a
    chapter, and the script would call `.querySelector` on a function and throw.
    `Object.create(null)` is what prevents it, and this is what proves it: with a
    plain object the harness reports a script error and every case here fails."""
    entries = {e["label"]: e for e in _run(built / "index.html")["sidebar"]["entries"]}
    assert [s["label"] for s in entries["1. First Chapter"]["subs"]] == [
        "A subsection", "Constructor", "Another subsection"]
    assert entries["2. Second Chapter"]["subs"] == []
    assert entries["3. Third Chapter"]["subs"] == []


def test_a_part_does_not_swallow_the_chapter_before_it(built):
    """A part heading is an `h1[id]` like any other and arrives mid-walk. Without
    its `data-anchor` the walk cannot recognise it, and the part's title and blurb
    are nested under whichever chapter happened to precede it."""
    entries = {e["label"]: e for e in _run(built / "index.html")["sidebar"]["entries"]}
    assert entries["2. Second Chapter"]["subs"] == [], (
        "Part II was filed as a sub-section of the chapter above it")
    part = entries["Part II — Going Further"]
    assert part["href"] is None, "the part label became a link"
    assert part["anchor"], "the part label carries no anchor for the walk to match"


def test_every_entry_on_the_one_page_view_is_an_in_page_anchor(built):
    sidebar = _run(built / "index.html")["sidebar"]
    hrefs = [e["href"] for e in sidebar["entries"] if e["kind"] == "chapter"]
    assert hrefs and all(h.startswith("#") for h in hrefs), hrefs
    assert sidebar["deadAnchors"] == [], sidebar["deadAnchors"]


def test_a_chapter_page_links_out_except_to_itself(built):
    sidebar = _run(built / "second-chapter" / "index.html")["sidebar"]
    by = {e["label"]: e["href"] for e in sidebar["entries"] if e["kind"] == "chapter"}
    assert by["2. Second Chapter"] == "#second-chapter"
    assert by["1. First Chapter"] == "../first-chapter/"
    assert sidebar["deadAnchors"] == [], sidebar["deadAnchors"]


# ---------------------------------------------------------------------------
# Expansion and the section marker
# ---------------------------------------------------------------------------

def test_exactly_one_chapter_is_expanded(built):
    for page in ("index.html", "first-chapter/index.html", "second-chapter/index.html"):
        entries = _run(built / page)["sidebar"]["entries"]
        expanded = [e["label"] for e in entries if e["expanded"]]
        assert len(expanded) == 1, f"{page}: expanded {expanded}"


def test_the_chapter_page_expands_the_chapter_being_read(built):
    entries = _run(built / "first-chapter" / "index.html")["sidebar"]["entries"]
    assert [e["label"] for e in entries if e["expanded"]] == ["1. First Chapter"]


def test_a_chapter_page_keeps_announcing_which_page_it_is(built):
    """THE REGRESSION THIS FILE WAS WRITTEN FOR, and the one every source-literal
    assertion passed through.

    Scroll-spy uses `aria-current` for the section in view; the server has
    already put `aria-current="page"` on the current chapter's entry. When the
    section in view IS that chapter, the two collided and `page` was overwritten
    with the weaker `location`. The first fix restored it when the highlight
    moved away — no help at all for a chapter with nothing to move to, which is
    34 of git-guide's chapters and 43 of accounting-guide's.

    Reachable here precisely because jsdom has no layout: every rect is at the
    origin, so `mark()` selects the last paired heading, which on a chapter with
    no sub-headings is the chapter's own entry."""
    entries = _run(built / "second-chapter" / "index.html")["sidebar"]["entries"]
    own = next(e for e in entries if e["label"] == "2. Second Chapter")
    assert own["ariaCurrent"] == "page", (
        f"the chapter page's own entry announces {own['ariaCurrent']!r}; the "
        f"server said `page` and scroll-spy must not downgrade it")
    assert own["isCurrent"], "the visible section marker no longer reaches it"


def test_a_sub_heading_in_view_is_marked_without_disturbing_the_page_entry(built):
    """Both statements coexist, on two different entries: the chapter is the
    page, the sub-heading is the location."""
    entries = _run(built / "first-chapter" / "index.html")["sidebar"]["entries"]
    own = next(e for e in entries if e["label"] == "1. First Chapter")
    assert own["ariaCurrent"] == "page"
    marked = [s["label"] for s in own["subs"] if s["ariaCurrent"] == "location"]
    assert marked == ["Another subsection"], marked


# ---------------------------------------------------------------------------
# The two state classes, which are opposite interactions wearing one name
# ---------------------------------------------------------------------------

def test_the_desktop_panel_collapses_persists_and_survives_a_link(built):
    out = _run(built / "index.html", "desktop")
    assert out["initial"]["collapsed"] is False, "the desktop panel starts hidden"
    assert out["afterToggle"]["collapsed"] is True
    assert out["afterToggle"]["rootCollapsed"] is True, (
        "the root flag is not set, so a guide's stylesheet cannot reclaim the "
        "space the sidebar was reserving")
    assert out["afterToggle"]["stored"] == "1", "the choice is not persisted"
    assert out["afterLinkClick"]["collapsed"] is True, (
        "the desktop panel closed itself when a link inside it was used, which "
        "is the one thing it must not do")


def test_the_mobile_drawer_opens_and_closes_itself_on_a_link(built):
    out = _run(built / "index.html", "mobile")
    assert out["initial"]["open"] is False, "the drawer starts open"
    assert out["initial"]["ariaExpanded"] == "false"
    assert out["afterToggle"]["open"] is True
    assert out["afterToggle"]["ariaExpanded"] == "true"
    assert out["afterLinkClick"]["open"] is False, (
        "the drawer stayed open over the page the reader just navigated to")


def test_both_top_controls_are_moved_into_the_header_in_order(built):
    """Both, or neither — the reported defect was that the view switch scrolled
    away while the download stayed pinned, because the download was relocated to
    fix its styling and the switch was left behind.

    `outside == 0` is what makes this a MOVE rather than a copy: a re-created
    control satisfies "it is in the header" while the server's original still
    sits in the topbar, which is exactly what the move-never-recreate rule is
    for. Order is asserted because the rightmost item should be the one pressed
    least."""
    h = _run(built / "index.html")["header"]
    assert h["built"] and h["download"] and h["mode"], h
    assert h["order"] == ["mode", "download"], h["order"]
    assert h["outside"] == 0, "a control was copied into the header, not moved"
