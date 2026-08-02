"""One stamp grammar, and all three of its consumers moving together.

`YYYY-MM-DD · <sha256[:12]>` (+ ` · dirty`). The composer, `strip_stamp` (which
keeps the render canary green) and the footer-wrap detector previously existed as
an f-string in the renderer and two regexes in the verifier — three spellings of
one contract, free to drift. They now share a single definition in `kitconfig`,
and this file pins the contract from all three directions.

The footer-wrap tests matter most. The grammar lost its time component when the
date moved to the authored edition date, so a bare ISO date — which occurs in
real guide prose, tables and code — is no longer a shape that only the footer
has. The detector is therefore geometric: confined to the footer band computed
from each page's own dimensions, and keyed on the stamp's SEPARATOR rather than
on a date being present at all.
"""
import subprocess
from pathlib import Path

import pytest
from weasyprint import HTML

import kitconfig
import verify_artifacts


# ----- The grammar itself ---------------------------------------------------

def test_compose_and_parse_round_trip():
    text = kitconfig.format_stamp("2026-07-26", "0123456789ab")
    assert text == "2026-07-26 · 0123456789ab"
    s = kitconfig.parse_stamp(text)
    assert (s.date, s.hash, s.dirty) == ("2026-07-26", "0123456789ab", False)


def test_dirty_composes_explicitly_and_parses_structurally():
    text = kitconfig.format_stamp("2026-07-26", "0123456789ab", dirty=True)
    assert text == "2026-07-26 · 0123456789ab · dirty"
    s = kitconfig.parse_stamp(text)
    assert s.dirty is True and s.hash == "0123456789ab"


@pytest.mark.parametrize("text", [
    "",
    "no stamp here",
    "0123456789ab",                       # hash with no date
    "2026-07-26",                         # date with no hash
    "2026-07-26 · zzzzzzzzzzzz",          # not hex
    "2026-07-26 · 0123456789",            # too short
    "2026-07-26 14:03:11 · 0123456789ab",  # the OLD grammar, deliberately rejected
])
def test_unparseable_inputs_return_none(text):
    assert kitconfig.parse_stamp(text) is None


def test_an_unknown_suffix_is_REJECTED_not_read_as_clean():
    # The point of a structured parse. Read permissively, `· stale` parses as a
    # clean stamp with dirty=False and promotion approves an artifact wearing a
    # segment the grammar does not model. It must fail to parse instead.
    assert kitconfig.parse_stamp("2026-07-26 · 0123456789ab · stale") is None
    # `· dirty` is the ONLY modelled suffix, and it still parses.
    assert kitconfig.parse_stamp("2026-07-26 · 0123456789ab · dirty").dirty is True
    # Trailing text that is not another `· <token>` is ordinary footer content
    # (the running title and page number surround the stamp) and must not break it.
    assert kitconfig.parse_stamp("Guide 2026-07-26 · 0123456789ab Page 1") is not None


def test_strip_stamp_removes_every_occurrence():
    body = f"before {kitconfig.format_stamp('2026-07-26', 'a' * 12)} middle " \
           f"{kitconfig.format_stamp('2026-07-27', 'b' * 12, dirty=True)} after"
    stripped = kitconfig.strip_stamp(body)
    assert "2026-07-26" not in stripped and "2026-07-27" not in stripped
    assert "before" in stripped and "middle" in stripped and "after" in stripped


def test_the_verifier_reads_through_the_single_grammar():
    # Not a second regex: verify_artifacts must resolve the stamp via kitconfig, or the
    # two definitions can drift again.
    src = (verify_artifacts.__file__)
    text = open(src, encoding="utf-8").read()
    assert "kitconfig.parse_stamp" in text
    assert "_STAMP_DATE_RE" not in text, "the retired text-only date scan is still present"


# ----- The geometric footer-wrap detector -----------------------------------

_PAGE_H = 792.0
_BAND_TOP = _PAGE_H * (1.0 - verify_artifacts._FOOTER_BAND_FRACTION)   # 696.96pt


def _render(tmp_path, body_html, name="probe.pdf"):
    """A one-page PDF with absolutely-positioned text, so a test can place a
    line inside or outside the footer band by coordinate."""
    html = (
        "<html><head><style>"
        f"@page {{ size: {_PAGE_H / 72}in {_PAGE_H / 72}in; margin: 0; }}"
        "body { margin: 0; font-family: 'Guide Serif', serif; font-size: 9pt; }"
        "div { position: absolute; left: 54pt; white-space: pre; }"
        "</style></head><body>" + body_html + "</body></html>"
    )
    out = tmp_path / name
    HTML(string=html, base_url=str(tmp_path)).write_pdf(str(out))
    return out


def _at(top_pt, text):
    return f'<div style="top:{top_pt}pt">{text}</div>'


def test_a_complete_stamp_in_the_band_passes(tmp_path):
    pdf = _render(tmp_path, _at(_BAND_TOP + 30, "2026-07-26 · 0123456789ab"))
    assert verify_artifacts.footer_wrap_failures(pdf) == []


@pytest.mark.parametrize("first,second", [
    ("2026-07-26 ·", "0123456789ab"),      # the break falls AFTER the separator
    ("2026-07-26", "· 0123456789ab"),      # ...and BEFORE it
])
def test_a_footer_split_mid_stamp_fails_at_either_break_point(tmp_path, first, second):
    """"Either order" means either side of the separator — the two places a line
    box can actually break a `<date> · <hash>` footer.

    A footer rendering the hash BEFORE the date is not a wrap of this grammar; it
    is a malformed footer, and it is already caught with a truer diagnosis — it
    parses nowhere, so `read_stamp` reports an unreadable stamp and staleness
    fails closed."""
    pdf = _render(tmp_path, _at(_BAND_TOP + 20, first) + _at(_BAND_TOP + 45, second))
    failures = verify_artifacts.footer_wrap_failures(pdf)
    assert failures, "a stamp split across two band lines was not detected"
    assert "split across lines" in failures[0]


@pytest.mark.parametrize("content", [
    "Released on 2026-07-26 in the second edition.",   # prose
    "| version | 2026-07-26 | shipped |",              # a table row
    "    git log --since=2026-07-26 --oneline",        # fenced code
    "2026-07-26  0123456789ab  refs/heads/main",       # a date NEXT TO hash-like text
])
def test_iso_dates_at_the_bottom_margin_do_not_false_positive(tmp_path, content):
    # All of these sit INSIDE the footer band — the case a text-only scan gets
    # wrong. None carries the stamp separator, so none is a wrap.
    pdf = _render(tmp_path, _at(_BAND_TOP + 30, content))
    assert verify_artifacts.footer_wrap_failures(pdf) == []


def test_body_content_reaching_the_bottom_margin_does_not_false_positive(tmp_path):
    pdf = _render(
        tmp_path,
        _at(_BAND_TOP - 40, "Body text that runs right down to the bottom margin.")
        + _at(_BAND_TOP + 10, "2026-07-26 continues here without a separator")
        + _at(_BAND_TOP + 35, "2026-07-26 · 0123456789ab"),
    )
    assert verify_artifacts.footer_wrap_failures(pdf) == []


def test_a_split_stamp_ABOVE_the_band_is_not_a_footer_wrap(tmp_path):
    # The band is what makes the check specific. A `·` and a date in body text
    # high on the page is not the footer wrapping.
    pdf = _render(tmp_path, _at(200, "2026-07-26 ·") + _at(225, "0123456789ab"))
    assert verify_artifacts.footer_wrap_failures(pdf) == []


# ----- The render canary's stamp exclusion ----------------------------------

def test_strip_stamp_makes_two_differently_stamped_renders_compare_equal():
    a = f"Guide\n{kitconfig.format_stamp('2026-07-26', 'a' * 12)}\nPage 1"
    b = f"Guide\n{kitconfig.format_stamp('2027-01-01', 'b' * 12, dirty=True)}\nPage 1"
    assert a != b
    assert kitconfig.strip_stamp(a) == kitconfig.strip_stamp(b)


# ----- baseline.yml's auto-refresh flow must survive the date change ---------
#
# This is the property the edition date most plausibly breaks. `baseline.yml`
# renders and commits a refreshed reference with no human action whenever a
# content push leaves the committed PDF stale. If promotion keyed on the DATE,
# an ordinary content edit would need someone to bump `[artifacts.pdf] date`
# first, and the automatic flow would deadlock — every push stale, every
# baseline refused. Staleness and promotion therefore key on the HASH; the date
# moves only at release.

def test_a_content_change_without_a_date_bump_is_still_promotable(guide_repo):
    from conftest import render
    import verify_artifacts

    root, _ = guide_repo
    render(root)
    (root / "probe-guide.pdf").write_bytes((root / "build" / "probe-guide.pdf").read_bytes())

    # A content edit — the everyday case — and NO change to [artifacts.pdf] date.
    (root / "guide.md").write_text(
        (root / "guide.md").read_text(encoding="utf-8") + "\nAn added paragraph.\n",
        encoding="utf-8",
    )
    render(root)

    ok, msg = verify_artifacts.promotable_stamp(
        root / "build" / "probe-guide.pdf", root, "pdf"
    )
    assert ok, f"the auto-refresh flow would deadlock: {msg}"


def test_the_stale_reference_is_what_makes_it_promotable(guide_repo):
    """The other half: the refreshed render must actually differ from the stale
    committed reference, or 'promotable' would be vacuous."""
    from conftest import render
    import verify_artifacts

    root, _ = guide_repo
    render(root)
    stale = (root / "build" / "probe-guide.pdf").read_bytes()
    (root / "probe-guide.pdf").write_bytes(stale)

    (root / "guide.md").write_text(
        (root / "guide.md").read_text(encoding="utf-8") + "\nAnother paragraph.\n",
        encoding="utf-8",
    )
    render(root)
    fresh = (root / "build" / "probe-guide.pdf").read_bytes()
    assert fresh != stale

    # The committed reference is now stale by hash, which is what triggers the
    # auto-baseline in the first place.
    assert verify_artifacts.staleness_check(root, "pdf") == 1


# ----- Defects found by cross-model review ---------------------------------

def test_an_intact_stamp_in_a_RETIRED_format_is_not_reported_as_a_wrap(tmp_path):
    """The migration path must stay open.

    The committed references carry the old `YYYY-MM-DD HH:MM:SS · hash` footer,
    intact and on one line. Reporting that as a wrap made `--smoke` fail, and CI
    runs smoke BEFORE the staleness check — so the auto-baseline that would
    refresh those very references could never be dispatched."""
    pdf = _render(tmp_path, _at(_BAND_TOP + 30,
                                "Guide Template 2026-07-26 05:33:51 · ae88659f41f3 Page 1"))
    assert verify_artifacts.footer_wrap_failures(pdf) == []
    # ...and it is correctly UNREADABLE rather than silently accepted.
    assert verify_artifacts.read_stamp_from_band(pdf) is None


def test_the_stamp_is_read_from_the_footer_band_not_the_whole_document(tmp_path):
    """A dated example in the BODY must not be mistaken for the footer stamp.

    Date-only grammar makes this reachable: `2026-07-26 · deadbeefcafe` is
    plausible body content, and a whole-document first-match read would return
    it — reporting a healthy reference stale."""
    pdf = _render(
        tmp_path,
        _at(150, "Example output: 2026-07-26 · deadbeefcafe")
        + _at(_BAND_TOP + 30, "Guide 2026-07-26 · 0123456789ab Page 1"),
    )
    stamp = verify_artifacts.read_stamp_from_band(pdf)
    assert stamp is not None
    assert stamp.hash == "0123456789ab", "body content was read as the footer stamp"


def test_a_clean_body_match_cannot_mask_a_dirty_footer(tmp_path):
    pdf = _render(
        tmp_path,
        _at(150, "Example: 2026-07-26 · deadbeefcafe")
        + _at(_BAND_TOP + 30, "Guide 2026-07-26 · 0123456789ab · dirty Page 1"),
    )
    stamp = verify_artifacts.read_stamp_from_band(pdf)
    assert stamp is not None and stamp.dirty is True


def test_the_artifact_spec_states_the_real_date_source():
    # It said "git" while the date came from `git log`; leaving that in place
    # would publish a false contract to anyone reading the spec.
    for name in kitconfig.ARTIFACT_NAMES:
        assert kitconfig.artifact_spec(name).stamp.source_date == "artifact-date"


# ----- Defects found by cross-model RE-review ------------------------------

def test_a_wrap_is_detected_even_with_page_furniture_between_the_halves(tmp_path):
    """The realistic wrap. Footers carry a running title and a page number, so
    the stamp's halves are rarely adjacent once the line breaks. Comparing the
    band's RAW join misses this, because 'Page 1' sits between the separator and
    the hash."""
    pdf = _render(
        tmp_path,
        _at(_BAND_TOP + 20, "Guide Template 2026-07-26 · Page 1")
        + _at(_BAND_TOP + 45, "0123456789ab"),
    )
    failures = verify_artifacts.footer_wrap_failures(pdf)
    assert failures, "a wrap with interleaved page furniture was not detected"


def test_a_legacy_footer_with_page_furniture_is_still_not_a_wrap(tmp_path):
    """The counterpart the fix must not break: the same furniture around an
    INTACT legacy stamp, all on one line."""
    pdf = _render(tmp_path, _at(_BAND_TOP + 30,
                                "Guide Template 2026-07-26 05:33:51 · ae88659f41f3 Page 1"))
    assert verify_artifacts.footer_wrap_failures(pdf) == []


def _fake_pages(monkeypatch, pages):
    """Drive read_stamp_from_band's page aggregation directly.

    The property under test is how MULTIPLE pages' bands combine, not whether
    WeasyPrint can be coaxed into a two-page absolute layout — synthesising the
    word boxes keeps the test about the logic it names."""
    def _pages(_pdf):
        out = []
        for lines in pages:
            words = []
            for i, line in enumerate(lines):
                y = _BAND_TOP + 20 + i * 25
                for j, word in enumerate(line.split()):
                    words.append((y, 54.0 + j * 40, word))
            out.append((_PAGE_H, words))
        return out
    monkeypatch.setattr(verify_artifacts, "_pages_with_boxes", _pages)


def test_a_clean_first_page_cannot_mask_a_dirty_later_page(tmp_path, monkeypatch):
    """The stamp is identical on every page, so a clean page 1 masking a dirty
    page 2 would let promotion approve an unreproducible render."""
    _fake_pages(monkeypatch, [
        ["Guide 2026-07-26 · 0123456789ab Page 1"],
        ["Guide 2026-07-26 · 0123456789ab · dirty Page 2"],
    ])
    stamp = verify_artifacts.read_stamp_from_band(tmp_path / "x.pdf")
    assert stamp is not None and stamp.dirty is True, "a dirty later page was masked"


def test_disagreeing_hashes_across_pages_fail_closed(tmp_path, monkeypatch):
    _fake_pages(monkeypatch, [
        ["Guide 2026-07-26 · 0123456789ab Page 1"],
        ["Guide 2026-07-26 · ffffffffffff Page 2"],
    ])
    assert verify_artifacts.read_stamp_from_band(tmp_path / "x.pdf") is None, (
        "an incoherent document should read as unreadable, not pick a hash"
    )


def test_extract_stamp_hash_reads_the_footer_not_the_body(tmp_path):
    pdf = _render(
        tmp_path,
        _at(150, "Example output: 2026-07-26 · deadbeefcafe")
        + _at(_BAND_TOP + 30, "Guide 2026-07-26 · 0123456789ab Page 1"),
    )
    assert verify_artifacts.extract_stamp_hash(pdf) == "0123456789ab"


def test_more_than_one_unstamped_page_fails_CLOSED(monkeypatch):
    """Absence is treated as seriously as disagreement — it was not.

    `read_stamp_from_band` dropped pages with no readable stamp from its tally,
    so a document that lost its footer on some pages still returned the coherent
    stamp from the rest and read as fresh and promotable. Disagreement failed
    closed; absence did not, and absence is the more likely damage.

    Exactly one bare page is tolerated on purpose: several guides suppress the
    page-1 footer with `@page :first { @bottom-center { content: "" } }`, and
    failing on any gap would refuse every one of them.

    Driven through `_pages_with_boxes` rather than a render: the property under
    test is how pages are TALLIED, and producing a real PDF with a footer on some
    pages and not others would test WeasyPrint's page-selector handling instead.
    """
    # `_pages_with_boxes` yields (height, [(y, x, text), ...]) — VERTICAL first;
    # `_band_lines` compares w[0] to the band top and sorts w[1] left-to-right.
    y = _BAND_TOP + 10.0          # inside the footer band
    stamped = (_PAGE_H, [(y, 54.0, "2026-07-26"), (y, 120.0, "·"),
                         (y, 140.0, "abcdef123456")])
    bare = (_PAGE_H, [(100.0, 54.0, "body text well above the band")])

    def pages(*seq):
        return lambda _pdf: [bare if p == "bare" else stamped for p in seq]

    def resolves(*seq):
        monkeypatch.setattr(verify_artifacts, "_pages_with_boxes", pages(*seq))
        return verify_artifacts.read_stamp_from_band(Path("ignored.pdf"))

    # No bare pages: resolves.
    assert (resolves("s", "s", "s", "s") or None) and resolves("s", "s").hash == "abcdef123456"

    # The suppressed-FIRST-page convention — the only tolerated gap.
    assert resolves("bare", "s", "s", "s").hash == "abcdef123456"

    # THE SAME COUNT, IN THE WRONG PLACE, MUST FAIL. This test asserted the
    # opposite: it built three stamped pages followed by a bare one and called
    # that "the suppressed-first-page convention", so it blessed a PDF that had
    # lost its footer on its LAST page. The implementation counted gaps instead
    # of locating them, and the test agreed with the implementation rather than
    # with the convention both of them named.
    assert resolves("s", "s", "s", "bare") is None
    assert resolves("s", "bare", "s", "s") is None

    # Two or more means the footer is going missing where it was meant to be.
    assert resolves("bare", "bare", "s", "s") is None
