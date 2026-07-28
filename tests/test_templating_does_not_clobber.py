"""Templated substitution must not rewrite text that merely CONTAINS a value.

WHY THIS EXISTS. `_render_templated` is a bare substring replace of the kit's
guide.toml values with the target's. That is right for distinctive strings — a
slug, a title, an author — and wrong for short common words.

The recorded case is the retired `baseline_platform` field, whose values were
"linux", "darwin", "win32". It sat in the templated field list and was harmless
only because every guide agreed with the kit, and substitution is skipped when a
value does not change. The moment the kit moved to "linux" while a target still
recorded "darwin", every templated pixi.toml had `linux-64` rewritten to
`darwin-64` — not a pixi platform at all, so every pixi command in seven repos
failed at once.

The field is gone; the hazard is not. Any future short-valued field added to
`_TEMPLATED_FIELDS` reproduces it exactly, so these tests assert the PROPERTY
rather than the absence of one particular key: substitution must be confined to
values distinctive enough that a substring match cannot hit unrelated text.
"""
from pathlib import Path

import pytest

import sync

REPO_ROOT = Path(__file__).resolve().parent.parent


class _Cfg:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_BASE = dict(OUTPUT_SLUG="guide-template", TITLE="T", AUTHOR="A",
             DESCRIPTION="D", KEYWORDS="K")


@pytest.mark.parametrize("field", ["OUTPUT_SLUG", "TITLE", "AUTHOR"])
def test_the_distinctive_fields_are_still_substituted(field):
    """Removing a field must not disable the mechanism."""
    assert field in sync._TEMPLATED_FIELDS


def test_the_REAL_kit_values_are_distinctive_enough_to_substitute():
    """The list being closed is not sufficient — the VALUES have to be safe too.

    An existing field can become dangerous without the list changing: if the
    kit's DESCRIPTION were ever set to "linux", rendering a target with a
    different description would rewrite `linux-64` in every templated pixi.toml,
    reproducing the original incident with the field list untouched. So this
    reads the kit's actual guide.toml rather than the field names.

    The bound is length plus "does not appear in a templated file for an
    unrelated reason". Short values are the hazard: `linux` is five characters
    and collided; a slug, a title and an author are not.
    """
    import kitconfig
    cfg = kitconfig.load(REPO_ROOT)
    for field in sync._TEMPLATED_FIELDS:
        value = getattr(cfg, field)
        assert isinstance(value, str) and len(value) >= 8, (
            f"guide.toml's {field} is {value!r} — too short to substitute safely; "
            "a bare substring replace will hit unrelated text"
        )


def test_the_templated_field_list_is_closed():
    """Every templated field must be a free-text identity value.

    None of these five is drawn from a small vocabulary, which is the property
    that made `linux` able to hit `linux-64`. This assertion is a tripwire, not
    a prohibition: adding a sixth field is fine once you have confirmed its
    values cannot appear inside unrelated text in a templated file.
    """
    assert set(sync._TEMPLATED_FIELDS) == {
        "OUTPUT_SLUG", "TITLE", "AUTHOR", "DESCRIPTION", "KEYWORDS"
    }


def test_a_short_enumerated_value_WOULD_clobber_a_platform_list(monkeypatch):
    """The hazard is still live — this reproduces it against today's code.

    Without this, the tripwire above is an unexplained list. Driving
    `_render_templated` with a temporarily-widened field list shows that a
    short-valued field really does corrupt the platform list, so the closed list
    is a live control rather than a historical note. If substitution ever stops
    being a bare substring replace this test fails, which is the signal to
    re-derive the whole guard.
    """
    kit = _Cfg(**_BASE, host="linux")
    target = _Cfg(**{**_BASE, "OUTPUT_SLUG": "some-guide"}, host="darwin")
    text = 'platforms = ["osx-arm64", "osx-64", "linux-64", "win-64"]\nname = "guide-template"\n'

    monkeypatch.setattr(sync, "_TEMPLATED_FIELDS", sync._TEMPLATED_FIELDS + ("host",))
    damaged = sync._render_templated(text, kit, target)

    assert "darwin-64" in damaged, (
        "substitution is no longer a bare substring replace — the hazard this "
        "guard describes may no longer exist; re-derive it before relaxing"
    )


def test_the_platform_list_survives_with_the_real_field_list():
    """The same input, rendered the way the kit actually renders it."""
    kit = _Cfg(**_BASE)
    target = _Cfg(**{**_BASE, "OUTPUT_SLUG": "some-guide"})
    text = 'platforms = ["osx-arm64", "osx-64", "linux-64", "win-64"]\nname = "guide-template"\n'

    out = sync._render_templated(text, kit, target)

    assert "linux-64" in out, out
    assert "darwin-64" not in out, out
    assert 'name = "some-guide"' in out, "the slug must still be substituted"
