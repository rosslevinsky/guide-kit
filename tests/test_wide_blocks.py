"""Tests for the wide-content breakout applied to the SCREEN output.

WHY THE WRAPPER EXISTS. Tables were `width: 100%` inside the prose measure with
no overflow escape, so a wide reference table was compressed into the text column
and wrapped into stacks — git-guide's widest row carries 179 characters across 50
rows. The prose measure itself is correct (~75-90 characters per line) and is
deliberately NOT widened; only specific blocks break out of it.

Pandoc emits a bare `<table>` with nowhere to hang `overflow-x`, and setting
`display: block` on the table to make it scrollable discards table layout, which
defeats the point. Hence a wrapper.

These tests cover the wrapping transform, which is string surgery on pandoc's
output and therefore exactly the kind of thing that silently produces unbalanced
HTML.
"""
from __future__ import annotations

import inspect
import re

import buildcore
import render_pdf
import render_site

# The wrapper carries an accessible name, which differs per element kind, so
# the shared constants below are the two concrete forms rather than one string.
WRAP_OPEN = '<div class="wide-block" tabindex="0" role="region" aria-label="Table, scrollable">'
WRAP_OPEN_SVG = '<div class="wide-block" tabindex="0" role="region" aria-label="Diagram, scrollable">'


def test_a_single_table_is_wrapped():
    out = render_site._wrap_wide_blocks("<p>x</p><table><tr><td>a</td></tr></table><p>y</p>")
    assert out == f"<p>x</p>{WRAP_OPEN}<table><tr><td>a</td></tr></table></div><p>y</p>"


def test_every_table_is_wrapped_and_balanced():
    html = "".join(f"<table><tr><td>{i}</td></tr></table>" for i in range(5))
    out = render_site._wrap_wide_blocks(html)
    assert out.count(WRAP_OPEN) == 5
    assert out.count("</table></div>") == 5
    # No stray wrappers and no stray closers.
    assert out.count('<div class="wide-block"') == out.count("</div>")


def test_a_table_with_attributes_is_still_wrapped():
    # pandoc emits attributes on <table> in some configurations; a naive
    # `"<table>"` literal match would silently skip those and leave them
    # constrained, which is the failure that looks like "it just didn't work".
    out = render_site._wrap_wide_blocks('<table class="journal" id="je-1"><tr><td>a</td></tr></table>')
    assert out.startswith(WRAP_OPEN)
    assert '<table class="journal" id="je-1">' in out
    assert out.endswith("</table></div>")


def test_no_tables_is_a_no_op():
    html = "<p>Nothing to see</p><pre>code</pre>"
    assert render_site._wrap_wide_blocks(html) == html


def test_pre_is_not_wrapped():
    """`pre` is deliberately excluded.

    Code already scrolls inside the prose measure, the widest code line in the
    family is 90 characters, and pulling code blocks out of the text column would
    break the read-along flow the guides depend on. If someone later wraps `pre`
    too, this should fail and make them argue for it.
    """
    out = render_site._wrap_wide_blocks("<pre><code>x</code></pre>")
    assert "wide-block" not in out


def test_tables_are_not_double_wrapped():
    once = render_site._wrap_wide_blocks("<table><tr><td>a</td></tr></table>")
    twice = render_site._wrap_wide_blocks(once)
    assert twice.count(WRAP_OPEN) == 1, "wrapping is not idempotent — a second pass nests it"


def test_wrapper_is_keyboard_reachable():
    """A horizontally scrolling region is unreachable by keyboard without a
    tabindex, which would make wide tables mouse-only."""
    out = render_site._wrap_wide_blocks("<table><tr><td>a</td></tr></table>")
    assert 'tabindex="0"' in out
    assert 'role="region"' in out


def _rules_only(css: str) -> str:
    """CSS with /* comments */ stripped.

    Every assertion below must run against this rather than the raw sheet. The
    rationale comments in WEB_CHROME_CSS discuss the mechanisms they replaced by
    name, so a plain substring check reads its own documentation and passes.
    That is not hypothetical: `test_breakout_is_viewport_capped` asserted
    `"100vw" in css` to pin a viewport cap, and when the cap was deleted the test
    stayed green on the word "100vw" inside the comment explaining the deletion.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _toplevel(css: str) -> str:
    """CSS with comments and every at-rule BLOCK (`@media { … }`) removed, so
    what is left is the unconditional, always-applied rules.

    Brace-counted rather than split on the literal "@media": the sheet has
    several media blocks and a naive split silently truncates the sheet at the
    first one, which is how `test_wrapper_does_not_stretch_its_table` came to
    look for a rule in a slice that could never contain it — and then passed on
    an `if m:` guard when it found nothing. A test that no-ops when it cannot
    locate its subject is worse than no test.
    """
    css, out, i = _rules_only(css), [], 0
    while i < len(css):
        at = css.find("@", i)
        if at == -1:
            out.append(css[i:]); break
        out.append(css[i:at])
        brace = css.find("{", at)
        if brace == -1:
            break
        depth, j = 0, brace
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1
    return "".join(out)


def _rule_body(css: str, selector: str) -> str:
    """The declarations of the first top-level `selector { … }` rule, comments
    and media blocks stripped. Assertions target a specific rule rather than the
    whole sheet, so a declaration living on some unrelated selector cannot
    satisfy them."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", _toplevel(css))
    assert m, f"no top-level `{selector}` rule in chrome CSS"
    return m.group(1)


class TestChromeCss:
    def test_wrapper_is_a_scroll_container(self):
        """`.wide-block` exists to give an over-wide table its own scrollbar."""
        body = _rule_body(render_site.WEB_CHROME_CSS, ".wide-block")
        assert "overflow-x: auto" in body

    def test_wrapper_cannot_exceed_its_content_box(self):
        """The wrapper must stay inside the space it is given.

        It used to be a breakout — `min-width: 100%` plus `width: max-content` and
        a centring transform — which is the classic cause of whole-page horizontal
        scrolling, and which also forced short tables to full width and dumped the
        slack into one column. It is an ordinary in-flow block now, and this pins
        both halves: `max-width: 100%` present, and no mechanism for re-acquiring
        the breakout without tripping a test.
        """
        body = _rule_body(render_site.WEB_CHROME_CSS, ".wide-block")
        assert "max-width: 100%" in body
        for banned in ("min-width: 100%", "width: max-content", "transform:", "margin-left: 50%"):
            assert banned not in body, (
                f"`{banned}` reintroduces the breakout: it lets the wrapper exceed "
                "its content box and stretches short tables to full width"
            )

    def test_wrapper_does_not_stretch_its_table(self):
        """The kit sets no desktop width on the table itself.

        A `width` or percentage `min-width` here overrides whatever the guide
        chose (accounting caps journal entries at 34rem) because it is both later
        and more specific, and it is how a three-column register ended up with a
        953px column holding an 18-character note. The phone floor inside the
        max-width media query is deliberate and is not covered by this.
        """
        body = _rule_body(render_site.WEB_CHROME_CSS, ".wide-block > table")
        assert "width" not in body, (
            "kit must not size the table; the guide's own sheet decides"
        )

    def test_breakout_is_neutralised_in_print(self):
        css = _rules_only(render_site.WEB_CHROME_CSS)
        print_block = css[css.index("@media print"):]
        assert ".wide-block" in print_block, "a scroll container paginates badly"
        assert "overflow-x: visible" in print_block

    def test_prose_measure_is_not_widened(self):
        """The fix must not touch the body measure.

        Widening prose past ~75-90 characters per line hurts reading, and the
        whole design of this change is per-element breakout instead. If chrome CSS
        ever starts setting a body width, that decision is being reversed by
        accident.
        """
        # Match a `body` SELECTOR, not the word — the rationale comments here
        # legitimately discuss "body text", and an assertion that trips on its own
        # documentation is an assertion nobody will keep.
        import re
        assert not re.search(r"(^|[\s,{}])body\s*(,|\{)", render_site.WEB_CHROME_CSS), \
            "chrome CSS must not restyle body; the prose measure is per-guide"


# --------------------------------------------------------------------------
# Inline SVG diagrams get the same breakout, for a reason that is the opposite
# of the table one. A table overflows its container and needs somewhere to
# scroll. A viewBox-sized SVG does the opposite — it honours `max-width: 100%`
# perfectly and SHRINKS, so a 700-unit-wide drawing at a 358px phone measure
# renders its 13-unit labels at under 7px. Fitted and unreadable is worse than
# scrollable and readable.
# --------------------------------------------------------------------------

def test_svg_diagram_is_wrapped():
    html = '<svg class="diagram" viewBox="0 0 700 186"><title>t</title></svg>'
    out = render_site._wrap_wide_blocks(html)
    assert re.match(r'<div class="wide-block" tabindex="0" role="region"[^>]*><svg', out)
    assert out.endswith("</svg></div>")


def test_svg_without_the_diagram_class_is_left_alone():
    """Only diagrams break out. An icon or a decorative mark stays inline."""
    html = '<svg class="icon" viewBox="0 0 16 16"></svg>'
    assert render_site._wrap_wide_blocks(html) == html


def test_svg_wrapping_is_idempotent():
    """Same guarantee the table path makes: a second pass must not nest
    wrappers, or one drawing ends up inside two focusable scroll regions."""
    html = '<svg class="diagram" viewBox="0 0 700 186"></svg>'
    once = render_site._wrap_wide_blocks(html)
    assert render_site._wrap_wide_blocks(once) == once


def test_a_diagram_and_a_table_are_both_wrapped():
    html = '<table><tr><td>x</td></tr></table><svg class="diagram" viewBox="0 0 10 10"></svg>'
    out = render_site._wrap_wide_blocks(html)
    assert out.count('class="wide-block"') == 2


def test_nested_same_tag_closes_at_the_right_place():
    """A nested table gets ONE wrapper, around the outer element.

    Two properties at once. The wrapper must close at the OUTER `</table>` —
    the blanket string-replace this replaced would have closed it at the inner
    one, putting the rest of the outer table outside its own scroll region. And
    the inner table must not gain a wrapper of its own: nesting scroll regions
    means two focusable regions around one table, which is the same defect the
    idempotence guard exists to prevent."""
    html = "<table><tr><td><table><tr><td>x</td></tr></table></td></tr></table>"
    out = render_site._wrap_wide_blocks(html)
    assert out.count('class="wide-block"') == 1
    assert out.endswith("</table></div>")
    assert out.count("</div>") == 1
    assert re.match(r'<div class="wide-block" tabindex="0" role="region"[^>]*><table>', out)


def test_a_skipped_element_does_not_gain_a_stray_close():
    """An svg WITHOUT the diagram class is skipped, so nothing may be appended
    after its closing tag. The blanket replace appended a </div> for every
    closing tag in the document, wrapped or not."""
    html = '<svg class="icon"></svg><svg class="diagram"></svg>'
    out = render_site._wrap_wide_blocks(html)
    assert out.count('class="wide-block"') == 1
    assert out.count("</div>") == 1
    assert out.startswith('<svg class="icon"></svg><div')


# --------------------------------------------------------------------------
# Malformed / adversarial input. The rule these all share: when the scanner
# cannot find a clean boundary it must leave the element ALONE. Not wrapping is
# always safe; opening a wrapper with no matching close is not — it swallows
# the rest of the page into a scroll container.
# --------------------------------------------------------------------------

def test_closing_tag_inside_a_comment_is_not_the_boundary():
    """A comment containing </svg> is legal markup. Mistaking it for the real
    close drops the </div> inside the comment, so the wrapper never closes."""
    html = '<svg class="diagram"><!-- </svg> --><text>x</text></svg><p>after</p>'
    out = render_site._wrap_wide_blocks(html)
    assert out.count('class="wide-block"') == 1
    assert out.count("</div>") == 1
    assert out.endswith("<p>after</p>"), "content after the diagram was swallowed"
    assert "</svg></div>" in out


def test_self_closing_svg_is_left_alone():
    html = '<svg class="diagram" viewBox="0 0 10 10"/><p>after</p>'
    assert render_site._wrap_wide_blocks(html) == html


def test_unclosed_element_is_left_alone():
    html = '<svg class="diagram"><text>x</text><p>after</p>'
    assert render_site._wrap_wide_blocks(html) == html


def test_mixed_case_closing_tag_is_found():
    html = '<svg class="diagram"><text>x</text></SVG><p>after</p>'
    out = render_site._wrap_wide_blocks(html)
    assert out.count('class="wide-block"') == 1
    assert out.count("</div>") == 1
    assert out.endswith("<p>after</p>")


def test_a_diagram_nested_in_a_table_gets_one_wrapper():
    """The table is wrapped; the diagram inside it must not gain a second
    scroll region."""
    html = '<table><tr><td><svg class="diagram"><text>x</text></svg></td></tr></table>'
    out = render_site._wrap_wide_blocks(html)
    assert out.count('class="wide-block"') == 1
    assert re.match(r'<div class="wide-block" tabindex="0" role="region"[^>]*><table>', out)


def test_scroll_regions_are_named():
    """A focusable region with no accessible name is announced as just
    "region" — the keyboard user lands somewhere and is told nothing."""
    out = render_site._wrap_wide_blocks('<table><tr><td>x</td></tr></table>')
    assert 'aria-label="Table, scrollable"' in out

    out = render_site._wrap_wide_blocks(
        '<svg class="diagram"><title id="d1">Branching</title></svg>')
    assert 'aria-labelledby="d1"' in out, out

    out = render_site._wrap_wide_blocks('<svg class="diagram"><text>x</text></svg>')
    assert 'aria-label="Diagram, scrollable"' in out


def test_second_pass_does_not_wrap_content_inside_an_existing_region():
    """The idempotence guarantee, for nested content. The open-tag lookbehind
    only sees an element sitting IMMEDIATELY inside a wrapper, so a diagram in a
    wrapped table's cell looked free-standing on a second pass and picked up a
    scroll region of its own."""
    html = '<table><tr><td><svg class="diagram"><text>x</text></svg></td></tr></table>'
    once = render_site._wrap_wide_blocks(html)
    assert once.count('class="wide-block"') == 1
    assert render_site._wrap_wide_blocks(once) == once


def test_second_pass_is_stable_for_every_shape_we_wrap():
    for html in (
        '<table><tr><td>x</td></tr></table>',
        '<svg class="diagram"><title id="t">T</title></svg>',
        '<table><tr><td>a</td></tr></table><svg class="diagram"></svg>',
    ):
        once = render_site._wrap_wide_blocks(html)
        assert render_site._wrap_wide_blocks(once) == once, html


def test_prose_can_break_an_unbreakable_word():
    """A bare URL is one word with no break opportunity. Without this the page
    itself scrolls horizontally on a phone — measured at 827px against a 390px
    viewport — and no container overflow can contain it, because the overflow is
    in the text flow.

    `anywhere`, not `break-word`: only `anywhere` also reduces the element's
    min-content width, which is what actually stops the page widening."""
    css = render_site.WEB_CHROME_CSS
    assert "overflow-wrap: anywhere" in css
    rule = [l for l in css.splitlines() if "overflow-wrap: anywhere" in l][0]
    for sel in ("a", "p", "li", "td", "th"):
        selectors = [s.strip() for s in rule.split("{")[0].split(",")]
        assert sel in selectors, f"{sel} not covered: {rule}"


# --------------------------------------------------------------------------
# Pandoc's <colgroup> percentages are a markdown-formatting artifact, and on
# screen they override the stylesheet (inline styles win) to force every pipe
# table to full window width in a ratio nobody chose.
# --------------------------------------------------------------------------

COLGROUP_TABLE = (
    "<table>\n<colgroup>\n"
    '<col style="width: 12%" />\n<col style="width: 88%" />\n'
    "</colgroup>\n<tbody><tr><td>a</td><td>b</td></tr></tbody>\n</table>"
)


def test_colgroup_is_stripped_for_screen():
    out = render_site._strip_pandoc_colgroups(COLGROUP_TABLE)
    assert "colgroup" not in out
    assert "width: 88%" not in out, "inline col widths beat the stylesheet"
    assert "<td>a</td>" in out, "only the colgroup goes; the table survives"


def test_colgroup_strip_handles_several_tables():
    out = render_site._strip_pandoc_colgroups(COLGROUP_TABLE + "<p>x</p>" + COLGROUP_TABLE)
    assert "colgroup" not in out
    assert out.count("<table>") == 2
    assert "<p>x</p>" in out, "the greedy-match trap: everything between two tables"


def test_colgroup_strip_is_web_only():
    """The PDF keeps it. A fixed page is exactly where a full-width table is
    right, and style.css is built around pandoc's markup."""
    src = inspect.getsource(render_pdf.render_html)
    assert "_strip_pandoc_colgroups" not in src
    assert "_strip_pandoc_colgroups" in inspect.getsource(render_site.render_web_html)


def test_inline_table_width_is_stripped():
    """Pandoc's other width hint, on the element: <table style="width:100%;">."""
    out = render_site._strip_pandoc_colgroups('<table style="width:100%;">\n<tr><td>a</td></tr></table>')
    assert "width" not in out, "inline width beats the stylesheet, so it must go"
    assert out.startswith("<table>"), "an emptied style attribute is removed, not left blank"


def test_inline_strip_keeps_other_declarations():
    """Only width goes. A table carrying anything else keeps it."""
    out = render_site._strip_pandoc_colgroups(
        '<table style="width:100%; background:#eee">\n<tr><td>a</td></tr></table>')
    assert "background:#eee" in out
    assert "width" not in out


def test_inline_strip_leaves_other_elements_alone():
    """The pattern is anchored to <table>; a styled cell or div is untouched."""
    html = '<div style="width:100%"><table><td style="width:50%">a</td></table></div>'
    assert render_site._strip_pandoc_colgroups(html) == html


def test_inline_strip_handles_single_quotes():
    """A rule that applies to one quote style and not the other is a difference
    nobody finds on purpose."""
    out = render_site._strip_pandoc_colgroups("<table style='width:100%;'><tr><td>a</td></tr></table>")
    assert "width" not in out
    assert out.startswith("<table>")


def test_inline_strip_keeps_a_deliberate_max_width():
    """`min-width` / `max-width` are how a guide CONSTRAINS a table — the opposite
    of pandoc's fill hint. Stripping them would overrule the guide."""
    out = render_site._strip_pandoc_colgroups(
        '<table style="width:100%; max-width:34rem"><tr><td>a</td></tr></table>')
    assert "max-width:34rem" in out
    assert "width:100%" not in out


def test_strip_runs_before_the_guide_transform():
    """Cleanup of pandoc's output belongs next to pandoc. Running it last erased
    whatever the guide's own transform had deliberately put on a table."""
    src = inspect.getsource(render_site.render_web_html)
    strip_at = src.index("_strip_pandoc_colgroups")
    apply_at = src.index("_apply_transforms")
    assert apply_at < strip_at, (
        "the strip must be the INNER call — _apply_transforms(_strip(...)), "
        "so the guide transform sees cleaned markup and has the last word"
    )


class TestStarterStylesheet:
    """The starter must agree with the layout the kit's chrome assumes.

    This drifted once and nothing caught it: every shipped guide moved to a fluid
    body with a per-element prose measure, while `style-screen.css.example` kept
    a centred 46rem body and `table { width: 100% }`. The seven live guides were
    fine — the file is target-owned, so they had already replaced it — and a
    newly bootstrapped guide would have been the only one to get the old layout.
    """

    @staticmethod
    def _sheet() -> str:
        from pathlib import Path
        return _rules_only((Path(buildcore.__file__).parent / "style-screen.css.example").read_text())

    def test_body_is_not_a_fixed_column(self):
        body = re.search(r"(?:^|\})\s*body\s*\{([^}]*)\}", self._sheet(), re.M)
        assert body, "no top-level body rule"
        assert "max-width: none" in body.group(1), (
            "a capped body puts tables, diagrams and video inside a text measure "
            "and strands the content beside the sidebar"
        )

    def test_tables_size_to_their_content(self):
        m = re.search(r"(?:^|\})\s*table\s*\{([^}]*)\}", self._sheet(), re.M)
        assert m, "no top-level table rule"
        # Match the DECLARATION, not the substring: `max-width: 100%` contains
        # the characters "width: 100%", so a plain `not in` check fails on the
        # correct sheet and would have to be deleted to make the suite pass.
        decls = dict(
            (k.strip().lower(), v.strip())
            for k, _, v in (d.partition(":") for d in m.group(1).split(";")) if v
        )
        assert decls.get("width") == "auto", decls
        assert decls.get("max-width") == "100%", decls

    def test_the_measure_is_on_the_text_not_the_container(self):
        assert re.search(r"max-width:\s*var\(--max-width\)", self._sheet()), (
            "the prose measure must be applied per element once body is fluid"
        )
