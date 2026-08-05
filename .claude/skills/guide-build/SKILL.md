---
name: guide-build
description: Build, verify, baseline and release a guide's artifacts. Use when running make verify / make baseline / make release, when deciding which of those commands answers which question, or after editing guide.md, style.css, guide.toml, transforms.py or a theme. Covers what each command checks, when a reference needs refreshing, and the order of steps after an edit.
---

# Building, verifying and releasing a guide

Loaded on demand. This is procedure — a session not running these commands does not need it
resident, which is why it moved out of `CLAUDE.md`.

## Verification: which command asks which question

Four commands, three questions. **Is the reference stale?** (`make verify`) — **has the
toolchain drifted?** (`make drift-canary`, with `make verify-render` as its older, weaker local
form) — **does each artifact look finished?** (`make smoke`, which covers the deck as well as
the PDF and asks each its own questions). CI runs all but `verify-render`.

- **`make verify`** — the **staleness check**, and the one a red run usually means. It compares the
  content hash embedded in the committed reference PDF's stamp against a freshly computed hash
  over `SOURCE_FILES` (one `pdftotext` call). No build, no rendering, platform-independent —
  milliseconds. It has three outcomes, not two: **stale** (the stamp parses, the hashes differ —
  someone edited source without re-running `make release`, and the error names the stale file);
  **unreadable stamp** (the stamp cannot be parsed at all, so freshness cannot be established and
  the check fails closed rather than guessing — no file is named; a reference PDF rendered before
  a stamp-format change lands here, and a re-render clears it); and **pre-first-release** (no
  reference PDF yet — passes with a notice). Note a red `make verify` also blocks `deploy.yml`,
  which gates on it.
- **`make drift-canary`** — the **environmental** check, and CI runs it as well. It builds a fresh
  PDF and compares **bytes plus the `pdffonts` embedded-face list** against the committed
  reference. Its target is drift with no source change at all — a dependency bump, a rebuilt
  runner image — which `make verify` cannot see, because `pixi.lock` is deliberately outside
  `SOURCE_FILES`. See "Dependency drift, and the canary that catches it" below for the two
  properties that make it trustworthy (it stays silent when the reference is stale, and it never
  auto-baselines).
- **`make verify-render`** — the older, weaker form of the drift question: page count plus
  stamp-excluded `pdftotext`. Kept as a local convenience. Being a text comparison it is blind to
  any change that preserves line breaks, including a face substitution — which is exactly why the
  canary above compares bytes and faces instead.

A fourth command asks something none of those three do. **`make smoke`** asks whether an
artifact *looks finished*: the other three compare bytes, hashes or text against a reference,
and on an intentional content edit the text is **supposed** to differ, so none of them would have
caught the footer wrapping onto a second line on every page of three shipped guides. It is
build-free and platform-independent, so CI runs it and `baseline.yml` gates the refreshed
reference on it.

**It covers EVERY declared artifact that has a reference, and asks each one its own question.**
It used to ignore `--artifact` outright — resolving `<slug>.pdf` whatever it was asked for — so
`make smoke ARTIFACT=slides` printed a pass for the guide PDF and the deck was committed, pushed
and published having never been inspected. Making it honour the selector showed why that had gone
unnoticed: **a deck fails the guide's assertions correctly and uselessly.** Nothing is projected
into a deck unless it is wrapped in a `::: slide` fence, so a perfectly good deck may never name
the guide. So the deck is not asked for the title, one slide is a legitimate deck, and it **is**
asked for its version stamp — the measured failure, since a full-bleed `margin: 0` makes
WeasyPrint drop every `@bottom-*` box and produce a deck that cannot say what built it.

`ARTIFACT=<pdf|slides|site>` narrows it; `PDF=<path>` inspects one file instead, which is how
`make baseline` and `make release` check a **fresh** render before promoting it — pair it with
`ARTIFACT=` for a deck, or the guide's assertions are the ones that run. Both promotion paths do
exactly that now; they used to exempt the deck, on the reasoning above, back when that reasoning
was true.

**A guide with no reference artifact yet PASSES with a notice**, matching `make verify`. It used
to exit 2 on the missing file, which made it the one command in the README's build block a
brand-new fork could not run. The discriminator is the same one staleness uses — git history for
the reference path — so a deliverable that WAS released and has gone missing still fails.

There is no image comparison anywhere anymore, and there is no canonical host: the bundled faces
make the render host-independent.

## When to run `make baseline` / `make release`

Refresh a reference after any **intentional** change to that artifact's closure, from whatever
host you have. Both commands take `ARTIFACT=` — `pdf` (the default) or `slides`, the two that HAVE a
reference. **On `site` the two commands deliberately differ.** `make baseline ARTIFACT=site` is accepted
and exits 0 printing why there is nothing to promote, because `baseline.yml` loops over every artifact
name and must not error on the one that is deployed rather than committed. `make release ARTIFACT=site`
**refuses by name and exits 1**: a release admits a new *edition*, proved against the last released
reference, and a site has none by construction — so there is no identity to prove freshness against and
every invocation would look like a first release. It refuses rather than pretending every deployment is
one. The two with references need separate refreshes because they have separate references and separate
closures — but they also *share* `_COMMON_FILES`, so a `buildcore.py` or `kitconfig.py` edit stales both
and both need refreshing.

Commit source **first**: `make baseline` on an uncommitted tree produces a `· dirty` stamp that
future `make verify` runs won't match (and `make baseline` refuses a dirty tree for exactly this
reason). `make release MSG="…"` does commit-source → render → promote → amend in one shot;
`make baseline` + a plain PDF commit is the alternative when source is already committed.

Not sure what is in the closure? Ask the kit rather than a list in prose. Pass the loaded
config — `kitconfig.SOURCE_FILES` is the static, config-free view, so it resolves
`themes/<theme>/print.css` to the **default** theme and would name the wrong sheet for any
guide that selected another one:

```bash
pixi run python -c "import kitconfig as k; print('\n'.join(k.stamp_pathspec('pdf', k.load())))"
```

The result is a git pathspec as well as a list, which is what `make verify`'s dirty check and
`make baseline`'s refusal both scope themselves to. Swap `'pdf'` for `'slides'` or `'site'`.

## After editing

```bash
# 1. Edit guide.md / style.css / guide.toml / transforms.py / a theme — or any
#    other SOURCE_FILES entry (the command above lists them)
# 2. make                          # render the working PDF (build/<slug>.pdf)
# 3. Open it and eyeball the render. Right? If not, fix and goto 2.
# 4. git commit && git push        # CI re-renders the reference PDF on Linux
```

Step 4 is a plain push from any platform. It leaves the committed reference stale, so `verify.yml`
dispatches `baseline.yml`, which re-renders on a Linux runner, smoke-checks, commits the refreshed
PDF and redeploys the site. **The push stays green** — staleness straight after a source push is
the expected state, not a fault, and only a rebuild that cannot produce a good render is reported
as a failure. `deploy.yml` skips that one deploy rather than failing it, so nothing ships stale. `make release MSG="…"` is the local equivalent of steps 2-4 and
runs from any host — rendering is hermetic, so there is no recorded platform to be on.

`release.py` refuses to run with **any** staged change, or with modifications outside the
**authorable set** (every artifact's inputs plus the bundled faces — wider than `SOURCE_FILES`,
which is the PDF's closure alone, so a `style-screen.css` edit alongside a PDF edit no longer
kills the release) — commit those with a plain `git commit` first. Doc-only edits (`README.md`,
this file, `LICENSE`, `Makefile`, `pixi.toml`, workflows) do not bump the stamp and never need a
baseline refresh. Never `git add` anything under `build/` — that is the working render, and it is
gitignored.

It also refuses unless the artifact is genuinely new (the **edition-date predicate**): the
content must differ from the last released reference, compared with the date normalised away, so
editing `[artifacts.pdf] date` by hand cannot pass off an identical PDF as a new edition.
`release.py` is the sole normal writer of that key — it assigns the release transaction's
**admission instant**, captured once and persisted on a git ref under `refs/guide-kit/`, so a
release that crosses midnight or is retried the next day keeps the date it was admitted with.
A reference whose stamp cannot be read is a **refusal**, not a first release: re-render it
(`make baseline`, or let `baseline.yml` do it) first. A retry after a failed build resumes the
same transaction and amends into the same source commit.

