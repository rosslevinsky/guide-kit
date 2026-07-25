"""Tests for the rendered-PDF smoke check (`make smoke`).

The assertions live in `verify_pdf.smoke_failures`, a pure function over
already-extracted text, so every one of them can be shown to FAIL on the defect
it exists to catch. That matters here more than usual: this check was added
*because* a whole class of defect shipped past green gates, and a new check
whose failure path has never been exercised is not evidence of anything.

The headline case is the footer wrap (defect 8 in the family record): the page
footer wrapped on every page of three shipped guides, splitting the version
stamp at its middle dot and orphaning the hash. Every automated gate was green.
"""
from __future__ import annotations

import verify_pdf

TITLE = "A Beginner's Guide to the Thing"

# A minimal two-page extraction that should pass everything.
GOOD = (
    f"{TITLE}\n"
    "Some body text on page one.\n"
    f"{TITLE} · 2026-07-25 03:00:00 · abc123def456\n"
    "\f"
    "More body text on page two.\n"
    f"{TITLE} · 2026-07-25 03:00:00 · abc123def456\n"
)


def _fail_text(failures: list[str]) -> str:
    return " | ".join(failures)


class TestPasses:
    def test_a_healthy_render_has_no_failures(self):
        assert verify_pdf.smoke_failures(GOOD, pages=2, title=TITLE) == []

    def test_title_wrapped_across_lines_still_counts_as_present(self):
        # The rendered title-block legitimately wraps on a narrow page; the check
        # collapses whitespace so that is not mistaken for a missing title.
        text = GOOD.replace(TITLE, "A Beginner's Guide\nto the Thing", 1)
        assert verify_pdf.smoke_failures(text, pages=2, title=TITLE) == []

    def test_hash_shaped_text_in_the_body_is_not_treated_as_a_stamp(self):
        # A `· <12 hex>` fragment in the body with no date prefix must not be
        # read as a footer stamp, wrapped or otherwise.
        text = GOOD.replace(
            "Some body text on page one.",
            "Example output: · 0123456789ab",
        )
        assert verify_pdf.smoke_failures(text, pages=2, title=TITLE) == []


class TestFooterWrap:
    """Defect 8. The stamp splits at its middle dot; the hash is orphaned."""

    def test_stamp_split_after_the_separator_is_caught(self):
        text = GOOD.replace(
            f"{TITLE} · 2026-07-25 03:00:00 · abc123def456",
            f"{TITLE} · 2026-07-25 03:00:00 ·\nabc123def456",
        )
        failures = verify_pdf.smoke_failures(text, pages=2, title=TITLE)
        assert any("split across lines" in f for f in failures), _fail_text(failures)

    def test_stamp_split_before_the_separator_is_caught(self):
        text = GOOD.replace(
            f"{TITLE} · 2026-07-25 03:00:00 · abc123def456",
            f"{TITLE} · 2026-07-25 03:00:00\n· abc123def456",
        )
        failures = verify_pdf.smoke_failures(text, pages=2, title=TITLE)
        assert any("split across lines" in f for f in failures), _fail_text(failures)

    def test_the_report_counts_every_wrapped_page(self):
        # The real defect wrapped on EVERY page, so the count is the signal that
        # it is systemic rather than one unlucky page.
        text = GOOD.replace(
            "2026-07-25 03:00:00 · abc123def456",
            "2026-07-25 03:00:00 ·\nabc123def456",
        )
        failures = verify_pdf.smoke_failures(text, pages=2, title=TITLE)
        assert any("on 2 line(s)" in f for f in failures), _fail_text(failures)

    def test_whole_text_regex_alone_would_miss_it(self):
        """Guards the reason this is per-line rather than a whole-text search.

        _STAMP_RE has `\\s*` around its separators so staleness can still read
        the hash out of a wrapped footer. That tolerance means searching the full
        text MATCHES a wrapped stamp — so a naive implementation would report no
        wrap. If this assertion ever fails, _STAMP_RE changed and the per-line
        detection may no longer be necessary (or may be broken)."""
        wrapped = "2026-07-25 03:00:00 ·\nabc123def456"
        assert verify_pdf._STAMP_RE.search(wrapped) is not None


class TestOtherFailures:
    def test_single_page_render_is_caught(self):
        failures = verify_pdf.smoke_failures(GOOD, pages=1, title=TITLE)
        assert any("did not render" in f for f in failures), _fail_text(failures)

    def test_blank_page_is_caught(self):
        text = GOOD + "\f" + "   \n  \n"
        failures = verify_pdf.smoke_failures(text, pages=3, title=TITLE)
        assert any("no extractable text" in f for f in failures), _fail_text(failures)

    def test_missing_title_is_caught(self):
        failures = verify_pdf.smoke_failures(
            GOOD.replace(TITLE, "Some Other Document"), pages=2, title=TITLE
        )
        assert any("title" in f for f in failures), _fail_text(failures)

    def test_every_declared_placeholder_is_caught(self):
        # Parameterised over the real list rather than a sample, so adding a
        # placeholder without a working detector cannot pass silently.
        for marker in verify_pdf._PLACEHOLDERS:
            text = GOOD.replace("Some body text on page one.", f"Intro {marker} here")
            failures = verify_pdf.smoke_failures(text, pages=2, title=TITLE)
            assert any(marker in f for f in failures), f"{marker} not caught"

    def test_failures_accumulate_rather_than_short_circuiting(self):
        # One run should report everything wrong with a render, so an operator
        # fixes it in one pass instead of rediscovering the next problem.
        text = "Nothing useful here.\n2026-07-25 03:00:00 ·\nabc123def456\n"
        failures = verify_pdf.smoke_failures(text, pages=1, title=TITLE)
        assert len(failures) >= 3, _fail_text(failures)
