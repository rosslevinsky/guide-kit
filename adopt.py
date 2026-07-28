#!/usr/bin/env python3
"""adopt.py — turn a declared output ON or OFF in an ALREADY-ADOPTED guide.

    python guide-kit/adopt.py --target ../mac-terminal-guide --output site --enable
    python guide-kit/adopt.py --target ../mac-terminal-guide --output site --disable

This is a **state transition**, not a fresh adoption. `sync.py --adopt` is
first contact and refuses a target that already has `.template-version`; this
runs on a target that is already `applied` and changes which output's managed
files it carries. Without it there is no way to add an output to a live guide:
`sync.py` refuses an existing managed destination that is absent from
`rendered_checksums` (`sync.py:368-374`), so files materialized by hand are
files sync will not touch — upstream changes to them never arrive and drift in
them is never reported, silently.

CONFIG-FIRST, and the tool NEVER writes guide.toml.
The user declares the output and commits that; `--enable` then materializes what
the declaration implies, and `--disable` removes what the un-declaration
abandoned. This is not ceremony: `guide.toml` is `policy = "never"` — target-owned
— so a tool writing it would be the one classification the manifest says must not
happen. It also keeps the declaration reviewable in the target's own history
rather than appearing as a side effect.

`--disable` DELETES rather than transferring ownership. Each managed file
whose checksum still matches its inventory record is removed; if ANY of them is
locally modified the whole transition refuses, because a silent transfer leaves
a file nobody is maintaining and a silent delete destroys someone's edit.

Transactional: every write and every delete is journaled, so a failure anywhere
rolls the target back to the state it was in.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cfadapter
import kitconfig
import kitmanifest
import sync

KIT_ROOT = Path(__file__).parent.resolve()

# Entries the web layer owns are marked `bootstrap-source` in the manifest, which
# the resolver surfaces as `web_only`. Slides has no managed destinations yet —
# `render_slides.py` and `style-slides.css` ship to every guide as ordinary
# `identical` files — so enabling it is purely a config declaration. Saying that
# here, rather than silently doing nothing, is the difference between "this output
# has nothing to materialize" and "this tool forgot about slides".
OUTPUTS = ("site", "slides")

# Appended to the target's .gitignore when the site is enabled (target-owned,
# idempotent). Untracked build output makes every later sync refuse a dirty tree.
GITIGNORE_ENTRIES = ("app/dist/", "node_modules/")

# transforms.py is NOT materialized by default: it is a SOURCE_FILES entry, so
# creating it shifts the PDF's version stamp and re-stales the reference for a
# hook most guides never use. adopt-web.py has always made it opt-in; enabling a
# SITE must not silently re-baseline the PDF.
_OPT_IN_DESTS = ("transforms.py",)

# Test seam: hook(n_written) after each write/delete, so a test can inject a
# failure mid-transition and exercise the rollback journal.
AFTER_WRITE_HOOK = None


class AdoptError(Exception):
    """A refusal: not a repo, not adopted, undeclared, or a local modification."""


def _git_toplevel(target: Path) -> None:
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=target, capture_output=True, text=True
    )
    if r.returncode != 0:
        raise AdoptError(f"--target {target} is not a git repository.")


def _declared(cfg, output: str) -> bool:
    return output in cfg.outputs.declared


def _owned_projections(kit_root: Path, target_cfg, output: str):
    """The managed destinations this OUTPUT owns.

    Resolved against the `web-enabled` shape deliberately, not the target's
    current one: `--disable` runs *after* the user has un-declared the output, at
    which point the target's own shape no longer projects the very files that
    need removing."""
    manifest = kitmanifest.load(kit_root)
    projs = manifest.expanded_projections(
        kit_root, "web-enabled", slug=target_cfg.OUTPUT_SLUG)
    if output == "site":
        return [p for p in projs if p.web_only]
    return []


def _load_tv(target: Path) -> tuple[Path, dict]:
    tv_path = target / sync.TEMPLATE_VERSION
    if not tv_path.is_file():
        raise AdoptError(
            f"{target.name} has no {sync.TEMPLATE_VERSION} — this is a state transition "
            f"for an adopted target, not first contact. Run "
            f"`sync.py {target.name} --adopt` first."
        )
    tv = json.loads(tv_path.read_text(encoding="utf-8"))
    state = tv.get("state")
    if state != "applied":
        # `adopted_unapplied` records the checksums of files that were ALREADY in
        # the target at first contact — files sync has never written. Transitioning
        # from that state would let `--disable` delete pre-existing content on the
        # strength of an inventory that only ever described it, never produced it.
        raise AdoptError(
            f"{target.name} is in state {state!r}, not 'applied'. A transition acts on "
            f"files sync has actually written; run `sync.py {target.name} --apply` first."
        )
    return tv_path, tv


def _require_clean(kit_root: Path, target: Path) -> None:
    """The declaration must be COMMITTED before the transition acts on it.

    Without this the config edit and the file changes are separable: undeclare the
    site in an uncommitted `guide.toml`, disable, then restore the edit — and the
    repository declares a site whose managed state has been deleted. It also keeps
    the transition reviewable, since `git status` afterwards shows exactly what the
    tool did and nothing else."""
    if sync._is_dirty(kit_root):
        # The same refusal `sync --apply` makes: uncommitted kit bytes would be
        # copied into the target and recorded as the kit's content, so the
        # inventory would describe a commit that does not exist.
        raise AdoptError(
            "refusing: the KIT worktree is dirty — commit the kit's changes first, "
            "or the transition records bytes no commit contains."
        )
    if sync._is_dirty(target):
        raise AdoptError(
            f"refusing: the target worktree ({target.name}) is dirty. Commit the "
            f"guide.toml declaration (and anything else in flight) first, so the "
            f"transition is reviewable against a clean tree."
        )


def _gitignore_bytes(target: Path) -> bytes | None:
    """The `.gitignore` with the web entries appended, or None if all are present.

    Target-owned, appended idempotently — and NOT optional: without `app/dist/`
    and `node_modules/`, the first web build or `npm install` leaves generated
    output untracked, and every later sync refuses the target as a dirty tree."""
    p = target / ".gitignore"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    missing = [e for e in GITIGNORE_ENTRIES if e not in set(text.splitlines())]
    if not missing:
        return None
    prefix = "" if (text == "" or text.endswith("\n")) else "\n"
    header = ("" if text == "" else "\n") + "# Opt-in web layer (added by adopt.py)\n"
    return (text + prefix + header + "".join(f"{e}\n" for e in missing)).encode("utf-8")


def _commit(target: Path, writes: list[tuple[Path, bytes]],
            deletes: list[Path]) -> None:
    """Apply every write and delete under one rollback journal."""
    journal: list[tuple[Path, bytes | None]] = []
    try:
        for dest, content in writes:
            journal.append((dest, dest.read_bytes() if dest.exists() else None))
            sync._atomic_write(dest, content)
            if AFTER_WRITE_HOOK is not None:
                AFTER_WRITE_HOOK(len(journal))
        for dest in deletes:
            journal.append((dest, dest.read_bytes() if dest.exists() else None))
            dest.unlink(missing_ok=True)
            if AFTER_WRITE_HOOK is not None:
                AFTER_WRITE_HOOK(len(journal))
    except BaseException:
        for dest, prior in reversed(journal):
            try:
                dest.unlink(missing_ok=True) if prior is None else sync._atomic_write(dest, prior)
            except Exception as exc:
                sys.stderr.write(f"adopt.py: WARNING could not roll back {dest}: {exc}\n")
        raise


def enable(kit_root: Path, target: Path, output: str,
           with_transforms: bool = False) -> int:
    kit_root, target = kit_root.resolve(), target.resolve()
    if not target.is_dir():
        raise AdoptError(f"--target not found: {target}")
    _git_toplevel(target)
    _require_clean(kit_root, target)
    tv_path, tv = _load_tv(target)

    target_cfg = kitconfig.load(target)
    if not _declared(target_cfg, output):
        raise AdoptError(
            f"{target.name} does not declare the {output!r} output, so there is nothing "
            f"to enable. Declare it in [outputs] and add an [artifacts.{output}] table "
            f"with its date in {target.name}/guide.toml, commit that, then re-run. "
            f"(adopt.py never writes guide.toml — it is target-owned.)"
        )

    kit_cfg = kitconfig.load(kit_root)
    recorded = dict(tv.get("rendered_checksums", {}))
    writes: list[tuple[Path, bytes]] = []
    n_new = 0
    for proj in _owned_projections(kit_root, target_cfg, output):
        if proj.dest in _OPT_IN_DESTS and not with_transforms:
            continue
        src = kit_root / proj.source
        if proj.dest == f"app/{cfadapter.WRANGLER_FILENAME}":
            # GENERATED from the target's own guide.toml — the same rule
            # bootstrap.py and adopt-web.py follow. Copying the kit's file here
            # would enable a site whose Worker is named after the KIT, with no
            # routes block and workers_dev off: it would deploy to the wrong
            # Worker and bind nothing.
            content = cfadapter.render_wrangler_jsonc(target_cfg).encode("utf-8")
        elif proj.policy == "templated":
            content = sync._render_templated(
                src.read_bytes().decode("utf-8"), kit_cfg, target_cfg).encode("utf-8")
        else:
            content = src.read_bytes()
        dest = sync._resolve_dest(target, proj.dest)
        if dest.exists():
            # Byte-identical is idempotent; different is a collision this tool
            # will not resolve by clobbering.
            if dest.read_bytes() != content:
                raise AdoptError(
                    f"refusing: {proj.dest} already exists in {target.name} and differs "
                    f"from the kit's version — resolve it by hand."
                )
        else:
            writes.append((dest, content))
            n_new += 1
        # never-tier destinations are target-owned seeds: written once, then never
        # managed, so they are not recorded.
        if proj.policy in ("identical", "templated"):
            recorded[proj.dest] = sync._sha256(
                sync._checkable_bytes(proj.policy, content))

    if output == "site":
        gi = _gitignore_bytes(target)
        if gi is not None:
            writes.append((target / ".gitignore", gi))
    tv["rendered_checksums"] = recorded          # `state` is left untouched
    writes.append((tv_path, (json.dumps(tv, indent=2, sort_keys=True) + "\n").encode("utf-8")))
    _commit(target, writes, [])
    print(f"{target.name}: {output} enabled "
          f"({n_new} file(s) written, {len(recorded)} recorded).")
    return 0


def disable(kit_root: Path, target: Path, output: str) -> int:
    kit_root, target = kit_root.resolve(), target.resolve()
    if not target.is_dir():
        raise AdoptError(f"--target not found: {target}")
    _git_toplevel(target)
    _require_clean(kit_root, target)
    tv_path, tv = _load_tv(target)

    target_cfg = kitconfig.load(target)
    if _declared(target_cfg, output):
        raise AdoptError(
            f"{target.name} still declares the {output!r} output. Un-declare it in "
            f"[outputs] (and remove the [artifacts.{output}] table) in "
            f"{target.name}/guide.toml, commit that, then re-run. (adopt.py never "
            f"writes guide.toml — it is target-owned.)"
        )

    recorded = dict(tv.get("rendered_checksums", {}))
    deletes: list[Path] = []
    modified: list[str] = []
    for proj in _owned_projections(kit_root, target_cfg, output):
        if proj.dest not in recorded:
            continue                     # never managed here; not ours to remove
        dest = sync._resolve_dest(target, proj.dest)
        if not dest.exists():
            recorded.pop(proj.dest, None)
            continue
        current = sync._sha256(sync._checkable_bytes(proj.policy, dest.read_bytes()))
        if current != recorded[proj.dest]:
            modified.append(proj.dest)
            continue
        deletes.append(dest)
        recorded.pop(proj.dest, None)

    # The WHOLE transition refuses on any local modification. Deleting the
    # matching files and leaving the edited ones would be the worst outcome: a
    # half-removed output whose remnants nobody owns.
    if modified:
        raise AdoptError(
            f"refusing to disable {output} in {target.name} — these managed files are "
            f"locally modified:\n  " + "\n  ".join(modified)
            + "\nCommit or revert them, or move them out of the managed set, then re-run."
        )

    tv["rendered_checksums"] = recorded
    writes = [(tv_path, (json.dumps(tv, indent=2, sort_keys=True) + "\n").encode("utf-8"))]
    _commit(target, writes, deletes)
    print(f"{target.name}: {output} disabled ({len(deletes)} file(s) deleted, "
          f"{len(recorded)} recorded).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Enable or disable a declared output in an already-adopted guide.",
        epilog="Config-first: declare the output in the target's guide.toml and commit "
               "it first; adopt.py never writes that file.",
    )
    p.add_argument("--target", required=True, help="Path to the guide repo to transition.")
    p.add_argument("--output", required=True, choices=OUTPUTS,
                   help="Which declared output to transition.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enable", action="store_true", help="Materialize the output's managed files.")
    mode.add_argument("--disable", action="store_true", help="Delete them (refuses on local edits).")
    p.add_argument("--with-transforms", action="store_true",
                   help="Also activate the transforms.py hook (shifts the version stamp).")
    args = p.parse_args(argv)
    try:
        if args.enable:
            return enable(KIT_ROOT, Path(args.target), args.output, args.with_transforms)
        return disable(KIT_ROOT, Path(args.target), args.output)
    except AdoptError as exc:
        sys.stderr.write(f"adopt.py: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
