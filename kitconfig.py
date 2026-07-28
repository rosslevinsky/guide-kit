#!/usr/bin/env python3
"""Strict loader/validator for guide.toml, and the `ArtifactSpec` table every
dependency closure in the kit is derived from.

This module is the SINGLE reader of guide.toml, and the single place the family's
canonical `SOURCE_FILES` list and content hash live. It *validates* rather than
trusts: required keys present, correct types, kebab-case OUTPUT_SLUG, an integer
COPYRIGHT_YEAR, every enum value in range, unknown keys REJECTED by name, and
every slug-derived path resolved and asserted to stay inside the repo root.

Deliberately DEPENDENCY-LIGHT — it imports only the standard library (no
WeasyPrint, no pandoc), so the staleness check built on top of it stays
milliseconds and platform-independent. Every renderer, `release.py`,
`verify_artifacts.py`, `driftcanary.py`, `verify_web.py` and `sync.py` read
through here; none of them keeps its own copy of a path list.
"""
from __future__ import annotations

import datetime as _datetime
import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

try:
    import tomllib  # Python >= 3.11 (the raised pixi floor guarantees this)
except ModuleNotFoundError:  # pragma: no cover - floor is >=3.11
    import tomli as tomllib  # type: ignore[no-redef]

# SOURCE_FILES and AUTHORABLE_SOURCES are DERIVED from the ArtifactSpec table
# further down, so the two can never drift from the closures they describe.
# See "ArtifactSpec — one dependency closure per artifact".

# The bundled font faces are RENDER INPUTS: swapping a face changes the PDF's
# typography exactly as editing style.css does, so they belong in the version
# stamp's closure or `make verify` would stay green across a font change and
# the committed reference would silently diverge from its source.
#
# A directory rather than a fixed list, because the face set is expected to
# grow (a CJK subset is the obvious next one) and a hardcoded list would need
# editing in lockstep — the kind of paired edit that gets forgotten once.
# Walked in SORTED order so the hash is independent of filesystem enumeration
# order, which differs between ext4 and APFS and would otherwise make the
# stamp itself host-dependent — the exact failure this bundling exists to fix.
# The vendored faces live in their OWN namespace, not flat in fonts/. That is an
# OWNERSHIP boundary: `fonts/vendor/**` is kit-owned and synced verbatim, while
# `fonts/generated/**` beside it is target-owned build output the kit must never
# write or delete. Flat, the two could not be separated — a generated subset would
# sit inside the kit-managed tree, where a sync could erase it.
FONT_DIR = "fonts/vendor"
# Target-owned GENERATED faces (CJK subsets from tools/subset-cjk.py). Sync never
# writes or deletes this directory — but the bytes are a RENDER INPUT exactly as
# the vendored faces are, so they are hashed, watched, and fed to the glyph gate.
# Omitting them would mean a guide's subset changed the PDF without moving its
# version stamp, and the coverage gate refusing CJK text the subset in fact
# covers.
GENERATED_FONT_DIR = "fonts/generated"

# Binary assets — images, screenshots, generated figures.
#
# THREE SIBLING NAMESPACES, never nested, for the same reason `fonts/vendor` and
# `fonts/generated` are siblings: a nested tree can be erased by the enclosing
# one's expansion, and here it would also silently put a screen-only image into
# the PDF's closure.
#
#   assets/shared/**  both outputs — the common case, an image in guide.md
#   assets/print/**   the PDF only
#   assets/web/**     the site only
#
# The split is the whole point. Before this, `kitconfig` tracked `assets/` in
# neither SOURCE_FILES nor the content hash, so editing a diagram there changed
# the PDF while `make verify` stayed green — a defect `CLAUDE.md` already
# recorded, and the reason every diagram in this family is inlined SVG today.
ASSET_SHARED_DIR = "assets/shared"
ASSET_PRINT_DIR = "assets/print"
ASSET_WEB_DIR = "assets/web"
_FONT_SUFFIXES = (".otf", ".ttf", ".woff2")

# Mirrors bootstrap.py's SLUG_RE (kebab-case). Kept as a local copy rather than
# importing bootstrap.py so kitconfig stays dependency-light and bootstrap can be
# rewired to read from here later without a circular import.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

# key -> expected python type. COPYRIGHT_YEAR is int; the rest are str.
#
# There is no platform key. Rendering is hermetic — bundled faces plus
# `fontconfig/fonts.conf`, both in every artifact's closure — so the host no
# longer selects typography and there is nothing for a recorded platform to
# pin. A leftover `baseline_platform` in a fork's guide.toml is rejected as an
# unknown top-level key, which is the same loud failure `[release]` gets: a
# retired key must fail rather than silently do nothing.
_REQUIRED: dict[str, type] = {
    "TITLE": str,
    "OUTPUT_SLUG": str,
    "AUTHOR": str,
    "DESCRIPTION": str,
    "KEYWORDS": str,
    "COPYRIGHT_YEAR": int,
}

# ---------------------------------------------------------------------------
# Declared shape
#
# Outputs are DECLARED, never inferred from the filesystem. The predecessor
# resolved the web layer by asking whether style-screen.css existed and
# transforms by asking whether transforms.py existed — a shape enum hiding
# inside a boolean, which a third and fourth output cannot be added to. Every
# table below is validated: unknown keys and out-of-enum values are rejected
# with a NAMED error, so a stale key fails loudly instead of silently doing
# nothing.
# ---------------------------------------------------------------------------

# "none" is the PDF-only guide; "single" is the predecessor's one-page website;
# "multipage" is the chapter-split site; "app" is an externally-built SPA the kit
# only deploys (romance-languages); "hub" is the omnibus index (guides/).
SITE_SHAPES = ("none", "single", "multipage", "app", "hub")

# ...of which the renderer actually IMPLEMENTS these. The enum above is wider on
# purpose: `app` names an externally-built SPA the kit only deploys, so it is a
# real shape in the family's vocabulary that this renderer cannot produce.
# Accepting a value the renderer then ignores is precisely the "the check and the
# claim were about different things" failure this schema exists to remove —
# `site = "multipage"` once passed validation and silently rendered ONE page. So
# `build_web()` REFUSES an unimplemented shape by name, and the wider enum can
# document the whole vocabulary without lying about what builds today.
IMPLEMENTED_SITE_SHAPES = ("none", "single", "multipage", "hub")
SLIDES_SOURCES = ("auto", "guide", "file")
# Han unification: JP/SC/TC/KR share codepoints but need different regional
# glyph shapes, so this is an ordered list of language selectors, not a boolean.
CJK_LOCALES = ("jp", "sc", "tc", "kr")
DEFAULT_THEME = "classic-sans"

# The artifacts the kit knows how to build. `[artifacts.<name>]` tables are
# keyed by these, and one exists per DECLARED output — no more, no fewer.
ARTIFACT_NAMES = ("pdf", "site", "slides")

# ISO-8601 calendar date. Shape alone is insufficient — the day must exist, so
# the value is additionally parsed (2026-02-30 matches this and is still wrong).
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class KitConfigError(Exception):
    """Raised when guide.toml is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class Outputs:
    """Which artifacts this guide declares. `site` is an enum rather than a
    bool because the site has genuinely different shapes."""

    pdf: bool = True
    site: str = "none"
    slides: bool = False

    @property
    def declared(self) -> tuple[str, ...]:
        """The declared artifact names, in ARTIFACT_NAMES order."""
        names = []
        if self.pdf:
            names.append("pdf")
        if self.site != "none":
            names.append("site")
        if self.slides:
            names.append("slides")
        return tuple(names)


# A custom property name, as it appears in CSS. Constrained because these values
# are emitted verbatim into a `:root {}` block: an unvalidated key or value is a
# stylesheet-injection hole, and `--x: red; } body { display:none } /*` would be a
# guide silently blanking its own render through a config file.
_TOKEN_NAME_RE = re.compile(r"^--[a-z0-9-]+$")
# `/*` is as dangerous as `;` here and less obvious: a value of `red/*`
# comments out the generated semicolon, the closing brace, AND every layer
# that follows — the CJK rules and the guide's whole stylesheet — producing a
# silently unstyled render rather than an error.
_TOKEN_VALUE_RE = re.compile(r"^(?:(?!/\*|\*/)[^;{}<>@\\])*$")


@dataclass(frozen=True)
class Theme:
    name: str = DEFAULT_THEME
    # Per-guide token overrides, the MIDDLE layer of the cascade: they sit
    # between the theme and the guide's own stylesheet, so a guide can retint one
    # value without forking a whole sheet.
    tokens: tuple[tuple[str, str], ...] = ()

    @property
    def token_css(self) -> str:
        """The tokens as a `:root {}` block, or "" when there are none."""
        if not self.tokens:
            return ""
        body = "\n".join(f"  {k}: {v};" for k, v in self.tokens)
        return f"/* [theme] tokens from guide.toml */\n:root {{\n{body}\n}}\n"


@dataclass(frozen=True)
class SiteConfig:
    # Empty means "emit noindex"; a base URL means "emit rel=canonical".
    canonical: str = ""
    # No fixed heading depth works across this family (git-guide has zero `##`),
    # so the chapter unit is per-guide and resolved over the Pandoc AST.
    chapter_level: int = 1


@dataclass(frozen=True)
class SlidesConfig:
    source: str = "auto"
    file: str = "slides.md"


@dataclass(frozen=True)
class FontsConfig:
    cjk: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeployConfig:
    domain: str = ""
    # AUTHORED, and defaulting to OFF — the opposite of `workers_dev` below,
    # deliberately.
    #
    # Preview URLs are a SECOND, independent workers.dev surface:
    # `<version>-<worker>.<subdomain>.workers.dev`. Turning off `workers_dev`
    # does nothing to them, and Cloudflare published a changelog about exactly
    # that ambiguity. Two properties make the default matter:
    #
    #   * EVERY version gets one — `wrangler deploy` as much as
    #     `wrangler versions upload` — so a guide accrues one per deploy, not
    #     one per pull request;
    #   * they do not expire. The documented retention rule covers *aliased*
    #     previews only ("the 1000 most recently deployed"); versioned ones are
    #     public from creation with no stated end.
    #
    # So a guide that has deliberately taken itself off workers.dev keeps a
    # growing set of public, un-WAF'd URLs serving the same content unless this
    # says otherwise. Off by default matches both `workers_dev` and Cloudflare's
    # own default since wrangler 4.44.0 (`preview_urls = workers_dev`); a guide
    # that wants PR preview links opts in, visibly, in its own config.
    preview_urls: bool = False

    @property
    def workers_dev(self) -> bool:
        """DERIVED, never authored: true when no custom domain is set, false
        when one is. Authoring it is rejected as an unknown key, so no deploy
        can re-assert Cloudflare's default behind the config's back."""
        return not self.domain


@dataclass(frozen=True)
class HubConfig:
    registry: str = "registry.toml"
    snapshot: str = "guides.snapshot.json"


@dataclass(frozen=True)
class KitMeta:
    # Reserved for kit-level requirements a guide can state about the kit that
    # builds it. Empty means "any version".
    min_version: str = ""


@dataclass(frozen=True)
class Artifact:
    """One declared output and its authored EDITION date.

    The date is authored rather than derived from git history because the stamp
    must not move when an unrelated table in the same file is edited: git cannot
    tell a [deploy] edit from a [theme] edit inside one guide.toml, so a
    path-derived date moves the rendered bytes for either."""

    name: str
    date: str


@dataclass(frozen=True)
class KitConfig:
    """The validated per-guide constants. Attribute names match build.py's
    former literal names so consumers read them unchanged."""

    TITLE: str
    OUTPUT_SLUG: str
    AUTHOR: str
    DESCRIPTION: str
    KEYWORDS: str
    COPYRIGHT_YEAR: int
    outputs: Outputs = field(default_factory=Outputs)
    theme: Theme = field(default_factory=Theme)
    site: SiteConfig = field(default_factory=SiteConfig)
    slides: SlidesConfig = field(default_factory=SlidesConfig)
    fonts: FontsConfig = field(default_factory=FontsConfig)
    deploy: DeployConfig = field(default_factory=DeployConfig)
    hub: HubConfig = field(default_factory=HubConfig)
    kit: KitMeta = field(default_factory=KitMeta)
    artifacts: dict[str, Artifact] = field(default_factory=dict)


def _root(root: Path | None) -> Path:
    return (root if root is not None else Path(__file__).parent).resolve()


def load(root: Path | None = None) -> KitConfig:
    """Read, validate, and return guide.toml from `root` (default: the directory
    containing this file). Raises KitConfigError on any problem."""
    base = _root(root)
    toml_path = base / "guide.toml"
    if not toml_path.is_file():
        raise KitConfigError(f"guide.toml not found at {toml_path}")
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise KitConfigError(f"guide.toml is not valid TOML: {exc}") from exc
    return _validate(data, base)


def _table(data: dict, name: str, allowed: dict[str, type]) -> dict:
    """Return `data[name]` (or {}) after rejecting unknown keys and wrong types.

    `allowed` maps key -> expected python type. bool is checked before int
    because bool is an int subclass — otherwise `pdf = 1` would validate."""
    raw = data.get(name, {})
    if not isinstance(raw, dict):
        raise KitConfigError(f"guide.toml: [{name}] must be a table, got {type(raw).__name__}")
    for key in raw:
        if key not in allowed:
            raise KitConfigError(
                f"guide.toml: [{name}] has unknown key {key!r} "
                f"(known: {sorted(allowed)})"
            )
    for key, typ in allowed.items():
        if key not in raw:
            continue
        val = raw[key]
        if typ is bool:
            if not isinstance(val, bool):
                raise KitConfigError(
                    f"guide.toml: [{name}] {key} must be a boolean, got {type(val).__name__}"
                )
        elif typ is int:
            if isinstance(val, bool) or not isinstance(val, int):
                raise KitConfigError(
                    f"guide.toml: [{name}] {key} must be an integer, got {type(val).__name__}"
                )
        elif not isinstance(val, typ):
            raise KitConfigError(
                f"guide.toml: [{name}] {key} must be {typ.__name__}, got {type(val).__name__}"
            )
    return raw


def _enum(name: str, key: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise KitConfigError(
            f"guide.toml: [{name}] {key} {value!r} not in {list(allowed)}"
        )
    return value


def _check_date(where: str, value: str) -> str:
    """An ISO-8601 CALENDAR date. Both halves matter: the regex fixes the shape
    (so `2026-7-26` and `20260726` are refused) and the parse fixes existence
    (so `2026-02-30` is refused)."""
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise KitConfigError(
            f"guide.toml: [{where}] date {value!r} must be an ISO-8601 date, YYYY-MM-DD"
        )
    try:
        _datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise KitConfigError(
            f"guide.toml: [{where}] date {value!r} is not a real calendar date: {exc}"
        ) from exc
    return value


def _check_repo_relative(table: str, key: str, value: str) -> str:
    """A user-authored path that enters an artifact closure and a git pathspec.

    Checked on the STRING, not by resolving on disk: the file need not exist
    yet, and a traversal must be refused whether or not it currently resolves.
    Three separate rejections, each for its own reachable failure:

    * **Pathspec magic.** A leading `:` makes git read the value as magic rather
      than a path — `":!guide.md"` is an EXCLUSION, which would quietly drop
      guide.md from the date and dirty checks while it stayed in the hashed
      closure. That is a falsely-clean tree produced by a config value.
    * **Windows shapes.** `pixi.toml` declares `win-64`, so a POSIX-only check
      is not enough: `PurePosixPath` sees no `..` part in `..\\..\\x` and does
      not consider `C:\\x` absolute, so both would pass.
    * **Traversal.** The ordinary case, under either path flavour.
    """
    if value.startswith(":"):
        raise KitConfigError(
            f"guide.toml: [{table}] {key} {value!r} must not begin with ':' — git "
            f"would read it as pathspec magic rather than as a path"
        )
    if "\\" in value:
        raise KitConfigError(
            f"guide.toml: [{table}] {key} {value!r} must use '/' separators, not "
            f"backslashes"
        )
    for flavour in (PurePosixPath, PureWindowsPath):
        p = flavour(value)
        if p.is_absolute() or p.drive or ".." in p.parts:
            raise KitConfigError(
                f"guide.toml: [{table}] {key} {value!r} must be a repo-relative path "
                f"that does not escape the repository root"
            )
    # * ? [ ] would be read as a GLOB by `_expand`, which resolves the closure's
    # file list — so `deck*.md` could pull several files into the hashed closure
    # while every membership predicate (`is_authorable`, `is_stamp_input`) compared
    # the literal string and matched none of them. One value, two meanings.
    if any(ch in value for ch in "*?[]"):
        raise KitConfigError(
            f"guide.toml: [{table}] {key} {value!r} must name ONE file — glob "
            f"characters are read as a pattern by the closure resolver"
        )
    # NORMALISED, and the normalised form is what is stored. git reports paths in
    # exactly one spelling, so `./deck.md` or `slides//deck.md` — both of which
    # pass every check above — would be compared against git's `deck.md` /
    # `slides/deck.md` and never match: the guide's real slide source would be
    # refused as out of scope while the unused default was admitted.
    return PurePosixPath(value).as_posix() if value else value


def _parse_shape(data: dict) -> tuple:
    """Every declared-shape table, validated. Returns the dataclasses in
    KitConfig's field order."""
    if "outputs" not in data:
        raise KitConfigError(
            "guide.toml: missing required table [outputs] — a guide's shape is "
            "declared, never inferred from which files happen to exist"
        )
    raw = _table(data, "outputs", {"pdf": bool, "site": str, "slides": bool})
    outputs = Outputs(
        pdf=raw.get("pdf", True),
        site=_enum("outputs", "site", raw.get("site", "none"), SITE_SHAPES),
        slides=raw.get("slides", False),
    )

    raw = _table(data, "theme", {"name": str, "tokens": dict})
    tokens_raw = raw.get("tokens", {})
    tokens = []
    for key in sorted(tokens_raw):
        value = tokens_raw[key]
        if not _TOKEN_NAME_RE.fullmatch(key):
            raise KitConfigError(
                f"guide.toml: [theme.tokens] {key!r} must be a CSS custom property "
                f"name like '--accent'"
            )
        if not isinstance(value, str) or not _TOKEN_VALUE_RE.fullmatch(value):
            raise KitConfigError(
                f"guide.toml: [theme.tokens] {key} value {value!r} must be a plain CSS "
                f"value — ';', '{{', '}}', '<', '>', '@' and backslash are rejected "
                f"because the value is emitted verbatim into a stylesheet"
            )
        tokens.append((key, value))
    theme = Theme(name=raw.get("name", DEFAULT_THEME), tokens=tuple(tokens))
    if not theme.name:
        raise KitConfigError("guide.toml: [theme] name must not be empty")
    if not _SLUG_RE.fullmatch(theme.name):
        # The name becomes a PATH (themes/<name>/print.css). Unconstrained, a
        # value like "../../etc" would read a file outside the repository into
        # every render.
        raise KitConfigError(
            f"guide.toml: [theme] name {theme.name!r} must be kebab-case — it names "
            f"a directory under themes/"
        )

    raw = _table(data, "site", {"canonical": str, "chapter_level": int})
    level = raw.get("chapter_level", 1)
    if not 1 <= level <= 6:
        raise KitConfigError(
            f"guide.toml: [site] chapter_level {level} must be between 1 and 6"
        )
    site = SiteConfig(canonical=raw.get("canonical", ""), chapter_level=level)

    raw = _table(data, "slides", {"source": str, "file": str})
    slides_source = _enum("slides", "source", raw.get("source", "auto"), SLIDES_SOURCES)
    slides_file = raw.get("file", "slides.md")
    if slides_source == "file" and not slides_file:
        raise KitConfigError(
            'guide.toml: [slides] source = "file" requires a non-empty file key'
        )
    # The NORMALISED form is what gets stored: this value is compared against the
    # paths git reports, so `./deck.md` must become `deck.md` here rather than at
    # each of the several comparison sites.
    slides = SlidesConfig(
        source=slides_source,
        file=_check_repo_relative("slides", "file", slides_file),
    )

    raw = _table(data, "fonts", {"cjk": list})
    cjk = raw.get("cjk", [])
    for loc in cjk:
        if not isinstance(loc, str) or loc not in CJK_LOCALES:
            raise KitConfigError(
                f"guide.toml: [fonts] cjk entry {loc!r} not in {list(CJK_LOCALES)}"
            )
    if len(set(cjk)) != len(cjk):
        raise KitConfigError(f"guide.toml: [fonts] cjk has duplicate entries: {cjk}")
    fonts = FontsConfig(cjk=tuple(cjk))

    raw = _table(data, "deploy", {"domain": str, "preview_urls": bool})
    deploy = DeployConfig(domain=raw.get("domain", ""),
                          preview_urls=raw.get("preview_urls", False))

    raw = _table(data, "hub", {"registry": str, "snapshot": str})
    hub = HubConfig(
        registry=raw.get("registry", "registry.toml"),
        snapshot=raw.get("snapshot", "guides.snapshot.json"),
    )

    raw = _table(data, "kit", {"min_version": str})
    kit = KitMeta(min_version=raw.get("min_version", ""))

    return outputs, theme, site, slides, fonts, deploy, hub, kit


def _parse_artifacts(data: dict, outputs: Outputs) -> dict[str, Artifact]:
    """One [artifacts.<name>] table per DECLARED output, each carrying that
    artifact's authored edition date. A table for an undeclared output, or a
    missing table for a declared one, is rejected — the two directions are what
    keep the declaration and the dates from drifting apart."""
    raw = data.get("artifacts", {})
    if not isinstance(raw, dict):
        raise KitConfigError(
            f"guide.toml: [artifacts] must be a table, got {type(raw).__name__}"
        )
    declared = set(outputs.declared)
    for name in raw:
        if name not in ARTIFACT_NAMES:
            raise KitConfigError(
                f"guide.toml: [artifacts.{name}] is not a known artifact "
                f"(known: {list(ARTIFACT_NAMES)})"
            )
        if name not in declared:
            raise KitConfigError(
                f"guide.toml: [artifacts.{name}] is declared but outputs does not "
                f"enable {name!r} — remove the table or declare the output"
            )
    out: dict[str, Artifact] = {}
    for name in ARTIFACT_NAMES:
        if name not in declared:
            continue
        if name not in raw:
            raise KitConfigError(
                f"guide.toml: output {name!r} is declared but [artifacts.{name}] is "
                f"missing — every declared output carries its own authored date"
            )
        entry = _table(raw, name, {"date": str})
        if "date" not in entry:
            raise KitConfigError(
                f"guide.toml: [artifacts.{name}] is missing the required key 'date'"
            )
        out[name] = Artifact(name=name, date=_check_date(f"artifacts.{name}", entry["date"]))
    return out


def _validate(data: dict, base: Path) -> KitConfig:
    # Unknown TOP-LEVEL keys are rejected too, which is what removes [release]
    # from the language entirely: publication always happens in the
    # guide's own repository, so nothing about it is user-configurable, and a
    # leftover [release] table must fail rather than silently do nothing.
    known_top = set(_REQUIRED) | {
        "outputs", "theme", "site", "slides", "fonts", "deploy", "hub", "kit", "artifacts",
    }
    for key in data:
        if key not in known_top:
            raise KitConfigError(
                f"guide.toml: unknown key {key!r} (known: {sorted(known_top)})"
            )

    for key, typ in _REQUIRED.items():
        if key not in data:
            raise KitConfigError(f"guide.toml: missing required key {key!r}")
        val = data[key]
        if typ is int:
            # bool is a subclass of int — reject it so a stray `true` doesn't
            # validate as the year.
            if isinstance(val, bool) or not isinstance(val, int):
                raise KitConfigError(
                    f"guide.toml: {key} must be an integer, got {type(val).__name__}"
                )
        elif not isinstance(val, typ):
            raise KitConfigError(
                f"guide.toml: {key} must be {typ.__name__}, got {type(val).__name__}"
            )

    slug = data["OUTPUT_SLUG"]
    # fullmatch, not match: re's `$` also matches just before a trailing
    # newline, so `.match()` would accept a TOML value like "slug\n" (an escaped
    # newline decodes to a real one) and yield a filename with an embedded
    # newline. fullmatch anchors both ends and rejects it.
    if not _SLUG_RE.fullmatch(slug):
        raise KitConfigError(
            f"guide.toml: OUTPUT_SLUG {slug!r} must be kebab-case matching "
            f"{_SLUG_RE.pattern}"
        )

    # Defense in depth: every slug-derived OUTPUT path must resolve inside the
    # repo root. _SLUG_RE (fullmatch) already forbids slashes, dots, and
    # newlines, so a traversal slug can't reach here — but asserting containment
    # on the ACTUAL derived paths makes the guarantee explicit and survives any
    # future loosening of the grammar. These mirror build.py's
    # REFERENCE_PDF (:103), OUT_PDF (:95), and OUT_HTML (:96). Symlinked output
    # directories are an explicit Non-Goal, so plain is_relative_to
    # containment — not symlink refusal — is the right guard here.
    derived = [
        base / f"{slug}.pdf",             # REFERENCE_PDF
        base / "build" / f"{slug}.pdf",   # OUT_PDF
        base / "build" / f"{slug}.html",  # OUT_HTML
    ]
    for path in derived:
        resolved = path.resolve()
        if not resolved.is_relative_to(base):
            raise KitConfigError(
                f"guide.toml: OUTPUT_SLUG {slug!r} escapes the repo root "
                f"(resolves to {resolved})"
            )

    outputs, theme, site, slides, fonts, deploy, hub, kit = _parse_shape(data)

    return KitConfig(
        TITLE=data["TITLE"],
        OUTPUT_SLUG=slug,
        AUTHOR=data["AUTHOR"],
        DESCRIPTION=data["DESCRIPTION"],
        KEYWORDS=data["KEYWORDS"],
        COPYRIGHT_YEAR=data["COPYRIGHT_YEAR"],
        outputs=outputs,
        theme=theme,
        site=site,
        slides=slides,
        fonts=fonts,
        deploy=deploy,
        hub=hub,
        kit=kit,
        artifacts=_parse_artifacts(data, outputs),
    )


def stamp_pathspec(artifact: str = "pdf", cfg: KitConfig | None = None) -> list[str]:
    """The git pathspec covering everything `artifact`'s closure reads. Pass it
    after a `--` to `git status` / `git log` / `git add`.

    Per-artifact, not global: scoped to the authorable UNION instead, an
    uncommitted `style-screen.css` edit would mark the PDF's stamp dirty — the
    exact coupling the split exists to remove.

    `guide.toml` is included whole even though the config dependency is
    key-level, because git cannot scope to a key. That is deliberately
    conservative: it can report dirty when only an out-of-closure table moved,
    which is safe (it never blesses an unreproducible reference). Making it
    exact needs a committed-vs-worktree key projection and belongs with the
    stamp-grammar work.

    WHY THIS IS NOT JUST SOURCE_FILES. Bundling fonts widened the stamp's input
    set — a face swap changes the PDF's typography exactly as a style.css edit
    does, so `content_hash()` reads the faces too. Every guard that asks "is the
    tree clean enough to bless a reference PDF?" must ask about the SAME set, or
    the two drift: an uncommitted font change moves the hash while
    `git status -- <SOURCE_FILES>` reports clean, the stamp omits its ` · dirty`
    marker, `make baseline` does not refuse, and the promoted reference is one
    no committed state can reproduce.

    WHY PATTERNS AND NOT A FILE LIST. A list built by walking `fonts/` can only
    name faces that still exist, so DELETING a tracked face would drop it from
    the very pathspec meant to notice the deletion — the same falsely-clean
    tree, reached from the other direction. A pattern is matched by git against
    the index as well as the worktree, so a deletion still reports.

    `:(glob)` magic keeps `*` from crossing `/`, which is what makes this agree
    with `font_files()`'s non-recursive scan: both cover `fonts/<face>` and
    neither covers `fonts/sub/<face>`. Non-face files under `fonts/` (README,
    the licence texts) are excluded because they are not render inputs — an
    edit to one must not stale a reference or move the stamp date.
    """
    spec = artifact_spec(artifact)
    resolve = (lambda f: _resolve_pattern(f, cfg)) if cfg is not None else _with_defaults
    # generated_deps are included, not just file_deps: they feed the closure
    # hash, so a guard scoped to file_deps alone would let the site's hash move
    # (its embedded copy of the reference PDF changed) while its stamp still
    # claimed clean — the same falsely-clean tree the font closure fixed, by a
    # different door.
    patterns = [resolve(f) for f in spec.file_deps + spec.generated_deps]
    # A pattern that still carries an unresolved placeholder cannot be scoped
    # (no config was supplied to resolve <slug>), so drop it rather than hand
    # git a literal "<slug>.pdf" that matches nothing.
    patterns = [p for p in patterns if "<" not in p]
    # Sorted, so the pathspec is deterministic and agrees exactly with the
    # closure's own file ordering rather than with the spec's declaration order.
    literals = sorted({p for p in patterns if "*" not in p} | {"guide.toml"})
    globs = [f":(glob,icase){p}" for p in patterns if "*" in p]
    # `:(literal)` on the non-glob paths: one of them ([slides] file) is
    # user-authored, and a value like ":!guide.md" would otherwise be parsed as
    # pathspec MAGIC — an exclusion that silently removes guide.md from the date
    # and dirty checks while it stays in the hashed closure. Validation rejects
    # such values too; this is the second lock on the same door.
    return [f":(literal){p}" for p in literals] + globs


def content_pathspec(artifact: str = "pdf", cfg: KitConfig | None = None) -> list[str]:
    """`stamp_pathspec` minus `guide.toml` — the artifact's FILE inputs only.

    This is the scope for "when did this artifact's content last change". The
    config is deliberately excluded: it reaches the artifact key-level, and git
    cannot scope to a key, so including the whole file would let a committed
    `[deploy]`-only edit move the displayed date of a PDF that did not change by
    one byte of content. The closure hash still covers every config key that
    does matter, so nothing is lost by narrowing the DATE's scope."""
    return [p for p in stamp_pathspec(artifact, cfg) if p != ":(literal)guide.toml"]


def glob_matches(rel_path: str, pattern: str) -> bool:
    """Whether a repo-relative path is covered by a closure pattern.

    THE MEMBERSHIP PREDICATES USED `in` AGAINST A LIST CONTAINING GLOBS, which
    is a string equality test: `"assets/shared/diagram.pdf" in ("assets/shared/**",)`
    is False, so a declared PDF input answered "not an input". The consequences
    were real and opposite in each caller — `is_authorable` said no, so
    `release.py` REFUSED a release whose only change was a tracked asset; and
    `is_stamp_input` said no about a path whose bytes are genuinely in the hash.

    `**` spans separators. A single `*` does NOT, matching `font_files()` and
    `_is_font_path`, which are deliberately non-recursive so a stray nested
    directory cannot quietly join the render closure. Case-insensitive, matching
    the `:(glob,icase)` pathspecs and `_is_font_path`'s own suffix folding — a
    face named `.OTF` is the same input as one named `.otf`.
    """
    if pattern.endswith("/**"):
        # Keep the separator: `assets/shared/**` must not match `assets/shared2/x`.
        return rel_path.lower().startswith(pattern[:-2].lower())
    p_dir, _, p_base = pattern.rpartition("/")
    r_dir, _, r_base = rel_path.rpartition("/")
    return (p_dir.lower() == r_dir.lower()
            and fnmatch.fnmatchcase(r_base.lower(), p_base.lower()))


def is_stamp_input(rel_path: str, artifact: str = "pdf",
                   cfg: KitConfig | None = None) -> bool:
    """Whether a repo-relative path (as `git status --porcelain` reports it) is
    a stamp input. The membership counterpart to `stamp_pathspec()`, for callers
    that classify paths rather than scope a git command — `release.py` deciding
    which changes are in scope for a release.

    Deliberately a predicate over the NAME, not a disk lookup: a deleted face is
    still a stamp input (its removal changes the hash), and a disk-based check
    would answer False for exactly the path that most needs staging.

    PASS `cfg` WHENEVER YOU HAVE ONE, for the reason spelled out on
    `is_authorable`: without it the spec's `<theme>` and `<slides_file>`
    placeholders resolve to the schema's defaults, so a guide that chose either
    gets an answer about a file it does not use.
    """
    resolve = (lambda f: _resolve_pattern(f, cfg)) if cfg is not None else _with_defaults
    if rel_path == "guide.toml":
        return True
    spec = artifact_spec(artifact)
    # GENERATED deps too. `stamp_pathspec()` scopes git to file_deps AND
    # generated_deps — the site's closure names `<slug>.pdf`, the committed
    # reference it ships — so a predicate that consulted only `file_deps`
    # disagreed with the pathspec it is documented to be the counterpart of.
    for dep in spec.file_deps + spec.generated_deps:
        resolved = resolve(dep)
        if rel_path == resolved or ("*" in resolved
                                    and glob_matches(rel_path, resolved)):
            return True
    return _is_font_path(rel_path)


def is_authorable(rel_path: str, cfg: KitConfig | None = None) -> bool:
    """Whether a path is an authorable source of ANY artifact.

    This — not `is_stamp_input` — is what release staging asks: a site-only edit
    is in scope for a release even though it is outside the PDF's closure, and
    rejecting it as out-of-scope was the confusion the split removes.

    PASS `cfg` WHENEVER YOU HAVE ONE. Without it the answer comes from
    `AUTHORABLE_SOURCES`, the union resolved against the schema's *defaults* —
    so a guide with `[slides] file = "deck.md"` would have an edit to its real
    slide source refused as out-of-scope while an edit to the unused default
    `slides.md` was admitted. The static form exists only for callers that
    genuinely have no config to hand (the docs, and `SOURCE_FILES`)."""
    if rel_path in authorable_sources(cfg):
        return True
    if any(glob_matches(rel_path, g) for g in authorable_globs(cfg)):
        return True
    return _is_font_path(rel_path)


def content_hash(root: Path | None = None) -> str:
    """The PDF artifact's closure hash — the value the footer stamp embeds and
    the staleness check compares. A thin alias for
    `artifact_closure_hash("pdf")`, kept because every existing consumer and
    CLAUDE.md name it `content_hash`.

    `stamp_pathspec()` scopes git to the same closure; keep the two in step."""
    return artifact_closure_hash("pdf", root=root)


# ---------------------------------------------------------------------------
# ArtifactSpec — one dependency closure per artifact
#
# Replaces the single SOURCE_FILES list that drove all six of: the embedded
# hash, the source date, the dirty marker, baseline cleanliness, the stale-file
# diagnostic, and release staging. Those are different questions with different
# answers, and conflating them is what made a slides stylesheet a PDF input.
# ---------------------------------------------------------------------------

def _is_font_path(rel_path: str) -> bool:
    """Whether a repo-relative path names a bundled face.

    NON-RECURSIVE, matching `font_files()` and the closure globs: only files
    directly in `fonts/vendor/` count, so a stray nested directory cannot quietly
    join the render closure. Written as a prefix test rather than a two-part path
    split because the namespace is itself two segments deep now."""
    for directory in (FONT_DIR, GENERATED_FONT_DIR):
        prefix = directory + "/"
        if rel_path.startswith(prefix):
            tail = rel_path[len(prefix):]
            return "/" not in tail and tail.lower().endswith(_FONT_SUFFIXES)
    return False


_FONT_GLOBS = tuple(f"{d}/*{suffix}" for d in (FONT_DIR, GENERATED_FONT_DIR)
                    for suffix in _FONT_SUFFIXES)

# The identity constants that reach the rendered page of EVERY artifact.
_COMMON_IDENTITY = (
    "TITLE", "OUTPUT_SLUG", "AUTHOR", "DESCRIPTION", "KEYWORDS",
    "COPYRIGHT_YEAR", "theme.name", "theme.tokens",
)
# The artifact-neutral render inputs. `build.py` is now a thin CLI and
# `buildcore.py` holds the shared pipeline; both genuinely affect every
# artifact's bytes, so both stay here. The per-artifact renderer modules do NOT
# — each appears in exactly one closure below, which is what makes a website or
# slides change stop re-staling the PDF.
# `fontconfig/fonts.conf` is a RENDER INPUT: it decides which font any given
# family resolves to, so editing or deleting it changes the rendered bytes. Left
# out of the closure it would do so without moving the version stamp, without
# marking the tree dirty, and without being staged by a release.
# The font provenance record. It is a RENDER INPUT in the only sense that
# matters: `buildcore._assert_font_provenance` reads it on every build and
# REFUSES to render when a bundled face's hash does not match it. Left out of the
# closure — where it sat until the boundary review found it — deleting the file
# silently disabled the gate while `make verify` stayed green, and corrupting it
# broke the next build with no staleness signal beforehand. A check whose own
# input can change without moving the stamp is not a check.
_FONT_PROVENANCE = f"{FONT_DIR}/{'UPSTREAM-HASHES.json'}"

_COMMON_FILES = (
    "guide.md", "build.py", "buildcore.py", "transforms.py", "kitconfig.py",
    _FONT_PROVENANCE,
    # The cascade guard: buildcore imports it during rendering, and a change
    # to what it accepts changes what can reach the page.
    "cascadecheck.py",
    "fontconfig/fonts.conf",
    # The bundled @font-face declarations: a render input for every artifact,
    # and kit-owned so no guide can redefine a face.
    "fontfaces.css",
) + _FONT_GLOBS


@dataclass(frozen=True)
class StampRule:
    """(d) How one artifact stamps itself.

    `source_date` names where the artifact's displayed date comes from. It reads
    "artifact-date": the authored `[artifacts.<name>] date` key. It said "git"
    while the date came from `git log` over a pathspec, and this field existing
    is what made that move a one-line, visible change rather than a hunt through
    the renderer."""

    embeds_stamp: bool
    source_date: str
    dirty_marker: bool


@dataclass(frozen=True)
class ArtifactSpec:
    """The complete dependency contract for one artifact."""

    name: str
    config_keys: tuple[str, ...]      # (a) key-level, never whole-file
    file_deps: tuple[str, ...]        # (b) literal paths and globs
    generated_deps: tuple[str, ...]   # (c) edges onto other artifacts' output
    stamp: StampRule                  # (d)
    reference: str | None             # (e) committed reference artifact, if any
    release_staging: tuple[str, ...]  # (f) what release.py may stage for it
    # Why (e) is None, in the artifact's own terms. `verify --staleness` prints
    # it verbatim on the no-reference path, and the reasons genuinely differ:
    # the site has no committed bytes to hash and never will, while the deck is
    # a file whose release path simply is not built yet. One shared sentence
    # would have to be false about one of them.
    no_reference_reason: str = ""


_STAMPED = StampRule(embeds_stamp=True, source_date="artifact-date", dirty_marker=True)

_ARTIFACT_SPECS: dict[str, ArtifactSpec] = {
    "pdf": ArtifactSpec(
        name="pdf",
        config_keys=_COMMON_IDENTITY + ("outputs.pdf", "artifacts.pdf.date", "fonts.cjk"),
        # By CONTENT HASH, via the recursive glob: swapping an image's bytes
        # without changing its name re-stales the PDF. `assets/web/**` is
        # deliberately absent — a screen-only image must not be a PDF input, or
        # the split buys nothing.
        file_deps=_COMMON_FILES + ("themes/<theme>/print.css", "style.css",
                                   "render_pdf.py",
                                   "assets/shared/**", "assets/print/**"),
        generated_deps=(),
        stamp=_STAMPED,
        reference="<slug>.pdf",
        release_staging=_COMMON_FILES + ("style.css", "render_pdf.py", "guide.toml",
                                         "assets/shared/**", "assets/print/**"),
    ),
    "site": ArtifactSpec(
        name="site",
        config_keys=_COMMON_IDENTITY + (
            "outputs.site", "artifacts.site.date", "fonts.cjk",
            "site.canonical", "site.chapter_level", "deploy.domain",
        ),
        # cfadapter.py is a site input, not merely an import: it writes `_headers`
        # into the built tree. Leaving it out would let an adapter-only change sync
        # into every target without moving the site's closure hash — so nothing
        # would report the site stale and nothing would trigger a redeploy, while
        # production kept serving the previous build.
        # chapters.py is a site input and deliberately NOT a pdf one: the split
        # decides the page set, so a change to it changes the site — while a
        # multipage change must never re-stale eight reference PDFs, which is
        # the property the whole build.py split exists to create.
        file_deps=_COMMON_FILES + ("themes/<theme>/print.css",
                                   "themes/<theme>/screen.css", "style-screen.css",
                                   "render_site.py", "cfadapter.py", "chapters.py",
                                   "assets/shared/**", "assets/web/**"),
        # The site ships the released PDF; that is a real edge, declared rather
        # than discovered when the site serves a 404 download link.
        generated_deps=("<slug>.pdf",),
        stamp=_STAMPED,
        reference=None,
        no_reference_reason=("a site is deployed, not blessed into the repo — there are "
                             "no committed bytes to hash, so staleness is not a question "
                             "that can be asked of it here"),
        release_staging=_COMMON_FILES + ("style-screen.css", "render_site.py",
                                         "cfadapter.py", "chapters.py", "guide.toml"),
    ),
    "slides": ArtifactSpec(
        name="slides",
        config_keys=_COMMON_IDENTITY + (
            "outputs.slides", "artifacts.slides.date", "fonts.cjk",
            "slides.source", "slides.file",
        ),
        # <slides_file> resolves from [slides] file, not a hardcoded slides.md:
        # with source = "file" and file = "deck.md", a literal would leave the
        # real source outside the closure and deck.md edits would never re-stale
        # the deck.
        file_deps=_COMMON_FILES + ("themes/<theme>/print.css",
                                   "themes/<theme>/slides.css", "style-slides.css",
                                   "<slides_file>", "render_slides.py"),
        generated_deps=(),
        stamp=_STAMPED,
        # The deck DOES have a committed reference now, and the thing that
        # changed is not an opinion — it is `baseline.py --artifact` plus
        # baseline.yml looping over every artifact that has one. Until those
        # existed, setting this was a trap: the deck shares `_COMMON_FILES` with
        # the PDF, so any buildcore/kitconfig change stales both, and a refresher
        # that only knew about the PDF would leave the deck permanently red.
        #
        # The site stays None for a different and permanent reason — it is
        # deployed rather than blessed into the repo, so there are no committed
        # bytes for staleness to be a question about.
        reference="<slug>-slides.pdf",
        release_staging=_COMMON_FILES + ("style-slides.css", "<slides_file>", "render_slides.py", "guide.toml"),
    ),
}

# (task 5) The union of AUTHORABLE source files — deliberately a different set
# from any one artifact's closure. release.py's staging policy and the dirty
# checks ask "what may a human have edited here?", which is a broader question
# than "what does the PDF depend on?".
def _with_defaults(pattern: str) -> str:
    """Resolve a spec placeholder using the schema's own defaults.

    The authorable union is a static, config-free view (release tooling and the
    docs both name it), so placeholders resolve to their default here. Callers
    that have a config should use `authorable_sources(cfg)`, which resolves
    against that guide's actual values."""
    return pattern.replace("<slides_file>", SlidesConfig().file).replace(
        "<theme>", DEFAULT_THEME)


AUTHORABLE_SOURCES: tuple[str, ...] = tuple(sorted(
    {_with_defaults(f) for spec in _ARTIFACT_SPECS.values()
     for f in spec.file_deps if "*" not in f}
    | {"guide.toml"}
))
# EVERY glob any artifact declares, not just the fonts. The font globs alone
# were the whole list, which quietly excluded `assets/**` — so a guide could not
# release an edit to a tracked asset that is a declared input of the very PDF
# being released. Derived from the specs rather than listed, so a spec that
# gains a glob cannot leave this behind.
AUTHORABLE_GLOBS: tuple[str, ...] = tuple(sorted(
    {_with_defaults(f) for spec in _ARTIFACT_SPECS.values()
     for f in spec.file_deps if "*" in f}
    | set(_FONT_GLOBS)
))


def authorable_globs(cfg: KitConfig | None = None) -> tuple[str, ...]:
    """`AUTHORABLE_GLOBS` resolved against `cfg` (defaults when None).

    The counterpart to `authorable_sources()`; the two are one set split by
    whether the pattern contains a wildcard, and a caller asking "may a human
    have edited this?" needs both halves.
    """
    if cfg is None:
        return AUTHORABLE_GLOBS
    return tuple(sorted(
        {_resolve_pattern(f, cfg) for spec in _ARTIFACT_SPECS.values()
         for f in spec.file_deps if "*" in f}
        | set(_FONT_GLOBS)
    ))


def authorable_sources(cfg: KitConfig | None = None) -> tuple[str, ...]:
    """The authorable union resolved against `cfg` (defaults when None), so a
    guide whose slides live in `deck.md` reports `deck.md`, not `slides.md`."""
    if cfg is None:
        return AUTHORABLE_SOURCES
    return tuple(sorted(
        {_resolve_pattern(f, cfg) for spec in _ARTIFACT_SPECS.values()
         for f in spec.file_deps if "*" not in f}
        | {"guide.toml"}
    ))

# The PDF's authorable inputs, kept under the historical name because every
# consumer and CLAUDE.md still say "SOURCE_FILES". Derived from the pdf spec so
# it cannot drift from the closure. Note ORDER is no longer significant: the
# hash sorts its inputs by repo-relative path rather than concatenating in list
# order, so this is a set, not a sequence contract.
SOURCE_FILES: list[str] = sorted(
    {_with_defaults(f) for f in _ARTIFACT_SPECS["pdf"].file_deps if "*" not in f}
    | {"guide.toml"}
)


# ---------------------------------------------------------------------------
# The version stamp grammar — ONE definition, three consumers
#
# `YYYY-MM-DD · <sha256[:12]>` (+ ` · dirty`). It lives here, in the module both
# the renderer and the verifier already import, because it previously existed as
# a regex in the verifier and an f-string in the renderer: two spellings of one
# contract, free to drift. The composer, `strip_stamp` (which keeps the render
# canary green) and the footer-wrap detector must move together, and a single
# definition is what makes that structural rather than a promise.
#
# The date half is the artifact's authored EDITION date. It used to be
# `YYYY-MM-DD HH:MM:SS` derived from git history over a path, which is why the
# time component is gone: there is no commit instant to report any more.
# ---------------------------------------------------------------------------

STAMP_SEP = "·"

# `\s*` around the separators is deliberate and load-bearing: pdftotext may fold
# a footer across a line break, and STALENESS still wants the hash in that case.
# Detecting the fold is the footer-wrap check's job, geometrically — not this
# regex's, which is why it must stay permissive here.
# The trailing negative lookahead is what makes the parse STRUCTURED rather than
# merely permissive: without it `<date> · <hash> · stale` parses as a clean stamp
# with dirty=False, and promotion would approve an artifact wearing a segment the
# grammar does not model. Anything after the hash that looks like another
# `· <token>` and is not `dirty` therefore fails to parse at all.
_STAMP_RE = re.compile(
    r"(\d{4}-\d\d-\d\d)\s*" + STAMP_SEP + r"\s*([0-9a-f]{12})"
    r"(?:\s*" + STAMP_SEP + r"\s*(dirty))?"
    r"(?!\s*" + STAMP_SEP + r")"
)


@dataclass(frozen=True)
class Stamp:
    """A parsed version stamp.

    Structured rather than a string match, so a consumer cannot silently accept
    an unknown suffix: promotion asks `stamp.dirty`, and anything the grammar
    does not model simply fails to parse instead of being ignored."""

    date: str
    hash: str
    dirty: bool


def format_stamp(date: str, content_hash: str, dirty: bool = False) -> str:
    """Compose the rendered stamp. The single writer of this format."""
    text = f"{date} {STAMP_SEP} {content_hash}"
    if dirty:
        text += f" {STAMP_SEP} dirty"
    return text


def parse_stamp(text: str) -> Stamp | None:
    """The single reader. None when no stamp is present — including a stamp in
    a format this grammar no longer accepts, which is why a reference rendered
    before a grammar change reads as *unreadable* rather than as fresh."""
    m = _STAMP_RE.search(text)
    if m is None:
        return None
    return Stamp(date=m.group(1), hash=m.group(2), dirty=m.group(3) == "dirty")


def parse_stamp_exact(text: str) -> Stamp | None:
    """Like `parse_stamp`, but the WHOLE string must be the stamp.

    Used where a candidate span is being tested rather than searched for: a
    searching parse finds a stamp *inside* a longer span, which would let an
    unrelated leading token be counted as part of it."""
    m = _STAMP_RE.fullmatch(text.strip())
    if m is None:
        return None
    return Stamp(date=m.group(1), hash=m.group(2), dirty=m.group(3) == "dirty")


def strip_stamp(text: str) -> str:
    """Remove every stamp occurrence — what the render canary compares around,
    since the stamp legitimately differs between two renders of one source."""
    return _STAMP_RE.sub("", text)


def artifact_spec(name: str) -> ArtifactSpec:
    """The closure contract for `name`. Raises on an unknown artifact rather
    than returning a permissive default."""
    try:
        return _ARTIFACT_SPECS[name]
    except KeyError:
        raise KitConfigError(
            f"unknown artifact {name!r} (known: {list(ARTIFACT_NAMES)})"
        ) from None


def _lookup(cfg: KitConfig, dotted: str):
    """Resolve a dotted config key against a validated KitConfig."""
    parts = dotted.split(".")
    if parts[0] == "artifacts":
        art = cfg.artifacts.get(parts[1])
        return None if art is None else getattr(art, parts[2])
    value = getattr(cfg, parts[0])
    for part in parts[1:]:
        value = getattr(value, part)
    return value


def config_projection(cfg: KitConfig, keys: tuple[str, ...],
                      overrides: dict[str, object] | None = None) -> dict:
    """The EFFECTIVE values of `keys`.

    Effective, not raw: a config that omits an optional key projects the same
    value as one that spells out that key's default, so a purely cosmetic config
    edit cannot re-stale a reference artifact.

    `overrides` answers a counterfactual — "what would this closure hash to if
    one key held a different value?" — which is how `closure_hash_at_date` asks
    whether the CONTENT changed independently of the edition date. An override
    naming a key outside `keys` raises rather than silently doing nothing: it
    would otherwise read as a comparison being made that is not."""
    over = overrides or {}
    unknown = sorted(set(over) - set(keys))
    if unknown:
        raise KitConfigError(
            f"config_projection: override key(s) {unknown} are not in this "
            f"projection, so overriding them would change nothing"
        )
    return {k: (over[k] if k in over else _lookup(cfg, k)) for k in keys}


def _resolve_pattern(pattern: str, cfg: KitConfig) -> str:
    """Substitute the config-derived placeholders a spec may carry."""
    return (
        pattern
        .replace("<slug>", cfg.OUTPUT_SLUG)
        .replace("<slides_file>", cfg.slides.file)
        .replace("<theme>", cfg.theme.name)
    )


def _expand(base: Path, patterns: tuple[str, ...], cfg: KitConfig) -> list[Path]:
    """Resolve literal paths and globs to existing files, deterministically
    sorted by repo-relative path — never by filesystem enumeration order, which
    differs between ext4 and APFS and would make the hash host-dependent.

    Globs match CASE-INSENSITIVELY and non-recursively, which is what keeps this
    in step with `font_files()` and `is_stamp_input()`. Both of those have always
    compared suffixes case-folded, so a plain case-sensitive `Path.glob` would
    accept `fonts/Face.TTF` as a stamp input while silently omitting its bytes
    from the hash — a face swap that moves the render and not the stamp."""
    found: set[Path] = set()
    for pattern in patterns:
        pattern = _resolve_pattern(pattern, cfg)
        if pattern.endswith("/**"):
            # A RECURSIVE tree. `assets/shared/**` is a directory of images an
            # author organises however they like, so unlike the flat font globs
            # this one has to descend. Symlinks are not followed: `is_file()`
            # would accept a link pointing outside the repo, and its bytes would
            # then join the closure hash of an artifact that does not contain it.
            directory = base / pattern[:-3]
            if directory.is_dir():
                found.update(
                    p for p in directory.rglob("*")
                    if p.is_file() and not p.is_symlink()
                )
        elif "*" in pattern:
            parent, _, name_pat = pattern.rpartition("/")
            directory = base / parent if parent else base
            if directory.is_dir():
                found.update(
                    p for p in directory.iterdir()
                    if p.is_file() and fnmatch.fnmatch(p.name.lower(), name_pat.lower())
                )
        else:
            p = base / pattern
            if p.is_file():
                found.add(p)
    return sorted(found, key=lambda p: p.relative_to(base).as_posix())


def _feed(h, *chunks: bytes) -> None:
    """Absorb length-framed records into `h`.

    Framing is load-bearing, not decoration: concatenating `name + bytes`
    unframed means a face `fonts/a.otf` whose content starts `x.otf` and an
    empty face named `fonts/a.otfx.otf` present the hash the same byte stream,
    so two different closures collide. `sync.py` already frames its digest
    records for the same reason."""
    for chunk in chunks:
        h.update(len(chunk).to_bytes(8, "big"))
        h.update(chunk)


def content_digest(name: str, root: Path | None = None, cfg: KitConfig | None = None) -> str:
    """The artifact's closure hash with its OWN edition date excluded.

    This is the identity of the CONTENT about to be released, as distinct from
    the identity of a released edition. The distinction is load-bearing for the
    release transaction: the date is what a transaction ASSIGNS, so it cannot
    also be part of the key that finds the transaction. Keyed on the full
    closure, writing the date would open a second transaction — the resume path
    would never find the instant it captured, and a hand-set date could never be
    detected as disagreeing with it."""
    spec = artifact_spec(name)
    keys = tuple(k for k in spec.config_keys if k != f"artifacts.{name}.date")
    return _closure_hash(name, keys, root=root, cfg=cfg)


def closure_hash_at_date(
    name: str, date: str, root: Path | None = None, cfg: KitConfig | None = None
) -> str:
    """`artifact_closure_hash` computed as if the artifact's edition date were
    `date` — the counterfactual "what would the tree AS IT STANDS have hashed to
    when that date was current?".

    This is what proves an artifact is genuinely new. Comparing the artifact's
    hash as authored against the last released hash does not: the date key is
    inside the closure, so hand-editing the date alone moves the hash and a
    byte-identical artifact masquerades as a new edition. Normalising the
    candidate to the last released date removes the date from the comparison
    without removing it from the identity."""
    key = f"artifacts.{name}.date"
    return _closure_hash(name, artifact_spec(name).config_keys, root=root, cfg=cfg,
                         overrides={key: date})


def artifact_closure_hash(
    name: str, root: Path | None = None, cfg: KitConfig | None = None
) -> str:
    """12-char sha256 prefix over one artifact's complete closure: its key-level
    config projection, then every file and generated dependency that exists.

    Each file contributes its NAME as well as its bytes — without that, renaming
    a font face (which changes which @font-face src resolves, hence the render)
    would leave the concatenated bytes identical and the hash unmoved."""
    return _closure_hash(name, artifact_spec(name).config_keys, root=root, cfg=cfg)


def _closure_hash(name: str, keys: tuple[str, ...], root: Path | None = None,
                  cfg: KitConfig | None = None,
                  overrides: dict[str, object] | None = None) -> str:
    base = _root(root)
    spec = artifact_spec(name)
    cfg = cfg if cfg is not None else load(base)

    h = hashlib.sha256()
    _feed(h, json.dumps(
        config_projection(cfg, keys, overrides),
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8"))
    for p in _expand(base, spec.file_deps + spec.generated_deps, cfg):
        _feed(h, p.relative_to(base).as_posix().encode("utf-8"), p.read_bytes())
    return h.hexdigest()[:12]


def font_files(root: Path | None = None) -> list[Path]:
    """Every bundled font face, sorted by filename. Empty when the directory is
    absent, so a fork that has not adopted bundled fonts hashes exactly as
    before."""
    found: list[Path] = []
    for directory in (FONT_DIR, GENERATED_FONT_DIR):
        d = _root(root) / directory
        if d.is_dir():
            found += [p for p in d.iterdir() if p.suffix.lower() in _FONT_SUFFIXES]
    # Sorted by REPO-RELATIVE path, not bare name: two directories can hold the
    # same filename, and sorting by name alone would make the order depend on
    # which directory was walked first.
    return sorted(found, key=lambda p: p.relative_to(_root(root)).as_posix())
