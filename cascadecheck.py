#!/usr/bin/env python3
"""Cascade checks: what families the resolved CSS can actually reach.

Two questions that look alike and are not:

  * **Coverage** — is every codepoint on the page drawn by a face the SELECTED
    cascade reaches? The predecessor answered a weaker question: it unioned the
    cmaps of every file in `fonts/`, whether or not any CSS referred to them, and
    its own docstring called that "a deliberate false-negative". A face that is
    present but unreachable covers nothing.
  * **Reachability** — can any override introduce a family the kit does not
    bundle? That is the guard, and it has to read VALUES, not grep for names: a
    `font` shorthand, a redefined custom property, or an `@font-face` block can
    each smuggle a host family past a substring search.

A REAL PARSER, not a regex, for a specific reason. `font: italic small-caps bold
12px/1.4 Georgia, serif` names a family in the middle of six other components,
and `--body-font: Georgia` names one in a place no `font-family` search will
look. Both were reachable before this existed.

STATED LIMIT — the family check proves a FAMILY, not a FACE. CSS resolves to a
family name; which binary Fontconfig then hands the renderer is a separate
question, answered by the hermetic environment (`buildcore.assert_hermetic_fontconfig`)
and by reading the rendered PDF back (`buildcore.embedded_faces`). All three are
needed; none subsumes another.
"""
from __future__ import annotations

import re
from pathlib import Path

import tinycss2

# Families every guide may name because the kit bundles them. Generic keywords
# are allowed: they resolve inside the hermetic Fontconfig environment, which has
# only bundled directories on its search path.
GENERIC = frozenset({"serif", "sans-serif", "monospace", "cursive", "fantasy",
                     "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace",
                     "ui-rounded", "math", "emoji", "fangsong", "inherit",
                     "initial", "unset", "revert", "revert-layer"})

# `system-ui` and friends ARE generic keywords, but they resolve to whatever the
# HOST considers its UI font — which is precisely the dependence the bundled
# faces exist to remove. Rejected by name rather than quietly allowed.
HOST_GENERICS = frozenset({"system-ui", "ui-serif", "ui-sans-serif",
                           "ui-monospace", "ui-rounded"})

_FONT_FAMILY_ATTR = re.compile(r'font-family\s*=\s*"([^"]*)"|font-family\s*=\s*\'([^\']*)\'')


class CascadeError(Exception):
    """A family that the kit does not bundle is reachable from the cascade."""


def _iter_font_face(nodes):
    """Every `@font-face`, at ANY nesting depth.

    WeasyPrint processes `@media { @font-face { … } }` and registers the face, so
    a top-level-only scan let a nested rule declare a face pointing at a host
    file while the guard reported nothing — and the rendered-family check saw
    only the (allowed) family NAME it had been given."""
    for rule in nodes:
        if rule.type != "at-rule":
            continue
        if rule.lower_at_keyword == "font-face":
            yield rule
        elif rule.content is not None:
            yield from _iter_font_face(
                tinycss2.parse_rule_list(rule.content, skip_whitespace=True,
                                         skip_comments=True))


def bundled_families(css: str) -> set[str]:
    """The families the cascade DEFINES, read from its own `@font-face` rules.

    Derived rather than hardcoded: the names are a kit convention ("Guide Serif",
    "Guide Sans", "Guide Mono", "Guide Fallback") and a hardcoded list would drift
    the moment a CJK subset is wired in."""
    families: set[str] = set()
    for rule in _iter_font_face(
            tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True)):
        for decl in tinycss2.parse_blocks_contents(rule.content or [],
                                                   skip_whitespace=True):
            if decl.type == "declaration" and decl.lower_name == "font-family":
                families |= _families_in_value(decl.value)
    return families


def _families_in_value(component_values) -> set[str]:
    """Family names from a declaration value.

    Both spellings count: a quoted string (`"Guide Sans"`) and a bare identifier
    sequence (`Guide Sans`, which CSS allows and the SVG attributes use)."""
    out: set[str] = set()
    current: list[str] = []
    for token in component_values:
        if token.type == "string":
            out.add(token.value.strip())
        elif token.type == "ident":
            current.append(token.value)
        elif token.type == "literal" and token.value == ",":
            if current:
                out.add(" ".join(current))
                current = []
        elif token.type == "whitespace":
            continue
        elif token.type == "function":
            args = token.arguments
            if token.lower_name == "var":
                # `var(--name, fallback)`: the FIRST argument is the property
                # NAME, not a family — reading it as one reported `--body-font`
                # as an unbundled family and rejected the kit's own stylesheet.
                # Only the FALLBACK is a family, and it is exactly the branch
                # that runs when the property is undefined, so it must be checked.
                comma = next((i for i, a in enumerate(args)
                              if a.type == "literal" and a.value == ","), None)
                args = args[comma + 1:] if comma is not None else []
            out |= _families_in_value(args)
        else:
            if current:
                out.add(" ".join(current))
                current = []
    if current:
        out.add(" ".join(current))
    return {f for f in out if f}


def _families_in_font_shorthand(component_values) -> set[str]:
    """The family list from a `font` shorthand.

    Only the TAIL is a family. `font: italic small-caps bold 12px/1.4 Georgia,
    serif` puts the family after five other components, so extracting every
    identifier would report `italic small-caps bold` as a family name and the
    guard would reject perfectly ordinary CSS. The font SIZE is the pivot: the
    grammar puts style/variant/weight/stretch before it and the family list after
    it, so everything past the last dimension or percentage token is the family."""
    pivot = -1
    for i, token in enumerate(component_values):
        if token.type in ("dimension", "percentage", "number"):
            pivot = i
    if pivot < 0:
        # No size: not a valid `font` shorthand (or it is a system keyword like
        # `font: menu`, which names no family). Nothing to extract.
        return set()
    tail = component_values[pivot + 1:]
    # A `/line-height` follows the size; skip it and its value.
    while tail and (tail[0].type == "whitespace"
                    or (tail[0].type == "literal" and tail[0].value == "/")
                    or tail[0].type in ("dimension", "percentage", "number")):
        tail = tail[1:]
    return _families_in_value(tail)


def families_in_css(css: str) -> set[str]:
    """Every family an override could put on the page.

    Covers the three routes a substring search misses:
      * `font-family: …`
      * the `font` SHORTHAND, where the family sits after five other components
      * CUSTOM PROPERTIES, where `--body-font: Georgia` names a family in a
        declaration whose name contains no hint that it does
    """
    found: set[str] = set()

    def walk(nodes):
        for rule in nodes:
            if rule.type == "qualified-rule":
                for decl in tinycss2.parse_blocks_contents(rule.content,
                                                           skip_whitespace=True):
                    if decl.type != "declaration":
                        continue
                    name = decl.lower_name
                    if name == "font":
                        found.update(_families_in_font_shorthand(decl.value))
                    elif name == "font-family" or name.startswith("--"):
                        found.update(_families_in_value(decl.value))
            elif rule.type == "at-rule" and rule.content is not None:
                # @media / @supports wrap ordinary rules; a family hidden inside
                # one is just as reachable.
                if rule.lower_at_keyword != "font-face":
                    walk(tinycss2.parse_rule_list(rule.content, skip_whitespace=True,
                                                  skip_comments=True))

    walk(tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True))
    return found


def font_face_rules(css: str) -> list[str]:
    """Every `@font-face` family an override declares. Forbidden outright: an
    override that defines a face points at a file the kit did not vet, and the
    hermetic Fontconfig environment cannot see it — so it either fails silently
    or reintroduces a host binary."""
    return sorted(bundled_families(css))


def svg_font_attributes(markdown: str) -> set[str]:
    """Families named by inline-SVG `font-family` PRESENTATION ATTRIBUTES.

    A vector the CSS guard cannot see. The diagrams are inline `<svg>` in
    `guide.md`, and a presentation attribute sets the family without any
    stylesheet being involved — so a guide could reintroduce an unbundled family
    with every CSS check still passing."""
    out: set[str] = set()
    for m in _FONT_FAMILY_ATTR.finditer(markdown):
        value = m.group(1) if m.group(1) is not None else m.group(2)
        out |= {part.strip().strip('"\'') for part in value.split(",") if part.strip()}
    return out


def _unbundled(names, allowed: set[str]) -> list[str]:
    """Family names are CASE-INSENSITIVE in CSS, so the comparison is too:
    `font-family: "guide sans"` is valid and resolves to Guide Sans, and an
    exact-case membership test rejected perfectly good CSS."""
    folded = {a.strip().lower() for a in allowed}
    bad = []
    for name in sorted(names):
        low = name.strip().lower()
        if low in HOST_GENERICS:
            bad.append(name)          # resolves to a HOST face by definition
        elif low in GENERIC or low in folded:
            continue
        else:
            bad.append(name)
    return bad


def check_override(path: Path, allowed: set[str], *, label: str | None = None) -> None:
    """Refuse an override file that can reach an unbundled family."""
    if not path.is_file():
        return
    css = path.read_text(encoding="utf-8")
    where = label or path.name

    faces = font_face_rules(css)
    if faces:
        raise CascadeError(
            f"{where}: @font-face is not allowed in an override ({', '.join(faces)}).\n"
            f"  An override that defines a face points at a file the kit never vetted, "
            f"and the hermetic Fontconfig environment cannot see it — so it either "
            f"renders nothing or reintroduces a host binary. Faces belong in the kit."
        )

    bad = _unbundled(families_in_css(css), allowed)
    if bad:
        raise CascadeError(
            f"{where}: names {len(bad)} family/families the kit does not bundle: "
            f"{', '.join(bad)}.\n"
            f"  Bundled: {', '.join(sorted(allowed))}. Use one of those, a theme "
            f"custom property, or a generic keyword. A host family here renders "
            f"differently on every machine, which is what bundling exists to prevent."
        )


_STYLE_ATTR = re.compile(r'\bstyle\s*=\s*"([^"]*)"|\bstyle\s*=\s*\'([^\']*)\'')
_STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)


def svg_inline_styles(markdown: str) -> set[str]:
    """Families reachable from inline `style="…"` attributes and `<style>` blocks.

    The presentation-attribute scan misses both, and WeasyPrint represents an
    inline `<svg>` as a single replaced box — so the rendered-family check cannot
    see inside it either. Between them these were the last routes by which a
    diagram could name a host family with every other check green."""
    out: set[str] = set()
    for m in _STYLE_ATTR.finditer(markdown):
        value = m.group(1) if m.group(1) is not None else m.group(2)
        # A style ATTRIBUTE is a declaration list, not a stylesheet.
        for decl in tinycss2.parse_blocks_contents(
                tinycss2.parse_component_value_list(value), skip_whitespace=True):
            if decl.type != "declaration":
                continue
            if decl.lower_name == "font":
                out |= _families_in_font_shorthand(decl.value)
            elif decl.lower_name == "font-family" or decl.lower_name.startswith("--"):
                out |= _families_in_value(decl.value)
    for m in _STYLE_BLOCK.finditer(markdown):
        out |= families_in_css(m.group(1))
    return out


def check_svg_attributes(markdown_path: Path, allowed: set[str]) -> None:
    """Refuse an inline-SVG `font-family` attribute naming an unbundled family."""
    if not markdown_path.is_file():
        return
    text = markdown_path.read_text(encoding="utf-8")
    bad = _unbundled(svg_font_attributes(text) | svg_inline_styles(text), allowed)
    if bad:
        raise CascadeError(
            f"{markdown_path.name}: an inline-SVG font-family attribute names "
            f"{', '.join(bad)}, which the kit does not bundle.\n"
            f"  Presentation attributes bypass every CSS check — this is the one "
            f"route by which a diagram can reintroduce a host family with the "
            f"stylesheet guard still green."
        )


def reachable_families(cascade_css: str) -> set[str]:
    """Families the RESOLVED cascade actually refers to — the set coverage should
    be computed over.

    Not the same as "families the cascade defines": a face can be bundled,
    declared with `@font-face`, and never named by any rule, in which case it
    covers nothing that reaches the page. Custom-property VALUES count, because
    the whole theme layer reaches families through them."""
    return {f for f in families_in_css(cascade_css)
            if f.strip().lower() not in GENERIC}


def families_for_source(css: str, filename: str) -> set[str]:
    """The CSS family a given font FILE is exposed as, from `@font-face`.

    ALL of them, not the first. One binary can legitimately be exposed under
    several family names, and returning only the first meant the face counted as
    unreachable whenever that one happened to be the unused name.

    The kit renames upstream families — Source Serif 4 is served as
    "Guide Serif" — so a binary's own name table says nothing about whether the
    cascade reaches it. This reads the rename from the rules that perform it."""
    found: set[str] = set()
    for rule in _iter_font_face(
            tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True)):
        family, src_matches = None, False
        for decl in tinycss2.parse_blocks_contents(rule.content or [],
                                                   skip_whitespace=True):
            if decl.type != "declaration":
                continue
            if decl.lower_name == "font-family":
                names = _families_in_value(decl.value)
                family = next(iter(names), None)
            elif decl.lower_name == "src":
                # `url("x.otf")` tokenizes as a FUNCTION whose argument is a
                # string — only the unquoted `url(x.otf)` form produces a URL
                # token. The kit quotes its paths, so matching URL tokens alone
                # found nothing and every face read as unreachable.
                for token in decl.value:
                    if token.type == "url" and filename in token.value:
                        src_matches = True
                    elif token.type == "function" and token.lower_name == "url":
                        for arg in token.arguments:
                            if arg.type in ("string", "ident") and filename in arg.value:
                                src_matches = True
        if src_matches and family:
            found.add(family)
    return found
