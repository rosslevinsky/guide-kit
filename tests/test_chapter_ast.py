"""Chapters are defined over the Pandoc AST, never by matching lines.

`git-guide` is the case that settles it: **64** lines in its `guide.md` begin
with `#`, and **41** of those are real headings. The other 23 are inside fenced
code blocks — shell prompts, comments, `#!` lines. A line-matching splitter is
56% wrong on that one guide, and it is wrong in the worst possible direction: it
invents chapters at positions no reader can see.

The second reason is `chapter_level`. The family has no consistent heading depth
— `accounting-guide` puts chapters at `##` under `#` Parts, everyone else at `#`,
and `git-guide` has **zero** `##` headings at all — so any fixed depth yields
zero units for someone.
"""
import json
import subprocess

import pytest

import chapters

# Real shapes, taken from the family (measured 2026-07-27), so the fixtures fail
# the way the guides would rather than the way a toy document would.
_GIT_SHAPE = """\
# Getting started

Prose.

```bash
# This is a shell comment, not a heading
git init
# So is this
```

# Branching

More prose.

```
#!/bin/sh
# and another
```

# Merging

Text.
"""

_ACCOUNTING_SHAPE = """\
# Part One

Intro to the part.

## The ledger

Prose.

### A sub-detail

More.

## The trial balance

Prose.

# Part Two

## Closing entries

Prose.
"""


def _split(md_text, tmp_path, level=1):
    p = tmp_path / "guide.md"
    p.write_text(md_text, encoding="utf-8")
    return chapters.split(p, chapter_level=level)


_shape = _split   # `{#id}` is optional, so a structural fixture needs no IDs


# ----- the AST is the point ---------------------------------------------------

def test_fenced_hash_lines_are_not_chapters(tmp_path):
    """The git-guide shape: 7 `#`-initial lines, 3 real headings.

    The shebang counts too — `#!/bin/sh` is exactly the kind of line a naive
    splitter turns into a chapter titled "!/bin/sh"."""
    raw = sum(1 for l in _GIT_SHAPE.splitlines() if l.startswith("#"))
    assert raw == 7, "fixture no longer exercises the trap"
    got = _shape(_GIT_SHAPE, tmp_path, level=1)
    assert [c.title for c in got] == ["Getting started", "Branching", "Merging"]


def test_chapter_level_2_splits_at_the_right_depth(tmp_path):
    """accounting-guide: chapters are `##`, and `#` Parts are NOT chapters."""
    got = _shape(_ACCOUNTING_SHAPE, tmp_path, level=2)
    assert [c.title for c in got] == [
        "The ledger", "The trial balance", "Closing entries"]


def test_chapter_level_1_on_the_same_document_gives_the_parts(tmp_path):
    got = _shape(_ACCOUNTING_SHAPE, tmp_path, level=1)
    assert [c.title for c in got] == ["Part One", "Part Two"]


def test_a_deeper_heading_stays_inside_its_chapter(tmp_path):
    """`### A sub-detail` belongs to "The ledger", not to a chapter of its own."""
    got = _shape(_ACCOUNTING_SHAPE, tmp_path, level=2)
    ledger = next(c for c in got if c.title == "The ledger")
    assert any(b.get("t") == "Header" and b["c"][0] == 3 for b in ledger.blocks)


def test_content_before_the_first_chapter_is_front_matter(tmp_path):
    got = _shape("Preamble prose.\n\n# One\n\nBody.\n", tmp_path, level=1)
    assert [c.title for c in got] == ["One"]
    # The preamble is not silently dropped — it belongs to the document, and the
    # renderer needs it for the landing page.
    assert chapters.front_matter(
        (tmp_path / "guide.md"), chapter_level=1), "preamble was lost"


def test_a_document_with_no_chapters_at_that_level_yields_none(tmp_path):
    """git-guide has zero `##`. Asking for level 2 must return an empty list, not
    guess a different level — the config is wrong and should be visibly wrong."""
    assert _shape(_GIT_SHAPE, tmp_path, level=2) == []


# ----- identity ---------------------------------------------------------------

def test_an_explicit_id_becomes_the_route(tmp_path):
    got = _split("# A Heading With A Long Name {#short}\n\nBody.\n", tmp_path)
    assert got[0].slug == "short"


def test_a_heading_without_an_id_gets_a_derived_slug(tmp_path):
    """As amended: `{#id}` is optional and the slug comes from the title.

    Derivation is OURS, not pandoc's `attr[0]` — pandoc numbers duplicates, so
    trusting its value would accept `setup-1` as a route without anyone asking."""
    got = _split("# A Heading, With Punctuation!\n\nBody.\n", tmp_path)
    assert got[0].slug == "a-heading-with-punctuation"


def test_an_authored_id_beats_the_derived_one(tmp_path):
    got = _split("# A Very Long Chapter Title {#short}\n\nBody.\n", tmp_path)
    assert got[0].slug == "short"


def test_a_title_with_no_ascii_needs_an_explicit_id(tmp_path):
    """japan-guide has Japanese headings. A title that derives to nothing is the
    one case still requiring a pin, and it says so rather than emitting an empty
    route."""
    with pytest.raises(chapters.ChapterError) as exc:
        _split("# 日本の交通\n\nBody.\n", tmp_path)
    assert "explicit identifier" in str(exc.value)


def test_a_pinned_id_survives_a_rename_and_a_derived_one_does_not(tmp_path):
    """Both halves of the amended bargain, in one test.

    Pinning still buys route stability for a chapter whose URL you care about.
    Not pinning means a rename moves the route — accepted deliberately, since
    `/ch/<slug>/` did not exist before this phase, so nothing was broken."""
    pinned_a = _split("# Getting started {#start}\n\nBody.\n", tmp_path)
    pinned_b = _split("# Getting Started, Revised {#start}\n\nBody.\n", tmp_path)
    assert pinned_a[0].slug == pinned_b[0].slug == "start"

    derived_a = _split("# Getting started\n\nBody.\n", tmp_path)
    derived_b = _split("# Getting Started, Revised\n\nBody.\n", tmp_path)
    assert derived_a[0].slug == "getting-started"
    assert derived_b[0].slug == "getting-started-revised"


def test_reordering_and_inserting_do_not_move_routes(tmp_path):
    a = _split("# One {#one}\n\nx\n\n# Two {#two}\n\ny\n", tmp_path)
    b = _split("# Two {#two}\n\ny\n\n# Mid {#mid}\n\nz\n\n# One {#one}\n\nx\n", tmp_path)
    assert {c.slug for c in a} <= {c.slug for c in b}
    assert [c.slug for c in b] == ["two", "mid", "one"]


def test_duplicate_ids_are_refused(tmp_path):
    with pytest.raises(chapters.ChapterError) as exc:
        _split("# One {#dup}\n\nx\n\n# Two {#dup}\n\ny\n", tmp_path)
    assert "dup" in str(exc.value)


def test_two_chapters_with_the_same_title_are_refused_not_numbered(tmp_path):
    """The one guard kept independent of route stability. Pandoc would silently
    emit `setup` and `setup-1`; a reader should never meet that URL, so the build
    stops and asks for a pin."""
    with pytest.raises(chapters.ChapterError) as exc:
        _split("# Setup\n\nx\n\n# Setup\n\ny\n", tmp_path)
    msg = str(exc.value)
    assert "setup" in msg and "Setup" in msg


@pytest.mark.parametrize("bad", ["Start", "a_b", "a.b", "-lead", "trail-",
                                 "üñî", "a--b"])
def test_an_id_outside_the_grammar_is_refused(tmp_path, bad):
    """lowercase ASCII, digits and single hyphens; no leading/trailing hyphen.
    These end up in URLs, so the grammar is enforced at build time rather than
    discovered by a reader.

    `{#sp ace}` is deliberately NOT in this list: pandoc reads it as id `sp`
    followed by a bare token, so the identifier really is `sp` and really is
    valid. Asserting a refusal there would have been testing a misreading of
    pandoc's attribute syntax rather than testing this grammar."""
    with pytest.raises(chapters.ChapterError):
        _split(f"# A heading {{#{bad}}}\n\nBody.\n", tmp_path)


@pytest.mark.parametrize("reserved", ["index", "all", "fonts", "assets", "static"])
def test_a_reserved_route_is_refused_not_mangled(tmp_path, reserved):
    """Chapters are served from the ROOT (`/meet-git/`, not `/ch/meet-git/`), so
    they share a namespace with the tree's own paths. A chapter claiming one
    would shadow it; silently renaming would produce a URL the author did not
    choose. Only dotless names can collide — `guide.json` and `<slug>.pdf` are
    unreachable by the slug grammar."""
    with pytest.raises(chapters.ChapterError) as exc:
        _split(f"# A heading {{#{reserved}}}\n\nBody.\n", tmp_path)
    assert reserved in str(exc.value)


def test_non_ascii_headings_are_fine_when_pinned(tmp_path):
    """The heading TEXT may be anything — japan-guide has Japanese headings. Only
    the identifier is constrained, because only it becomes a URL."""
    got = _split("# 日本の交通 {#transport}\n\nBody.\n", tmp_path)
    assert got[0].slug == "transport"
    assert got[0].title == "日本の交通"


# ----- the real guides --------------------------------------------------------

def test_the_ast_split_matches_pandocs_own_header_count(tmp_path):
    """A cross-check against pandoc itself rather than against our own parser:
    the number of level-N headers pandoc reports is the number of chapters."""
    (tmp_path / "guide.md").write_text(_ACCOUNTING_SHAPE, encoding="utf-8")
    doc = json.loads(subprocess.run(
        ["pandoc", "-f", "markdown+raw_html-smart", "-t", "json",
         str(tmp_path / "guide.md")],
        capture_output=True, text=True, check=True).stdout)
    level2 = sum(1 for b in doc["blocks"]
                 if b.get("t") == "Header" and b["c"][0] == 2)
    assert level2 == 3
    # ...and ours agrees, without the explicit-id requirement getting in the way.
    assert len(chapters.split(tmp_path / "guide.md", chapter_level=2)) == level2


# ----- leading chapter numbers -------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("1. What accounting actually is", "what-accounting-actually-is"),
    ("2. Meet Git", "meet-git"),
    ("3) Something", "something"),
    ("10. A later chapter", "a-later-chapter"),
])
def test_a_leading_chapter_number_is_dropped(title, expected):
    """90 of this family's 105 chapter headings are numbered. Keeping the ordinal
    would put POSITION in nearly every URL, and renumbering chapters — a routine
    edit — would then move every later route."""
    assert chapters.derive_slug(title) == expected


@pytest.mark.parametrize("title,expected", [
    ("1984 and dystopia", "1984-and-dystopia"),
    ("10 Downing Street", "10-downing-street"),
    ("3D printing", "3d-printing"),
])
def test_a_number_that_is_part_of_the_title_survives(title, expected):
    """The reason the rule requires punctuation after the digits. Stripping
    `^\\d+-` off the finished slug would read "1984 and dystopia" as chapter 1984
    and publish `/ch/and-dystopia/`."""
    assert chapters.derive_slug(title) == expected


def test_renumbering_chapters_does_not_move_routes(tmp_path):
    """The stability this buys back for free, having given up the guarantee."""
    before = _split("# 1. Alpha\n\nx\n\n# 2. Beta\n\ny\n", tmp_path)
    after = _split("# 1. New one\n\nz\n\n# 2. Alpha\n\nx\n\n# 3. Beta\n\ny\n", tmp_path)
    assert [c.slug for c in before] == ["alpha", "beta"]
    assert [c.slug for c in after] == ["new-one", "alpha", "beta"]


# ----- authored-id parsing, per the round-1 review ------------------------------

@pytest.mark.parametrize("heading,slug", [
    ("# Long title {#short}", "short"),
    ("# Long title {.cls #short}", "short"),
    ("# Long title {#short .cls}", "short"),
    ("# Long title {.a .b #short key=val}", "short"),
])
def test_an_authored_id_is_found_whatever_else_is_in_the_braces(tmp_path, heading, slug):
    """`{.class #id}` is valid pandoc and means the same as `{#id}`. Reading only
    the first brace position published `/long-title/` for half of these."""
    assert _split(heading + "\n\nBody.\n", tmp_path)[0].slug == slug


def test_a_braced_id_inside_a_fence_is_not_an_authored_id(tmp_path):
    """The inverse error, and the more dangerous one: a `{#...}` in a shell
    example would register as authored and let pandoc's numeric disambiguation
    through as a real route, defeating the duplicate check."""
    md = ("# Setup\n\nx\n\n```bash\n# fake {#setup-1}\n```\n\n# Setup\n\ny\n")
    with pytest.raises(chapters.ChapterError):
        _split(md, tmp_path)


def test_an_image_only_heading_uses_its_alt_text(tmp_path):
    """Without this the title is empty, the slug derives to "" and the chapter is
    refused for having no route — on a heading that reads fine to a human."""
    got = _split("# ![Getting started](x.png)\n\nBody.\n", tmp_path)
    assert got[0].slug == "getting-started"


def test_the_chapter_keeps_its_own_header_block(tmp_path):
    """The renderer emits this rather than synthesising `<h1>{title}</h1>`, which
    would drop the id and leave a same-chapter `[back](#start)` with no target."""
    got = _split("# Intro {#start}\n\nBody.\n", tmp_path)
    assert got[0].header is not None
    assert got[0].header["c"][1][0] == "start"


# ----- link rebasing happens on the AST, not on rendered HTML ------------------

def _rebased(md, slug, home):
    import json, subprocess
    doc = json.loads(subprocess.run(
        ["pandoc", "-f", "markdown+raw_html-smart", "-t", "json"],
        input=md, capture_output=True, text=True, check=True).stdout)
    return chapters.blocks_to_html(
        chapters.rebase(doc["blocks"], slug, home), doc["pandoc-api-version"])


def test_a_code_sample_showing_html_is_not_rewritten():
    """The reason rebasing is done on the AST. These are guides that TEACH markup:
    a regex over `href="..."` in the output cannot tell a link from a code sample,
    and corrupting the sample breaks the thing being taught."""
    out = _rebased('Use `href="trap.html"` in your HTML.', "a", {})
    assert 'href="trap.html"' in out
    assert 'href="../trap.html"' not in out


def test_a_fenced_block_showing_html_is_not_rewritten():
    out = _rebased('```html\n<a href="trap.html">x</a>\n```\n', "a", {})
    assert "../trap.html" not in out


def test_a_cross_chapter_fragment_is_retargeted_and_a_local_one_is_not():
    out = _rebased("[far](#there) and [near](#here)", "a", {"there": "b", "here": "a"})
    assert 'href="../b/#there"' in out
    assert 'href="#here"' in out


def test_an_unknown_fragment_is_left_alone():
    """It may target something the renderer does not own. Inventing a destination
    is worse than a link that behaves exactly as it does today."""
    assert 'href="#mystery"' in _rebased("[x](#mystery)", "a", {})


@pytest.mark.parametrize("url", ["https://e/x", "//cdn/x", "/root", "mailto:a@b.c"])
def test_targets_that_do_not_resolve_against_the_directory_are_untouched(url):
    assert f'href="{url}"' in _rebased(f"[x]({url})", "a", {})


def test_an_image_target_is_rebased_too():
    assert 'src="../pic.png"' in _rebased("![alt](pic.png)", "a", {})


def test_a_longer_fence_is_not_closed_by_a_shorter_one(tmp_path):
    """```` opened and ``` seen is still inside the block. Treating it as closed
    resumes scanning mid-example, where a `{#id}` would register as authored."""
    md = ("# Setup\n\nx\n\n````\n```\n# fake {#setup-1}\n````\n\n# Setup\n\ny\n")
    with pytest.raises(chapters.ChapterError):
        _split(md, tmp_path)


def test_an_indented_code_block_is_not_a_fence(tmp_path):
    """4+ spaces is an indented code block, not a fence opener — mistaking one
    for a fence would swallow the rest of the document."""
    md = "# Alpha {#alpha}\n\n    ```\n    indented, not a fence\n\n# Beta {#beta}\n\ny\n"
    assert [c.slug for c in _split(md, tmp_path)] == ["alpha", "beta"]
