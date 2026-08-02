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


class TestTheDeckIsAskedItsOwnQuestions:
    """`--smoke` used to ignore `--artifact` — it resolved `<slug>.pdf` whatever
    it was asked for, so `--smoke --artifact slides` printed `PASS smoke:
    <slug>.pdf` and the deck was committed, pushed and published having never
    been inspected. `baseline.yml` refreshes every artifact's reference and then
    ran one `make smoke`, in a step whose own comment calls it "the only
    inspection left".

    Making it honour `--artifact` immediately showed why nobody had noticed: the
    deck FAILS the guide's assertions, correctly and uselessly. Nothing is
    projected into a deck unless it is wrapped in a `::: slide` fence, so a
    perfectly good deck may never name the guide. A check that always reports the
    same non-defect is the other way a check stops meaning anything.
    """

    DECK = (
        "What this template gives you\n"
        "One Markdown source, three outputs\n"
        "2026-07-27 · f71bbcce9299\n"
    )

    def test_the_deck_is_not_asked_for_the_guides_title(self):
        assert verify_artifacts.smoke_failures(
            self.DECK, pages=2, title=TITLE, artifact="slides") == []
        # ...and the guide still is, or the exemption would be global.
        assert verify_artifacts.smoke_failures(
            self.DECK, pages=2, title=TITLE, artifact="pdf") != []

    def test_a_one_slide_deck_is_a_deck(self):
        """MIN_PAGES is 2 because a one-page GUIDE means the body was dropped.
        A one-slide deck is a deck."""
        assert verify_artifacts.smoke_failures(
            self.DECK, pages=1, title=TITLE, artifact="slides") == []
        assert any("did not render" in f for f in verify_artifacts.smoke_failures(
            self.DECK, pages=1, title=TITLE, artifact="pdf"))

    def test_a_deck_with_no_stamp_is_caught(self):
        """The measured failure, not a symmetry. The obvious full-bleed
        `@page { margin: 0 }` makes WeasyPrint drop every `@bottom-*` margin box,
        which produced a deck carrying no stamp at all — and a file that does not
        say what built it is one `verify --staleness` must refuse. The 6mm bottom
        margin exists for this; nothing noticed when it did not."""
        stampless = "What this template gives you\nOne Markdown source\n"
        failures = verify_artifacts.smoke_failures(
            stampless, pages=2, title=TITLE, artifact="slides")
        assert any("no version stamp" in f for f in failures), failures


class TestSmokeHonoursTheArtifactSelector:
    """The routing, asserted separately from the assertions.

    `smoke_check` is stubbed so this is about WHICH files get inspected, not
    about what inspecting them concludes — the defect was that `--artifact` chose
    nothing at all.
    """

    TOML = (
        'TITLE = "Probe"\nOUTPUT_SLUG = "probe-guide"\nAUTHOR = "A"\n'
        'DESCRIPTION = "d"\nKEYWORDS = "k"\nCOPYRIGHT_YEAR = 2026\n'
        '[outputs]\npdf = true\nsite = "single"\nslides = true\n'
        '[artifacts.pdf]\ndate = "2026-07-26"\n'
        '[artifacts.site]\ndate = "2026-07-26"\n'
        '[artifacts.slides]\ndate = "2026-07-26"\n'
    )

    def _root(self, tmp_path, *, references=True):
        root = tmp_path / "guide"
        root.mkdir()
        (root / "guide.toml").write_text(self.TOML, encoding="utf-8")
        if references:
            (root / "probe-guide.pdf").write_bytes(b"%PDF-1.7\n")
            (root / "probe-guide-slides.pdf").write_bytes(b"%PDF-1.7\n")
        return root

    def _seen(self, monkeypatch):
        seen = []
        monkeypatch.setattr(verify_artifacts, "smoke_check",
                            lambda pdf, root, artifact="pdf": seen.append(
                                (artifact, pdf.name)) or 0)
        return seen

    def test_all_inspects_every_reference_the_guide_has(self, tmp_path, monkeypatch):
        seen = self._seen(monkeypatch)
        root = self._root(tmp_path)
        assert verify_artifacts.smoke_check_all(root, "all") == 0
        assert seen == [("pdf", "probe-guide.pdf"),
                        ("slides", "probe-guide-slides.pdf")]

    def test_the_selector_selects(self, tmp_path, monkeypatch):
        """`--smoke --artifact slides` printed `PASS smoke: <slug>.pdf`. The
        deck was never the file being read."""
        seen = self._seen(monkeypatch)
        root = self._root(tmp_path)
        assert verify_artifacts.smoke_check_all(root, "slides") == 0
        assert seen == [("slides", "probe-guide-slides.pdf")]

    def test_the_site_has_no_reference_to_inspect(self, tmp_path, monkeypatch):
        """A site is deployed rather than blessed into the repo, so there are no
        committed bytes to smoke — reported, not silently skipped."""
        seen = self._seen(monkeypatch)
        root = self._root(tmp_path)
        assert verify_artifacts.smoke_check_all(root, "site") == 0
        assert seen == []

    def test_a_never_released_guide_passes_with_a_notice(self, tmp_path,
                                                         monkeypatch, capsys):
        """`make smoke` used to exit 2 with `<slug>.pdf does not exist` on a
        fresh fork, while `make verify` handled the identical state with a
        pre-first-release notice — and it is listed in the build block a new fork
        reads, so it was the one command there that could not succeed."""
        monkeypatch.setattr(verify_artifacts, "_was_ever_released",
                            lambda root, ref: False)
        root = self._root(tmp_path, references=False)
        assert verify_artifacts.smoke_check_all(root, "all") == 0
        assert "pre-first-release" in capsys.readouterr().out

    def test_a_deliverable_that_was_released_and_vanished_still_fails(
            self, tmp_path, monkeypatch):
        """The discriminator is git history, exactly as staleness uses it — or
        "pre-first-release" would launder a deleted deliverable."""
        monkeypatch.setattr(verify_artifacts, "_was_ever_released",
                            lambda root, ref: True)
        root = self._root(tmp_path, references=False)
        assert verify_artifacts.smoke_check_all(root, "all") == 1
