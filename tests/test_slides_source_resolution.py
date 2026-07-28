"""The deck's source is RESOLVED and RECORDED, and its page is exactly 16:9.

Two things this file is careful about.

**The resolved source is returned, not inferred silently.** `auto` is a
convenience, and a convenience that cannot say what it chose leaves nobody able
to answer "which source did that deck come from" — the question you ask
precisely when the deck is wrong.

**The ratio is asserted as arithmetic, never as a string.** 254 × 9/16 is
142.875mm; the 143mm that reads like the obvious value gives 1.7762 against
1.7778 — visibly wrong on a projector and invisible in review. A test matching
the CSS text would be satisfied by the wrong number written confidently.
"""
import json
import shutil

import pytest

import kitconfig
import render_slides

from conftest import render  # noqa: PLC0415 — the fixture's own helper

_MARKED_MD = """\
# 1. Alpha {#alpha}

Prose that is not a slide.

::: slide
## Alpha, in one slide

- a point
:::

# 2. Beta {#beta}

More prose.

::: slide
## Beta, in one slide

- another point
:::

# 3. Gamma {#gamma}

No slide for this chapter.
"""

_DECK_MD = """\
## A deck of its own

- written separately from the guide
"""


def _cfg(root, **slides):
    return kitconfig.load(root)


def _setup(guide_repo, *, source="auto", file="slides.md", deck=None, md=_MARKED_MD):
    root, write_toml = guide_repo
    (root / "guide.md").write_text(md, encoding="utf-8")
    # `site: "single"` rather than "none": the fixture's default artifacts table
    # carries an [artifacts.site] entry, and the schema rejects a declared
    # artifact table for an output that is off. Keeping the site on is the
    # smaller lie — this file is about slides, and the site is inert here.
    write_toml(outputs={"pdf": True, "site": "single", "slides": True},
               slides={"source": source, "file": file},
               artifacts={"pdf": {"date": "2026-07-26"},
                          "site": {"date": "2026-07-26"},
                          "slides": {"date": "2026-07-26"}})
    if deck is not None:
        (root / file).write_text(deck, encoding="utf-8")
    return root


# ----- exactly 16:9 ------------------------------------------------------------

def test_the_page_ratio_is_exactly_16_9():
    """Asserted as ARITHMETIC. A string match would pass on 143mm."""
    assert render_slides.SLIDE_WIDTH_MM / render_slides.SLIDE_HEIGHT_MM == pytest.approx(
        16 / 9, abs=1e-12)


def test_the_obvious_wrong_value_would_fail_this():
    """143mm is what someone writes when they round. It is 1.7762, not 1.7778 —
    the test exists because that difference is invisible in a diff."""
    assert 254 / 143 != pytest.approx(16 / 9, abs=1e-4)
    assert render_slides.SLIDE_HEIGHT_MM == pytest.approx(142.875)


def test_the_page_rule_carries_the_computed_size():
    css = render_slides.SLIDE_PAGE_CSS
    assert "254mm" in css and "142.875mm" in css


# ----- source resolution -------------------------------------------------------

def test_auto_prefers_the_deck_file_when_present(guide_repo):
    root = _setup(guide_repo, source="auto", deck=_DECK_MD)
    kind, path = render_slides.resolve_source(kitconfig.load(root), root)
    assert kind == "file" and path.name == "slides.md"


def test_auto_projects_from_the_guide_when_the_file_is_absent(guide_repo):
    root = _setup(guide_repo, source="auto")
    kind, path = render_slides.resolve_source(kitconfig.load(root), root)
    assert kind == "guide" and path is None


def test_explicit_guide_ignores_a_present_deck_file(guide_repo):
    """`guide` means the guide. Falling back to a file that happens to exist
    would make the explicit setting weaker than the automatic one."""
    root = _setup(guide_repo, source="guide", deck=_DECK_MD)
    kind, _ = render_slides.resolve_source(kitconfig.load(root), root)
    assert kind == "guide"


def test_explicit_file_with_a_non_default_name(guide_repo):
    root = _setup(guide_repo, source="file", file="deck.md", deck=_DECK_MD)
    kind, path = render_slides.resolve_source(kitconfig.load(root), root)
    assert kind == "file" and path.name == "deck.md"


def test_a_configured_but_missing_file_is_a_named_refusal(guide_repo):
    """NOT a quiet fall back to projection: the guide asked for a specific deck,
    and rendering a different one under its name is worse than stopping."""
    root = _setup(guide_repo, source="file", file="deck.md")
    with pytest.raises(render_slides.SlidesError, match="deck.md"):
        render_slides.resolve_source(kitconfig.load(root), root)


def test_projection_with_no_marked_regions_is_a_refusal(guide_repo):
    """An empty deck is a build that produced nothing while reporting success."""
    root = _setup(guide_repo, source="guide", md="# Alpha {#alpha}\n\nNo slides.\n")
    with pytest.raises(render_slides.SlidesError, match="no `::: slide`"):
        render_slides.slide_blocks(kitconfig.load(root), root)


# ----- projection --------------------------------------------------------------

def test_only_marked_regions_are_projected(guide_repo):
    """Opt-in per region is what keeps a 40-chapter guide from becoming a
    400-slide deck by default."""
    root = _setup(guide_repo, source="guide")
    blocks = render_slides.project_from_guide(root / "guide.md")
    assert len(blocks) == 2
    import json
    text = json.dumps(blocks)
    assert "Prose that is not a slide" not in text
    # A heading is TOKENISED — "Alpha, in one slide" is four `Str` nodes, so the
    # phrase never appears intact. Asserting on it was the same mistake the
    # coverage matcher made before it was rewritten to use position.
    assert '"Alpha,"' in text and '"slide"' in text


def test_a_slide_region_is_a_real_div_in_the_ast(guide_repo):
    root = _setup(guide_repo, source="guide")
    blocks = render_slides.project_from_guide(root / "guide.md")
    assert all(b["t"] == "Div" and "slide" in b["c"][0][1] for b in blocks)


# ----- coverage is a REPORT -----------------------------------------------------

def test_coverage_reports_uncovered_chapters_without_failing(guide_repo):
    """A deck is a selection. "Every chapter has a slide" was never the goal, so
    an uncovered count is information, not an error."""
    root = _setup(guide_repo, source="guide")
    report = render_slides.coverage(kitconfig.load(root), root)
    assert report["total"] == 3
    assert report["covered"] == ["alpha", "beta"], "positional coverage is wrong"
    assert report["uncovered"] == ["gamma"]


def test_coverage_units_come_from_the_ast_not_from_hash_hash(guide_repo):
    """`git-guide` has ZERO `##` headings. A coverage report built on literal
    `##` would say "0 of 0 units covered" for a 34-chapter guide."""
    root = _setup(guide_repo, source="guide",
                  md=_MARKED_MD.replace("# 1.", "# 1.").replace("## ", "### "))
    report = render_slides.coverage(kitconfig.load(root), root)
    assert report["total"] == 3, "chapters were counted by heading depth, not the AST"


# ----- the seam holds ----------------------------------------------------------

def test_a_deck_renders_and_is_reproducible_on_this_host(guide_repo):
    """Byte-identity across two runs is REPRODUCIBILITY and nothing more. It says
    nothing about another host — that is what the drift canary comparing CI's
    render against the committed reference is for."""
    root = _setup(guide_repo, source="guide")
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    first = render_slides_bytes(root)
    second = render_slides_bytes(root)
    assert first == second and first.startswith(b"%PDF-")


def render_slides_bytes(root):
    import subprocess
    import sys
    proc = subprocess.run([sys.executable, "build.py", "--slides"], cwd=root,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return (root / "build" / "probe-guide-slides.pdf").read_bytes()


def test_the_deck_carries_a_readable_version_stamp(guide_repo):
    """The deck's ArtifactSpec declares `stamp=_STAMPED`, and `verify
    --staleness` fails CLOSED on a reference whose stamp it cannot read —
    correctly, since freshness cannot be established from a file that does not
    say what built it.

    This is a regression test for a defect that reached CI: the first renderer
    used `margin: 0` for a full-bleed 16:9 page, and WeasyPrint drops every
    `@bottom-*` margin box when the margin is zero — so the deck had nowhere for
    a stamp to live and silently carried none."""
    import re
    import subprocess
    root = _setup(guide_repo, source="guide")
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render_slides_bytes(root)
    text = subprocess.run(
        ["pdftotext", str(root / "build" / "probe-guide-slides.pdf"), "-"],
        capture_output=True, text=True, check=True).stdout
    assert re.search(r"\d{4}-\d{2}-\d{2} · [0-9a-f]{12}", text), \
        "the deck carries no readable version stamp"


def test_reserving_the_stamp_strip_does_not_change_the_page_size(guide_repo):
    """The margin exists only so a margin box can. The PAGE must still be 16:9 —
    the reserved strip comes out of the content area, not the sheet."""
    import re
    import subprocess
    root = _setup(guide_repo, source="guide")
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render_slides_bytes(root)
    out = subprocess.run(["pdfinfo", str(root / "build" / "probe-guide-slides.pdf")],
                         capture_output=True, text=True, check=True).stdout
    w, h = (float(x) for x in re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", out).groups())
    assert w / h == pytest.approx(16 / 9, abs=1e-4), f"page is {w}x{h}, not 16:9"


# ----- one slide, one page -----------------------------------------------------
#
# The deck was 16:9, stamped, reproducible and byte-identical across runs — and
# it was not paginated. Three marked regions rendered as two pages: slides shared
# a sheet and bullet lists orphaned across the break. Every existing assertion
# passed, because they were about the page's SIZE and the stamp on it, and
# nothing asked how many pages there were.
#
# "One slide, one page" is not a style preference that a guide might reasonably
# override — it is what the word "slide" means. So the rule is emitted by the
# renderer alongside the @page geometry, not written into `style-slides.css`,
# which is target-owned: a rule that lives there is absent from every new guide
# and from any guide whose author never copied it.

_THREE_SLIDES_MD = """\
# 1. Alpha {#alpha}

::: slide
## First

- one
- two
:::

# 2. Beta {#beta}

::: slide
## Second

- three
:::

# 3. Gamma {#gamma}

::: slide
## Third

- four
:::
"""


def _page_count(pdf) -> int:
    import re
    import subprocess
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True,
                         check=True).stdout
    return int(re.search(r"^Pages:\s+(\d+)", out, re.M).group(1))


@pytest.mark.parametrize("slides", [1, 2, 3, 5])
def test_the_deck_has_exactly_one_page_per_slide(guide_repo, slides):
    """The assertion the deck never had. Parameterized because a single count
    can be satisfied by accident — 3 slides on 3 pages is also what a deck with
    one enormous slide that happens to overflow twice would report."""
    body = "".join(
        f"# {i}. Chapter {i} {{#c{i}}}\n\n::: slide\n## Slide {i}\n\n- point\n:::\n\n"
        for i in range(1, slides + 1))
    root = _setup(guide_repo, source="guide", md=body)
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render_slides_bytes(root)
    got = _page_count(root / "build" / "probe-guide-slides.pdf")
    assert got == slides, (
        f"{slides} marked region(s) rendered as {got} page(s). A deck that packs "
        f"several slides onto a sheet — or trails an empty one — is not a deck.")


def test_a_slide_is_not_split_across_a_page_boundary(guide_repo):
    """The other half of pagination, and the one a page COUNT cannot see: with
    `break-after` alone a tall slide still fragments, so its bullets orphan onto
    the next sheet while the count stays right."""
    root = _setup(guide_repo, source="guide", md=_THREE_SLIDES_MD)
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render_slides_bytes(root)

    import subprocess
    per_page = subprocess.run(
        ["pdftotext", "-layout", str(root / "build" / "probe-guide-slides.pdf"), "-"],
        capture_output=True, text=True, check=True).stdout.split("\f")
    pages = [p for p in per_page if p.strip()]
    assert len(pages) == 3, f"expected 3 pages, got {len(pages)}"
    for n, (page, heading) in enumerate(zip(pages, ("First", "Second", "Third")), 1):
        assert heading in page, f"page {n} does not carry {heading!r}: {page!r}"
        others = {"First", "Second", "Third"} - {heading}
        found = sorted(o for o in others if o in page)
        assert not found, f"page {n} also carries {found} — slides share a sheet"


_FILE_DECK_MD = """\
## First

- one

## Second

- two

## Third

- three
"""


def test_a_standalone_deck_file_is_paginated_too(guide_repo):
    """The path the projection tests never took.

    A file deck's blocks were returned RAW — no `.slide` anywhere — so every
    rule keyed on that class did nothing. The deck ran together on one page and
    its text matched no font rule, resolving to a generic `serif` with no
    bundled family behind it. The geometry and the stamp were right throughout,
    which is why nothing noticed.
    """
    root = _setup(guide_repo, source="file", file="deck.md", deck=_FILE_DECK_MD)
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render_slides_bytes(root)
    assert _page_count(root / "build" / "probe-guide-slides.pdf") == 3


def test_a_deck_file_may_use_the_same_slide_fences(guide_repo):
    """One convention for both sources, so a deck moves between them unchanged."""
    fenced = ("::: slide\n## A\n\n- a\n:::\n\n::: slide\n## B\n\n- b\n:::\n")
    root = _setup(guide_repo, source="file", file="deck.md", deck=fenced)
    _, blocks = render_slides.slide_blocks(kitconfig.load(root), root)
    assert len(blocks) == 2
    assert all(b["t"] == "Div" and "slide" in b["c"][0][1] for b in blocks)


@pytest.mark.parametrize("md, expected", [
    ("## A\n\ntext\n\n## B\n\nmore\n", 2),
    ("intro\n\n## A\n\ntext\n", 2),          # content before the first heading
    ("just prose, no headings\n", 1),
    ("# A\n\nx\n\n# B\n\ny\n\n# C\n\nz\n", 3),
    # THE MIXED DECK — a fence PLUS unfenced content. Every case above is
    # fence-free, so the one path that dropped blocks was the one this
    # parametrization did not reach: with any fence present, the function
    # returned only the fenced Divs and discarded the title, the introduction
    # and every unfenced section, silently. The test asserting "nothing may be
    # dropped" was already here and could not see it.
    ("# Title\n\nintro\n\n::: slide\n## Fenced\n\n- a\n:::\n", 2),
    ("::: slide\n## One\n:::\n\nafter\n\n::: slide\n## Two\n:::\n", 3),
    ("::: slide\n## Only\n\n- a\n:::\n", 1),
])
def test_every_block_lands_in_a_slide(md, expected, tmp_path):
    """Nothing may be dropped on the way in — a deck that silently loses its
    opening paragraph is worse than one that fails."""
    import chapters
    path = tmp_path / "deck.md"
    path.write_text(md, encoding="utf-8")
    blocks = chapters.document(path).get("blocks", [])
    slides = render_slides.split_into_slides(blocks)
    assert len(slides) == expected
    assert all(s["t"] == "Div" and "slide" in s["c"][0][1] for s in slides)

    # CONSERVATION, stated over CONTENT rather than over a count. A `::: slide`
    # fence is ONE input block whose CHILDREN become the slide's contents, so
    # comparing `len(inner)` against `len(blocks)` compares two different
    # things and is off by one for every fence — which is what the first
    # version of this assertion did.
    def _is_fence(b):
        return (isinstance(b, dict) and b.get("t") == "Div"
                and "slide" in (b["c"][0][1] or []))

    expected_content = []
    for b in blocks:
        expected_content.extend(b["c"][1] if _is_fence(b) else [b])
    got_content = [inner for s in slides for inner in s["c"][1]]
    assert json.dumps(got_content) == json.dumps(expected_content), (
        f"content changed during grouping: {len(expected_content)} block(s) in, "
        f"{len(got_content)} out — a deck must not silently lose its prose")


def test_the_pagination_rule_is_kit_emitted_not_target_owned(repo_root):
    """`style-slides.css` is `policy = "never"` — sync never writes it. A
    pagination rule placed there would be missing from every guide that has not
    hand-copied it, which is how this family shipped unstyled site chrome to
    seven repos once already."""
    emitted = render_slides._page_css("2026-01-01 · abcdef123456")
    assert "break-after" in emitted, (
        "the deck's pagination is not emitted by the renderer")
    target_owned = (repo_root / "style-slides.css").read_text(encoding="utf-8")
    assert "break-after" not in target_owned, (
        "the pagination rule has migrated into the target-owned stylesheet, "
        "where a new guide will not receive it")


# ----- the deck's committed reference, and what had to exist first -------------

def test_the_deck_has_a_committed_reference(guide_repo):
    """It did not, for one phase, and the reason is worth keeping: a reference
    the family cannot automatically refresh is staled by the first shared-input
    change and stays red forever. The deck shares `_COMMON_FILES` with the PDF,
    so 'shared-input change' means every buildcore or kitconfig edit."""
    assert kitconfig.artifact_spec("slides").reference == "<slug>-slides.pdf"


def test_the_refresh_path_that_makes_that_safe_exists():
    """The precondition, pinned. If baseline.yml stops refreshing the deck, the
    reference above becomes a permanently-red verify and this says so."""
    import pathlib
    wf = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows" / "baseline.yml"
    text = wf.read_text(encoding="utf-8")
    assert "--artifact" in text, (
        "baseline.yml no longer refreshes per artifact — the deck's committed "
        "reference has nothing to refresh it and will stay stale")


def test_the_site_still_has_no_reference():
    """A permanent difference, not an oversight: a site is deployed, so there
    are no committed bytes for staleness to ask about."""
    assert kitconfig.artifact_spec("site").reference is None
    assert "deployed" in kitconfig.artifact_spec("site").no_reference_reason


def test_the_deck_still_carries_a_stamp(guide_repo):
    assert kitconfig.artifact_spec("slides").stamp is not None
