"""A PART is a division above chapters, and it is not a chapter.

WHY THIS EXISTS. Two guides invented "part" independently and incompatibly:
accounting-guide rewrote every `<h1>` to `<h1 class="part">` in its own
`transforms.py`, which works only because it uses `#` for divisions and `##` for
chapters; git-guide hand-wrote `<div class="part-divider">`, which works only
because it uses `#` for chapters and so had no heading level left. The kit knew
neither, and both then hit the SAME defect on their own — the heading following a
part draws its own separating rule, so a part opened with two lines 40px apart.

THE MARKER IS A CLASS, NOT A DEPTH. `chapter_level` is 1 in five guides and 2 in
one, so "the level above chapters" is `#` for one guide and does not exist for the
rest. A class lets a part sit at the SAME level as the chapters it groups, which
is what git-guide's eight divisions do, and it means adding a part to a guide is a
one-line edit rather than a demotion of every chapter heading in the document.

A class rather than a naming convention, too: accounting-guide's divisions are six
Parts AND three Appendices, so a `^# Part ` rule silently drops the appendices.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

import chapters
import render_site


def _md(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "guide.md"
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


SAME_LEVEL = """
    # Part I — The Basics {.part}

    Blurb belonging to the part.

    # 1. What Is a Widget?

    Prose.

    # 2. Your First Widget

    Prose.

    # Part II — Going Further {.part}

    # 3. Widgets at Scale

    Prose.
    """


def test_a_part_is_never_a_chapter_even_at_the_chapter_level(tmp_path):
    """THE REGRESSION THIS RULE EXISTS FOR. git-guide writes parts at `#`
    alongside `#` chapters with chapter_level = 1. Without the rule each of its
    eight divisions takes a chapter page of its own — measured on this exact
    shape, six pages where there should be three."""
    chs = chapters.split(_md(tmp_path, SAME_LEVEL), chapter_level=1)
    assert [c.slug for c in chs] == [
        "what-is-a-widget", "your-first-widget", "widgets-at-scale"]


def test_the_part_rides_on_the_chapter_it_opens(tmp_path):
    chs = chapters.split(_md(tmp_path, SAME_LEVEL), chapter_level=1)
    by_slug = {c.slug: c for c in chs}
    assert chapters._inline_text(by_slug["what-is-a-widget"].part["c"][2]) \
        == "Part I — The Basics"
    assert by_slug["your-first-widget"].part is None, (
        "a chapter that does not open a part must not claim one"
    )
    assert chapters._inline_text(by_slug["widgets-at-scale"].part["c"][2]) \
        == "Part II — Going Further"


def test_the_blurb_goes_with_the_part_not_the_next_chapter(tmp_path):
    """Unattached it belonged to no chapter and to no front matter, so the
    multipage view dropped it silently — prose present in the source and absent
    from the site."""
    chs = chapters.split(_md(tmp_path, SAME_LEVEL), chapter_level=1)
    opener = next(c for c in chs if c.slug == "what-is-a-widget")
    assert len(opener.part_blocks) == 1, "the part's blurb was lost"
    assert "Blurb belonging to the part" in chapters.blocks_to_html(
        opener.part_blocks, chapters._ast(_md(tmp_path, SAME_LEVEL)).get("pandoc-api-version"))
    assert not any("Blurb belonging" in chapters.blocks_to_html(
        c.blocks, None) for c in chs), "the blurb leaked into a chapter's body"


def test_a_part_closes_the_open_chapter(tmp_path):
    """Whatever follows a part belongs to the new division, not to the chapter
    the reader was in."""
    chs = chapters.split(_md(tmp_path, SAME_LEVEL), chapter_level=1)
    second = next(c for c in chs if c.slug == "your-first-widget")
    body = chapters.blocks_to_html(second.blocks, None)
    assert "Part II" not in body and "Widgets at Scale" not in body


def test_a_part_above_the_chapter_level_still_works(tmp_path):
    """accounting-guide's shape: `#` divisions over `##` chapters. The class is
    what marks them, so the same rule covers both dialects."""
    chs = chapters.split(_md(tmp_path, """
        # Part I — The Foundations {.part}

        ## 1. First Chapter

        Prose.

        # Appendix A — Glossary {.part}
        """), chapter_level=2)
    assert [c.slug for c in chs] == ["first-chapter"]
    assert chapters._inline_text(chs[0].part["c"][2]) == "Part I — The Foundations"


def test_front_matter_stops_at_a_part(tmp_path):
    """Otherwise a part and its blurb are swallowed into the landing page's
    opening. Belt and braces — usually the depth test stops first, but a part is
    marked by class and may legitimately sit deeper."""
    p = _md(tmp_path, """
        Opening lede.

        # Part I — The Basics {.part}

        Blurb.

        # 1. Chapter

        Prose.
        """)
    fm = chapters.front_matter(p, chapter_level=1)
    assert "Part I" not in chapters.blocks_to_html(fm, None)
    assert "Opening lede" in chapters.blocks_to_html(fm, None)


def test_is_part_reads_the_class_not_the_text(tmp_path):
    """"Part" is the concept, not the word. accounting-guide's divisions include
    three Appendices, which any `^# Part ` rule drops."""
    doc = chapters._ast(_md(tmp_path, """
        # Appendix A — Glossary {.part}

        # Part Two Without The Class

        # 1. Chapter
        """))
    heads = [b for b in doc["blocks"] if b.get("t") == "Header"]
    assert chapters.is_part(heads[0]) is True, "a classed Appendix is a part"
    assert chapters.is_part(heads[1]) is False, (
        "a heading whose TEXT starts with 'Part' but carries no class is not one"
    )


def test_a_part_that_groups_nothing_but_holds_content_is_a_chapter(tmp_path):
    """"A part groups chapters" is the definition; one with no chapters under it
    is not grouping, it is a leaf, and a leaf with content is a chapter.

    accounting-guide's three appendices are exactly this shape — Glossary, Answer
    Key and Cheat Sheet carry prose and no headings. Before this they had no page
    at all: present on the one-page view, absent from chapter mode, so a reader
    who chose chapters could not open the glossary."""
    chs = chapters.split(_md(tmp_path, """
        # Part I — The Basics {.part}

        ## 1. First Chapter

        Prose.

        # Appendix A — Glossary {.part}

        **widget** — a thing that does a job.
        """), chapter_level=2)
    assert [c.slug for c in chs] == ["first-chapter", "appendix-a-glossary"]
    appendix = chs[-1]
    assert appendix.part is None, "a part that IS the chapter must not also open one"
    assert "a thing that does a job" in chapters.blocks_to_html(appendix.blocks, None)


def test_an_empty_part_does_not_become_a_chapter(tmp_path):
    """Only CONTENT earns a page. A part that groups chapters is a grouping and
    has nothing of its own to show."""
    chs = chapters.split(_md(tmp_path, """
        # Part I — The Basics {.part}

        ## 1. First Chapter

        Prose.

        # Part II — Empty {.part}

        ## 2. Second Chapter

        Prose.
        """), chapter_level=2)
    assert [c.slug for c in chs] == ["first-chapter", "second-chapter"]


def test_only_the_first_chapter_under_a_part_carries_it(tmp_path):
    """Otherwise every chapter in a part would reprint the part heading above it,
    and the sidebar would repeat the group label before each entry."""
    chs = chapters.split(_md(tmp_path, """
        # Part I {.part}

        ## 1. One

        ## 2. Two

        ## 3. Three
        """), chapter_level=2)
    assert [bool(c.part) for c in chs] == [True, False, False]


def test_the_sidebar_labels_the_group_and_does_not_link_it(tmp_path):
    """A part has no page, so linking it would 404 or point at the first chapter
    while claiming to be the part."""
    chs = chapters.split(_md(tmp_path, SAME_LEVEL), chapter_level=1)
    nav = render_site._chapter_nav(chs, None)
    part_li = nav.split('guide-chapter-part')[1].split("</li>")[0]
    assert "Part I — The Basics" in part_li, "the part label lost its text"
    assert 'role="presentation"' in part_li
    assert "<a" not in part_li, "the part label is a link"


def test_the_part_label_carries_the_id_of_its_own_heading(tmp_path):
    """NOT for linking — it is still not a link. The sidebar is one tree now, and
    the script nests each chapter's sub-headings under its entry by matching
    heading ids against the list. A part heading is an `h1[id]` like any other,
    so it arrives in that walk between two chapters; without its id the script
    cannot tell a division from a sub-section, and the part title and its blurb
    are filed under whichever chapter happened to precede it.

    Cross-checked against the id that actually lands in the page rather than
    against the attribute's own value, because the failure this guards is the
    server and the renderer disagreeing about what the anchor is."""
    src = _md(tmp_path, SAME_LEVEL)
    chs = chapters.split(src, chapter_level=1)
    nav = render_site._chapter_nav(chs, None)
    rendered = chapters.blocks_to_html(
        [chs[0].part], chapters._ast(src).get("pandoc-api-version"))
    ident = re.search(r'id="([^"]+)"', rendered).group(1)
    assert f'data-anchor="{ident}"' in nav, (
        f"the part label does not carry {ident!r}, the id its heading is rendered "
        f"with, so the script cannot recognise the division in the heading walk"
    )


def test_the_kit_ships_structure_for_parts_but_not_appearance():
    """Colour and weight belong to the guide, like `.callout`. What the kit owns
    is the thing both guides got wrong alone: the doubled rule where a heading
    follows a part."""
    css = render_site.WEB_CHROME_CSS
    assert ".part + h1" in css and ".part + h2" in css, (
        "the heading after a part still draws its own rule"
    )
    assert ".guide-chapter-part" in css, "the sidebar's part label is unstyled"
    for appearance in ("color: #", "text-transform: uppercase;\n  color"):
        assert f".part {{\n  {appearance}" not in css, (
            "the kit is dictating a part's appearance; that belongs to the guide"
        )
