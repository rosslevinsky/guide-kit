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

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

LIFECYCLES = frozenset({"retained-in-kit", "bootstrap-source", "generated"})
POLICIES = frozenset({"identical", "templated", "managed-region", "never"})
# Every shape `projections()` accepts. Named once so "the kit declares this
# destination under SOME shape" is derived from the enum rather than from a
# second hand-maintained list that would silently stop covering a new shape —
# and sync's deletion path turns that question into a file removal in seven
# repositories.
SHAPES = ("web-enabled", "pdf-only")


def _tree_base_readable(kit_root: Path, src_prefix: str) -> bool:
    """Whether a tree entry is present COMPLETELY and safe to walk.

    The BASE is checked before anything under it. Validating each file against
    `base.resolve()` is circular if `base` is itself a link: `fonts -> /elsewhere`
    anchors the whole comparison outside the repository, every external file
    passes, and the tree projects content the kit does not contain into all seven
    targets.

    Then completeness, which the base alone does not establish. A sparse checkout
    need not lose the whole directory: `fonts/` can be present with a tracked
    `fonts/B.ttf` absent, and checking only the base reports the tree readable
    while expansion silently omits B — which the deletion path cannot tell from
    the kit having removed B upstream. The precise question is therefore not
    "does the directory exist" but "is every path git still TRACKS actually
    here". A face genuinely deleted upstream is untracked by the commit that
    deleted it, so this never blocks a real deletion; a face merely absent is
    still tracked, and blocks one.

    `lexists`, not `exists`: expansion deliberately skips a tracked symlink
    rather than following it, and a skipped symlink is present, not missing.
    When git cannot answer (`_tracked_under` -> None) completeness is unknowable,
    so this degrades to the base check — the same way expansion degrades.

    Shared with `unreadable_tree_dests` so expansion and the deletion path agree
    on what "readable" means — if they disagreed, the deletion path would fail
    closed on trees expansion had happily read, or worse, the reverse."""
    base = kit_root / src_prefix
    if not base.is_dir() or base.is_symlink():
        return False
    root_resolved = kit_root.resolve()
    base_resolved = base.resolve()
    if not (base_resolved == root_resolved or root_resolved in base_resolved.parents):
        return False
    tracked = _tracked_under(kit_root, src_prefix)
    if tracked is None:
        return True
    return all(os.path.lexists(kit_root / rel) for rel in tracked)


def _tracked_under(root: Path, prefix: str) -> set[str] | None:
    """Repo-relative paths git tracks under `prefix`, or None when that cannot be
    established (not a repo yet, or no git) — in which case the caller falls back
    to the filesystem walk, which is what keeps `bootstrap.py` working in a fresh
    fork before `git init`."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", prefix],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return {p for p in out.split("\0") if p}


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
        """The entry governing `path`: an exact match wins, then the LONGEST
        matching glob prefix.

        Longest-match, not first-match, is what lets ownership namespaces nest:
        `fonts/**` is kit-owned while `fonts/generated/**` inside it is
        target-owned, and only the longer prefix winning makes the inner
        namespace mean anything. First-match made the answer depend on the order
        entries happen to appear in the file."""
        for e in self.entries:
            if not e.is_glob and e.path == path:
                return e
        matches = [e for e in self.entries
                   if e.is_glob and (path == e.prefix or path.startswith(e.prefix + "/"))]
        if not matches:
            return None
        return max(matches, key=lambda e: len(e.prefix))

    def expanded_projections(self, kit_root: Path, shape: str,
                             slug: str | None = None) -> list[Projection]:
        """`projections`, with every TREE entry expanded to the files it covers.

        A glob projection (`fonts/**` -> `fonts/**`) is a directory-tree
        projection: one declaration standing for however many files are in the
        kit's tree today. Before this existed, `projects_to` was resolved as a
        literal path, so a glob destination made sync try to read a file called
        `fonts/**` and the copy failed — which is why the font faces were
        ENUMERATED one manifest entry each, the paired edit the glob was meant to
        remove.

        Files governed by a LONGER entry are excluded here, not merely
        deprioritised: `fonts/generated/**` being target-owned has to mean the
        kit-owned `fonts/**` projection does not also claim those files.

        Ordering is by destination, so callers that hash the result (the managed
        digest) get a stable answer independent of filesystem enumeration order,
        which differs between ext4 and APFS."""
        out: list[Projection] = []
        for proj in self.projections(shape, slug=slug):
            if not proj.source.endswith("/**"):
                out.append(proj)
                continue
            src_prefix = proj.source[:-3]
            dest_prefix = proj.dest[:-3]
            base = kit_root / src_prefix
            if not _tree_base_readable(kit_root, src_prefix):
                continue        # unfilled, missing, or not safely readable
            base_resolved = base.resolve()
            tracked = _tracked_under(kit_root, src_prefix)
            for path in sorted(base.rglob("*")):
                # SYMLINKS ARE SKIPPED, not followed. `is_file()` follows them, so
                # a tracked `fonts/host-secret -> ~/.ssh/id_rsa` would satisfy it
                # and the expansion would hand sync a projection whose "kit bytes"
                # are read from outside the repository — and copied into every
                # target. The resolved-parent check is the second lock: a symlinked
                # DIRECTORY inside the tree cannot smuggle files in either.
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    resolved_parent = path.parent.resolve()
                except OSError:
                    continue
                if resolved_parent != base_resolved and base_resolved not in resolved_parent.parents:
                    continue
                rel = path.relative_to(kit_root).as_posix()
                # Only TRACKED files are projected. `rglob` happily returns
                # `.DS_Store`, editor droppings and `node_modules/` — none of
                # which dirty the kit (they are gitignored) yet all of which
                # would be copied into, and recorded in, every target.
                if tracked is not None and rel not in tracked:
                    continue
                owner = self.classify(rel)
                if owner is None or owner.path != proj.source:
                    continue                  # a nested namespace owns it
                tail = path.relative_to(base).as_posix()
                out.append(Projection(rel, f"{dest_prefix}/{tail}", proj.policy,
                                      proj.web_only))
        return sorted(out, key=lambda p: (p.dest, p.policy))

    def target_owned_dests(self, shape: str, slug: str | None = None):
        """(exact destinations, tree prefixes) the TARGET owns — every `never`
        projection, whether or not the kit currently has a file there.

        Membership must be decided by NAMESPACE, not by which files exist: a
        `never` file the kit has since deleted is exactly the case where the
        enclosing kit-owned tree would otherwise call it an upstream deletion."""
        exact, prefixes = set(), []
        for p in self.projections(shape, slug=slug):
            if p.policy != "never":
                continue
            if p.dest.endswith("/**"):
                prefixes.append(p.dest[:-3])
            else:
                exact.add(p.dest)
        return exact, prefixes

    def unreadable_tree_dests(self, kit_root: Path, slug: str | None = None) -> list[str]:
        """Destination prefixes of managed trees the kit DECLARES but cannot read.

        Unioned over `SHAPES`, for the same reason `dests_under_any_shape` is: the
        deletion path considers a destination from ANY shape, so a guard computed
        for the active shape alone has a hole exactly the width of the difference
        between them. A pdf-only target skips a web-only tree entirely — which
        would leave that tree's recorded destinations eligible for deletion while
        the guard that exists to protect them never looked at it.

        Expansion answers "which files are in this tree" by reading the kit's
        filesystem, and it cannot distinguish "the tree is empty" from "the tree
        did not appear". Both yield no destinations — and to the deletion path
        that is indistinguishable from the kit having removed every file in the
        tree at once. A sparse checkout, an interrupted clone or a mount that did
        not come up would therefore delete a whole managed tree across seven
        repositories, while the manifest and the git index both still declare it.

        So the deletion path fails closed on these instead. `never` trees are
        excluded: sync does not write them, so nothing under them is its to
        remove."""
        out: set[str] = set()
        for shape in SHAPES:
            for proj in self.projections(shape, slug=slug):
                if not proj.source.endswith("/**") or proj.policy == "never":
                    continue
                if not _tree_base_readable(kit_root, proj.source[:-3]):
                    out.add(proj.dest[:-3])
        return sorted(out)

    def dests_under_any_shape(self, kit_root: Path, slug: str | None = None) -> set[str]:
        """Every destination the kit declares under ANY shape, `never` included.

        The question sync's deletion path actually asks. "Absent from this
        target's projections" conflates two different events: the kit removed the
        entry (an upstream deletion, sync's to act on), and this target's
        `[outputs]` no longer wants an entry the kit still has (the `disable`
        transition, `adopt.py`'s to act on — config-first, refusing a dirty tree).
        Unioning over `SHAPES` separates them: a destination in this set is one
        the kit still classifies, whatever the target declares.

        Tree entries are expanded, so a face removed from `fonts/**` leaves this
        set exactly as a removed literal entry does — which is why one deletion
        protocol now covers both."""
        out: set[str] = set()
        for shape in SHAPES:
            for proj in self.expanded_projections(kit_root, shape, slug=slug):
                out.add(proj.dest)
        return out

    def tree_dests(self, shape: str, slug: str | None = None) -> list[str]:
        """The destination PREFIXES of every managed tree projection.

        Deletion is no longer scoped to these — `dests_under_any_shape` is what
        decides it, so a removed literal entry and a file gone from a tree are
        one event. This survives as the answer to "which destinations does the
        kit own wholesale", which is a different question with other callers."""
        return [p.dest[:-3] for p in self.projections(shape, slug=slug)
                if p.dest.endswith("/**") and p.policy != "never"]

    def projections(self, shape: str, slug: str | None = None) -> list[Projection]:
        """Source -> destination list for a target shape.

        shape is "web-enabled" (all projections) or "pdf-only" (web-layer
        projections are inert and excluded). A destination may carry
        a `<slug>` placeholder (only the reference PDF does today); pass `slug` to
        resolve it to a concrete path — sync does this from the target's
        guide.toml. Without `slug` the placeholder is left verbatim."""
        if shape not in SHAPES:
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

    def projections_for(self, cfg, slug: str | None = None) -> list[Projection]:
        """Source -> destination list for a DECLARED shape.

        The config-driven entry point, and the one callers should use. Shape is
        read from `[outputs]`, never probed from the filesystem: creating
        `style-screen.css` must not silently enable a web layer the guide never
        declared, and — the reason this matters beyond tidiness — a third and
        fourth output cannot be expressed as "some file exists".

        `slug` defaults to the config's own OUTPUT_SLUG, since the two always
        agreed at every call site anyway."""
        return self.projections(
            shape_of(cfg), slug=cfg.OUTPUT_SLUG if slug is None else slug
        )


def shape_of(cfg) -> str:
    """The manifest shape a validated KitConfig declares.

    Every site shape — including `app` (an externally-built SPA the kit only
    deploys) and `hub` (the omnibus index) — resolves the web destinations:
    they all need the deploy workflow and the `app/` tree. What differs between
    them is who RENDERS into that tree, which is the renderer's business, not
    the manifest's."""
    return "web-enabled" if cfg.outputs.site != "none" else "pdf-only"


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
    # A tree source needs a tree destination and vice versa. Mixing them is not a
    # projection anyone can resolve: `fonts/**` -> `fonts/faces.ttf` would have
    # every face in the tree claim one destination, and the last one copied would
    # win silently.
    if entry.projects_to is not None and entry.is_glob != entry.projects_to.endswith("/**"):
        raise ManifestError(
            f"{entry.path}: a directory-tree entry must project to a directory tree — "
            f"got path={entry.path!r} projects_to={entry.projects_to!r} (both or neither "
            f"must end in '/**')"
        )
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
