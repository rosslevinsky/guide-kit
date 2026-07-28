"""Han unification: the same codepoint must select a DIFFERENT face per locale.

This is the reason `[fonts] cjk` is an ordered list of locales and not a boolean,
and the reason an ordered list is still not sufficient on its own. Japanese,
Simplified Chinese, Traditional Chinese and Korean share codepoints for a large
part of their character sets, with different correct glyph shapes: U+76F4 is one
codepoint and four different drawings.

A priority list can only pick ONE face for that codepoint. A guide declaring two
locales would therefore render one of them wrong — and wrong in a way that reads
as a font choice rather than as an error, which is what makes it worth a gate.
`:lang()` moves the decision to the text's own annotation, where the answer
actually lives.
"""
import pytest

import buildcore
import kitconfig


def _with_cjk(monkeypatch, *locales):
    fonts = kitconfig.FontsConfig(cjk=tuple(locales))
    monkeypatch.setattr(buildcore, "_cfg",
                        type(buildcore._cfg)(**{**vars(buildcore._cfg), "fonts": fonts}))


def test_no_declared_locales_emits_nothing(monkeypatch):
    _with_cjk(monkeypatch)
    assert buildcore.cjk_css() == ""


def test_each_declared_locale_gets_its_own_lang_rule(monkeypatch):
    _with_cjk(monkeypatch, "jp", "sc")
    css = buildcore.cjk_css()
    assert ":lang(ja)" in css and ":lang(zh-Hans)" in css
    assert "Guide CJK JP" in css and "Guide CJK SC" in css


def test_the_same_codepoint_selects_a_different_family_per_locale(monkeypatch):
    """The property, stated directly: two locales, two selectors, two families.
    An ordered list would produce one family for both."""
    _with_cjk(monkeypatch, "jp", "tc")
    css = buildcore.cjk_css()
    jp = [l for l in css.splitlines() if ":lang(ja)" in l][0]
    tc = [l for l in css.splitlines() if ":lang(zh-Hant)" in l][0]
    assert "Guide CJK JP" in jp and "Guide CJK TC" in tc
    assert jp != tc, "both locales resolved to the same declaration"


def test_declaration_order_is_preserved(monkeypatch):
    """The list is ordered, and the order is the guide's stated preference for
    anything the annotations do not settle."""
    _with_cjk(monkeypatch, "kr", "jp")
    # Filtered on font-family too: the header comment also contains ":lang()".
    lines = [l for l in buildcore.cjk_css().splitlines()
             if ":lang(" in l and "font-family" in l]
    assert ":lang(ko)" in lines[0] and ":lang(ja)" in lines[1]


def test_the_rules_fall_back_to_the_body_token(monkeypatch):
    """A CJK face covers CJK. Latin text inside an annotated element must still
    reach the theme's body family rather than whatever the subset happens to
    carry."""
    _with_cjk(monkeypatch, "jp")
    assert "var(--body-font)" in buildcore.cjk_css()


def test_the_cascade_includes_the_lang_rules(monkeypatch):
    _with_cjk(monkeypatch, "jp")
    css = buildcore.theme_css("print", "/* OVERRIDE */")
    assert ":lang(ja)" in css
    # After the theme and before the guide's own sheet, so a guide can still
    # override the selection it was given.
    assert css.index("theme:") < css.index(":lang(ja)") < css.index("OVERRIDE")


# ----- the annotation requirement --------------------------------------------

_JA = "<p>直</p>"                       # unannotated Han
_ANNOTATED = '<p lang="ja">直</p>'


def test_a_single_locale_needs_no_annotation(monkeypatch):
    """With one locale there is nothing to disambiguate — the document language
    settles it, and demanding annotations would be noise."""
    _with_cjk(monkeypatch, "jp")
    buildcore.check_cjk_annotations(_JA)   # must not raise


def test_two_locales_refuse_unannotated_cjk_text(monkeypatch):
    """Unannotated Han under two locales is a coin flip between two
    correct-looking renders."""
    _with_cjk(monkeypatch, "jp", "sc")
    with pytest.raises(SystemExit, match="outside any lang-annotated element"):
        buildcore.check_cjk_annotations(_JA)


def test_two_locales_accept_annotated_cjk_text(monkeypatch):
    _with_cjk(monkeypatch, "jp", "sc")
    buildcore.check_cjk_annotations(_ANNOTATED)   # must not raise


def test_latin_only_text_is_never_refused(monkeypatch):
    _with_cjk(monkeypatch, "jp", "sc")
    buildcore.check_cjk_annotations("<p>ordinary prose, no Han here</p>")


@pytest.mark.parametrize("sample", ["<p>ひらがな</p>", "<p>カタカナ</p>", "<p>한글</p>"])
def test_kana_and_hangul_count_as_cjk(monkeypatch, sample):
    """Not only unified Han: a guide mixing Japanese and Korean needs the
    annotation for kana and hangul too, or they resolve from the wrong subset."""
    _with_cjk(monkeypatch, "jp", "kr")
    with pytest.raises(SystemExit):
        buildcore.check_cjk_annotations(sample)


# ----- the cases a regex got wrong, in both directions ------------------------

def test_a_void_element_with_lang_does_not_annotate_what_follows(monkeypatch):
    """The regex ACCEPTED this: its non-greedy match ran past the void element
    and swallowed the following paragraph, so unannotated Han read as annotated."""
    _with_cjk(monkeypatch, "jp", "sc")
    with pytest.raises(SystemExit, match="outside any lang-annotated element"):
        buildcore.check_cjk_annotations('<img lang="ja"/><p>直</p>')


def test_lang_is_inherited_by_every_descendant(monkeypatch):
    """The regex REJECTED this: it stopped at the first closing tag, so the
    second paragraph looked unannotated even though its ancestor carries lang."""
    _with_cjk(monkeypatch, "jp", "sc")
    buildcore.check_cjk_annotations('<div lang="ja"><p>直</p><p>文</p></div>')


def test_a_sibling_outside_the_annotated_element_is_still_caught(monkeypatch):
    _with_cjk(monkeypatch, "jp", "sc")
    with pytest.raises(SystemExit):
        buildcore.check_cjk_annotations('<div lang="ja"><p>直</p></div><p>文</p>')


def test_deep_nesting_under_an_annotated_ancestor_is_accepted(monkeypatch):
    _with_cjk(monkeypatch, "jp", "sc")
    buildcore.check_cjk_annotations(
        '<section lang="ja"><div><ul><li><em>直</em></li></ul></div></section>')


def test_an_empty_lang_attribute_does_not_annotate(monkeypatch):
    """`lang=""` explicitly means "unknown", which is exactly the state the gate
    exists to refuse."""
    _with_cjk(monkeypatch, "jp", "sc")
    with pytest.raises(SystemExit):
        buildcore.check_cjk_annotations('<p lang="">直</p>')
