# Contributing to guide-kit

This repository is the **toolkit**, not a guide. If you forked it to write a guide,
you don't need this file — your fork's `README.md` and `CLAUDE.md` cover the
editing loop, and `bootstrap.py` has already deleted this one.

## Setup

```bash
pixi install          # pandoc, WeasyPrint, poppler, qpdf, Python — all project-local
make                  # renders build/guide-template.pdf
pixi run test         # the kit suite
```

There is no `pip`, no virtualenv and no `brew`. If `pixi install` succeeds you have
everything; if it doesn't, that's the bug to report.

## The one rule that surprises people

**The reference PDFs at the repo root are build artifacts, and they are committed.**
Each carries a footer stamp holding a hash of its own source files, so editing any
of those files makes the committed PDF *stale by construction*. That is expected,
not a fault.

```bash
# which files stale the PDF, for this guide's actual config
pixi run python -c "import kitconfig as k; print('\n'.join(k.stamp_pathspec('pdf', k.load())))"
```

You do **not** have to re-render by hand. Push, and `verify.yml` dispatches
`baseline.yml`, which re-renders on a Linux runner, smoke-checks the result, and
commits the refreshed PDF. The push stays green throughout. Rendering is hermetic —
fonts are bundled and `fontconfig/fonts.conf` replaces the system config — so there
is no canonical machine to be on.

To do it yourself: commit your source first, then `make baseline` (add
`ARTIFACT=slides` for the deck), then fold the PDF into the same commit with
`git commit --amend --no-edit`. `make release MSG="…"` does the whole sequence in
one shot. Committing source *first* is load-bearing: a render on a dirty tree gets a
` · dirty` stamp that no later `make verify` can match, which is why `make baseline`
refuses one.

## What CI checks

`verify.yml` runs on Ubuntu only, paths-filtered: the kit suite, a PDF build smoke,
a web build smoke, `make smoke` (does the PDF look like a finished guide?),
`make verify` (is the reference stale?), and the drift canary (did the toolchain
move under us?). A pull request gets all of that and no deploy credentials — that
is deliberate and explained in the README.

## Boundaries worth knowing before you edit

- **`kit-manifest.toml` must classify every tracked file.** Add a file, add its
  entry in the same commit, or `test_manifest_roles.py` fails. A `retained-in-kit`
  entry with no `projects_to` is kit-only and is pruned from forks automatically.
- **The block between `<!-- kit:begin -->` and `<!-- kit:end -->` in `CLAUDE.md`
  is shared with every guide.** Change it here; `sync.py` propagates it. Editing a
  guide's copy is wasted work.
- **`app/wrangler.jsonc` and `style-screen.css` are target-owned.** Sync never
  writes them. `wrangler.jsonc` is generated — run `make wrangler`, don't hand-edit.
- **Each output has its own dependency closure.** A screen-only change must not
  re-stale the PDF. If your change blurs that line, `kitconfig.ArtifactSpec` is the
  place to make it explicit.

## Tests

Add one when you fix a defect, and make it fail first. The suite's own convention is
that a test should assert the *behaviour*, not the *spelling* — several files here
document a regression that a literal-matching test waved through. `tests/` is
kit-only and never syncs, so it can depend on anything the kit has.

## Style

Match the surrounding code: comments explain *why*, especially where the obvious
implementation is wrong for a reason someone had to discover. Don't cite documents
that aren't in this repository — if a decision needs recording, state it inline.

## Licensing

Code is Apache 2.0 (`LICENSE`); guide content is CC BY 4.0 (`LICENSE-CONTENT`).
Contributions are accepted under those terms.
