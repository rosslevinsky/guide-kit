#!/usr/bin/env python3
"""chapters.py — resolve a guide's chapter units over the Pandoc AST.

WHY AN AST AND NOT LINE MATCHING. `git-guide`'s `guide.md` has 64 lines starting
with `#` and 41 real headings; the other 23 are inside fenced code blocks — shell
prompts, comments, `#!` lines. A line-matching splitter is 56% wrong there, and
wrong in the worst direction: it invents chapters at positions no reader can see.
So the split runs `pandoc -t json` and walks blocks, where a fenced block is a
`CodeBlock` and cannot be mistaken for a `Header`.

WHY `chapter_level` IS PER GUIDE. This family has no consistent heading depth:
`accounting-guide` puts chapters at `##` beneath `#` Parts, the other six use
`#`, and `git-guide` has **zero** `##` headings. Any fixed depth yields zero
units for somebody.

WHERE ROUTES COME FROM (amended 2026-07-27).
A slug is derived from the heading text; an authored `{#id}` is honoured and
wins. `{#id}` was originally MANDATORY, to stop a rename from silently moving a
route — a real hazard, since pandoc derives identifiers from heading text. The
mandate was dropped deliberately once it was clear it protected nothing that
existed: `/ch/<slug>/` is created by this phase, so there were no chapter
bookmarks to break. Route stability is consciously given up, and there are no
redirects. Measured before deciding: derivation yields zero non-derivable titles
and zero duplicate slugs across all seven guides.

WHY DERIVATION IS OURS AND NOT PANDOC'S. Pandoc fills `attr[0]` in for every
heading, so "did the author write this?" is unanswerable from the AST — it
reports 100% coverage on guides with zero authored IDs. Worse, pandoc
disambiguates duplicates with numeric suffixes, so two "Setup" chapters would
quietly become `/ch/setup/` and `/ch/setup-1/`. So the source is read for
authored `{#...}`, and everything else is derived here — which is what lets a
duplicate be a build error instead of a silently numbered URL.

This module is a **site/slides input and deliberately not a PDF one** — see the
closure note in `kitconfig.py`. A multipage change must not re-stale eight PDFs.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Chapters live at the ROOT — `/meet-git/`, not `/ch/meet-git/` — so they share
# a namespace with the tree's own top-level routes and this list is what keeps
# them apart. With a `/ch/` prefix it would be unnecessary; unprefixed URLs are
# the trade, and they read the way a book does.
#
# Only DOTLESS names can ever collide: a slug is `[a-z0-9-]+`, so `guide.json`
# and `<slug>.pdf` are unreachable by construction, and `_headers` / `_redirects`
# are excluded by the leading underscore. Listing them would be theatre.
#
# `all` is reserved despite `/all/` having been dropped — a one-page view is the
# obvious thing to want back, and reserving a name costs nothing while
# un-reserving one that a guide has already published costs a broken URL.
RESERVED_SLUGS = frozenset({"index", "all", "fonts", "assets", "static"})

# lowercase ASCII, digits, single interior hyphens. This ends up in a permanent
# URL, so it is enforced at build time rather than discovered by a reader.
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class ChapterError(ValueError):
    """A guide's chapter structure cannot be resolved safely."""


PART_CLASS = "part"


def is_part(block) -> bool:
    """Is this block a PART heading — a division above chapters?

    Marked by a class, `# Part I — The Basics {.part}`, and NOT by depth. Depth
    cannot express it: `chapter_level` is 1 in five guides and 2 in one, so a
    part is `#` in the first case and would have to be level zero in the rest.
    Marking it explicitly lets a part sit at the SAME level as the chapters it
    groups, which is what git-guide's eight divisions do today with a `<div>`.

    A class rather than a naming convention, because "part" is the concept and
    not the word: accounting-guide's divisions are six Parts AND three
    Appendices, and a `^# Part ` rule silently drops the appendices.
    """
    if not isinstance(block, dict) or block.get("t") != "Header":
        return False
    return PART_CLASS in block["c"][1][1]


@dataclass(frozen=True)
class Chapter:
    slug: str
    title: str
    level: int
    blocks: list = field(default_factory=list)
    # The chapter's own Header block, kept verbatim. The renderer emits THIS
    # rather than synthesising `<h1>{title}</h1>`: a synthetic heading drops the
    # id, so a same-chapter `[back to top](#start)` has no target, and it drops
    # emphasis, code, images and classes the author wrote.
    header: dict | None = None
    # The PART this chapter opens, if any: the part's own Header block, plus the
    # blocks between it and this chapter's heading — the part's blurb.
    #
    # Carried on the chapter that OPENS the part because a part has no page of
    # its own, and its blurb has to be somewhere. Left unattached it belonged to
    # no chapter and to no front matter, so the multipage view dropped it
    # silently — prose in the source, absent from the site. Rendering it above
    # the first chapter of the part is also how a book reads.
    part: dict | None = None
    part_blocks: list = field(default_factory=list)


def _ast(md_path: Path) -> dict:
    proc = subprocess.run(
        ["pandoc", "-f", "markdown+raw_html-smart", "-t", "json", str(md_path)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(proc.stdout)


def _inline_text(inlines) -> str:
    """The plain text of a heading's inlines.

    Only what a reader sees: `Str`/`Code` contribute their text, `Space` and
    `SoftBreak` a space, and anything with nested inlines recurses. Formatting
    wrappers (`Emph`, `Strong`, `Link`) contribute their contents, not markup."""
    out: list[str] = []
    for node in inlines or []:
        if not isinstance(node, dict):
            continue
        t, c = node.get("t"), node.get("c")
        if t in ("Str", "Code"):
            out.append(c if isinstance(c, str) else c[1])
        elif t in ("Space", "SoftBreak", "LineBreak"):
            out.append(" ")
        elif t == "Link":
            out.append(_inline_text(c[1]))
        elif t == "Image":
            # An image-only heading has no text at all, and its slug would then
            # derive to "" and be refused. The alt text is what a reader sees.
            out.append(_inline_text(c[1]))
        elif isinstance(c, list):
            # Emph / Strong / Span / SmallCaps / Quoted: contents are inlines,
            # possibly behind an attribute tuple.
            out.append(_inline_text(c if c and isinstance(c[0], dict) else c[-1]))
    return "".join(out).strip()


# A LEADING CHAPTER NUMBER, and nothing else. The digits must be followed by
# `.` or `)` and a space — which is how these guides write them ("1. What
# accounting actually is") and is not how a title that merely starts with a
# number reads. Stripping `^\d+-` off the finished slug instead would turn
# "1984 and dystopia" into `and-dystopia` and "10 Downing Street" into
# `downing-street`; requiring the punctuation is what separates an ordinal from
# a number that is part of the title.
_ORDINAL_RE = re.compile(r"^\s*\d+[.)]\s+")


def derive_slug(title: str) -> str:
    """A route slug from a heading's text.

    The leading chapter number is dropped: 90 of this family's 105 chapter
    headings are numbered, so keeping it would put the ordinal in almost every
    URL — `/ch/2-meet-git/`. That encodes POSITION, which is the one thing a
    route should not do now that routes are derived: renumbering chapters is a
    routine edit, and it would move every later URL. Measured collision-free
    across all seven guides.

    Otherwise deliberately the same grammar `_SLUG_RE` enforces, so a derived
    slug and an authored one are indistinguishable downstream: lowercase, every
    run of non-alphanumerics becomes one hyphen, ends trimmed."""
    stem = _ORDINAL_RE.sub("", title)
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", stem.lower())).strip("-")


def _validate_slug(slug: str, title: str) -> str:
    if not slug:
        raise ChapterError(
            f"chapter heading {title!r} yields no usable route. Its text contains "
            f"no ASCII letters or digits to derive one from, so give it an "
            f"explicit identifier: `## {title} {{#some-id}}`."
        )
    if not _SLUG_RE.match(slug):
        raise ChapterError(
            f"chapter identifier {slug!r} (heading {title!r}) is not a valid "
            f"route: use lowercase ASCII letters, digits and single hyphens, "
            f"with no leading or trailing hyphen."
        )
    if slug in RESERVED_SLUGS:
        raise ChapterError(
            f"chapter route /{slug}/ (heading {title!r}) collides with a path the "
            f"site itself owns ({sorted(RESERVED_SLUGS)}). Chapters are served "
            f"from the root, so give this one an explicit identifier — "
            f"`## {title} {{#a-distinct-id}}`. The kit will not silently pick a "
            f"different URL for you."
        )
    return slug


def split(md_path: Path, chapter_level: int) -> list[Chapter]:
    """The guide's chapters, in document order.

    A chapter is a **top-level** heading at `chapter_level`. Top-level matters
    and is not incidental: every guide opens with a `<div class="title-block">`
    and an authored `<div>` Contents block, both of which contain headings. They
    are document furniture, not chapters, and being inside a `Div` is exactly
    what excludes them — measured across the family, it is the entire difference
    between the raw heading count and the chapter count (japan-guide 5 → 3).

    A chapter runs to the next heading at that level or shallower, so deeper
    headings stay inside it and a shallower one (an `#` Part above `##` chapters)
    closes it without opening a new one. Content before the first chapter heading
    is front matter: the document's opening, before the first chapter.
    """
    doc = _ast(md_path)
    authored = _authored_ids(md_path)
    chapters_out: list[Chapter] = []
    seen: dict[str, str] = {}
    current: Chapter | None = None
    # The part we are inside: its Header, its blurb, and whether any chapter has
    # opened beneath it yet.
    pending_part: dict | None = None
    pending_part_blocks: list = []
    pending_part_used = False

    def _route(title: str, attr) -> str:
        slug = attr[0] if attr[0] in authored else derive_slug(title)
        _validate_slug(slug, title)
        if slug in seen:
            raise ChapterError(
                f"two chapters produce the same route {slug!r}: "
                f"{seen[slug]!r} and {title!r}. Give one an explicit "
                f"identifier — `## {title} {{#a-distinct-id}}` — rather "
                f"than letting a reader meet a numbered URL."
            )
        seen[slug] = title
        return slug

    def _close_part() -> None:
        """A part that grouped NOTHING but holds content is a chapter.

        "A part groups chapters" is the whole definition; a part with no chapters
        under it is not grouping, it is a leaf, and a leaf with content is a
        chapter. accounting-guide's three appendices are exactly this — Glossary,
        Answer Key and Cheat Sheet carry prose and no headings — and before this
        they had no page at all: reachable on the one-page view and nowhere in
        chapter mode, so a reader who chose chapters could not open the glossary.

        Emitted as a chapter of its own rather than folded into a neighbour,
        because it is a division: folding it into the chapter above would file the
        glossary under whatever section happened to precede it.
        """
        nonlocal pending_part, pending_part_blocks, pending_part_used
        if (pending_part is not None and not pending_part_used
                and any(b for b in pending_part_blocks)):
            title = _inline_text(pending_part["c"][2])
            chapters_out.append(Chapter(
                slug=_route(title, pending_part["c"][1]),
                title=title,
                level=pending_part["c"][0],
                blocks=list(pending_part_blocks),
                header=pending_part,
            ))
        pending_part, pending_part_blocks, pending_part_used = None, [], False

    for block in doc.get("blocks", []):
        if is_part(block):
            _close_part()
            # A PART IS NEVER A CHAPTER, whatever its level. Without this the
            # marker is inert where it matters most: git-guide writes parts at
            # `#` alongside `#` chapters with chapter_level = 1, so each of its
            # eight divisions would take a chapter page of its own — six pages
            # where there should be three, in the sample this was measured on.
            #
            # It also CLOSES the open chapter, the same way a shallower heading
            # does: whatever follows belongs to the new division, not to the
            # chapter the reader was in.
            current = None
            pending_part = block
            pending_part_blocks = []
            continue
        if isinstance(block, dict) and block.get("t") == "Header":
            level, attr, inlines = block["c"]
            if level <= chapter_level:
                title = _inline_text(inlines)
                if level == chapter_level:
                    # An AUTHORED id wins; otherwise derive. `attr[0]` alone will
                    # not do — pandoc fills it for every heading and numbers
                    # duplicates, so trusting it would accept `setup-1` as a route.
                    current = Chapter(slug=_route(title, attr), title=title,
                                      level=level, blocks=[], header=block,
                                      # Only the FIRST chapter under a part
                                      # carries it; the rest are simply inside it.
                                      part=None if pending_part_used else pending_part,
                                      part_blocks=([] if pending_part_used
                                                   else pending_part_blocks))
                    chapters_out.append(current)
                    pending_part_used = True
                else:
                    current = None
                continue
        if current is not None:
            current.blocks.append(block)
        elif pending_part is not None and not pending_part_used:
            # The part's blurb: everything between the part heading and the
            # first chapter under it.
            pending_part_blocks.append(block)
    _close_part()
    return chapters_out


def rebase(blocks: list, slug: str, home: dict) -> list:
    """Retarget a chapter's links for being served one directory down.

    Done on the AST, not on the rendered HTML, and that is the whole point. A
    regex over `href="..."` in the output cannot tell a real link from a code
    sample, and these guides are *full* of code samples — rewriting
    `<code>href="foo.html"</code>` corrupts the very thing the guide is teaching.
    In the AST a `Link` target and a `Code` span are different constructors and
    cannot be confused.

    Two rewrites:

    * a fragment (`#anchor`) whose target lives in ANOTHER chapter becomes
      `../<owner>/#anchor`. Same-chapter fragments are left alone so they stay
      in-page jumps, and an unknown fragment is left alone rather than guessed
      at — inventing a destination is worse than a link that behaves as it does
      today.
    * a document-relative target gains one `../`, which maps "relative to `/`"
      onto "relative to `/<slug>/`" exactly. Absolute, protocol-relative,
      scheme'd and fragment-only targets already resolve independently of the
      page's directory and are untouched.
    """
    def retarget(url: str) -> str:
        if url.startswith("#"):
            owner = home.get(url[1:])
            return url if owner is None or owner == slug else f"../{owner}/{url}"
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:|//|/", url):
            return url
        return f"../{url}" if url else url

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") in ("Link", "Image"):
                target = node["c"][2]
                target[0] = retarget(target[0])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    out = copy.deepcopy(blocks)
    walk(out)
    return out


def blocks_to_html(blocks: list, api_version: list | None = None) -> str:
    """Render AST blocks back to HTML through pandoc.

    Round-tripping through pandoc rather than slicing the full document's HTML
    by heading. Slicing looks cheaper and is wrong in the ways string surgery on
    HTML is always wrong: a chapter containing a `<div class="callout">` island,
    or an inline `<svg>` whose markup happens to contain a heading-shaped string,
    would be cut in the middle of an element. The AST already knows where a
    chapter ends; asking pandoc to serialise those exact blocks keeps that.

    `api_version` must be the one the source document reported — pandoc rejects a
    JSON document whose API version it does not recognise, and hardcoding a
    version here would break silently on a pandoc upgrade.
    """
    doc = {
        "pandoc-api-version": api_version or _api_version(),
        "meta": {},
        "blocks": blocks,
    }
    proc = subprocess.run(
        ["pandoc", "-f", "json", "-t", "html5"],
        input=json.dumps(doc), capture_output=True, text=True,
        encoding="utf-8", check=True,
    )
    return proc.stdout


_API_VERSION_CACHE: list | None = None


def _api_version() -> list:
    """Pandoc's JSON API version, asked of pandoc rather than assumed."""
    global _API_VERSION_CACHE
    if _API_VERSION_CACHE is None:
        proc = subprocess.run(["pandoc", "-f", "markdown", "-t", "json"],
                              input="", capture_output=True, text=True, check=True)
        _API_VERSION_CACHE = json.loads(proc.stdout)["pandoc-api-version"]
    return _API_VERSION_CACHE


def document(md_path: Path) -> dict:
    """The parsed document, for callers that need chapters AND the api version."""
    return _ast(md_path)


# A heading line's trailing `{...}` attribute block, whatever else is in it.
# `{#id}`, `{.cls #id}` and `{#id .cls}` are all valid pandoc and all mean the
# same thing, so the id is extracted from ANYWHERE inside the braces rather than
# from the first position.
_ATTR_BLOCK_RE = re.compile(r"^#{1,6}\s+.*\{([^}]*)\}\s*$")
_ATTR_ID_RE = re.compile(r"(?:^|\s)#([^\s}]+)")
# A fenced block opener/closer, so lines inside one can be skipped. Without
# this, a `# fake {#setup-1}` inside a shell example would register as an
# authored id and let pandoc's numeric disambiguation through as a real route.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _authored_ids(md_path: Path) -> frozenset[str]:
    """Identifiers the AUTHOR wrote, read from the source.

    The one thing the AST cannot answer. Pandoc fills every heading's identifier
    in, deriving it from the text when the author gave none, so an AST-only check
    reports 100% coverage on a guide with zero authored IDs — measured across all
    eight guides in this family. Reading the source is what makes "explicit"
    mean explicit.

    Deliberately a narrow regex over heading lines only, not a Markdown parser:
    it is answering "did the author type `{#...}` on this heading", and a fenced
    line that looks like one is not a heading in the AST anyway, so a false
    positive here cannot create a chapter — it can only fail to *reject* one the
    AST already found."""
    ids: set[str] = set()
    fence: str | None = None
    for line in md_path.read_text(encoding="utf-8").splitlines():
        f = _FENCE_RE.match(line)
        if fence is not None:
            # A fence closes only on the SAME character and at least as many of
            # them. ```` opened and ``` seen is still inside the block, and
            # treating it as closed would resume scanning mid-example.
            if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence):
                fence = None
            continue
        if f:
            fence = f.group(1)
            continue
        m = _ATTR_BLOCK_RE.match(line)
        if m:
            got = _ATTR_ID_RE.search(m.group(1))
            if got:
                ids.add(got.group(1))
    return frozenset(ids)
