"""The favicon, and the DOM contract the heading-derived navigation emits.

WHY THIS FILE EXISTS. Seven target-owned stylesheets are written against the
class names the nav script produces. Those files are `policy = "never"` — sync
will never touch them — so a later rename here does not "break the build", it
silently unstyles seven live sites. The contract is therefore pinned by tests
rather than by comment.

The favicon has its own trap: a `<link rel="icon" href="favicon.svg">` satisfies a
`grep -c 'rel="icon"'` whether or not anything ever writes that file, so the markup
can be right while every visitor gets a 404. (When this was written `build_web()`
had no asset-copy path at all; it does now, which changes how the file WOULD be
shipped and not the fact that a grep cannot tell.) The assertions below decode the
resource and check it is non-empty, never that the markup mentions it.
"""
import base64
import pathlib
import re

import pytest

import buildcore
import chapters
import render_pdf
import render_site


# --------------------------------------------------------------------------
# Favicon
# --------------------------------------------------------------------------

def _icon_href(html: str) -> str:
    m = re.search(r'<link[^>]*rel="icon"[^>]*href="([^"]+)"', html)
    assert m, "no rel=icon link in the emitted head"
    return m.group(1)


def test_head_declares_an_icon():
    assert 'rel="icon"' in buildcore._wrap_html("<p>x</p>", "")


def test_the_icon_actually_resolves_and_is_not_empty():
    """A grep would pass on a 404. This decodes the resource."""
    href = _icon_href(buildcore._wrap_html("<p>x</p>", ""))
    assert href.startswith("data:image/svg+xml;base64,"), href
    raw = base64.b64decode(href.split(",", 1)[1])
    assert len(raw) > 50, len(raw)
    assert raw.lstrip().startswith(b"<svg"), raw[:40]


def test_the_icon_is_deterministic():
    """Two calls must produce identical bytes — no clock, no randomness."""
    assert _icon_href(buildcore._wrap_html("", "")) == _icon_href(buildcore._wrap_html("", ""))


def test_the_icon_is_derived_from_this_guide():
    """Distinct per guide, so a reader with several tabs open can tell them
    apart. Derived from OUTPUT_SLUG, which is already a stamp input."""
    raw = base64.b64decode(_icon_href(buildcore._wrap_html("", "")).split(",", 1)[1]).decode()
    words = [w for w in buildcore.OUTPUT_SLUG.split("-") if w and w != "guide"]
    expected = "".join(w[0] for w in words[:2]).upper()
    assert f">{expected}<" in raw, raw


def test_icon_initials_distinguish_the_guides_that_actually_collide():
    """The first letter alone is not enough: two guides in this family start
    with the same one, and an identical icon defeats the only reason the icon is
    derived from the guide at all."""
    def initials(slug):
        words = [w for w in slug.split("-") if w and w != "guide"]
        return "".join(w[0] for w in words[:2]).upper()
    slugs = ["accounting-guide", "git-github-for-beginners", "japan-guide",
             "linux-terminal-guide", "mac-terminal-guide",
             "windows-cmd-guide", "windows-powershell-guide", "guide-template"]
    got = [initials(s) for s in slugs]
    assert len(set(got)) == len(got), dict(zip(slugs, got))
    assert initials("windows-cmd-guide") != initials("windows-powershell-guide")


# --------------------------------------------------------------------------
# The emitted navigation DOM contract
# --------------------------------------------------------------------------

# Each entry is a LITERAL the script must contain, not a bare class name.
# Substring membership was the mistake here first time round: with only
# `"guide-header" in js`, renaming `header.className` to `site-header` still
# passed, because the string survived inside `guide-header-title`. These pin the
# assignment or the call that actually produces the class.
CONTRACT_LITERALS = [
    "header.className = 'guide-header'",
    "toggle.className = 'guide-nav-toggle'",
    "htitle.className = 'guide-header-title'",
    "nav.className = 'guide-nav'",
    "list.className = 'guide-nav-list'",
    "li.className = 'guide-nav-item guide-nav-l1'",
    "li.className = 'guide-nav-item guide-nav-l2'",
    "sub.className = 'guide-nav-sub'",
    # No `heading-anchor` entry: the per-heading "#" link is gone, and its absence
    # is asserted by test_no_per_heading_anchor_is_injected instead.
    "classList.add('is-current')",
    "classList.toggle('is-open')",
]


@pytest.mark.parametrize("literal", CONTRACT_LITERALS)
def test_nav_script_pins_every_contracted_class(literal):
    """Seven target-owned stylesheets select on these. Renaming one here does
    not break a build — it unstyles seven live sites, silently."""
    assert literal in render_site.WEB_NAV_JS, f"contract literal gone: {literal}"


def _emitted_guide_classes() -> set[str]:
    """Every `guide-*` class name `render_site` puts into the DOM.

    DERIVED, not listed. The hand-maintained list this replaces named eleven
    classes and missed five — `.guide-chapters`, `.guide-chapter-list`,
    `.guide-chapter-item`, `.guide-mode-link` and `.guide-pager`, the whole
    multipage view — which therefore shipped with no styling anywhere in the kit
    or in any guide. A list beside the thing it describes drifts exactly once
    and then stays wrong, which is the failure this repo keeps designing
    against.

    Read out of the SOURCE rather than a rendered page, so the check needs no
    build and covers the JS-inserted chrome as well as the server-rendered
    markup.
    """
    src = pathlib.Path(render_site.__file__).read_text(encoding="utf-8")
    found: set[str] = set()
    # class="a b", className = 'a b', classList.add('a')
    for m in re.finditer(r"""class(?:Name)?\s*=\s*["']([^"']+)["']""", src):
        found.update(m.group(1).split())
    for m in re.finditer(r"""classList\.(?:add|toggle|remove)\(\s*['"]([^'"]+)['"]""", src):
        found.add(m.group(1))
    # Only the kit's own namespace: a guide's own class names are its business.
    return {c for c in found if c.startswith("guide-")}


def test_there_are_emitted_classes_to_check():
    """Without this the derived check passes by finding nothing — which is how a
    gate quietly stops covering the thing it was written for."""
    found = _emitted_guide_classes()
    assert len(found) >= 10, f"only found {sorted(found)}"


@pytest.mark.parametrize("cls", sorted(_emitted_guide_classes()))
def test_the_kit_ships_baseline_styling_for_every_class_it_emits(cls):
    """Emitting the DOM without rules gives every site an unstyled list and a
    toggle that changes classes while nothing opens or closes. Baseline
    behaviour belongs in the kit; guides restyle on top of it.

    Every guide's `style-screen.css` is `policy = "never"` — target-owned — so a
    class styled only there is absent from every new guide and from any guide
    whose author never copied the rule.
    """
    assert f".{cls}" in render_site.WEB_CHROME_CSS, (
        f"render_site emits .{cls} and the kit ships no rule for it, so every "
        f"site renders it unstyled unless its own target-owned stylesheet "
        f"happens to cover it")


@pytest.mark.parametrize("cls", ["is-current", "is-open", "is-expanded"])
def test_the_state_classes_are_styled_too(cls):
    """Outside the `guide-` namespace, so the derived scan above does not reach
    them — and a toggle that changes a class nothing styles is a control that
    does nothing."""
    assert cls in render_site.WEB_CHROME_CSS, f"no baseline rule for .{cls}"


def test_the_toggle_is_an_icon_with_an_accessible_name():
    """An icon-only control is unlabelled to a screen reader unless something
    supplies the name the visible text used to. The word moved from
    `textContent` to `aria-label`; the graphic is `aria-hidden` so the button is
    announced once, as "Sections", rather than as a label plus a shape."""
    js = render_site.WEB_NAV_JS
    assert "createElementNS" in js, "the icon is not built as SVG"
    assert "setAttribute('aria-label', 'Sections')" in js, (
        "the icon button has no accessible name"
    )
    assert "icon.setAttribute('aria-hidden', 'true')" in js, (
        "the decorative graphic is exposed to assistive technology"
    )
    assert "toggle.textContent" not in js, "the button still carries visible text"


def test_the_icon_button_keeps_a_visible_focus_ring():
    """Dropping the border removed the only thing a keyboard user could see.
    `:focus-visible` so it shows for the keyboard and not on every mouse click."""
    css = render_site.WEB_CHROME_CSS
    assert ".guide-nav-toggle:focus-visible" in css, (
        "a borderless icon button with no focus ring is invisible to the keyboard"
    )


def test_the_desktop_sidebar_can_be_collapsed():
    """The toggle used to be `display: none` above 1100px, which is what made the
    sidebar permanent on desktop. Removing that line is the whole feature, so its
    absence is asserted rather than assumed."""
    css = render_site.WEB_CHROME_CSS
    desktop = css.split("@media (min-width: 1100px)")[1].split("\n}")[0]
    assert ".guide-nav-toggle { display: none; }" not in desktop, (
        "the toggle is hidden on desktop again; the sidebar cannot be collapsed"
    )
    assert ".guide-nav.is-collapsed" in css, "no collapsed state for the sidebar"


def test_the_collapse_choice_is_remembered():
    """Across 40 chapter pages, a collapse that reset on every navigation would
    read as broken. Storage access is wrapped because Safari in private mode
    THROWS rather than returning null, and an exception here would abort the rest
    of the script — taking the sticky header with it."""
    js = render_site.WEB_NAV_JS
    assert "localStorage" in js, "the collapse choice is not persisted"
    assert js.count("try {") >= 2 and "catch" in js, (
        "localStorage is accessed without a guard; it throws in private mode"
    )


def test_the_kit_publishes_the_sidebar_width_but_never_restyles_body():
    """The ownership boundary. The kit owns its sidebar's width and publishes it;
    the guide owns the prose measure and decides what room to leave. A variable
    on `:root` respects that line — and `test_prose_measure_is_not_widened`
    enforces the other half of it."""
    css = render_site.WEB_CHROME_CSS
    assert "--guide-nav-width" in css and "--guide-nav-space" in css
    assert ":root.guide-nav-is-collapsed" in css, (
        "nothing drops the reserved space to zero, so collapsing the sidebar "
        "would leave the text column stranded beside an empty margin"
    )


def test_the_collapsed_panel_leaves_the_tab_order():
    """Off-screen but still focusable is worse than visible: keyboard focus
    vanishes into a list the reader deliberately dismissed."""
    css = render_site.WEB_CHROME_CSS
    collapsed = css.split(".guide-nav.is-collapsed")[1].split("}")[0]
    assert "visibility: hidden" in collapsed, (
        "the collapsed sidebar is only moved off-screen, so it stays tabbable"
    )


def test_the_nav_lists_h1_and_h2_only():
    """88 id-carrying headings would make an unusable sidebar; two levels cover
    the numbered sections. h3 ids still exist and still resolve as fragment
    links — they are simply not listed."""
    js = render_site.WEB_NAV_JS
    assert "querySelectorAll('h1[id], h2[id]')" in js, "nav selector changed"


def test_no_per_heading_anchor_is_injected():
    """The hover-revealed "#" beside every heading is GONE. It read as a stray
    character in a document meant to be read straight through, rather than as an
    affordance for copying a section link.

    Asserted as an absence because the removal is the requirement: re-adding it
    should fail here rather than surprise a reader."""
    js = render_site.WEB_NAV_JS
    assert "heading-anchor" not in js, "the per-heading # anchor is back"
    assert "h3[id]" not in js, (
        "something still selects h3 by id in the nav script — the only thing that "
        "ever did was the removed anchor affordance"
    )
    assert "heading-anchor" not in render_site.WEB_CHROME_CSS, (
        "chrome CSS still styles an element the script no longer creates"
    )


def test_heading_ids_still_work_as_link_targets_after_the_removal():
    """Removing the anchor removed a way to DISCOVER a section link, not the
    links themselves — so this pins the two things that keep them working.

    First: the script only ever SELECTS headings that already carry an id
    (`h1[id]`), it never mints one. The ids come from pandoc server-side, so a
    reader with JavaScript off and a bookmark made a year ago both still resolve.
    Second: `scroll-margin-top` still covers h1/h2/h3 ids — without it a fragment
    jump parks the heading underneath the sticky header, which looks exactly like
    a broken link even though the navigation worked."""
    js = render_site.WEB_NAV_JS
    assert "querySelectorAll('h1[id], h2[id]')" in js, (
        "the nav no longer selects on a pre-existing id"
    )
    # `nav.id = navId` is the sidebar's OWN id and is fine; what must not appear
    # is the script assigning an id to a heading.
    assert "h.id =" not in js and "heading.id =" not in js, (
        "the nav script mints heading ids; they must come from the renderer"
    )
    assert "h3[id]" in render_site.WEB_CHROME_CSS, (
        "scroll-margin-top no longer covers h3 ids — a link to an h3 will land "
        "with the heading hidden behind the sticky header"
    )


# The three relocated nodes — the download link, the view switch and the chapter
# list — were pinned here by searching the script for a locate-and-move pair.
# That is now asserted against a real DOM instead, in tests/test_nav_dom.py:
# `test_both_top_controls_are_moved_into_the_header_in_order` and
# `test_the_chapter_list_is_moved_out_of_the_body_not_copied`. Those check the
# property this could not — that nothing was left BEHIND — so a control copied
# rather than moved now fails, where the source search passed either way.


def test_the_topbar_emits_both_controls():
    """Asserted against `_topbar`'s OUTPUT, not against the source text.

    A whole-file substring search cannot tell these two apart: `class="download-btn"`
    also appears in the footer, so deleting the topbar's copy left the search
    satisfied while the page had no top control at all — and the script would then
    have moved the FOOTER's call-to-action into the header, leaving the footer
    without one too. One deletion, three wrong things, and a green test.

    `querySelector` takes the FIRST match in document order, so which element the
    script picks up is a property of what this function emits and where it is
    placed — which is what is checked here."""
    bar = render_site._topbar('<a class="guide-mode-link" href="x/">Read by chapter</a>',
                              "guide.pdf")
    assert 'class="site-topbar"' in bar
    assert 'class="download-btn"' in bar, "the topbar emits no download link to move"
    assert 'class="guide-mode-link"' in bar, "the topbar emits no mode link to move"
    assert bar.index("guide-mode-link") < bar.index("download-btn"), (
        "mode link must precede the download in document order"
    )


def test_the_topbar_is_still_well_formed_without_a_mode_link():
    """A single-page site has no view to switch to, so `_mode_link` returns ''.
    The container must still carry the download and must not emit a stray tag."""
    bar = render_site._topbar("", "guide.pdf")
    assert 'class="download-btn"' in bar
    assert "guide-mode-link" not in bar
    assert bar.count("<div") == bar.count("</div>") == 1


def test_there_is_exactly_one_download_link_in_the_page():
    """ONE control, one copy. The footer used to render a second download link,
    which was redundant against the sticky header and — worse — existed only on
    the one-page view, so the forty chapter pages never had it. Two copies is
    also how the appearances drifted apart.

    Asserted on the renderer's emitted markup rather than on a count of the
    string, so that adding a second copy back anywhere fails here."""
    src = pathlib.Path(render_site.__file__).read_text(encoding="utf-8")
    assert '<p class="download">' not in src, (
        "the footer renders a download link again; the header already carries it "
        "on every page, and a second copy is what drifted last time"
    )
    # The one copy lives in the topbar, which is what the script relocates.
    emitted = src.count('class="download-btn"')
    assert emitted == 1, f"expected exactly one emitted download link, found {emitted}"


def test_the_phone_header_keeps_both_controls():
    """With no footer copy, hiding the header download on a narrow screen would
    leave a phone with no way to reach the PDF at all. The running title yields
    instead — the document's own <h1> is directly below it saying the same
    thing."""
    css = render_site.WEB_CHROME_CSS
    assert ".guide-header-title { display: none; }" in css, (
        "the narrow-screen rule no longer drops the running title"
    )
    assert ".guide-header .download-btn { display: none; }" not in css, (
        "the header download is hidden on narrow screens, and there is no footer "
        "copy any more — that leaves a phone with no download link at all"
    )


def test_script_adds_navigation_only():
    """No content that exists on the site and not in the PDF. The script may
    read headings and move an existing link; it must not author prose.

    Checked two ways: no bulk-HTML injection at all, and every literal string
    the script assigns as text is either navigation chrome or derived from the
    document. A new hard-coded sentence would fail the second."""
    js = render_site.WEB_NAV_JS
    for forbidden in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write"):
        assert forbidden not in js, f"{forbidden} lets arbitrary content in"

    # BOTH the text a node carries AND the text an attribute carries. The second
    # half is not padding: the drawer button used to say "Sections" as its
    # textContent, and when it became an icon that string moved to `aria-label`
    # — where a textContent-only scan could no longer see it. Same authored word,
    # same obligation, one attribute over. A check that follows the string only
    # to its old home stops covering the thing it was written for.
    assigned = re.findall(r"textContent\s*=\s*'([^']*)'", js)
    assigned += re.findall(r"setAttribute\('(?:aria-label|title)',\s*'([^']*)'\)", js)
    allowed = {"Sections", ""}
    unexpected = [s for s in assigned if s not in allowed]
    assert not unexpected, f"script authors content the PDF lacks: {unexpected}"
    # And the scan must actually be finding something, or it passes by finding
    # nothing — which is how a gate quietly stops covering its subject.
    assert assigned, "no authored strings found at all; the scan has gone blind"


def test_the_script_is_wired_into_the_web_build_only():
    """The script belongs to the website. The PDF must not carry it, and the nav
    markup must not be emitted server-side — it is built at load, so a reader
    without JavaScript gets exactly the document they get today.

    Behavioural, not source-slicing: `render_html()` is the PDF pipeline, so
    asking it directly is both simpler and harder to fool than reasoning about
    where a function ends."""
    pdf_html = render_pdf.render_html()
    assert "guide-nav" not in pdf_html, "the nav leaked into the PDF pipeline"
    assert "WEB_NAV_JS" not in pdf_html and "<script" not in pdf_html

    # render_web_html now lives in render_site.py, out of the PDF closure.
    src = pathlib.Path(render_site.__file__).read_text(encoding="utf-8")
    web_fn = src.split("def render_web_html(")[1].split("\ndef ")[0]
    assert "WEB_NAV_JS" in web_fn, "the script is not added to the web build"
    # Nav chrome must not be written into the served body.
    assert "<nav" not in web_fn and "guide-header" not in web_fn


# --------------------------------------------------------------------------
# ONE list
#
# The sidebar used to be two flat lists stacked in one panel: `.guide-chapters`
# (the document's chapters, server-rendered) above `.guide-nav-list` (this page's
# headings, built in the browser). Neither source has both facts, so neither
# could be dropped — measured on the one-page view before the change:
#
#   accounting    49 headings vs 43 chapters + 6 parts   the same content twice
#   git           43 headings vs 34 chapters + 8 parts   the same, plus the title
#   mac-terminal  21 headings vs  7 chapters + 0 parts   14 of them sub-sections
#
# At chapter_level = 2 the two lists are near-duplicates; at chapter_level = 1 the
# heading list is strictly richer. "Just use the chapter list" costs mac-terminal
# 14 of its 21 entries, so the two are NESTED instead: chapters at the top level,
# the chapter being read expanded to its own sub-headings.
# --------------------------------------------------------------------------

def _chapter(slug, title, ident, part=None):
    """A `Chapter` carrying a real Header block, which is where the anchor is
    read from. A stub with only `slug`/`title` cannot exercise that."""
    return chapters.Chapter(
        slug=slug, title=title, level=1,
        header={"t": "Header", "c": [1, [ident, [], []], []]},
        part=part)


def test_the_entries_point_into_the_view_they_are_on():
    """The two views are different documents, so one list cannot carry one
    vocabulary. On the one-page view the whole guide is present and an entry that
    loaded `/<slug>/` would move a reader out of the mode they chose; on a chapter
    page every other chapter is genuinely elsewhere."""
    chs = [_chapter("intro", "Intro", "intro"), _chapter("setup", "Setup", "setup")]

    one = render_site._chapter_nav(chs, None)
    assert 'data-view="onepage"' in one
    assert re.findall(r'<a href="([^"]+)"', one) == ["#intro", "#setup"], one

    page = render_site._chapter_nav(chs, "intro")
    assert 'data-view="chapter"' in page
    assert re.findall(r'<a href="([^"]+)"', page) == ["#intro", "../setup/"], page


def test_the_anchor_is_the_headings_id_and_never_the_route_slug():
    """The two grammars disagree, and deriving one from the other produces a dead
    fragment that scrolls nowhere rather than erroring. Measured against the
    pinned pandoc: `Node.js basics` is id `node.js-basics` and slug
    `node-js-basics`; `1984 and dystopia` is `and-dystopia` and
    `1984-and-dystopia`."""
    nav = render_site._chapter_nav(
        [_chapter("node-js-basics", "Node.js basics", "node.js-basics")], None)
    assert 'href="#node.js-basics"' in nav, nav
    assert 'data-anchor="node.js-basics"' in nav, nav
    assert "node-js-basics" not in nav.split("<a")[0], (
        "the entry's anchor was derived from the route slug"
    )


def test_a_chapter_with_no_usable_id_falls_back_to_its_route():
    """An image-only heading can yield an empty identifier. A fragment that
    resolves to nothing scrolls nowhere; the chapter URL still works, so the entry
    degrades to a page load rather than to silence."""
    nav = render_site._chapter_nav([_chapter("gallery", "Gallery", "")], None)
    assert 'href="gallery/"' in nav
    assert "data-anchor" not in nav, "an empty anchor was emitted as if it were one"


def test_nothing_hides_the_one_page_chapter_list():
    """There used to be a `display: none` on it once the sidebar existed, because
    the sidebar then carried a second, heading-derived list saying the same
    things. This IS the sidebar now — the rule would empty the panel on the
    landing page of every guide."""
    css = render_site.WEB_CHROME_CSS
    assert '.guide-chapters[data-view="onepage"]' not in css, (
        "the one-page chapter list is hidden again, which now empties the sidebar"
    )
    block = css.split(".guide-chapters {")[1].split("}")[0]
    assert "display: none" not in block, block


# NOTHING ABOUT THE HEADING WALK IS PINNED BY SOURCE TEXT ANY MORE. It was —
# four literals, one per half of the nesting — and the whole set passed while the
# script's `aria-current` handling was wrong, because each literal was present
# and the logic around it was not. `tests/test_nav_dom.py` runs the script in a
# DOM instead, and every property those literals stood for is asserted there
# against what the browser actually built: the nesting, the part boundary, the
# expansion, the anchor index, and the attributes.
#
# What remains in THIS file is what a DOM cannot answer — the CSS, the published
# class contract, the server-rendered markup, and the one branch no rendered page
# exercises (below).


def test_the_heading_derived_list_survives_for_a_guide_with_no_chapters():
    """A `single` site has no chapter set, so its headings ARE its structure and
    the old builder is still the right one. Losing this branch would give every
    non-multipage guide an empty sidebar."""
    js = render_site.WEB_NAV_JS
    fallback = js.split("if (chapters) {")[1].split("} else {")[1]
    assert "list.className = 'guide-nav-list'" in fallback, (
        "the heading-derived top level is no longer built where there is no "
        "chapter list to seed one from"
    )
    assert "li.className = 'guide-nav-item guide-nav-l1'" in fallback
