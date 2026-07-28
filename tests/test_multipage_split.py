"""The multipage tree: what is emitted, that it resolves, and its ceilings.

Asserted against the AST-derived chapter set, never a source-line count — the
whole reason `chapters.py` exists is that counting `#` lines is 56% wrong on
git-guide.

Routes are UNPREFIXED (`/meet-git/`, not `/ch/meet-git/`) and there is no
`/all/`, both by owner decision during this phase. That makes one thing worth
testing harder than it looks: a chapter is served one level down, so every
relative asset needs a `../` that the landing page must not have. Getting it
wrong 404s every font on every chapter page while `/` stays perfect.
"""
import json
import re
import shutil
import subprocess
import sys

import pytest

import cfadapter
import chapters
import render_site

from conftest import render  # noqa: PLC0415 — the fixture's own helper


_MULTI_MD = """\
Front matter prose.

# 1. First Chapter

Body of the first.

## A subsection

Nested, not its own chapter.

# 2. Second Chapter

Body of the second.

# 3. Third Chapter {#pinned}

Body of the third.
"""


@pytest.fixture
def multipage(guide_repo):
    """A built multipage site, from a real render."""
    root, write_toml = guide_repo
    (root / "guide.md").write_text(_MULTI_MD, encoding="utf-8")
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    return root, root / "app" / "dist"


def _chapters(root):
    return chapters.split(root / "guide.md", chapter_level=1)


# ----- the page set -----------------------------------------------------------

def test_the_page_set_matches_the_ast_chapter_set(multipage):
    root, dist = multipage
    expected = {c.slug for c in _chapters(root)}
    assert expected == {"first-chapter", "second-chapter", "pinned"}
    got = {p.parent.name for p in dist.glob("*/index.html")}
    assert got == expected, "the tree does not match the chapters the AST found"
    assert (dist / "index.html").is_file(), "the whole guide must stay at /"


def test_there_is_no_all_route(multipage):
    """Dropped deliberately: `/` already serves the whole guide, so `/all/` was
    the same bytes at a second URL."""
    _, dist = multipage
    assert not (dist / "all").exists()


def test_the_landing_page_is_still_the_whole_guide(multipage):
    """The reason `/` is not a chapter index. A `#fragment` never reaches the
    server, so moving the document off `/` would break every shared heading link
    with no redirect able to rescue it."""
    _, dist = multipage
    html = (dist / "index.html").read_text(encoding="utf-8")
    for phrase in ("Body of the first.", "Body of the second.", "Body of the third."):
        assert phrase in html


def test_a_chapter_page_carries_only_its_own_body(multipage):
    _, dist = multipage
    html = (dist / "second-chapter" / "index.html").read_text(encoding="utf-8")
    assert "Body of the second." in html
    assert "Body of the first." not in html
    assert "Body of the third." not in html


def test_a_subsection_stays_with_its_chapter(multipage):
    _, dist = multipage
    html = (dist / "first-chapter" / "index.html").read_text(encoding="utf-8")
    assert "A subsection" in html and "Nested, not its own chapter." in html


# ----- navigation -------------------------------------------------------------

def test_every_page_carries_the_whole_chapter_list(multipage):
    """Server-rendered, because `WEB_NAV_JS` builds its sidebar from the headings
    ON THE PAGE — which on a chapter page is one chapter, collapsing the nav to a
    single entry."""
    root, dist = multipage
    n = len(_chapters(root))
    for page in [dist / "index.html", *dist.glob("*/index.html")]:
        html = page.read_text(encoding="utf-8")
        assert html.count('class="guide-chapter-item') == n, page


def _sidebar(html: str) -> str:
    """The server-rendered list, which IS the sidebar's top level."""
    assert 'class="guide-chapters"' in html, "no chapter list on the page"
    return html.split('class="guide-chapters"')[1].split("</nav>")[0]


def test_the_landing_pages_entries_are_in_page_anchors(multipage):
    """The whole document is on this page. An entry that loaded `/<slug>/` would
    move a reader who had deliberately chosen one page into chapter mode —
    choosing the mode is what the header's view switch is for."""
    _, dist = multipage
    hrefs = re.findall(r'<a href="([^"]+)"', _sidebar(
        (dist / "index.html").read_text(encoding="utf-8")))
    assert hrefs, "the landing page's chapter list has no entries at all"
    assert all(h.startswith("#") for h in hrefs), hrefs


def test_a_chapter_pages_entries_are_urls_except_its_own(multipage):
    """Every other chapter is genuinely elsewhere; this one is already here."""
    _, dist = multipage
    hrefs = re.findall(r'<a href="([^"]+)"', _sidebar(
        (dist / "second-chapter" / "index.html").read_text(encoding="utf-8")))
    assert hrefs.count("#second-chapter") == 1, hrefs
    assert "../first-chapter/" in hrefs and "../pinned/" in hrefs, hrefs


@pytest.mark.parametrize("page", ["index.html", "first-chapter/index.html",
                                  "second-chapter/index.html", "pinned/index.html"])
def test_every_anchor_the_sidebar_offers_resolves_on_its_own_page(multipage, page):
    """THE FAILURE THIS EXISTS FOR is silent: a `#fragment` with no matching id
    scrolls nowhere and reports nothing. It is what deriving the anchor from the
    route slug produces — the two grammars agree on most headings and diverge on
    the punctuated ones (`Node.js basics` is id `node.js-basics` and slug
    `node-js-basics`), so it would look correct across a whole guide and break on
    one chapter."""
    _, dist = multipage
    html = (dist / page).read_text(encoding="utf-8")
    ids = set(re.findall(r'<h[1-6][^>]*\bid="([^"]+)"', html))
    for href in re.findall(r'<a href="(#[^"]+)"', _sidebar(html)):
        assert href[1:] in ids, (
            f"{page}: the sidebar offers {href}, which is not a heading id on "
            f"that page — the jump would scroll nowhere")


def test_the_sub_headings_the_sidebar_nests_are_still_on_the_page(multipage):
    """The unification must not cost `chapter_level = 1` guides their depth:
    mac-terminal's sidebar is 7 chapters and 14 sub-sections, and a top level
    seeded from the chapter set ALONE would have dropped 14 of its 21 entries.

    The second level comes from the DOM, so what the server owes is the ids — and
    a sub-section must not have become a top-level entry in the process."""
    _, dist = multipage
    html = (dist / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<h2[^>]*\bid="a-subsection"', html), (
        "the sub-heading the sidebar nests carries no id to nest by")
    assert "a-subsection" not in _sidebar(html), (
        "a sub-section was promoted to a top-level chapter entry")


def test_only_the_current_chapter_is_marked(multipage):
    _, dist = multipage
    landing = (dist / "index.html").read_text(encoding="utf-8")
    assert "guide-chapter-item is-current" not in landing
    chapter = (dist / "first-chapter" / "index.html").read_text(encoding="utf-8")
    assert chapter.count("guide-chapter-item is-current") == 1


def test_prev_and_next_are_absent_at_the_ends(multipage):
    _, dist = multipage
    first = (dist / "first-chapter" / "index.html").read_text(encoding="utf-8")
    assert 'class="next"' in first and 'class="prev"' not in first
    last = (dist / "pinned" / "index.html").read_text(encoding="utf-8")
    assert 'class="prev"' in last and 'class="next"' not in last


def test_the_mode_link_points_both_ways(multipage):
    _, dist = multipage
    landing = (dist / "index.html").read_text(encoding="utf-8")
    assert 'class="guide-mode-link" href="first-chapter/"' in landing
    chapter = (dist / "first-chapter" / "index.html").read_text(encoding="utf-8")
    assert 'class="guide-mode-link" href="../"' in chapter


# ----- depth ------------------------------------------------------------------

def test_chapter_assets_resolve_one_level_down(multipage):
    """The bug this exists to catch 404s every font on every chapter page while
    the landing page renders perfectly."""
    _, dist = multipage
    landing = (dist / "index.html").read_text(encoding="utf-8")
    chapter = (dist / "first-chapter" / "index.html").read_text(encoding="utf-8")
    assert 'url("fonts/vendor/' in landing or "url(fonts/vendor/" in landing
    assert "../fonts/vendor/" in chapter
    assert f'href="../probe-guide.pdf"' in chapter


# ----- indexing ---------------------------------------------------------------

def test_no_canonical_means_noindex_everywhere(multipage):
    """`site.canonical` is empty, so the guide has not said where it is
    published. Serving the same prose at `/` and at every chapter route without
    saying which is canonical would ask a search engine to guess."""
    _, dist = multipage
    for page in [dist / "index.html", *dist.glob("*/index.html")]:
        assert '<meta name="robots" content="noindex">' in page.read_text(encoding="utf-8")


def test_a_canonical_base_makes_each_page_canonical_for_itself(guide_repo):
    root, write_toml = guide_repo
    (root / "guide.md").write_text(_MULTI_MD, encoding="utf-8")
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False},
               site={"canonical": "https://example.com", "chapter_level": 1})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    dist = root / "app" / "dist"
    assert '<link rel="canonical" href="https://example.com/">' in \
        (dist / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://example.com/first-chapter/">' in \
        (dist / "first-chapter" / "index.html").read_text(encoding="utf-8")


# ----- guide.json -------------------------------------------------------------

def test_guide_json_lists_the_chapters_and_the_pdf(multipage):
    root, dist = multipage
    m = json.loads((dist / "guide.json").read_text(encoding="utf-8"))
    assert m["site"] == "multipage"
    assert [c["slug"] for c in m["chapters"]] == [c.slug for c in _chapters(root)]
    assert m["pdf"] == "probe-guide.pdf"
    assert m["canonical"] is None


def test_guide_json_reports_an_absent_pdf_as_null(multipage):
    """The hub's "romance-languages has no PDF" rule is enforced by DATA, so
    absence has to be expressible — and it must not be a dead link.

    Run INSIDE the fixture, not in the test process: `buildcore` resolves its
    paths at import against whichever repo imported it, which here is the kit,
    whose guide.toml has no `[artifacts.site]` table at all."""
    root, dist = multipage
    (dist / "probe-guide.pdf").unlink()
    proc = subprocess.run(
        [sys.executable, "-c",
         "import json, pathlib, kitconfig, render_site;"
         "cfg = kitconfig.load(pathlib.Path('.'));"
         "p = render_site.write_guide_json(cfg, pathlib.Path('app/dist'));"
         "print(json.loads(p.read_text())['pdf'])"],
        cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "None"


def test_guide_json_is_emitted_for_a_single_page_guide_too(guide_repo):
    """The hub reads it from guides that have not flipped to multipage. A
    manifest only some guides publish is one the hub cannot rely on."""
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    m = json.loads((root / "app" / "dist" / "guide.json").read_text(encoding="utf-8"))
    assert m["site"] == "single"
    assert m["chapters"] == []


# ----- ceilings ---------------------------------------------------------------

def test_a_tree_within_the_ceilings_passes(multipage):
    _, dist = multipage
    render_site.check_ceilings(dist)          # must not raise


def test_too_many_headers_rules_is_refused(multipage, tmp_path):
    _, dist = multipage
    (dist / cfadapter.HEADERS_FILENAME).write_text(
        "".join(f"/p{i}\n  X-A: b\n" for i in range(render_site.CF_MAX_HEADER_RULES + 1)),
        encoding="utf-8")
    with pytest.raises(SystemExit, match="_headers"):
        render_site.check_ceilings(dist)


def test_an_over_long_headers_line_is_refused(multipage):
    _, dist = multipage
    (dist / cfadapter.HEADERS_FILENAME).write_text(
        "/p\n  X-A: " + "b" * render_site.CF_MAX_HEADER_LINE + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="_headers"):
        render_site.check_ceilings(dist)


@pytest.mark.parametrize("n,ok", [(render_site.CF_MAX_REDIRECTS_STATIC, True),
                                  (render_site.CF_MAX_REDIRECTS_STATIC + 1, False)])
def test_the_static_redirect_boundary(multipage, n, ok):
    """Exactly at the ceiling passes; one over is refused. Boundary fixtures
    because an off-by-one here fails at deploy, not at build."""
    _, dist = multipage
    (dist / "_redirects").write_text(
        "".join(f"/a{i} /b{i} 301\n" for i in range(n)), encoding="utf-8")
    if ok:
        render_site.check_ceilings(dist)
    else:
        with pytest.raises(SystemExit, match="static redirects"):
            render_site.check_ceilings(dist)


def test_dynamic_redirects_use_the_much_lower_ceiling(multipage):
    """A splat makes a rule dynamic, and the dynamic limit is twenty times lower
    — so the classification is what decides which gate applies."""
    _, dist = multipage
    (dist / "_redirects").write_text(
        "".join(f"/a{i}/* /b{i} 301\n"
                for i in range(render_site.CF_MAX_REDIRECTS_DYNAMIC + 1)),
        encoding="utf-8")
    with pytest.raises(SystemExit, match="dynamic redirects"):
        render_site.check_ceilings(dist)


def test_an_over_long_redirect_rule_is_refused(multipage):
    _, dist = multipage
    (dist / "_redirects").write_text(
        "/a" + "b" * render_site.CF_MAX_REDIRECT_LINE + " /c 301\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="_redirects rule"):
        render_site.check_ceilings(dist)


def test_an_oversized_file_is_refused(multipage):
    _, dist = multipage
    (dist / "big.bin").write_bytes(b"\0" * (render_site.CF_MAX_FILE_BYTES + 1))
    with pytest.raises(SystemExit, match="per-file limit"):
        render_site.check_ceilings(dist)


# ----- relative-URL rewriting for chapter depth --------------------------------

@pytest.mark.parametrize("url,expected", [
    ('url("fonts/vendor/A.otf")', 'url("../fonts/vendor/A.otf")'),
    ("url(assets/hero.png)", "url(../assets/hero.png)"),
    ("url('sub/dir/x.svg')", "url('../sub/dir/x.svg')"),
])
def test_relative_css_urls_get_the_chapter_prefix(url, expected):
    """Rewritten generically, not by substituting the one prefix the kit happens
    to emit today. No guide's style-screen.css contains a `url()` at all right
    now — so a `fonts/vendor/`-only replace would be correct by luck and would
    404 the first time a guide referenced an image."""
    import buildcore
    assert buildcore._prefix_css_urls(url, "../") == expected


@pytest.mark.parametrize("url", [
    "url(/absolute.png)", "url(//cdn.example.com/x.png)",
    "url(https://example.com/x.png)", "url(data:image/svg+xml;base64,AAA)",
    "url('#gradient')", "url(blob:abc)",
])
def test_non_relative_css_urls_are_left_alone(url):
    """None of these resolve against the page's directory, so prefixing them
    breaks what works. The scheme test is general — `blob:` and `about:` exist
    too, and a rewriter knowing only http/data would corrupt the rest."""
    import buildcore
    assert buildcore._prefix_css_urls(url, "../") == url


def test_no_prefix_is_the_identity(multipage):
    """The landing page and the PDF both pass an empty prefix. If this were not
    exactly the identity, adding chapter support would have changed the PDF."""
    import buildcore
    css = (multipage[0] / "style-screen.css").read_text(encoding="utf-8")
    assert buildcore._prefix_css_urls(css, "") == css


# ----- round-1 review fixes ----------------------------------------------------

_LINKED_MD = """\
# 1. Alpha {#alpha}

See [beta's part](#beta-sub) and [back to alpha](#alpha).

# 2. Beta {#beta}

## A subsection {#beta-sub}

Text.
"""


@pytest.fixture
def linked(guide_repo):
    root, write_toml = guide_repo
    (root / "guide.md").write_text(_LINKED_MD, encoding="utf-8")
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    return root, root / "app" / "dist"


def test_a_cross_chapter_fragment_is_retargeted(linked):
    """~100 of these exist in the family (accounting 41, git 33, japan 26). On a
    chapter page every one whose target lives elsewhere is a dead anchor."""
    _, dist = linked
    html_ = (dist / "alpha" / "index.html").read_text(encoding="utf-8")
    assert 'href="../beta/#beta-sub"' in html_


def test_a_same_chapter_fragment_is_left_alone(linked):
    """Retargeting a local link would make it a page load instead of a jump."""
    _, dist = linked
    html_ = (dist / "alpha" / "index.html").read_text(encoding="utf-8")
    assert 'href="#alpha"' in html_


def test_the_chapters_own_heading_keeps_its_id(linked):
    """The heading is the REAL Header block, not a synthesised `<h1>`. Without
    its id, the same-page link above has no target to jump to."""
    _, dist = linked
    assert 'id="alpha"' in (dist / "alpha" / "index.html").read_text(encoding="utf-8")


def test_a_renamed_chapter_does_not_leave_its_old_route_behind(linked):
    """Nothing else would ever remove it, and it stays deployable with obsolete
    content."""
    root, dist = linked
    assert (dist / "alpha" / "index.html").exists()
    (root / "guide.md").write_text(
        _LINKED_MD.replace("{#alpha}", "{#alpha-renamed}"), encoding="utf-8")
    render(root, "--web")
    assert (dist / "alpha-renamed" / "index.html").exists()
    assert not (dist / "alpha").exists(), "the stale route survived the rebuild"


def test_a_title_with_markup_cannot_escape_the_title_element(guide_repo):
    """Chapter titles come from headings, and a heading may contain anything."""
    root, write_toml = guide_repo
    (root / "guide.md").write_text(
        "# Use `</title><meta name=\"x\">` here {#t}\n\nBody.\n", encoding="utf-8")
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    head = (root / "app" / "dist" / "t" / "index.html").read_text(
        encoding="utf-8").split("</head>")[0]
    assert head.count("</title>") == 1, "the title element was closed early"
    assert '<meta name="x">' not in head


def test_control_files_do_not_count_against_the_asset_quota(multipage):
    """Cloudflare parses `_headers`/`_redirects` and does not serve them."""
    _, dist = multipage
    (dist / "_redirects").write_text("/a /b 301\n", encoding="utf-8")
    n_real = len([p for p in dist.rglob("*") if p.is_file()]) - 2
    render_site.CF_MAX_ASSET_FILES, old = n_real, render_site.CF_MAX_ASSET_FILES
    try:
        render_site.check_ceilings(dist)          # must not raise
    finally:
        render_site.CF_MAX_ASSET_FILES = old


def test_a_colon_in_a_static_path_is_not_a_placeholder(multipage):
    """A Cloudflare placeholder is `:name`. `/archive/12:30` is an ordinary
    static path, and calling it dynamic tests it against a ceiling 20x lower."""
    _, dist = multipage
    (dist / "_redirects").write_text(
        "".join(f"/archive/{i}:30 /b{i} 301\n"
                for i in range(render_site.CF_MAX_REDIRECTS_DYNAMIC + 5)),
        encoding="utf-8")
    render_site.check_ceilings(dist)              # must not raise


# ----- round-2 review fixes ----------------------------------------------------

def test_a_level_2_chapter_page_still_has_an_h1(guide_repo):
    """accounting-guide splits at `##`, so the chapter's own heading is an `<h2>`
    and the page would otherwise have no `<h1>` at all. Promoted by TAG only, so
    the id and inline markup survive."""
    root, write_toml = guide_repo
    (root / "guide.md").write_text(
        "# Part One\n\n## The ledger {#ledger}\n\nProse.\n", encoding="utf-8")
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False},
               site={"canonical": "", "chapter_level": 2})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    page = (root / "app" / "dist" / "ledger" / "index.html").read_text(encoding="utf-8")
    assert "<h1" in page and 'id="ledger"' in page
    assert "<h2" not in page.split("</head>")[1].split("<footer")[0]


def test_a_part_opening_chapter_closes_the_tag_it_opened(guide_repo):
    """THE DEFECT THIS PINS SHIPPED to six of accounting-guide's 43 chapter pages
    and was invisible on every one of them.

    Promotion used to be two string operations on the rendered HTML, and only the
    first was anchored: an `^\\s*<h2` substitution for the opening tag, then an
    unanchored `replace("</h2>", "</h1>", 1)` for the closing one. On a chapter
    that OPENS A PART the body begins with the part's own `<h1 class="part">`, so
    the anchored half matched nothing while the unanchored half rewrote the
    chapter heading's closing tag regardless:

        <h2 id="the-ledger">The ledger</h1>

    Browsers discard the stray end tag and render it correctly, which is exactly
    why nobody found it. Asserted as tag BALANCE rather than by looking for an
    `<h1>` somewhere on the page — the part's heading is an `<h1>` too, so a
    presence check passes on the broken output."""
    root, write_toml = guide_repo
    (root / "guide.md").write_text(
        "# Part I — The Basics {.part}\n\nBlurb.\n\n"
        "## The ledger {#ledger}\n\nProse.\n", encoding="utf-8")
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False},
               site={"canonical": "", "chapter_level": 2})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    page = (root / "app" / "dist" / "ledger" / "index.html").read_text(encoding="utf-8")
    body = page.split("</head>")[1].split("<footer")[0]
    for level in (1, 2, 3):
        assert body.count(f"<h{level}") == body.count(f"</h{level}>"), (
            f"h{level} open and close tags disagree — the chapter heading was "
            f"closed with a tag it was not opened with:\n{body[:400]}")
    assert '<h1 id="ledger">' in body, (
        "the chapter's own heading was not promoted on a page that opens a part")
    assert 'class="part"' in body, "the part heading was lost"


def test_chapter_pages_carry_the_nav_script(multipage):
    """A chapter page needs the same progressive enhancement as the one-page
    view: the sticky header, the sidebar, and the relocation of the two top
    controls all come from the script.

    Keyed on the sidebar class rather than on the removed heading anchor, which
    is what this used to assert."""
    _, dist = multipage
    page = (dist / "first-chapter" / "index.html").read_text(encoding="utf-8")
    assert "guide-nav" in page, "chapter page carries no nav script"


def test_cleanup_will_not_delete_a_hand_made_directory(multipage):
    """Ownership is proven by the marker this renderer writes, not inferred from
    the directory looking generated — "contains only index.html" also describes
    a page somebody added by hand."""
    root, dist = multipage
    mine = dist / "hand-written"
    mine.mkdir()
    (mine / "index.html").write_text("<p>not the build's</p>", encoding="utf-8")
    render(root, "--web")
    assert (mine / "index.html").exists(), "the build deleted someone's page"


def test_leaving_multipage_removes_the_old_chapter_routes(multipage):
    """The case cleanup exists for most, and the one that never reaches the
    multipage code path at all."""
    root, dist = multipage
    assert (dist / "first-chapter").exists()
    root_toml = (root / "guide.toml").read_text(encoding="utf-8")
    (root / "guide.toml").write_text(
        root_toml.replace('site = "multipage"', 'site = "single"'), encoding="utf-8")
    render(root, "--web")
    assert not (dist / "first-chapter").exists(), "a stale route survived the flip"


def test_a_heading_inside_a_div_is_still_a_link_target(guide_repo):
    """Nested in the AST, and just as linkable. Scanning only top-level blocks
    left these unmapped, so a link to one stayed bare and died."""
    root, write_toml = guide_repo
    (root / "guide.md").write_text(
        '# One {#one}\n\n[go](#deep)\n\n# Two {#two}\n\n'
        '<div class="callout tip">\n\n### Deep {#deep}\n\ntext\n\n</div>\n',
        encoding="utf-8")
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    page = (root / "app" / "dist" / "one" / "index.html").read_text(encoding="utf-8")
    assert 'href="../two/#deep"' in page


def test_a_malformed_canonical_is_refused(guide_repo):
    """It is emitted into every page's <head>; a relative value would point every
    canonical at the wrong place."""
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "multipage", "slides": False},
               site={"canonical": "example.com", "chapter_level": 1})
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    with pytest.raises(AssertionError, match="canonical"):
        render(root, "--web")


# ---------------------------------------------------------------------------
# Nothing navigational precedes the document's own title
#
# THE DEFECT, and it shipped to seven live sites: the chapter list was rendered
# between the topbar and the page's <h1>, so every page — the guide's front page
# included — opened with a table of contents instead of with the guide.
#
# It was reported as "TOC info inline with the text before the doc title", and
# the first fix STYLED it rather than moving it. So this asserts ORDER, never
# appearance: a prettier table of contents in the wrong place is the same
# defect, and a test about how it looks would have passed throughout.
# ---------------------------------------------------------------------------

def _before_the_title(html: str, needle: str) -> bool:
    """Whether `needle` appears before the page's first <h1>."""
    h1 = re.search(r"<h1[ >]", html)
    assert h1, "no <h1> on the page at all"
    at = html.find(needle)
    return at != -1 and at < h1.start()


def test_no_chapter_list_precedes_the_title_on_a_chapter_page(multipage):
    _, dist = multipage
    pages = sorted(dist.glob("*/index.html"))
    assert pages, "the fixture produced no chapter pages"
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert not _before_the_title(html, 'class="guide-chapters"'), (
            f"{page.parent.name}: the chapter list is rendered before the <h1>, "
            f"so the page opens with a table of contents instead of the chapter")


def test_the_one_page_view_opens_with_the_guide_not_a_contents_list(multipage):
    """The landing page is the sharpest case: a reader arriving at the guide met
    a table of contents before the guide's own title."""
    _, dist = multipage
    html = (dist / "index.html").read_text(encoding="utf-8")
    assert not _before_the_title(html, 'class="guide-chapters"'), (
        "the landing page renders its chapter list before the document title")


def test_moving_it_down_did_not_remove_it(multipage):
    """The list is RELOCATED, not deleted, and that distinction is load-bearing
    twice over. It is the sidebar's whole top level, so a page that did not emit
    it would have no sidebar at all once the script ran — and it is what a reader
    without JavaScript gets instead of one."""
    _, dist = multipage
    for page in [dist / "index.html", *sorted(dist.glob("*/index.html"))]:
        assert 'class="guide-chapters"' in page.read_text(encoding="utf-8"), (
            f"{page.parent.name or 'index'} has no chapter list anywhere")
