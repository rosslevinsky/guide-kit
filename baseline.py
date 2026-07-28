#!/usr/bin/env python3
"""`make baseline`: promote a fresh render onto the committed reference PDF, with
a guard that closes a destructive path in code rather than by discipline.

Refuses BEFORE mutating anything (no build, no copy, no commit) on a dirty
SOURCE_FILES tree (staged, modified, or untracked). Baselining a
`· dirty`-stamped render makes a reference no future `make verify` can ever
match. Commit or revert first — `make release` is the normal
promotion path.

There is no platform guard. It was retired once rendering became hermetic:
bundled faces plus `fontconfig/fonts.conf` in every artifact's closure mean the
host does not select typography, so there is no host to bless a baseline from.
The check that replaced it is the drift canary (driftcanary.py), which compares
a fresh render against the committed reference on every CI run — a measurement
rather than a recorded intention.

Only then does it build, assert the fresh render's stamp carries no `dirty`
segment, and copy build/<slug>.pdf onto <slug>.pdf. Commit the reference
together with the source that changed it (see CLAUDE.md), or use `make release`.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import kitconfig
import verify_artifacts

ROOT = Path(__file__).parent.resolve()


def _dirty_source_files(cfg: kitconfig.KitConfig) -> list[str]:
    # Scoped to stamp_pathspec(), not SOURCE_FILES: the bundled faces feed
    # content_hash(), so an uncommitted face swap yields a render this guard
    # must refuse to bless — a reference PDF no committed state reproduces.
    #
    # `cfg` IS REQUIRED, and passing it is the whole point of this signature.
    # `stamp_pathspec()` with no config resolves its placeholders against the
    # SCHEMA DEFAULTS, so on a guide that selects a non-default theme it returned
    # `themes/classic-sans/print.css` while the render actually read
    # `themes/editorial/print.css` — and an uncommitted edit to the guide's REAL
    # theme file was invisible to this guard. Measured, on this repository: the
    # tree reported ` M themes/editorial/print.css` and the guard saw nothing.
    #
    # The consequence was not a bad reference — `buildcore._is_dirty` passes its
    # config, so the render still stamped `· dirty` and `promotable_stamp`
    # refused it. But that turned a documented "refuses BEFORE building" into a
    # wasted build plus a late, unspecific error, and left the whole guarantee
    # resting on the stamp path alone. The same shape bites `<slides_file>` for a
    # guide whose deck is not the default `slides.md`.
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", *kitconfig.stamp_pathspec("pdf", cfg)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # Fail CLOSED: baseline overwrites the reference PDF, so if we cannot
        # confirm the tree is clean we must refuse, not proceed.
        sys.exit(
            f"make baseline refused: cannot determine stamp-input cleanliness "
            f"(git error: {exc}). Aborting rather than risk blessing a dirty render."
        )
    return [line[3:] for line in out.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Promote a fresh render to a reference artifact.")
    # PER ARTIFACT, because "refresh the reference" is now a question with more
    # than one answer. This is also the enabler for the deck having a committed
    # reference at all: a reference the family cannot automatically refresh is
    # staled by the first shared-input change and stays red forever, so
    # `ArtifactSpec.reference` could not be set for slides until this existed.
    ap.add_argument("--artifact", default="pdf", choices=kitconfig.ARTIFACT_NAMES)
    # For CI: print the reference filenames this guide actually has, so the
    # workflow stages them by NAME rather than by a `$SLUG.pdf` literal — which
    # would silently never pick up `<slug>-slides.pdf`. It lives here, next to
    # the promotion logic, because a shell reimplementation of the same
    # resolution is a second source of truth that can drift.
    ap.add_argument("--list-references", action="store_true",
                    help="print each declared artifact's committed reference filename")
    args = ap.parse_args()
    artifact = args.artifact

    cfg = kitconfig.load(ROOT)

    if args.list_references:
        for name in kitconfig.ARTIFACT_NAMES:
            spec = kitconfig.artifact_spec(name)
            if spec.reference and name in cfg.outputs.declared:
                print(spec.reference.replace("<slug>", cfg.OUTPUT_SLUG))
        return 0

    spec = kitconfig.artifact_spec(artifact)
    if spec.reference is None:
        # Not an error: `site` legitimately has none, and saying so is more use
        # than a traceback. The workflow loops over every artifact and lets the
        # ones with nothing to promote say why.
        print(f"  {artifact}: no committed reference — {spec.no_reference_reason}")
        return 0
    if artifact not in cfg.outputs.declared:
        print(f"  {artifact}: not declared by this guide — nothing to promote")
        return 0

    # The guard: a dirty stamp-input tree (SOURCE_FILES plus the bundled faces).
    # Fires before anything is mutated.
    dirty = _dirty_source_files(cfg)
    if dirty:
        sys.exit(
            "make baseline refused: stamp-input tree is dirty — a `· dirty` stamp would\n"
            "become a reference no `make verify` can match. Commit or revert first:\n  "
            + "\n  ".join(dirty)
        )

    slug = cfg.OUTPUT_SLUG
    reference_name = spec.reference.replace("<slug>", slug)
    # The deck is rendered by its own build flag; the PDF by the default target.
    build_cmd = (["pixi", "run", "build"] if artifact == "pdf"
                 else ["pixi", "run", "python", "build.py", f"--{artifact}"])
    subprocess.run(build_cmd, cwd=ROOT, check=True)

    working = ROOT / "build" / reference_name
    if not working.exists():
        sys.exit(f"make baseline: expected fresh render at {working} but it's missing.")

    # Do not promote a render that isn't demonstrably fresh and clean (no stamp,
    # a dirty stamp, or a stamp that doesn't match current source — e.g. a stale
    # render left in build/), any of which would make the new reference fail
    # `make verify` immediately. Shared with `make release`.
    ok, msg = verify_artifacts.promotable_stamp(working, ROOT, artifact)
    if not ok:
        sys.exit(f"make baseline refused: {msg} — not promoting.")

    # And do not promote a render that does not look like a finished guide.
    # `promotable_stamp` is a question about BYTES — is this render fresh, clean
    # and stamped? `smoke_check` is the question about the DOCUMENT: enough
    # pages, none blank, the title present, no placeholders, and — the reason
    # this matters most — the footer stamp not WRAPPED.
    #
    # `footer_wrap_failures` is reachable only through smoke_check, so before
    # this call the local promotion path had no route to it at all. CI's
    # baseline.yml has run `make smoke` between render and commit since it was
    # written, and its own comment claims "the inspection is now the `make smoke`
    # step inside baseline.yml, which aborts before committing a bad render" —
    # true of the CI path, false of this one. Two paths doing the same job with
    # different guarantees is how recorded defect 8 (a footer wrapping on every
    # page of three shipped guides) reaches a reader.
    # The smoke check asks "does this look like a finished GUIDE" — enough pages,
    # a title, no placeholders, an unwrapped footer. That is a question about a
    # prose document, and a slide deck answers it wrongly by construction: two
    # slides is a legitimate deck and a broken guide. Applying it here would make
    # every deck unpromotable, so it runs for the PDF, which is what it was
    # written about.
    if artifact == "pdf" and verify_artifacts.smoke_check(working, ROOT) != 0:
        sys.exit(
            "make baseline refused: the fresh render does not pass `make smoke` "
            "(see above) — not promoting."
        )

    reference = ROOT / reference_name
    shutil.copyfile(working, reference)
    # NOT "stamp". `content_digest` excludes the artifact's own edition date —
    # it is the identity of the CONTENT, which is what the release transaction
    # keys on — while the footer stamp is `artifact_closure_hash`, over the full
    # closure including that date. The two differ, so printing one under the
    # other's name gave an operator a value that matches nothing they can find
    # in the PDF they just promoted.
    print(f"  {artifact} reference <- {working.relative_to(ROOT)}")
    print(f"      stamp   {kitconfig.artifact_closure_hash(artifact, root=ROOT)[:12]}"
          f"   (the hash in the footer)")
    print(f"      content {kitconfig.content_digest(artifact, root=ROOT)[:12]}"
          f"   (date-excluded — the release transaction's key)")
    print(f"  commit {reference.name} together with the source that changed it (see CLAUDE.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
