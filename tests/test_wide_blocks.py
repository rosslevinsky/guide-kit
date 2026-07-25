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

import build

WRAP_OPEN = '<div class="wide-block" tabindex="0" role="region">'


def test_a_single_table_is_wrapped():
    out = build._wrap_wide_blocks("<p>x</p><table><tr><td>a</td></tr></table><p>y</p>")
    assert out == f"<p>x</p>{WRAP_OPEN}<table><tr><td>a</td></tr></table></div><p>y</p>"


def test_every_table_is_wrapped_and_balanced():
    html = "".join(f"<table><tr><td>{i}</td></tr></table>" for i in range(5))
    out = build._wrap_wide_blocks(html)
    assert out.count(WRAP_OPEN) == 5
    assert out.count("</table></div>") == 5
    # No stray wrappers and no stray closers.
    assert out.count('<div class="wide-block"') == out.count("</div>")


def test_a_table_with_attributes_is_still_wrapped():
    # pandoc emits attributes on <table> in some configurations; a naive
    # `"<table>"` literal match would silently skip those and leave them
    # constrained, which is the failure that looks like "it just didn't work".
    out = build._wrap_wide_blocks('<table class="journal" id="je-1"><tr><td>a</td></tr></table>')
    assert out.startswith(WRAP_OPEN)
    assert '<table class="journal" id="je-1">' in out
    assert out.endswith("</table></div>")


def test_no_tables_is_a_no_op():
    html = "<p>Nothing to see</p><pre>code</pre>"
    assert build._wrap_wide_blocks(html) == html


def test_pre_is_not_wrapped():
    """`pre` is deliberately excluded.

    Code already scrolls inside the prose measure, the widest code line in the
    family is 90 characters, and pulling code blocks out of the text column would
    break the read-along flow the guides depend on. If someone later wraps `pre`
    too, this should fail and make them argue for it.
    """
    out = build._wrap_wide_blocks("<pre><code>x</code></pre>")
    assert "wide-block" not in out


def test_tables_are_not_double_wrapped():
    once = build._wrap_wide_blocks("<table><tr><td>a</td></tr></table>")
    twice = build._wrap_wide_blocks(once)
    assert twice.count(WRAP_OPEN) == 1, "wrapping is not idempotent — a second pass nests it"


def test_wrapper_is_keyboard_reachable():
    """A horizontally scrolling region is unreachable by keyboard without a
    tabindex, which would make wide tables mouse-only."""
    out = build._wrap_wide_blocks("<table><tr><td>a</td></tr></table>")
    assert 'tabindex="0"' in out
    assert 'role="region"' in out


class TestChromeCss:
    def test_breakout_rules_are_emitted(self):
        css = build.WEB_CHROME_CSS
        assert ".wide-block" in css
        assert "--wide-width" in css

    def test_breakout_is_viewport_capped(self):
        """The width must be capped against the VIEWPORT, not only a rem value.

        A fixed-rem breakout wider than a narrow viewport is the classic cause of
        whole-page horizontal scrolling. Measured zero overflow from 320px to
        1600px; this pins the mechanism that achieves it.
        """
        assert "100vw" in build.WEB_CHROME_CSS

    def test_breakout_is_neutralised_in_print(self):
        css = build.WEB_CHROME_CSS
        print_block = css[css.index("@media print"):]
        assert ".wide-block" in print_block, "a translated viewport-sized box paginates badly"

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
        assert not re.search(r"(^|[\s,{}])body\s*(,|\{)", build.WEB_CHROME_CSS), \
            "chrome CSS must not restyle body; the prose measure is per-guide"
