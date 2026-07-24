#!/usr/bin/env python3
"""sync.py — copy-and-checksum sync from the kit to a guide.

One canonical invocation, from the WORKSPACE ROOT (the parent of guide-template):

    python guide-template/sync.py <guide>            # dry-run: report drift, write nothing
    python guide-template/sync.py <guide> --apply    # transactional apply

`<guide>` is a sibling directory of guide-template (e.g. mac-terminal-guide), NOT
`../<guide>` — from the workspace root that would resolve outside the workspace.

Model: copy-and-checksum, not merge. The manifest (kit-manifest.toml, via
kitmanifest.py) says what each file is and what sync does to its live path:
  identical      copy kit bytes verbatim
  templated      substitute the kit's guide.toml values with the target's
  managed-region replace only the <!-- kit:begin -->..<!-- kit:end --> block
  never          target-owned — NEVER written (this is what protects the
                 macOS-rendered reference PDF, style.css, guide.md, ...)

Sync NEVER deletes: files present in a target but absent from the manifest are
left untouched. It refuses to run over unreviewed local work: a writable-tier
file whose recorded checksum no longer matches is named and the run aborts.

Exit codes (a contract — downstream phases gate on these):
    0  fully in sync
    1  drift reported (dry-run) OR a refusal (dirty tree, local edit, unadopted
       existing destination)
    2  the target has no .template-version — run `--adopt` first (Phase 6)

.template-version: a JSON record {schema_version, source_repo, kit_version,
managed_digest, state, rendered_checksums{dest -> sha256}} (Phase 6 formalizes
the schema and adds --adopt + the drift digest; this phase reads/writes it).
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
from pathlib import Path

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

_TEMPLATED_FIELDS = ("OUTPUT_SLUG", "TITLE", "AUTHOR", "DESCRIPTION", "KEYWORDS", "baseline_platform")

# Kit-only regions: lines between these sentinels exist ONLY in the kit and are
# dropped when a templated file is rendered into a target. The kit's test
# environment is the motivating case — pytest/pyyaml and the `kit` environment
# must never reach a target's pixi.toml, or every target's pixi.lock gains a
# `kit` environment and regenerates merely because the kit gained a test runner
# (plan.md:89, :90). Before this existed the sections templated through verbatim:
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
    out, depth, seen = [], 0, 0
    for line in text.splitlines(keepends=True):
        if KIT_ONLY_BEGIN in line:
            if depth:
                raise SyncError(f"{where}: nested '{KIT_ONLY_BEGIN}'")
            depth, seen = 1, seen + 1
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
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(f"{TEMPLATE_VERSION} is not valid JSON: {exc}") from exc


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
    shape = "web-enabled" if (target / "style-screen.css").exists() or (target / "app").is_dir() else "pdf-only"

    manifest = kitmanifest.load(kit_root)
    kit_digest = compute_managed_digest(kit_root)  # same snapshot as the reads below
    items: list[Item] = []
    for proj in manifest.projections(shape, slug=slug):
        if proj.policy == "never":
            continue  # target-owned; never written, never counted as drift
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
        if current_check != recorded[proj.dest]:
            items.append(Item(proj.dest, dest_abs, proj.policy, None, None, "refuse",
                              "local modification does not match recorded checksum"))
            continue

        action = "in-sync" if current == expected else "update"
        items.append(Item(proj.dest, dest_abs, proj.policy, expected,
                          _checkable_bytes(proj.policy, expected), action))
    return items, tv, kit_digest


# ---------------------------------------------------------------------------
# apply (transactional, rollback journal)
# ---------------------------------------------------------------------------

def _apply(target: Path, items: list[Item], tv: dict, kit_digest: str) -> None:
    to_write = [it for it in items if it.action in ("create", "update")]
    # Journal holds only destinations ALREADY replaced (prior bytes, or None if
    # the dest did not exist). Because _atomic_write is atomic, a FAILED write
    # leaves its dest unchanged — so we journal a dest only AFTER its write
    # succeeds, and rollback never has to "restore" a dest whose write is the one
    # that's failing (which would abort the rollback and strand earlier writes).
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

        # .template-version is written LAST but INSIDE the transaction and
        # journaled — if it fails, every destination write rolls back too, so the
        # files and the recorded checksums can never disagree.
        recorded = dict(tv.get("rendered_checksums", {}))
        for it in to_write:
            recorded[it.dest_rel] = _sha256(it.checkable)
        new_tv = dict(tv)
        new_tv["rendered_checksums"] = recorded
        new_tv["state"] = "applied"          # clears adopted_unapplied
        new_tv["managed_digest"] = kit_digest  # the SAME snapshot the plan wrote from
        tv_path = target / TEMPLATE_VERSION
        tv_prior = tv_path.read_bytes() if tv_path.exists() else None
        journal.append((tv_path, tv_prior))
        _atomic_write(tv_path, (json.dumps(new_tv, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    except BaseException:
        # Best-effort rollback across EVERY journaled entry (a single restore
        # failure must not abort the rest); report any that could not be restored.
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
    projs = [p for p in manifest.projections("web-enabled") if p.policy in _MANAGED_POLICIES]
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
    return "web-enabled" if (target / "style-screen.css").exists() or (target / "app").is_dir() else "pdf-only"


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
    for proj in manifest.projections(_target_shape(target), slug=target_cfg.OUTPUT_SLUG):
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
    or the kit's managed digest has moved since it last synced (upstream drift),
    or its own managed files were edited away from the recorded checksums
    (local drift). Warn-only — the caller decides how to surface it."""
    kit_root, target = kit_root.resolve(), target.resolve()
    tv = _read_template_version(target)
    if tv is None:
        return False, [f"{target.name}: no {TEMPLATE_VERSION} — not an adopted target; skipping."]
    msgs: list[str] = []
    drifted = False

    if tv.get("state") == "adopted_unapplied":
        drifted = True
        msgs.append(f"{target.name}: state is adopted_unapplied — behind (run --apply).")

    kit_digest = compute_managed_digest(kit_root)
    if tv.get("managed_digest") != kit_digest:
        drifted = True
        msgs.append(
            f"{target.name}: upstream managed content changed "
            f"(recorded {str(tv.get('managed_digest'))[:12]} != kit {kit_digest[:12]}) — run sync."
        )

    # Local drift: a managed file edited away from its recorded checksum.
    try:
        target_cfg = kitconfig.load(target)
        manifest = kitmanifest.load(kit_root)
        recorded = tv.get("rendered_checksums", {})
        for proj in manifest.projections(_target_shape(target), slug=target_cfg.OUTPUT_SLUG):
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
            f"{target.name}: no {TEMPLATE_VERSION} — first contact requires `--adopt` (Phase 6).\n"
        )
        return EXIT_NEEDS_ADOPT

    refusals = [it for it in items if it.action == "refuse"]
    updates = [it for it in items if it.action in ("create", "update")]

    if not apply:
        # Dry-run report.
        for it in items:
            if it.action == "in-sync":
                continue
            tag = {"update": "would update", "create": "would create", "refuse": "REFUSE"}[it.action]
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
    _apply(target, updates, tv, kit_digest)
    print(f"{target.name}: applied {len(updates)} update(s).")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Sync the kit's shared files into a sibling guide (copy-and-checksum).",
        epilog="Run from the workspace root: `python guide-template/sync.py <guide> [--apply]`.",
    )
    p.add_argument("guide", nargs="?", help="Sibling guide directory name (for sync / --adopt).")
    p.add_argument("--apply", action="store_true", help="Write the changes (default: dry-run).")
    p.add_argument("--adopt", action="store_true",
                   help="First-contact adoption (needs --source-repo and --kit-version).")
    p.add_argument("--source-repo", help="Upstream kit repo recorded at adoption (e.g. rosslevinsky/guide-template).")
    p.add_argument("--kit-version", help="Human-readable kit version label recorded at adoption.")
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
        target = kit_root.parent / args.guide
        if args.adopt:
            if not args.source_repo or not args.kit_version:
                p.error("--adopt requires --source-repo and --kit-version")
            return adopt(kit_root, target, args.source_repo, args.kit_version, assume_yes=args.yes)
        return run_sync(kit_root, target, args.apply)
    except SyncError as exc:
        sys.stderr.write(f"sync.py: {exc}\n")
        return EXIT_DRIFT


if __name__ == "__main__":
    raise SystemExit(main())
