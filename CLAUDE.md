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

### Per-guide values: `guide.toml`

Everything a guide states about itself lives in `guide.toml`, read and validated by
`kitconfig.py` — the single strict loader, which **rejects unknown keys**, so a retired or
misspelled key fails loudly instead of silently doing nothing. Six identity constants:
`TITLE`, `OUTPUT_SLUG`, `AUTHOR`, `DESCRIPTION`, `KEYWORDS` and `COPYRIGHT_YEAR`. Alongside
them the declared shape and its supporting tables: `[outputs]`, one `[artifacts.<name>]`
edition date per declared output, `[theme]`, `[site]`, `[slides]`, `[deploy]` and `[fonts]`.
The README's "Every key, in one config that loads" block is the whole vocabulary, and a test
feeds it to the real loader so it cannot drift from the schema.

No renderer holds a guide-specific literal — they all read through kitconfig. The four
`LICENSE_*` constants stay in `buildcore.py` because they are family-fixed, not per-guide.
`OUTPUT_SLUG` drives the PDF filename and the worker name and is **independent of the repo
name** (e.g. a repo can render `git-github-for-beginners.pdf`). `COPYRIGHT` is derived as
`© {COPYRIGHT_YEAR} {AUTHOR}` — a stored constant, never a clock read, so renders stay
deterministic.

### Build pipeline

```
guide.md  --pandoc-->  HTML body  --transforms.py?-->  HTML'  --wrap-->  styled HTML  --WeasyPrint-->  PDF  --qpdf-->  PDF (canonical)
                                                                                ^
                                                              themes/<theme>/print.css + style.css
```

`build.py` is only the CLI: it parses the flags and dispatches. `buildcore.py` is the
artifact-neutral pipeline — config and paths, the version stamp, the transforms hook, the
glyph-coverage gate, pandoc, the shared HTML wrapper — and one `render_*.py` owns each output
(`render_pdf.py`, `render_site.py`, `render_slides.py`). That split is not tidiness: pipeline
code used to live in `build.py`, which is a stamp input for **every** artifact, so a
website-only change re-staled every reference PDF in the family. The renderers are imported
lazily, per branch, so the isolation the closures declare is real at run time too.

Run `make` to build (writes the working render to `build/<slug>.pdf`). `make html` renders
a standalone HTML preview. The pipeline pins WeasyPrint's timestamp via `SOURCE_DATE_EPOCH`
— midnight UTC of the artifact's **authored** `[artifacts.<name>] date`, never a clock or a
commit time — and canonicalizes with `qpdf --deterministic-id --normalize-content=y`, so two
builds of identical committed source produce content-identical PDFs.

### The version stamp

The PDF footer carries `YYYY-MM-DD · <sha256[:12]>`. The date is the artifact's authored
`[artifacts.<name>] date` in `guide.toml` — an *edition* date, not a commit date — and the hash
is over that artifact's own dependency closure, so the site's stamp and the PDF's move
independently. A ` · dirty` segment is appended when the working tree has uncommitted changes
to that artifact's inputs. Why the render path reads no git history: see `README.md`.

### The kit, the manifest, and `sync.py`

Sync is copy-and-checksum, not merge. **This `CLAUDE.md` is a `managed-region` file** — only
the block between the markers is replaced.

`sync.py <guide>` reports drift and writes nothing; `--apply` writes transactionally and refuses
a dirty tree. It prints any breaking changes your guide has not passed yet **before** it writes.

The manifest's two classification axes, the six-step adoption sequence, and why a sync can hand
you a change it cannot make for you are in the kit's `README.md`.

### Tone

Direct and friendly. Adult reader new to the topic. No singsong asides, no fake dialogue, no
narrative openers, no pep-talk endings.

### Where everything else went

Loaded on demand instead, because none of it is true every session:

- `.claude/rules/` — `guide.md` conventions, site sources, `transforms.py`, slides, and
  `pixi.lock` changes. Each loads only when a matching file is opened.
- the `guide-build` skill — verify / baseline / release, and the order of steps after an edit.
- **the kit's** `README.md` — why the reference artifacts, the deploy path, the drift canary
  and the version stamp are shaped as they are, plus the manifest and adoption detail. It is
  in the `guide-kit` checkout, not this repository: this block is synced verbatim into every
  guide, so a bare `README.md` here would name a file that has none of it.
  `guide-kit/docs/claude-md-decomposition.md` records the full apportionment.

<!-- kit:end -->
