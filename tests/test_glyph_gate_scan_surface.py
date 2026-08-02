"""What `check_glyph_coverage()` actually scans.

WHY THIS EXISTS. The gate's value is entirely in its recall: a codepoint it
misses renders through a host font (or as tofu) while the build stays green and
`make verify` stays green, because the SOURCE genuinely did not change. Every
false negative is therefore a silent breach of the one property bundling fonts
was bought to provide.

The gate scans guide.md's raw bytes rather than the rendered text, on the
argument that Markdown and inline-HTML syntax is all ASCII so the raw file is a
superset of what renders. That argument has one hole: an HTML character
reference is pure ASCII in source and a non-ASCII codepoint on the page.
`&#x1F9D1;` scans as `&`, `#`, `x`, digits and `;` — all covered — and renders
as U+1F9D1, which no bundled face has.

Decoding it is not as simple as `html.unescape()`, and the last two tests pin
why: that function applies the HTML5 parser's invalid-codepoint rules and
returns '' for a noncharacter (so `&#xFDD0;` would vanish from the scan while
pandoc renders it — a false negative in the exotic corner where coverage is
least likely), and it turns `&#10;` into a real newline, which would shift every
later line number in the diagnostic.

These tests pin the decoded scan, and pin that the strings `buildcore.py` injects
into the page (title, author, copyright, and the footer's separator) are scanned
too — they are not in guide.md but they are just as rendered.
"""
import pytest

import buildcore


def _covered_stub(monkeypatch, covered):
    monkeypatch.setattr(buildcore, "_covered_codepoints", lambda: set(covered))
    monkeypatch.setattr(buildcore, "_bundled_font_files", lambda: [])


ASCII = set(range(0x20, 0x7F))
# The real bundled faces all cover the stamp separator, so a stub that models
# them must too. Only the separator test itself withholds it.
ASCII_PLUS_SEP = ASCII | {0x00B7}


def test_numeric_character_reference_is_decoded_before_scanning(tmp_path, monkeypatch):
    """The documented hole: all-ASCII source, non-ASCII render."""
    src = tmp_path / "guide.md"
    src.write_text("A cook &#x1F9D1; appears.\n", encoding="utf-8")
    monkeypatch.setattr(buildcore, "SRC", src)
    monkeypatch.setattr(buildcore, "TITLE", "T")
    monkeypatch.setattr(buildcore, "AUTHOR", "A")
    monkeypatch.setattr(buildcore, "COPYRIGHT", "C")
    _covered_stub(monkeypatch, ASCII_PLUS_SEP)

    with pytest.raises(SystemExit) as exc:
        buildcore.check_glyph_coverage()
    assert "U+1F9D1" in str(exc.value)


def test_named_character_reference_is_decoded_before_scanning(tmp_path, monkeypatch):
    src = tmp_path / "guide.md"
    src.write_text("Angle &alefsym; here.\n", encoding="utf-8")
    monkeypatch.setattr(buildcore, "SRC", src)
    monkeypatch.setattr(buildcore, "TITLE", "T")
    monkeypatch.setattr(buildcore, "AUTHOR", "A")
    monkeypatch.setattr(buildcore, "COPYRIGHT", "C")
    _covered_stub(monkeypatch, ASCII_PLUS_SEP)

    with pytest.raises(SystemExit) as exc:
        buildcore.check_glyph_coverage()
    assert "U+2135" in str(exc.value)


def test_nbsp_entity_does_not_trip_the_gate(tmp_path, monkeypatch):
    """Decoding must not manufacture failures. `&nbsp;` is used throughout the
    family for table-cell indents; it decodes to U+00A0, which is
    non-rendering, so it must stay silent."""
    src = tmp_path / "guide.md"
    src.write_text("| &nbsp;&nbsp;Cash | 267,000 |\n", encoding="utf-8")
    monkeypatch.setattr(buildcore, "SRC", src)
    monkeypatch.setattr(buildcore, "TITLE", "T")
    monkeypatch.setattr(buildcore, "AUTHOR", "A")
    monkeypatch.setattr(buildcore, "COPYRIGHT", "C")
    _covered_stub(monkeypatch, ASCII_PLUS_SEP)

    buildcore.check_glyph_coverage()  # must not raise


def test_injected_footer_separator_is_scanned(tmp_path, monkeypatch):
    """The version stamp's `·` is written by `buildcore.py`, not by guide.md. It
    reaches the page, so it belongs in the scan."""
    src = tmp_path / "guide.md"
    src.write_text("plain ascii only\n", encoding="utf-8")
    monkeypatch.setattr(buildcore, "SRC", src)
    monkeypatch.setattr(buildcore, "TITLE", "T")
    monkeypatch.setattr(buildcore, "AUTHOR", "A")
    monkeypatch.setattr(buildcore, "COPYRIGHT", "C")
    _covered_stub(monkeypatch, ASCII)

    with pytest.raises(SystemExit) as exc:
        buildcore.check_glyph_coverage()
    assert "U+00B7" in str(exc.value)


def test_noncharacter_reference_survives_decoding(tmp_path, monkeypatch):
    """`html.unescape()` returns '' here; pandoc renders U+FDD0. The gate must
    see what pandoc renders, or it goes quiet on exactly the codepoints the
    bundled faces are least likely to cover."""
    src = tmp_path / "guide.md"
    src.write_text("edge &#xFDD0; case\n", encoding="utf-8")
    monkeypatch.setattr(buildcore, "SRC", src)
    monkeypatch.setattr(buildcore, "TITLE", "T")
    monkeypatch.setattr(buildcore, "AUTHOR", "A")
    monkeypatch.setattr(buildcore, "COPYRIGHT", "C")
    _covered_stub(monkeypatch, ASCII_PLUS_SEP)

    with pytest.raises(SystemExit) as exc:
        buildcore.check_glyph_coverage()
    assert "U+FDD0" in str(exc.value)


def test_newline_reference_does_not_shift_reported_line_numbers(tmp_path, monkeypatch):
    """`&#10;` decodes to a newline. Left as one, every later line number in the
    diagnostic is wrong — the gate would name the wrong line for a real gap."""
    src = tmp_path / "guide.md"
    src.write_text("first &#10; line\nsecond line\nthird \u2603 line\n", encoding="utf-8")
    monkeypatch.setattr(buildcore, "SRC", src)
    monkeypatch.setattr(buildcore, "TITLE", "T")
    monkeypatch.setattr(buildcore, "AUTHOR", "A")
    monkeypatch.setattr(buildcore, "COPYRIGHT", "C")
    _covered_stub(monkeypatch, ASCII_PLUS_SEP)

    with pytest.raises(SystemExit) as exc:
        buildcore.check_glyph_coverage()
    # The snowman is on source line 3 and must be reported as line 3.
    assert "guide.md:3" in str(exc.value), str(exc.value)


def test_unknown_reference_is_left_literal(tmp_path, monkeypatch):
    """An unrecognised reference renders as its own ASCII text, so scanning the
    literal is correct — and must not raise."""
    src = tmp_path / "guide.md"
    src.write_text("see &notaref; here\n", encoding="utf-8")
    monkeypatch.setattr(buildcore, "SRC", src)
    monkeypatch.setattr(buildcore, "TITLE", "T")
    monkeypatch.setattr(buildcore, "AUTHOR", "A")
    monkeypatch.setattr(buildcore, "COPYRIGHT", "C")
    _covered_stub(monkeypatch, ASCII_PLUS_SEP)

    buildcore.check_glyph_coverage()  # must not raise
