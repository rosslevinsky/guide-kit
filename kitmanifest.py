#!/usr/bin/env python3
"""Loader + resolver for kit-manifest.toml — the two-axis file classification.

Deliberately a SEPARATE module from kitconfig.py: kitconfig.py is a canonical
SOURCE_FILES entry, so putting this logic there would move the content hash and
re-stale the reference PDF. The manifest affects sync and bootstrap, not
rendering, so it stays OUT of SOURCE_FILES.

Two independent axes (see kit-manifest.toml's header):
  * source lifecycle — retained-in-kit / bootstrap-source / generated (required)
  * destination policy — identical / templated / managed-region / never, present
    only when the file has a projected live path (`projects_to` + `policy`).

Stdlib only (tomllib on >=3.11, tomli fallback), so it is dependency-light.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

LIFECYCLES = frozenset({"retained-in-kit", "bootstrap-source", "generated"})
POLICIES = frozenset({"identical", "templated", "managed-region", "never"})


class ManifestError(Exception):
    """Raised when kit-manifest.toml is malformed or an entry is invalid."""


@dataclass(frozen=True)
class Entry:
    path: str
    lifecycle: str
    projects_to: str | None = None
    policy: str | None = None

    @property
    def is_glob(self) -> bool:
        return self.path.endswith("/**")

    @property
    def prefix(self) -> str:
        return self.path[:-3] if self.is_glob else self.path  # strip "/**"

    @property
    def has_destination(self) -> bool:
        return self.policy is not None

    @property
    def web_only(self) -> bool:
        # Every bootstrap-source entry is a web-layer file: its destination is
        # materialized only by bootstrap --with-web / adopt-web, so it is inert
        # in a PDF-only target.
        return self.lifecycle == "bootstrap-source"


@dataclass(frozen=True)
class Projection:
    source: str
    dest: str
    policy: str
    web_only: bool


class Manifest:
    def __init__(self, entries: list[Entry]):
        self.entries = entries

    def classify(self, path: str) -> Entry | None:
        """The entry governing `path`: an exact match wins over a glob prefix."""
        for e in self.entries:
            if not e.is_glob and e.path == path:
                return e
        for e in self.entries:
            if e.is_glob and (path == e.prefix or path.startswith(e.prefix + "/")):
                return e
        return None

    def projections(self, shape: str, slug: str | None = None) -> list[Projection]:
        """Source -> destination list for a target shape.

        shape is "web-enabled" (all projections) or "pdf-only" (web-layer
        projections are inert and excluded — plan.md:76). A destination may carry
        a `<slug>` placeholder (only the reference PDF does today); pass `slug` to
        resolve it to a concrete path — sync does this from the target's
        guide.toml. Without `slug` the placeholder is left verbatim."""
        if shape not in ("web-enabled", "pdf-only"):
            raise ManifestError(f"unknown target shape {shape!r}")
        out: list[Projection] = []
        for e in self.entries:
            if not e.has_destination:
                continue
            if shape == "pdf-only" and e.web_only:
                continue
            dest = e.projects_to
            assert dest is not None and e.policy is not None  # has_destination guarantees both
            if slug is not None:
                dest = dest.replace("<slug>", slug)
            out.append(Projection(e.path, dest, e.policy, e.web_only))
        return out


def _validate(entry: Entry) -> Entry:
    if entry.lifecycle not in LIFECYCLES:
        raise ManifestError(
            f"{entry.path}: lifecycle {entry.lifecycle!r} not in {sorted(LIFECYCLES)}"
        )
    # projects_to and policy travel together — a destination is both or neither.
    if (entry.projects_to is None) != (entry.policy is None):
        raise ManifestError(
            f"{entry.path}: projects_to and policy must be set together (a destination "
            f"is both or neither); got projects_to={entry.projects_to!r}, policy={entry.policy!r}"
        )
    if entry.policy is not None and entry.policy not in POLICIES:
        raise ManifestError(f"{entry.path}: policy {entry.policy!r} not in {sorted(POLICIES)}")
    return entry


def load(root: Path | None = None) -> Manifest:
    """Read, validate, and return kit-manifest.toml from `root` (default: this
    file's directory)."""
    base = (root if root is not None else Path(__file__).parent).resolve()
    toml_path = base / "kit-manifest.toml"
    if not toml_path.is_file():
        raise ManifestError(f"kit-manifest.toml not found at {toml_path}")
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"kit-manifest.toml is not valid TOML: {exc}") from exc

    raw_entries = data.get("entry", [])
    if not raw_entries:
        raise ManifestError("kit-manifest.toml has no [[entry]] tables")

    entries: list[Entry] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if "path" not in raw or "lifecycle" not in raw:
            raise ManifestError(f"entry missing path/lifecycle: {raw!r}")
        path = raw["path"]
        if path in seen:
            raise ManifestError(f"duplicate manifest entry for {path!r}")
        seen.add(path)
        entries.append(
            _validate(Entry(
                path=path,
                lifecycle=raw["lifecycle"],
                projects_to=raw.get("projects_to"),
                policy=raw.get("policy"),
            ))
        )
    return Manifest(entries)
