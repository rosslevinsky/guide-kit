#!/usr/bin/env python3
"""sync.py — copy-and-checksum sync from the kit to a guide.

One canonical invocation, from the WORKSPACE ROOT (the parent of guide-kit):

    python guide-kit/sync.py <guide>            # dry-run: report drift, write nothing
    python guide-kit/sync.py <guide> --apply    # transactional apply

`<guide>` is a sibling directory of guide-kit (e.g. mac-terminal-guide), NOT
`../<guide>` — from the workspace root that would resolve outside the workspace.

Model: copy-and-checksum, not merge. The manifest (kit-manifest.toml, via
kitmanifest.py) says what each file is and what sync does to its live path:
  identical      copy kit bytes verbatim
  templated      substitute the kit's guide.toml values with the target's
  managed-region replace only the <!-- kit:begin -->..<!-- kit:end --> block
  never          target-owned — NEVER written (this is what protects the
                 macOS-rendered reference PDF, style.css, guide.md, ...)

Sync deletes ONLY what it previously wrote, and only where the KIT has stopped
declaring the destination altogether — a face gone from `fonts/**`, or a literal
manifest entry removed: a destination it recorded, that the kit no longer
classifies under any shape, whose bytes still match the recorded checksum.
Everything else present in a target but absent from the manifest is left
untouched — sync does not delete what it did not create. A destination the kit
still declares that this target's `[outputs]` no longer wants is NOT this: that
is `adopt.py --disable`'s transition, and sync leaves it alone. A locally
modified file that vanished upstream is a refusal, not a deletion. It likewise
refuses to run over unreviewed local work: a writable-tier file whose recorded
checksum no longer matches is named and the run aborts.

Exit codes (a contract — downstream phases gate on these):
    0  fully in sync
    1  drift reported (dry-run) OR a refusal (dirty tree, local edit, unadopted
       existing destination)
    2  the target has no .template-version — run `--adopt` first

.template-version: a JSON record {schema_version, source_repo, kit_version,
managed_digest, state, rendered_checksums{dest -> sha256}}. `--adopt` establishes
it; every later `--apply` reads and rewrites it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import kitconfig
import kitmanifest

TEMPLATE_VERSION = ".template-version"
SCHEMA_VERSION = 1
MARK_BEGIN = "<!-- kit:begin -->"
MARK_END = "<!-- kit:end -->"

# Destination policies whose content the kit "manages" (feeds the managed-content
# digest); never-tier is target-owned and excluded.
_MANAGED_POLICIES = ("identical", "templated", "managed-region")

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_NEEDS_ADOPT = 2

# Test seam: a callable invoked as hook(n_written) after each destination write
# during --apply, so a test can inject a failure AFTER a real destination has
# been replaced and exercise the rollback journal. None in normal operation.
AFTER_WRITE_HOOK = None


class SyncError(Exception):
    """A refusal or malformed input; carries an operator-readable message."""


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def _head_sha(root: Path) -> str:
    """The kit's current commit, or "" if it cannot be read."""
    try:
        return _git(root, "rev-parse", "HEAD").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _is_dirty(root: Path) -> bool:
    try:
        return bool(_git(root, "status", "--porcelain").strip())
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # Fail closed: if we cannot confirm the tree is clean, refuse.
        raise SyncError(f"cannot determine git cleanliness of {root} ({exc})") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# managed-region
# ---------------------------------------------------------------------------

def _find_all(text: str, sub: str) -> list[int]:
    out, i = [], text.find(sub)
    while i != -1:
        out.append(i)
        i = text.find(sub, i + len(sub))
    return out


def _marker_span(text: str, where: str) -> tuple[int, int]:
    """Return (begin_index, end_index) of the single marker pair, validating that
    exactly one begin and one end exist and begin precedes end. Duplicate or
    nested markers -> more than one of each -> rejected; reversed -> end before
    begin -> rejected; missing -> zero -> rejected."""
    begins, ends = _find_all(text, MARK_BEGIN), _find_all(text, MARK_END)
    if len(begins) != 1 or len(ends) != 1:
        raise SyncError(
            f"{where}: managed-region markers must appear exactly once "
            f"(found {len(begins)} '{MARK_BEGIN}', {len(ends)} '{MARK_END}')"
        )
    b, e = begins[0], ends[0]
    if e < b:
        raise SyncError(f"{where}: reversed markers ('{MARK_END}' before '{MARK_BEGIN}')")
    return b, e


def _region(text: str, where: str) -> str:
    """The text between (exclusive) the begin and end markers."""
    b, e = _marker_span(text, where)
    return text[b + len(MARK_BEGIN):e]


def _render_managed(target_text: str, kit_text: str) -> str:
    """Replace the target's managed block with the kit's, preserving everything
    outside the target's markers verbatim."""
    kit_region = _region(kit_text, "kit source")
    b, e = _marker_span(target_text, "target file")
    return target_text[:b + len(MARK_BEGIN)] + kit_region + target_text[e:]


# ---------------------------------------------------------------------------
# templated
# ---------------------------------------------------------------------------

# ONLY DISTINCTIVE FIELDS BELONG HERE. Templating is a bare substring replace,
# so a field whose value is a short common word clobbers any unrelated text that
# happens to contain it. The retired `baseline_platform` field is the recorded
# case: its values were "linux" / "darwin" / "win32", and with the kit recording
# "linux" while a target still recorded "darwin", every templated pixi.toml had
# its platform list rewritten from `linux-64` to `darwin-64` — not a pixi
# platform at all, so every pixi command in seven repos failed at once. It had
# been safe only while every guide agreed with the kit, because substitution is
# skipped when the value does not change: safe exactly until the field was used
# for the thing it existed for.
#
# The five fields below are distinctive strings — a slug, a title, an author, a
# description, a keyword list — where a substring match is what you want. Before
# adding a sixth, ask whether its value could appear inside unrelated text.
_TEMPLATED_FIELDS = ("OUTPUT_SLUG", "TITLE", "AUTHOR", "DESCRIPTION", "KEYWORDS")

# Kit-only regions: lines between these sentinels exist ONLY in the kit and are
# dropped when a templated file is rendered into a target. The kit's test
# environment is the motivating case — pytest/pyyaml and the `kit` environment
# must never reach a target's pixi.toml, or every target's pixi.lock gains a
# `kit` environment and regenerates merely because the kit gained a test runner
#. Before this existed the sections templated through verbatim:
# the placement test asserted the structure, but nothing consumed it.
#
# Comment-syntax-agnostic by design: the sentinel is matched as a substring, so
# the same idiom works in TOML/YAML (`#`), and the markers live on their own
# lines and are removed with the block.
KIT_ONLY_BEGIN = "kit-only:begin"
KIT_ONLY_END = "kit-only:end"


def _strip_kit_only(text: str, where: str = "templated file") -> str:
    """Drop every kit-only region (marker lines included). Unbalanced or nested
    markers are an error rather than a silent partial strip — a missed strip
    leaks the kit's test env into a target, which is the bug this prevents."""
    out, depth = [], 0
    for line in text.splitlines(keepends=True):
        if KIT_ONLY_BEGIN in line:
            if depth:
                raise SyncError(f"{where}: nested '{KIT_ONLY_BEGIN}'")
            depth = 1
            continue
        if KIT_ONLY_END in line:
            if not depth:
                raise SyncError(f"{where}: '{KIT_ONLY_END}' without '{KIT_ONLY_BEGIN}'")
            depth = 0
            continue
        if not depth:
            out.append(line)
    if depth:
        raise SyncError(f"{where}: unterminated '{KIT_ONLY_BEGIN}'")
    return "".join(out)


def _render_templated(kit_text: str, kit_cfg, target_cfg) -> str:
    """Substitute the kit's guide.toml string values with the target's. In
    practice this rewrites the slug (`guide-template`) into pixi.toml's project
    name; verify.yml carries no kit guide.toml value and renders identically.

    SINGLE-PASS: a regex alternation (longest kit value first) is matched once
    over the ORIGINAL text, so a replacement's output can never be re-matched — a
    naive sequence of str.replace() could cascade (e.g. kit TITLE -> a value that
    equals kit AUTHOR, then AUTHOR -> its target). A kit value that maps to two
    different target values is ambiguous and rejected.

    Kit-only regions are stripped FIRST, so a target never receives them and the
    substitution never has to reason about text that is about to be deleted."""
    kit_text = _strip_kit_only(kit_text)
    # Collect ALL kit->target values first, INCLUDING identity mappings (kv == tv):
    # a kit value that must stay unchanged for one field but be rewritten for
    # another is ambiguous, and skipping identities before the check would miss it
    # (e.g. kit TITLE == AUTHOR == "Same", target TITLE "Same" but AUTHOR "Other"
    # would silently rewrite every "Same" to "Other").
    targets_for: dict[str, set[str]] = {}
    for field in _TEMPLATED_FIELDS:
        kv, tv = getattr(kit_cfg, field), getattr(target_cfg, field)
        if isinstance(kv, str) and kv:
            targets_for.setdefault(kv, set()).add(str(tv))
    for kv, tvs in targets_for.items():
        if len(tvs) > 1:
            raise SyncError(
                f"templated substitution is ambiguous: kit value {kv!r} maps to {sorted(tvs)}"
            )
    # Substitute only where the value actually changes.
    mapping = {kv: next(iter(tvs)) for kv, tvs in targets_for.items() if next(iter(tvs)) != kv}
    if not mapping:
        return kit_text
    pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
    return pattern.sub(lambda m: mapping[m.group(0)], kit_text)


# ---------------------------------------------------------------------------
# .template-version
# ---------------------------------------------------------------------------

def _read_template_version(target: Path) -> dict | None:
    p = target / TEMPLATE_VERSION
    if not p.is_file():
        return None
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(f"{TEMPLATE_VERSION} is not valid JSON: {exc}") from exc
    # VALID JSON IS NOT ENOUGH. `null` parses, and returning it here made the
    # file indistinguishable from an absent one — so sync said "run --adopt" and
    # --adopt said "you already have a .template-version", with nothing
    # suggesting the way out. `[]`, `""` and a number parse too, and every
    # caller then does `.get()` on them, so the promised SyncError arrived as an
    # AttributeError traceback instead.
    if not isinstance(record, dict):
        raise SyncError(
            f"{TEMPLATE_VERSION} is valid JSON but not an object (got "
            f"{type(record).__name__}). It records adoption state as a mapping; "
            f"delete the file to re-adopt with `sync.py <guide> --adopt`."
        )
    # A record from a NEWER sync than this one. Written since the format was
    # introduced and never read, which made it a version gate that gated
    # nothing — the one thing a schema version exists to prevent.
    version = record.get("schema_version")
    if version is not None and version > SCHEMA_VERSION:
        raise SyncError(
            f"{TEMPLATE_VERSION} declares schema_version {version}, newer than "
            f"this sync understands ({SCHEMA_VERSION}). Update the kit checkout "
            f"you are running from rather than letting an older tool rewrite it."
        )
    return record


def _atomic_write(dest: Path, data: bytes) -> None:
    """Write `data` to `dest` atomically. The temp file is created with
    tempfile.mkstemp (O_CREAT|O_EXCL, a UNIQUE unpredictable name, and no symlink
    follow), so a pre-planted symlink at a predictable temp path can't redirect
    the write outside the target, and an existing file is never silently consumed.
    os.replace then replaces a symlink AT `dest` rather than following it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".sync-tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            # FLUSH + FSYNC before the rename. `os.replace` is atomic with
            # respect to the DIRECTORY ENTRY, which is what stops a reader ever
            # seeing a half-written file — but it says nothing about the data
            # reaching disk. Without this, a power loss just after the rename can
            # publish a file whose name is committed and whose contents are not.
            f.flush()
            os.fsync(f.fileno())
        # mkstemp creates the temp 0600; preserve the destination's existing mode
        # (or a sane 0644 for a new file) so a sync never silently tightens or
        # loosens permissions on the file it replaces.
        try:
            mode = os.stat(dest).st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------

class Item:
    """One resolved projection and what sync would do to it."""

    def __init__(self, dest_rel, dest_abs, policy, expected, checkable, action, reason=""):
        self.dest_rel = dest_rel
        self.dest_abs = dest_abs
        self.policy = policy
        self.expected = expected          # bytes to write (None for in-sync/refuse)
        self.checkable = checkable        # bytes whose sha is recorded (region for managed)
        self.action = action              # in-sync | update | create | refuse
        self.reason = reason


def _resolve_dest(target: Path, rel: str) -> Path:
    """Resolve `rel` under `target`: resolve the PARENT directory through symlinks
    and assert it is beneath the target root, but do NOT resolve the leaf. This
    rejects traversal and symlinked parents that escape the root, while a
    destination that is itself a symlink gets REPLACED by os.replace (the link is
    unlinked) rather than followed to overwrite some other file."""
    target_root = target.resolve()
    dest = target / rel
    parent = dest.parent.resolve()
    if parent != target_root and target_root not in parent.parents:
        raise SyncError(f"destination {rel!r} escapes the target root (parent resolves to {parent})")
    return parent / dest.name


def _checkable_bytes(policy: str, file_bytes: bytes) -> bytes:
    """The bytes whose checksum is recorded / compared. For managed-region only
    the marked block is covered, so a guide's edits OUTSIDE the markers never
    block sync; for other tiers, the whole file."""
    if policy == "managed-region":
        return _region(file_bytes.decode("utf-8"), "target file").encode("utf-8")
    return file_bytes


def build_plan(kit_root: Path, target: Path) -> tuple[list[Item], dict | None, str | None]:
    """Compute the per-destination plan. Returns (items, template_version,
    kit_digest) — the digest is computed from the SAME kit read as the plan, so
    --apply records exactly the content it wrote. Raises SyncError on a genuine
    refusal (local edit, unadopted existing dest). Exit-2 (needs adopt) is
    signalled by a None template_version."""
    # Check .template-version FIRST: an unadopted guide (which may not even have a
    # guide.toml yet — the adoption sequence hand-writes it) exits cleanly as
    # needs-adopt rather than crashing in kitconfig.load(target).
    tv = _read_template_version(target)
    if tv is None:
        return [], None, None  # caller maps this to EXIT_NEEDS_ADOPT
    recorded = tv.get("rendered_checksums", {})

    kit_cfg = kitconfig.load(kit_root)
    target_cfg = kitconfig.load(target)
    slug = target_cfg.OUTPUT_SLUG
    shape = kitmanifest.shape_of(target_cfg)

    manifest = kitmanifest.load(kit_root)
    kit_digest = compute_managed_digest(kit_root)  # same snapshot as the reads below
    items: list[Item] = []
    projected: set[str] = set()
    declared: set[str] = set()
    for proj in manifest.expanded_projections(kit_root, shape, slug=slug):
        declared.add(proj.dest)
        if proj.policy == "never":
            continue  # target-owned; never written, never counted as drift
        projected.add(proj.dest)
        dest_abs = _resolve_dest(target, proj.dest)
        kit_src = kit_root / proj.source

        # expected bytes for this destination
        if proj.policy == "identical":
            expected = kit_src.read_bytes()
        elif proj.policy == "templated":
            # decode from bytes (NOT read_text) so CRLF/CR are not translated to LF.
            expected = _render_templated(
                kit_src.read_bytes().decode("utf-8"), kit_cfg, target_cfg
            ).encode("utf-8")
        elif proj.policy == "managed-region":
            if dest_abs.exists():
                # Preserve the target's own bytes verbatim outside the markers —
                # read_bytes().decode avoids read_text's universal-newline rewrite.
                expected = _render_managed(
                    dest_abs.read_bytes().decode("utf-8"), kit_src.read_bytes().decode("utf-8")
                ).encode("utf-8")
            else:
                expected = kit_src.read_bytes()  # no target file yet -> create whole
        else:
            raise SyncError(f"{proj.dest}: unknown policy {proj.policy!r}")

        if not dest_abs.exists():
            items.append(Item(proj.dest, dest_abs, proj.policy, expected,
                              _checkable_bytes(proj.policy, expected), "create"))
            continue

        current = dest_abs.read_bytes()
        if proj.dest not in recorded:
            # An existing destination with no recorded checksum: a new managed
            # dest that already exists in the target. Refuse — never clobber
            # unreviewed content by default; it must be explicitly adopted.
            items.append(Item(proj.dest, dest_abs, proj.policy, None, None, "refuse",
                              "exists but is not in rendered_checksums (needs adoption)"))
            continue

        current_check = _sha256(_checkable_bytes(proj.policy, current))
        diverged = current_check != recorded[proj.dest]
        # MANAGED-REGION IS THE ONE TIER WHERE A DIVERGENCE IS NOT A REFUSAL, and
        # that is what the documentation has always promised: both `CLAUDE.md`
        # files tell every guide that editing inside `kit:begin`/`kit:end` is
        # "wasted work — the next sync overwrites it". It was not. Sync refused
        # the file AND, because one refusal aborts the run, every other file with
        # it: one edited heading in the shared block stopped an unrelated
        # `build.py` update from landing.
        #
        # Overwriting is the designed behaviour, not a concession —
        # `_checkable_bytes` scopes the comparison to the MARKED BLOCK, which is
        # kit-owned, and `_render_managed` rebuilds it from the kit while
        # preserving every byte the guide owns outside the markers. So nothing of
        # the target's is lost, and the reason below says what happened rather
        # than doing it silently.
        if diverged and proj.policy != "managed-region":
            items.append(Item(proj.dest, dest_abs, proj.policy, None, None, "refuse",
                              "local modification does not match recorded checksum"))
            continue

        action = "in-sync" if current == expected else "update"
        items.append(Item(proj.dest, dest_abs, proj.policy, expected,
                          _checkable_bytes(proj.policy, expected), action,
                          "the managed region had local edits; reset from the kit "
                          "(your sections outside the markers are untouched)"
                          if diverged else ""))

    items += _deletions(kit_root, target, manifest, shape, slug, recorded, projected, declared)
    return items, tv, kit_digest


def _deletions(kit_root: Path, target: Path, manifest, shape: str, slug: str,
               recorded: dict, projected: set[str], declared: set[str]) -> list[Item]:
    """Destinations the KIT used to declare and no longer declares at all.

    THE ONLY PLACE SYNC DELETES, and every clause of the guard is load-bearing:

    * **Only when the kit declares the destination under NO shape.** This is the
      clause that separates the two events that both look like "absent from the
      projections". A file gone from `fonts/**`, or a literal entry removed from
      the manifest, is an upstream deletion — the kit no longer classifies that
      path, and leaving it behind is what orphaned `verify_pdf.py` in all seven
      targets when it became `verify_artifacts.py`. A destination the kit still
      declares but *this target's* `[outputs]` no longer wants is a different
      thing entirely: that is `adopt.py --disable`'s transition, which is
      config-first, never writes `guide.toml`, and refuses a dirty tree.
      Sync performing it as a side effect of an ordinary `--apply` would bypass
      all three, so a shape-only absence is skipped here.
    * **Only a previously RECORDED destination.** An unrecorded path was never
      written by sync, so its presence means a guide put it there.
      `tests/test_sync_never_deletes.py` is the standing statement of this: sync
      does not delete what it did not create.
    * **Only a well-formed inventory key.** The inventory is JSON in the target
      repo, so its keys are input, not fact — and with the managed-tree scope
      gone this is the only thing between a corrupt `.template-version` and an
      arbitrary deletion.
    * **Only when the checksum still matches.** A locally modified file is
      unreviewed work; the transition REFUSES rather than deleting, because the
      whole point of recording checksums is to know the difference.
    """
    # Expanded, and unioned over every shape — see `dests_under_any_shape`.
    kit_declares = manifest.dests_under_any_shape(kit_root, slug=slug)
    # Managed trees the kit declares but could not READ. Expansion cannot tell an
    # empty tree from an absent one, and to this loop either looks like the kit
    # having removed every file in it at once — see `unreadable_tree_dests`.
    unreadable = manifest.unreadable_tree_dests(kit_root, slug=slug)
    # Target-owned NAMESPACES, not just target-owned files that happen to exist.
    # `declared` is built from the kit's tree as it stands, so a `never` file the
    # kit has since removed is absent from it — and the enclosing kit-owned tree
    # would then read that absence as an upstream deletion and remove the very
    # file the `never` classification handed to the guide.
    owned_exact, owned_prefixes = manifest.target_owned_dests(shape, slug=slug)
    # Seeded from EVERY shape's destinations, not just this target's. Deletion
    # eligibility is unioned over shapes, so protection has to be — otherwise a
    # pdf-only target's alias onto a web-only destination is protected by name
    # (`kit_declares`) and not at all by identity.
    protected = _ProtectedFiles(target, declared | kit_declares)
    out: list[Item] = []
    for dest_rel, recorded_sha in sorted(recorded.items()):
        if dest_rel in projected:
            continue
        if dest_rel in declared or dest_rel in owned_exact or any(
                dest_rel == p or dest_rel.startswith(p + "/") for p in owned_prefixes):
            # Recorded, but the kit hands this path to the GUIDE (`policy =
            # "never"`, or a target-owned namespace). Surviving is not enough:
            # the record has to go too. Sync neither writes a `never` destination
            # nor reports drift on one, so its checksum is dead weight — except
            # that the checksum is exactly what authorises a deletion. Keep it and
            # the handover is half done, and removing the `never` entry LATER
            # deletes a file the guide has owned ever since, on the strength of a
            # record from before it owned it.
            out.append(Item(dest_rel, _resolve_dest(target, dest_rel), "never",
                            None, None, "forget",
                            "target-owned now — sync no longer tracks it"))
            continue
        if dest_rel in kit_declares:
            continue          # the kit still owns it; only this shape dropped it
        if not _safe_inventory_key(dest_rel):
            continue
        if any(dest_rel.startswith(p + "/") for p in unreadable):
            out.append(Item(dest_rel, _resolve_dest(target, dest_rel), "identical",
                            None, None, "refuse",
                            "its managed tree is declared but unreadable in the kit "
                            "(sparse checkout?) — refusing to read that as a deletion"))
            continue
        dest_abs = _resolve_dest(target, dest_rel)
        if not protected.names_a_distinct_file(dest_rel, dest_abs):
            # `_safe_inventory_key` checks the STRING. `alias/guide.md` is
            # canonical — no `..`, no leading slash — yet with `alias -> .` in the
            # target it IS the guide's own `guide.md`, and every set compared
            # above holds `guide.md`, not `alias/guide.md`. Comparing what the key
            # RESOLVES to is what closes that, along with hard links and the
            # case-insensitive aliases a case-folding filesystem supplies for free.
            out.append(Item(dest_rel, dest_abs, "identical", None, None, "refuse",
                            "resolves onto a file the kit still owns — resolve by hand"))
            continue
        if dest_abs.is_symlink():
            # `exists()` is False for a BROKEN link, which would read as "already
            # gone" and quietly forget the record while the link stayed. A symlink
            # where sync wrote a regular file is a local change either way.
            out.append(Item(dest_rel, dest_abs, "identical", None, None, "refuse",
                            "replaced by a symlink — resolve by hand"))
            continue
        if not dest_abs.exists():
            # Already gone. The RECORD is still stale, though, and leaving it
            # means a later guide-authored file at that path is falsely refused —
            # or, if its bytes happen to match, deleted. Forget it instead.
            out.append(Item(dest_rel, dest_abs, "identical", None, None, "forget",
                            "recorded but absent from both kit and target"))
            continue
        current = dest_abs.read_bytes()
        if MARK_BEGIN.encode("utf-8") in current and MARK_END.encode("utf-8") in current:
            # SHARED ownership: the kit owned the marked block, the guide owns
            # everything around it. The kit dropping the entry means the block is
            # no longer maintained — not that the guide's own prose should vanish.
            # This is also where "byte-for-byte by construction" stops holding:
            # the record covers only the region, so a whole-file hash can never
            # match it, and calling that a local modification would wedge sync in
            # a refusal no edit could clear.
            out.append(Item(dest_rel, dest_abs, "managed-region", None, None, "forget",
                            "shared-ownership file — the kit's block is no longer managed"))
            continue
        policy = "identical"  # what remains is byte-for-byte by construction
        if _sha256(_checkable_bytes(policy, current)) != recorded_sha:
            out.append(Item(dest_rel, dest_abs, policy, None, None, "refuse",
                            "deleted upstream but locally modified — resolve by hand"))
            continue
        out.append(Item(dest_rel, dest_abs, policy, None, None, "delete",
                        "removed from the kit"))
    return out


class _ProtectedFiles:
    """Do two inventory keys name the same file on disk?

    Every guard around the deletion decision compares STRINGS — `dest_rel`
    against the sets of destinations the kit declares. A filesystem supplies
    several ways to spell one file that those comparisons cannot see:

    * a symlinked directory committed in the target (`alias -> .`, so
      `alias/guide.md` is `guide.md`),
    * a hard link,
    * case folding, on a case-insensitive filesystem (`Guide.md` opens
      `guide.md`, and macOS is where a good deal of this authoring happens).

    Each of those turns a string the declaration sets do not contain into a file
    they do. `(st_dev, st_ino)` is the identity the filesystem itself uses, so
    comparing on that catches all three at once and needs no per-platform
    special case. Built lazily: the stats cost nothing on the overwhelmingly
    common run where no destination is a deletion candidate at all."""

    def __init__(self, target: Path, declared: set[str]):
        # Resolved here rather than trusting the caller: the lexical test below
        # compares against `self._target / dest_rel`, so an unresolved target
        # (say `/tmp/...` where `/tmp` is itself a link) would make every
        # candidate look aliased and refuse the lot.
        self._target, self._declared = target.resolve(), declared
        self._ids: set[tuple[int, int]] | None = None

    def _identities(self) -> set[tuple[int, int]]:
        if self._ids is None:
            ids: set[tuple[int, int]] = set()
            for rel in self._declared:
                try:
                    st = (self._target / rel).stat()
                except OSError:
                    continue      # absent or unreadable: nothing to alias onto
                ids.add((st.st_dev, st.st_ino))
            self._ids = ids
        return self._ids

    def names_a_distinct_file(self, dest_rel: str, dest_abs: Path) -> bool:
        """False when `dest_rel` reaches a file the kit still declares."""
        if dest_abs != self._target / dest_rel:
            return False          # a symlinked component was traversed away
        try:
            st = dest_abs.lstat()
        except OSError:
            return True           # absent — later clauses own that case
        return (st.st_dev, st.st_ino) not in self._identities()


def _safe_inventory_key(dest_rel: str) -> bool:
    """Whether an INVENTORY KEY names a plain relative path inside the target.

    The inventory is JSON living in the target repository, so its keys are input,
    not fact — and this is the one place a key decides that a file gets deleted.
    A raw prefix test accepted `fonts/../guide.md`: `_resolve_dest` resolves its
    PARENT to the target root (legitimately inside the target, so nothing
    objects) and the guide's own `guide.md` is planned for deletion. Rejecting
    anything absolute, escaping, or not already in canonical form is what makes
    the rest of the guard mean what it reads as.

    This was the front half of `_inside_tree`. The managed-tree scope it served
    is gone — deletion is decided by whether the kit still declares the
    destination — which makes this check load-bearing on its own rather than a
    normalisation step before a prefix test: EVERY recorded key the kit does not
    declare now reaches it."""
    if not dest_rel or dest_rel.startswith("/") or "\\" in dest_rel:
        return False
    pure = PurePosixPath(dest_rel)
    return not (pure.is_absolute() or ".." in pure.parts
                or pure.as_posix() != dest_rel)


# ---------------------------------------------------------------------------
# apply (transactional, rollback journal)
# ---------------------------------------------------------------------------

def _apply(kit_root: Path, target: Path, items: list[Item], tv: dict,
           kit_digest: str) -> None:
    to_write = [it for it in items if it.action in ("create", "update")]
    to_delete = [it for it in items if it.action == "delete"]
    to_forget = [it for it in items if it.action == "forget"]
    # Journal holds each destination's PRIOR bytes (or None if it did not exist).
    # See the entry below for the ordering, which is BEFORE the write — an
    # earlier version of this comment claimed after, and was contradicted three
    # lines down by both the code and its own inline note.
    journal: list[tuple[Path, bytes | None]] = []
    written = 0
    try:
        for it in to_write:
            # Journal the prior state BEFORE the write, so a crash/signal landing
            # after os.replace succeeds but before the next line is still covered.
            # Best-effort rollback (below) makes this safe even for the dest whose
            # write is the one that failed: restoring its (unchanged) prior bytes
            # is a harmless rewrite, and a per-entry failure never aborts the rest.
            prior = it.dest_abs.read_bytes() if it.dest_abs.exists() else None
            journal.append((it.dest_abs, prior))
            _atomic_write(it.dest_abs, it.expected)
            written += 1
            if AFTER_WRITE_HOOK is not None:
                AFTER_WRITE_HOOK(written)

        # Deletions run inside the SAME transaction and journal, so a failure
        # anywhere restores the removed bytes along with everything else. They
        # come after the writes because a rename inside a managed tree arrives as
        # create-new + delete-old, and doing the create first means the tree is
        # never momentarily missing both.
        for it in to_delete:
            prior = it.dest_abs.read_bytes() if it.dest_abs.exists() else None
            journal.append((it.dest_abs, prior))
            it.dest_abs.unlink(missing_ok=True)
            written += 1
            if AFTER_WRITE_HOOK is not None:
                AFTER_WRITE_HOOK(written)

        # .template-version is written LAST but INSIDE the transaction and
        # journaled — if it fails, every destination write rolls back too, so the
        # files and the recorded checksums can never disagree.
        recorded = dict(tv.get("rendered_checksums", {}))
        for it in to_write:
            recorded[it.dest_rel] = _sha256(it.checkable)
        for it in to_delete:
            recorded.pop(it.dest_rel, None)
        for it in to_forget:
            recorded.pop(it.dest_rel, None)
        new_tv = dict(tv)
        new_tv["rendered_checksums"] = recorded
        new_tv["state"] = "applied"          # clears adopted_unapplied
        new_tv["managed_digest"] = kit_digest  # the SAME snapshot the plan wrote from
        # ADVANCE kit_version to the commit actually applied. It only ever
        # recorded the ADOPTION commit, and it is not inert metadata: verify.yml
        # feeds it to `actions/checkout`'s `ref:` when a target borrows the kit's
        # test suite, so a guide ran today's files against the kit as it stood at
        # adoption. The family had been correcting it by hand — a "Re-point
        # kit_version" commit per guide per sync.
        #
        # Best-effort: a kit checkout with no readable HEAD leaves the recorded
        # value alone rather than failing an otherwise good apply over a
        # provenance field. Full 40-char sha, which is the only form that `ref:`
        # resolves (a short one fails outright).
        head = _head_sha(kit_root)
        if head:
            new_tv["kit_version"] = head
        tv_path = target / TEMPLATE_VERSION
        tv_prior = tv_path.read_bytes() if tv_path.exists() else None
        journal.append((tv_path, tv_prior))
        _atomic_write(tv_path, (json.dumps(new_tv, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    except BaseException:
        # Best-effort rollback across EVERY journaled entry (a single restore
        # failure must not abort the rest); report any that could not be restored.
        #
        # WHAT THIS DOES NOT COVER, since the guarantee is easy to over-read: a
        # RAISED exception rolls back. An uncatchable kill (SIGKILL, power loss)
        # between the first write and the `.template-version` write does not, and
        # leaves files carrying the kit's new bytes against the old recorded
        # checksums — which every later run then refuses as the operator's own
        # edits. `git checkout -- .` in the target is the recovery.
        for dest, prior in reversed(journal):
            try:
                if prior is None:
                    dest.unlink(missing_ok=True)
                else:
                    _atomic_write(dest, prior)
            except Exception as exc:
                sys.stderr.write(f"sync.py: WARNING could not roll back {dest}: {exc}\n")
        raise


# ---------------------------------------------------------------------------
# managed-content digest + adoption + drift
# ---------------------------------------------------------------------------

def compute_managed_digest(kit_root: Path) -> str:
    """sha256 over the kit's MANAGED content — the bytes of identical/templated
    kit source files and the marked block of managed-region files, in a fixed
    (dest-sorted) order. Recomputed at check time so ANY change to a managed kit
    file moves the digest: this closes the forget-to-bump-the-version
    silent-staleness hole a hand-maintained counter would leave open. never-tier
    is excluded (target-owned)."""
    manifest = kitmanifest.load(kit_root)
    kit_cfg = kitconfig.load(kit_root)
    projs = [p for p in manifest.expanded_projections(kit_root, "web-enabled")
             if p.policy in _MANAGED_POLICIES]
    h = hashlib.sha256()
    # The kit's guide.toml values are substitution ANCHORS for templated files —
    # changing one alters rendered target output even when no managed source
    # file's bytes change, so they are digest inputs.
    for f in _TEMPLATED_FIELDS:
        h.update(b"kitcfg:" + f.encode("utf-8") + b"=" + str(getattr(kit_cfg, f)).encode("utf-8") + b"\0")
    for proj in sorted(projs, key=lambda p: (p.dest, p.policy)):
        content = (kit_root / proj.source).read_bytes()
        if proj.policy == "managed-region":
            content = _region(content.decode("utf-8"), f"kit {proj.source}").encode("utf-8")
        # Include the POLICY: a policy change (e.g. identical -> templated) alters
        # the projection even when the source bytes are unchanged.
        h.update(proj.dest.encode("utf-8") + b"\0" + proj.policy.encode("utf-8") + b"\0" + content + b"\0")
    return h.hexdigest()


def _target_shape(target: Path) -> str:
    """The target's DECLARED shape, read from its own `[outputs]` table.

    Formerly probed the filesystem (`style-screen.css` exists, or `app/` is a
    directory). That answered a different question than the one being asked: a
    half-materialized web layer read as web-enabled, and a guide that declared
    no site could acquire one by having a stray file."""
    return kitmanifest.shape_of(kitconfig.load(target))


def adopt(kit_root: Path, target: Path, source_repo: str, kit_version: str,
          assume_yes: bool = False, confirm=input) -> int:
    """First-contact adoption: record the target's CURRENT (pre-sync) managed
    checksums and establish managed state. A one-time reviewed event — not the
    steady-state path. Refuses if already adopted or the target tree is dirty;
    prints a per-file inventory and requires confirmation; writes state
    `adopted_unapplied` (which the drift check treats as BEHIND until --apply)."""
    kit_root, target = kit_root.resolve(), target.resolve()
    if (target / TEMPLATE_VERSION).exists():
        raise SyncError(f"{target.name} already has {TEMPLATE_VERSION} — adoption is first-contact only.")
    if _is_dirty(target):
        raise SyncError(f"refusing --adopt: the target worktree ({target.name}) is dirty — commit first.")

    target_cfg = kitconfig.load(target)  # requires guide.toml (adoption step 1)
    manifest = kitmanifest.load(kit_root)
    rendered: dict[str, str] = {}
    print(f"Adoption inventory for {target.name} (source: {source_repo}):")
    for proj in manifest.expanded_projections(
            kit_root, _target_shape(target), slug=target_cfg.OUTPUT_SLUG):
        if proj.policy == "never":
            continue
        dest_abs = _resolve_dest(target, proj.dest)
        if dest_abs.exists():
            rendered[proj.dest] = _sha256(_checkable_bytes(proj.policy, dest_abs.read_bytes()))
            print(f"  will manage  {proj.dest} [{proj.policy}] (recording current hash)")
        else:
            print(f"  will create  {proj.dest} [{proj.policy}] on --apply")

    if not assume_yes:
        ans = confirm(f"Record these {len(rendered)} pre-sync hashes and establish managed state? [y/N] ")
        if str(ans).strip().lower() not in ("y", "yes"):
            print("Adoption cancelled — nothing written.")
            return EXIT_DRIFT

    record = {
        "schema_version": SCHEMA_VERSION,
        "source_repo": source_repo,
        "kit_version": kit_version,
        "managed_digest": compute_managed_digest(kit_root),
        "state": "adopted_unapplied",
        "rendered_checksums": rendered,
    }
    _atomic_write(target / TEMPLATE_VERSION, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(f"{target.name}: adopted ({len(rendered)} files recorded, state=adopted_unapplied).")
    print(f"  Next: commit {TEMPLATE_VERSION}, then `sync.py {target.name} --apply`.")
    return EXIT_OK


def drift_report(kit_root: Path, target: Path) -> tuple[bool, list[str]]:
    """Return (drifted, messages). A target drifts if it is adopted-but-unapplied,
    or the kit has managed content it has not taken yet (upstream drift),
    or its own managed files were edited away from the recorded checksums
    (local drift). Warn-only — the caller decides how to surface it."""
    # "UP TO DATE" must mean CHECKED AND CLEAN, never "never looked". Without
    # this, a family sweep with a typo'd or not-yet-cloned path reported a clean
    # bill of health, and `kit-drift.yml` greps that verdict. `run_sync` has
    # always guarded this; this path did not.
    if not target.is_dir():
        return True, [f"{target} is not a directory — nothing was checked"]

    # "UP TO DATE" must mean CHECKED AND CLEAN, never "never looked". Without
    # this, a family sweep with a typo'd or not-yet-cloned path reported a clean
    # bill of health, and `kit-drift.yml` greps that verdict. `run_sync` has
    # always guarded this; this path did not.
    if not target.is_dir():
        return True, [f"{target} is not a directory — nothing was checked"]

    kit_root, target = kit_root.resolve(), target.resolve()
    tv = _read_template_version(target)
    if tv is None:
        return False, [f"{target.name}: no {TEMPLATE_VERSION} — not an adopted target; skipping."]
    msgs: list[str] = []
    drifted = False

    if tv.get("state") == "adopted_unapplied":
        drifted = True
        msgs.append(f"{target.name}: state is adopted_unapplied — behind (run --apply).")

    # ASKED THROUGH build_plan — the same question `sync <guide>` answers, and
    # that is the whole point. This compared a kit-wide `managed_digest`, and the
    # two disagreed for two structural reasons: the digest resolves against the
    # `web-enabled` shape unconditionally, so a WEB-ONLY kit change flagged a
    # PDF-ONLY target; and it hashes managed source bytes including the kit-only
    # regions `_strip_kit_only` provably never ships. Measured: after a one-line
    # edit to `deploy.yml.example`, `--check-drift` said DRIFT DETECTED while the
    # documented remedy said "in sync — nothing to do" and exited 0. A warning
    # whose own remedy reports nothing to do is one people learn to ignore.
    #
    # `build_plan` compares RENDERED bytes for the target's REAL shape, so it is
    # narrower and exact. A refusal counts as drift: it means a managed file was
    # edited locally, which is a thing to act on. `managed_digest` is still
    # RECORDED as provenance — what the kit looked like at the last apply — but
    # it decides nothing.
    try:
        items, _, _ = build_plan(kit_root, target)
    except SyncError as exc:
        return True, msgs + [f"{target.name}: {exc}"]
    # The same predicate `run_sync` uses for "nothing to do", so the two commands
    # cannot disagree about one target.
    pending = [it.dest_rel for it in items
               if it.action in ("create", "update", "delete", "forget", "refuse")]
    if pending:
        drifted = True
        msgs.append(
            f"{target.name}: upstream managed content changed — {len(pending)} "
            f"file(s) behind the kit "
            f"({', '.join(pending[:5])}{'…' if len(pending) > 5 else ''}) — run sync."
        )

    # Local drift: a managed file edited away from its recorded checksum.
    try:
        target_cfg = kitconfig.load(target)
        manifest = kitmanifest.load(kit_root)
        recorded = tv.get("rendered_checksums", {})
        for proj in manifest.expanded_projections(
                kit_root, _target_shape(target), slug=target_cfg.OUTPUT_SLUG):
            if proj.policy == "never" or proj.dest not in recorded:
                continue
            dest_abs = _resolve_dest(target, proj.dest)
            if not dest_abs.exists():
                drifted = True
                msgs.append(f"{target.name}: recorded managed file {proj.dest} is missing (deleted).")
            elif _sha256(_checkable_bytes(proj.policy, dest_abs.read_bytes())) != recorded[proj.dest]:
                drifted = True
                msgs.append(f"{target.name}: local edit to managed file {proj.dest} (differs from recorded).")
    except Exception as exc:  # the warn-only check must never crash — but an
        # incomplete validation is INDETERMINATE, so treat it as drift rather than
        # letting a "could not validate" line be followed by "UP TO DATE".
        drifted = True
        msgs.append(f"{target.name}: could not fully validate local checksums ({exc}) — treating as drift.")

    if not drifted:
        msgs.append(f"{target.name}: up to date with the kit.")
    return drifted, msgs


# ---------------------------------------------------------------------------
# top-level
# ---------------------------------------------------------------------------

def run_sync(kit_root: Path, target: Path, apply: bool) -> int:
    kit_root = kit_root.resolve()
    target = target.resolve()
    if not target.is_dir():
        raise SyncError(f"target guide not found: {target}")

    if apply:
        # Preconditions BEFORE any planning-with-writes: both trees clean. These
        # are expected refusals (return a nonzero code), not malformed input.
        if _is_dirty(kit_root):
            sys.stderr.write(
                "sync.py: refusing --apply: the KIT (template) worktree is dirty — commit "
                "template changes first, else uncommitted bytes get synced while "
                ".template-version records the old clean HEAD.\n"
            )
            return EXIT_DRIFT
        if _is_dirty(target):
            sys.stderr.write(
                f"sync.py: refusing --apply: the target worktree ({target.name}) is dirty — "
                "commit or revert local work first.\n"
            )
            return EXIT_DRIFT

    items, tv, kit_digest = build_plan(kit_root, target)
    if tv is None:
        sys.stderr.write(
            f"{target.name}: no {TEMPLATE_VERSION} — first contact requires `--adopt`.\n"
        )
        return EXIT_NEEDS_ADOPT

    refusals = [it for it in items if it.action == "refuse"]
    updates = [it for it in items if it.action in ("create", "update", "delete", "forget")]

    if not apply:
        # Dry-run report.
        for it in items:
            if it.action == "in-sync":
                continue
            tag = {"update": "would update", "create": "would create",
                   "delete": "would delete", "forget": "would forget (stale record)",
                   "refuse": "REFUSE"}[it.action]
            extra = f" — {it.reason}" if it.reason else ""
            print(f"  {tag:12} {it.dest_rel} [{it.policy}]{extra}")
        if refusals:
            sys.stderr.write(f"{target.name}: {len(refusals)} refusal(s); resolve before syncing.\n")
            return EXIT_DRIFT
        if updates:
            print(f"{target.name}: {len(updates)} file(s) drifted (dry-run — nothing written). Re-run with --apply.")
            return EXIT_DRIFT
        print(f"{target.name}: in sync — nothing to do.")
        return EXIT_OK

    # --apply
    if refusals:
        for it in refusals:
            sys.stderr.write(f"  REFUSE {it.dest_rel} — {it.reason}\n")
        sys.stderr.write(f"{target.name}: refusing to apply — resolve the above first.\n")
        return EXIT_DRIFT
    _apply(kit_root, target, updates, tv, kit_digest)
    print(f"{target.name}: applied {len(updates)} update(s).")
    return EXIT_OK


def _resolve_target(kit_root: Path, guide: str) -> Path:
    """A bare NAME resolves as a sibling of the kit; anything path-shaped is taken
    as written.

    Sibling-only used to be the entire vocabulary — `kit_root.parent / guide` —
    and no document said so. `README.md` shows `python sync.py <guide>` and
    describes no workspace layout, so a guide checked out anywhere else failed
    with a message naming a path the operator had never typed. Accepting a path
    costs one branch and removes a constraint the tool had no reason to impose.
    """
    p = Path(guide)
    if p.is_absolute() or len(p.parts) > 1 or p.exists():
        return p.resolve()
    return (kit_root.parent / guide).resolve()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Sync the kit's shared files into a guide (copy-and-checksum).",
        epilog=("From a workspace root where the guides sit beside the kit: "
                "`python guide-kit/sync.py <guide> [--apply]`. A guide anywhere "
                "else: pass its path instead of its name."),
    )
    p.add_argument("guide", nargs="?",
                   help="Guide directory: a bare name is resolved as a sibling of "
                        "the kit; a path is used as given.")
    p.add_argument("--apply", action="store_true", help="Write the changes (default: dry-run).")
    p.add_argument("--adopt", action="store_true",
                   help="First-contact adoption (needs --source-repo and --kit-version).")
    p.add_argument("--source-repo", help="Upstream kit repo recorded at adoption (e.g. rosslevinsky/guide-kit).")
    # Same contract as bootstrap.py's: this becomes `actions/checkout`'s `ref:`
    # in verify.yml, which resolves a branch, a tag or a FULL 40-char sha and
    # fails outright on a short one. "Human-readable label" is what this said,
    # and it was in direct tension with the workflow that consumes the value.
    p.add_argument("--kit-version",
                   help="Kit commit adopted: a FULL 40-char SHA (a tag or branch "
                        "name also resolves). Used as CI's checkout ref for the "
                        "borrowed kit test runner.")
    p.add_argument("--yes", action="store_true", help="Skip the adoption confirmation prompt.")
    p.add_argument("--managed-digest", action="store_true",
                   help="Print the kit's computed managed-content digest and exit.")
    p.add_argument("--check-drift", action="store_true",
                   help="Warn-only drift check of --target against the kit (never fails).")
    p.add_argument("--target", help="Target repo path for --check-drift (default: current directory).")
    args = p.parse_args(argv)

    # One primary mode at a time; --apply modifies sync only.
    primary = [m for m in ("adopt", "managed_digest", "check_drift") if getattr(args, m)]
    if len(primary) > 1:
        p.error(f"choose at most one of --adopt / --managed-digest / --check-drift (got {primary})")
    if args.apply and (args.adopt or args.managed_digest or args.check_drift):
        p.error("--apply cannot be combined with --adopt / --managed-digest / --check-drift")

    kit_root = Path(__file__).parent.resolve()
    try:
        if args.managed_digest:
            print(compute_managed_digest(kit_root))
            return EXIT_OK
        if args.check_drift:
            drifted, msgs = drift_report(kit_root, Path(args.target or ".").resolve())
            for m in msgs:
                print(m)
            print("DRIFT DETECTED" if drifted else "UP TO DATE")
            return EXIT_OK  # warn-only: the scheduled check must never fail the run
        if not args.guide:
            p.error("a guide is required for sync / --adopt")
        target = _resolve_target(kit_root, args.guide)
        if args.adopt:
            if not args.source_repo or not args.kit_version:
                p.error("--adopt requires --source-repo and --kit-version")
            return adopt(kit_root, target, args.source_repo, args.kit_version, assume_yes=args.yes)
        return run_sync(kit_root, target, args.apply)
    except SyncError as exc:
        sys.stderr.write(f"sync.py: {exc}\n")
        return EXIT_DRIFT
    except kitconfig.KitConfigError as exc:
        # A target whose guide.toml is invalid or not yet on the declared shape is
        # an ordinary, expected refusal — the state every guide is in until it is
        # migrated. Letting it escape printed a traceback with the real message
        # buried at the bottom, which reads like a crash in sync rather than a
        # problem in the file it is telling you about.
        sys.stderr.write(f"sync.py: cannot read the target's configuration — {exc}\n")
        return EXIT_DRIFT


if __name__ == "__main__":
    raise SystemExit(main())
