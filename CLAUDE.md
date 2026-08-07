<!-- claude-front:begin — REPLACED WHOLESALE by bootstrap.py, not placeholder-filled.

     Same reasoning as README.md's front-matter block, and the same defect it was
     written for. This repository is the KIT; a fork is a book. Writing the kit's
     own opening in `{{GUIDE_NAME}}` placeholders left the kit's copy headed
     "## What this is / <DESCRIBE YOUR GUIDE>" — an unfilled blank, in the file
     that is supposed to explain the project, on a public repository.

     A fork's opening describes ITS guide, so bootstrap swaps the whole block
     rather than substituting into it. Everything below the marker — including
     the kit:begin/kit:end managed region — is untouched by that swap.
-->
# Project notes for Claude

This file documents the conventions of this project so you can make good edits.

## What this is

**This repository is `guide-kit` — the toolkit, not a guide.** It builds the guides;
it is not one of them. What it renders (`guide.md` → `guide-template.pdf`) is a
worked example that exercises every styled element, so the pipeline always has
something to build and a stylesheet change is easy to eyeball.

The shared policy below is what gets synced into every guide in the family. Change
it **here** — editing a guide's copy is overwritten on the next sync.

| Working on… | Read |
|---|---|
| The kit's own build, sync or CI | [`README.md`](README.md) |
| Contributing to the kit | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Why the family looks like this | [`docs/family-as-built.md`](docs/family-as-built.md) |
<!-- claude-front:end -->

<!-- Add your GUIDE-SPECIFIC sections (conventions, doc structure, exercise format, …) here, ABOVE the managed-region markers below. Everything between them is shared kit policy synced from guide-kit — do not edit it per-guide. -->

<!-- kit:begin -->

## Shared kit policy (synced — do not edit per-guide)

Everything between these markers is **shared across the guide family** and is kept up to
date from the kit (`guide-kit`) by `sync.py`. Do **not** edit it here for one guide —
change it in the kit and re-sync. Your guide-specific sections belong **outside** the markers.

Sync is copy-and-checksum, not merge. `sync.py <guide>` reports drift and writes nothing;
`--apply` writes transactionally, refuses a dirty tree, and prints any breaking changes your
guide has not passed **before** it writes.

### Tone

Direct and friendly. Adult reader new to the topic. No singsong asides, no fake dialogue, no
narrative openers, no pep-talk endings.

### Where the rest is

Nothing below is true in every session, so none of it loads at startup. Each arrives when
it applies:

- `.claude/rules/` — one rule per subject, keyed on the file you open: `guide.md`
  conventions and slides, `guide.toml` and its strict loader, the build pipeline and version
  stamp, the website sources, `transforms.py`, and `pixi.lock` drift.
- the `guide-build` skill — verify / baseline / release, and the order of steps after an edit.
- **the kit's** `README.md` — why the reference artifacts, the deploy path, the drift canary
  and the version stamp are shaped as they are, plus the manifest's two classification axes
  and the six-step adoption sequence. It is in the `guide-kit` checkout, not this repository:
  this block is synced verbatim into every guide, so a bare `README.md` here would name a
  file that has none of it. `guide-kit/docs/claude-md-decomposition.md` records the full
  apportionment.

<!-- kit:end -->
