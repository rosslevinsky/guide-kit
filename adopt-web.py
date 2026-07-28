#!/usr/bin/env python3
"""adopt-web.py — add the opt-in web layer to an ALREADY-INITIALIZED guide.

SUPERSEDED BY `adopt.py`, which generalizes this to any declared output:

    python guide-kit/adopt.py --target ../my-guide --output site --enable
    python guide-kit/adopt.py --target ../my-guide --output site --disable

Prefer that one. It is config-first (the guide declares `[outputs] site` and its
`[artifacts.site]` date and commits that; `--enable` then materializes what the
declaration implies), and it can also turn an output back OFF, which this file
has no path for. This remains as the single-purpose form it grew out of.

Two-root model: an immutable **kit_root** (this script's directory — staging
assets are READ from it, never written or deleted) and an explicit **--target**
(the guide to web-enable). bootstrap.py cannot serve this: it self-deletes on
success, hard-refuses once the sentinel is gone, and anchors ROOT to its own
directory (so running the kit's copy against another repo would materialize the
web layer INTO the kit and delete the kit's own bootstrap).

    python guide-kit/adopt-web.py --target ../mac-terminal-guide
    python guide-kit/adopt-web.py --target ../mac-terminal-guide --with-transforms

It is transactional (rollback on any failure), idempotent (a second run on an
already-adopted target is a no-op), refuses a non-identical pre-existing
collision, and — crucially — records every new MANAGED destination in the
target's .template-version.rendered_checksums, so a later `sync.py --apply` does
not refuse the files the kit just wrote (sync refuses an existing managed dest
absent from rendered_checksums). It leaves `state` untouched.

transforms.py is NOT activated unless --with-transforms: it is a SOURCE_FILES
entry, so writing it shifts the version stamp, and most guides (e.g. the mac
terminal guide) have no videos to embed.
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
GITIGNORE_ENTRIES = ("app/dist/", "node_modules/")

# Test seam: called as hook(n_written) after each write during adoption, so a
# test can inject a failure and exercise the rollback journal. None in normal use.
AFTER_WRITE_HOOK = None


class AdoptError(Exception):
    """A refusal (collision, non-repo target, missing .template-version)."""


def _git_toplevel(target: Path) -> None:
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=target, capture_output=True, text=True
    )
    if r.returncode != 0:
        raise AdoptError(f"--target {target} is not a git repository.")
    top = Path(r.stdout.strip()).resolve()
    if top != target.resolve():
        raise AdoptError(f"--target {target} is not the repository root (that is {top}).")


class _W:
    """One planned write: dest, its bytes, and the tier to record (or None)."""

    def __init__(self, rel: str, dest: Path, content: bytes, record: str | None):
        self.rel, self.dest, self.content, self.record = rel, dest, content, record


def _plan(kit_root: Path, target: Path, with_transforms: bool) -> list[_W]:
    kit_cfg = kitconfig.load(kit_root)
    target_cfg = kitconfig.load(target)
    manifest = kitmanifest.load(kit_root)
    writes: list[_W] = []
    for proj in manifest.expanded_projections(
            kit_root, "web-enabled", slug=target_cfg.OUTPUT_SLUG):
        if not proj.web_only:
            continue  # only the bootstrap-source web layer
        if proj.dest == "transforms.py" and not with_transforms:
            continue
        src = kit_root / proj.source
        if proj.dest == f"app/{cfadapter.WRANGLER_FILENAME}":
            # GENERATED from the target's own guide.toml, not copied. Its `routes`
            # block is conditional structure — present only when [deploy] domain is
            # set — which neither a verbatim copy nor value substitution can
            # express, and the domain-less target is the case that matters most.
            content = cfadapter.render_wrangler_jsonc(target_cfg).encode("utf-8")
        elif proj.policy == "templated":
            content = sync._render_templated(src.read_bytes().decode("utf-8"), kit_cfg, target_cfg).encode("utf-8")
        else:
            content = src.read_bytes()
        # record only writable tiers; never-tier (seed style-screen.css / transforms.py) is target-owned.
        record = proj.policy if proj.policy in ("identical", "templated") else None
        writes.append(_W(proj.dest, sync._resolve_dest(target, proj.dest), content, record))
    # NOTE: verify_web.py is deliberately NOT handled here. It is a retained-in-kit
    # `identical` file that sync already projects into EVERY guide (pdf-only too),
    # so sync creates/updates/records it like build.py or the Makefile. Adopting it
    # here would spuriously REFUSE web adoption whenever the target's copy is merely
    # out of date with the kit — the fix for which is `sync --apply`, not adopt-web.
    return writes


def _gitignore_bytes(target: Path) -> bytes | None:
    """The new .gitignore bytes with the web entries appended, or None if all
    entries are already present (idempotent — no duplicates)."""
    p = target / ".gitignore"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    missing = [e for e in GITIGNORE_ENTRIES if e not in set(text.splitlines())]
    if not missing:
        return None
    prefix = "" if (text == "" or text.endswith("\n")) else "\n"
    header = ("" if text == "" else "\n") + "# Opt-in web layer (added by adopt-web.py)\n"
    return (text + prefix + header + "".join(f"{e}\n" for e in missing)).encode("utf-8")


def adopt_web(kit_root: Path, target: Path, with_transforms: bool = False) -> int:
    kit_root, target = kit_root.resolve(), target.resolve()
    if not target.is_dir():
        raise AdoptError(f"--target not found: {target}")
    _git_toplevel(target)
    tv_path = target / sync.TEMPLATE_VERSION
    if not tv_path.is_file():
        raise AdoptError(
            f"{target.name} has no {sync.TEMPLATE_VERSION} — adopt the kit first "
            f"(`sync.py {target.name} --adopt`), then run adopt-web.py."
        )

    # Shape is DECLARED, and sync now resolves managed destinations from that
    # declaration rather than from which files exist. So materializing the web
    # layer under `outputs.site = "none"` would write files that sync then
    # refuses to see: upstream web changes would never reach the target and
    # drift in them would never be reported — silently, which is the worst
    # version of this failure.
    #
    # Config-first: this tool does NOT write guide.toml (it is
    # target-owned, `policy = "never"`). The user declares the site and commits,
    # then adopts.
    target_cfg = kitconfig.load(target)
    if target_cfg.outputs.site == "none":
        raise AdoptError(
            f'{target.name} declares outputs.site = "none" — the web layer must be '
            f"DECLARED before it is materialized, or sync will not manage the files "
            f'this would write. Set `site` in [outputs] (e.g. "single") and add an '
            f"[artifacts.site] table with its date in {target.name}/guide.toml, commit "
            f"that, then re-run adopt-web.py."
        )

    plan = _plan(kit_root, target, with_transforms)

    # Preflight: an existing destination that DIFFERS is a collision; one that
    # MATCHES is idempotent (skip the write, still record it below).
    to_write: list[_W] = []
    for w in plan:
        if w.dest.exists():
            if w.dest.read_bytes() != w.content:
                raise AdoptError(
                    f"refusing: {w.rel} already exists in {target.name} and differs from the "
                    "web-layer version — resolve it by hand (never clobbered by default)."
                )
        else:
            to_write.append(w)

    # Build the FULL write set — web files, .gitignore, and .template-version —
    # and journal them all together so ANY failure rolls back everything (never
    # the "files present but unrecorded" state a later `sync --apply` refuses).
    recorded = {**json.loads(tv_path.read_text(encoding="utf-8")).get("rendered_checksums", {})}
    for w in plan:
        if w.record is not None:
            recorded[w.rel] = sync._sha256(sync._checkable_bytes(w.record, w.content))
    tv = json.loads(tv_path.read_text(encoding="utf-8"))
    tv["rendered_checksums"] = recorded  # state left untouched
    final_writes: list[tuple[Path, bytes]] = [(w.dest, w.content) for w in to_write]
    gi = _gitignore_bytes(target)
    if gi is not None:
        final_writes.append((target / ".gitignore", gi))
    final_writes.append((tv_path, (json.dumps(tv, indent=2, sort_keys=True) + "\n").encode("utf-8")))

    journal: list[tuple[Path, bytes | None]] = []
    try:
        for dest, content in final_writes:
            journal.append((dest, dest.read_bytes() if dest.exists() else None))
            sync._atomic_write(dest, content)
            if AFTER_WRITE_HOOK is not None:
                AFTER_WRITE_HOOK(len(journal))
    except BaseException:
        for dest, prior in reversed(journal):
            try:
                dest.unlink(missing_ok=True) if prior is None else sync._atomic_write(dest, prior)
            except Exception as exc:
                sys.stderr.write(f"adopt-web.py: WARNING could not roll back {dest}: {exc}\n")
        raise

    if to_write:
        print(f"{target.name}: web layer adopted ({len(to_write)} file(s) written, {len(recorded)} recorded).")
    else:
        print(f"{target.name}: already web-enabled — no changes (idempotent).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Add the opt-in web layer to an already-initialized guide (kit_root + --target).",
    )
    p.add_argument("--target", required=True, help="Path to the guide repo to web-enable.")
    p.add_argument("--with-transforms", action="store_true",
                   help="Also activate the transforms.py hook (shifts the version stamp).")
    args = p.parse_args(argv)
    try:
        return adopt_web(KIT_ROOT, Path(args.target), args.with_transforms)
    except AdoptError as exc:
        sys.stderr.write(f"adopt-web.py: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
