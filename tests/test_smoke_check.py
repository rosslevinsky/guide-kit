"""Tests for the rendered-PDF smoke check (`make smoke`).

The assertions live in `verify_artifacts.smoke_failures`, a pure function over
already-extracted text, so every one of them can be shown to FAIL on the defect
it exists to catch. That matters here more than usual: this check was added
*because* a whole class of defect shipped past green gates, and a new check
whose failure path has never been exercised is not evidence of anything.

The headline case is the footer wrap (defect 8 in the family record): the page
footer wrapped on every page of three shipped guides, splitting the version
stamp at its middle dot and orphaning the hash. Every automated gate was green.
"""
from __future__ import annotations

import verify_artifacts

TITLE = "A Beginner's Guide to the Thing"

# A minimal two-page extraction that should pass everything.
GOOD = (
    f"{TITLE}\n"
    "Some body text on page one.\n"
    f"{TITLE} · 2026-07-25 · abc123def456\n"
    "\f"
    "More body text on page two.\n"
    f"{TITLE} · 2026-07-25 · abc123def456\n"
)


def _fail_text(failures: list[str]) -> str:
    return " | ".join(failures)


class TestPasses:
    def test_a_healthy_render_has_no_failures(self):
        assert verify_artifacts.smoke_failures(GOOD, pages=2, title=TITLE) == []

    def test_title_wrapped_across_lines_still_counts_as_present(self):
        # The rendered title-block legitimately wraps on a narrow page; the check
        # collapses whitespace so that is not mistaken for a missing title.
        text = GOOD.replace(TITLE, "A Beginner's Guide\nto the Thing", 1)
        assert verify_artifacts.smoke_failures(text, pages=2, title=TITLE) == []

    def test_hash_shaped_text_in_the_body_is_not_treated_as_a_stamp(self):
        # A `· <12 hex>` fragment in the body with no date prefix must not be
        # read as a footer stamp, wrapped or otherwise.
        text = GOOD.replace(
            "Some body text on page one.",
            "Example output: · 0123456789ab",
        )
        assert verify_artifacts.smoke_failures(text, pages=2, title=TITLE) == []


class TestFooterWrapMovedButIsStillWired:
    """Defect 8's detector is now GEOMETRIC and lives in
    `verify_artifacts.footer_wrap_failures`, not in `smoke_failures`.

    It had to move. The old check flagged any extracted line carrying the
    stamp's date-time without the whole stamp, which only worked because the old
    grammar embedded a time — a shape prose never contains. The grammar is now
    date-only, so a bare ISO date in a table or a fenced code block would have
    tripped it on documents that render perfectly.

    Its behaviour — both halves of a split footer in either order, and the ISO
    dates at the bottom margin that must NOT fire — is covered in
    tests/test_version_stamp_grammar.py against real rendered PDFs. What is
    asserted here is only that `smoke_check` still RUNS it, so the capability
    cannot be lost by the move."""

    def test_smoke_failures_no_longer_owns_wrap_detection(self):
        # Text alone cannot answer the question any more; asserting this stops a
        # future edit from quietly reinstating a text-only scan beside the
        # geometric one.
        wrapped_text = f"{TITLE}\n2026-07-25 ·\nabc123def456\n"
        assert not any(
            "split across lines" in f
            for f in verify_artifacts.smoke_failures(wrapped_text, pages=2, title=TITLE)
        )

    def test_smoke_check_merges_the_geometric_detector(self):
        import inspect
        src = inspect.getsource(verify_artifacts.smoke_check)
        assert "footer_wrap_failures" in src, (
            "smoke_check no longer runs the footer-wrap detector — defect 8 would "
            "ship again unnoticed"
        )


class TestOtherFailures:
    def test_single_page_render_is_caught(self):
        failures = verify_artifacts.smoke_failures(GOOD, pages=1, title=TITLE)
        assert any("did not render" in f for f in failures), _fail_text(failures)

    def test_blank_page_is_caught(self):
        text = GOOD + "\f" + "   \n  \n"
        failures = verify_artifacts.smoke_failures(text, pages=3, title=TITLE)
        assert any("no extractable text" in f for f in failures), _fail_text(failures)

    def test_missing_title_is_caught(self):
        failures = verify_artifacts.smoke_failures(
            GOOD.replace(TITLE, "Some Other Document"), pages=2, title=TITLE
        )
        assert any("title" in f for f in failures), _fail_text(failures)

    def test_every_declared_placeholder_is_caught(self):
        # Parameterised over the real list rather than a sample, so adding a
        # placeholder without a working detector cannot pass silently.
        for marker in verify_artifacts._PLACEHOLDERS:
            text = GOOD.replace("Some body text on page one.", f"Intro {marker} here")
            failures = verify_artifacts.smoke_failures(text, pages=2, title=TITLE)
            assert any(marker in f for f in failures), f"{marker} not caught"

    def test_failures_accumulate_rather_than_short_circuiting(self):
        # One run should report everything wrong with a render, so an operator
        # fixes it in one pass instead of rediscovering the next problem.
        # Missing title, a single page, AND an unsubstituted placeholder. (The
        # footer wrap used to be the third failure here; it is geometric now and
        # is not answerable from text.)
        text = "Nothing useful here.\n{{GUIDE_NAME}}\n"
        failures = verify_artifacts.smoke_failures(text, pages=1, title=TITLE)
        assert len(failures) >= 3, _fail_text(failures)
