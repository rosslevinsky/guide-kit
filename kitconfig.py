#!/usr/bin/env python3
"""Strict loader/validator for guide.toml, plus the canonical SOURCE_FILES list
and the content-hash helper shared across the kit's tooling.

This module is the SINGLE reader of guide.toml. It *validates* rather than
trusts (plan.md:56): required keys present, correct types, kebab-case
OUTPUT_SLUG, an enum for baseline_platform, an integer COPYRIGHT_YEAR, and every
slug-derived path resolved and asserted to stay inside the repo root.

Deliberately DEPENDENCY-LIGHT — it imports only the standard library (no
WeasyPrint, no pandoc), so the fast staleness check built on top of it (Phase 3)
stays milliseconds and platform-independent (plan.md:236).

Phase 1 introduces this file WITHOUT rewiring the existing consumers. build.py
keeps its own constants and _content_hash for now; Phase 2 rewires build.py,
release.py, verify_pdf.py, verify_web.py, and sync.py to read through here. From
this point on, the canonical copies of SOURCE_FILES and the content hash live in
this file.
"""
from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # Python >= 3.11 (the raised pixi floor guarantees this)
except ModuleNotFoundError:  # pragma: no cover - floor is >=3.11
    import tomli as tomllib  # type: ignore[no-redef]

# The canonical version-stamp input list. guide.toml and kitconfig.py join the
# original four: moving the per-guide constants into guide.toml (and the loader
# logic into kitconfig.py) means a change to either can alter the rendered page
# while leaving the old four-file hash untouched — so both become build input
# (plan.md:59, :61).
SOURCE_FILES = [
    "guide.md",
    "style.css",
    "build.py",
    "transforms.py",
    "guide.toml",
    "kitconfig.py",
]

# Mirrors bootstrap.py's SLUG_RE (kebab-case). Kept as a local copy rather than
# importing bootstrap.py so kitconfig stays dependency-light and bootstrap can be
# rewired to read from here later without a circular import.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

# The values sys.platform can take; the make baseline/release guard compares the
# recorded baseline_platform against sys.platform. Keyed on the recorded value,
# never hardcoded to macOS — a Linux forker records "linux" and baselines
# normally (plan.md:102).
_PLATFORM_ENUM = ("darwin", "linux", "win32")

# key -> expected python type. COPYRIGHT_YEAR is int; the rest are str.
_REQUIRED: dict[str, type] = {
    "TITLE": str,
    "OUTPUT_SLUG": str,
    "AUTHOR": str,
    "DESCRIPTION": str,
    "KEYWORDS": str,
    "COPYRIGHT_YEAR": int,
    "baseline_platform": str,
}


class KitConfigError(Exception):
    """Raised when guide.toml is missing, malformed, or fails validation."""


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
    baseline_platform: str


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


def _validate(data: dict, base: Path) -> KitConfig:
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

    platform = data["baseline_platform"]
    if platform not in _PLATFORM_ENUM:
        raise KitConfigError(
            f"guide.toml: baseline_platform {platform!r} not in {list(_PLATFORM_ENUM)}"
        )

    # Defense in depth: every slug-derived OUTPUT path must resolve inside the
    # repo root. _SLUG_RE (fullmatch) already forbids slashes, dots, and
    # newlines, so a traversal slug can't reach here — but asserting containment
    # on the ACTUAL derived paths makes the guarantee explicit and survives any
    # future loosening of the grammar (plan.md:56). These mirror build.py's
    # REFERENCE_PDF (:103), OUT_PDF (:95), and OUT_HTML (:96). Symlinked output
    # directories are an explicit Non-Goal (plan.md:207), so plain is_relative_to
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

    return KitConfig(
        TITLE=data["TITLE"],
        OUTPUT_SLUG=slug,
        AUTHOR=data["AUTHOR"],
        DESCRIPTION=data["DESCRIPTION"],
        KEYWORDS=data["KEYWORDS"],
        COPYRIGHT_YEAR=data["COPYRIGHT_YEAR"],
        baseline_platform=platform,
    )


def baseline_platform_matches(
    root: Path | None = None, current_platform: str | None = None
) -> tuple[bool, str]:
    """Return (ok, message) for whether this host may take a baseline for the
    guide at `root`. `make baseline` / `make release` refuse when they don't
    match (unless explicitly overridden) so a Linux VM can't render a
    Linux-typography PDF into a family of macOS-rendered ones (plan.md:102).
    Keyed on the recorded platform, never hardcoded to macOS — a Linux forker
    records "linux" and baselines normally. `current_platform` is injectable for
    tests; it defaults to sys.platform."""
    cfg = load(root)
    current = current_platform if current_platform is not None else sys.platform
    if current == cfg.baseline_platform:
        return True, f"platform OK ({current} == baseline_platform)"
    return (
        False,
        f"platform mismatch: this host is {current!r} but guide.toml records "
        f"baseline_platform={cfg.baseline_platform!r}",
    )


def content_hash(root: Path | None = None) -> str:
    """12-char sha256 prefix over the concatenated bytes of every SOURCE_FILES
    entry that exists on disk, in the fixed SOURCE_FILES order. Dependency-light
    — nothing heavier than hashlib — so callers get a fast staleness signal
    without pulling in the renderer."""
    base = _root(root)
    h = hashlib.sha256()
    for name in SOURCE_FILES:
        p = base / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]
