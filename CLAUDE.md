# Project notes for Claude

This file documents the conventions of this project so you can make good edits.

## What this is

<DESCRIBE YOUR GUIDE>

A single-document Markdown → PDF project for `{{GUIDE_NAME}}`. Source lives in `guide.md`; styling in `style.css`; the per-guide constants in `guide.toml`; the build pipeline in `build.py`. The committed reference PDF `{{GUIDE_SLUG}}.pdf` at the repo root is the deliverable readers download.

<!-- Add your GUIDE-SPECIFIC sections (conventions, doc structure, exercise format, …) here, ABOVE the managed-region markers below. Everything between them is shared kit policy synced from guide-template — do not edit it per-guide. -->

<!-- kit:begin -->

## Shared kit policy (synced — do not edit per-guide)

Everything between these markers is **shared across the guide family** and is kept up to
date from the kit (`guide-template`) by `sync.py`. Do **not** edit it here for one guide —
change it in the kit and re-sync. Your guide-specific sections belong **outside** the markers.

### Per-guide constants: `guide.toml`

The seven per-guide values live in `guide.toml`, read and validated by `kitconfig.py`
(the single strict loader): `TITLE`, `OUTPUT_SLUG`, `AUTHOR`, `DESCRIPTION`, `KEYWORDS`,
`COPYRIGHT_YEAR`, and `baseline_platform`. `build.py` reads them through kitconfig and
holds no guide-specific literal (the four `LICENSE_*` constants stay in `build.py` —
they are family-fixed). `OUTPUT_SLUG` drives the PDF filename and is **independent of the
repo name** (e.g. a repo can render `git-github-for-beginners.pdf`). `COPYRIGHT` is
derived as `© {COPYRIGHT_YEAR} {AUTHOR}` — a stored constant, never a clock read, so
renders stay deterministic.

### Build pipeline

```
guide.md  --pandoc-->  HTML body  --transforms.py?-->  HTML'  --wrap-->  styled HTML  --WeasyPrint-->  PDF  --qpdf-->  PDF (canonical)
                                                                                ^
                                                                            style.css
```

Run `make` to build (writes the working render to `build/<slug>.pdf`). `make html` renders
a standalone HTML preview. The pipeline pins WeasyPrint's timestamp via `SOURCE_DATE_EPOCH`
(from the most-recent source commit) and canonicalizes with `qpdf --deterministic-id
--normalize-content=y`, so two builds of identical committed source produce content-identical
PDFs.

### Markdown vs. HTML conventions

`guide.md` is real Markdown for almost everything. Inline HTML is reserved for elements
Markdown cannot express — the fixed, allowed island vocabulary (each recognized and styled by
`style.css`):

| HTML | Purpose |
|------|---------|
| `<div class="title-block">` | Document title (h1) + tagline at the top of page 1. |
| `<div class="callout warn">` | Amber warning box. First paragraph's leading `**bold**` becomes the header. |
| `<div class="callout tip">` | Green tip box. Same bold-becomes-header convention. |
| `<div class="callout accent">` | Light-blue mental-model callout; plain prose. |
| `<div class="exercise">` | Green-bordered exercise box; first paragraph becomes the title strip. |
| `<pre class="diagram">…</pre>` | Monospace ASCII-diagram panel (`<pre>` required — pandoc collapses whitespace in a plain `<div>`). |
| `<div class="page-break"></div>` | Forces a page break. |
| `<div class="embed youtube" data-id="VIDEO_ID">label</div>` | (Opt-in web layer) A YouTube embed; `transforms.py` rewrites it per output. Inert without an active `transforms.py`. |

Do **not** add other island types. Do **not** convert Markdown that already works into HTML.
Smart quotes are disabled in pandoc (`markdown+raw_html-smart`) so `---`, `'`, and `"` stay
literal for ASCII diagrams and copy-pasteable snippets.

### The version stamp

The PDF footer carries `YYYY-MM-DD HH:MM:SS · <sha256[:12]>` derived from the `SOURCE_FILES`
list — `guide.md`, `style.css`, `build.py`, `transforms.py`, `guide.toml`, `kitconfig.py`
(the canonical list lives in `kitconfig.py`). Date/time is `%ad` (**author** date) of the most
recent commit touching any of those, not `%cd`: `git commit --amend` inside `release.py` perturbs
committer time, so `%ad` keeps the displayed stamp stable across the release amend. The hash is
the sha256 over those files' bytes.
A ` · dirty` segment is appended when the working tree has uncommitted changes to any of them.

### Verification: two commands, not one

- **`make verify`** — the **staleness check**, and the only verify CI runs. It compares the
  content hash embedded in the committed reference PDF's stamp against a freshly computed hash
  over `SOURCE_FILES` (one `pdftotext` call). No build, no rendering, platform-independent —
  milliseconds. It has three outcomes, not two: **stale** (the stamp parses, the hashes differ —
  someone edited source without re-running `make release`, and the error names the stale file);
  **unreadable stamp** (the stamp cannot be parsed at all, so freshness cannot be established and
  the check fails closed rather than guessing — no file is named; a reference PDF rendered before
  a stamp-format change lands here, and a re-render clears it); and **pre-first-release** (no
  reference PDF yet — passes with a notice). Note a red `make verify` also blocks `deploy.yml`,
  which gates on it.
- **`make verify-render`** — a secondary, **canonical-host-only** canary: it builds a fresh PDF
  and compares page count plus stamp-excluded `pdftotext` against the reference. It needs a build
  and is platform-sensitive (font substitution changes line wrapping), so it is **never** wired
  into CI. Its one genuine catch is environmental drift (a dependency bump that shifts layout with
  no source change).

There is no image comparison anywhere anymore.

### Reference PDFs are canonical-host-rendered (the `baseline_platform` guard)

Every guide's reference PDF is the reader-facing deliverable, and the family renders them on **one
canonical host** so the downloadable PDFs share typography. `guide.toml` records
`baseline_platform`; `make baseline` and `make release` both **refuse** when `sys.platform`
differs from it (unless explicitly overridden). `make baseline` additionally **refuses a dirty
`SOURCE_FILES` tree** (a `· dirty` baseline could never be matched by `make verify`); `make
release` instead **commits** your source edits itself and then refuses to promote a render whose
stamp is `· dirty` or stale (the same freshness guard), so neither command can bless an
unmatchable reference. The `.github/workflows/baseline.yml` workflow
renders the reference PDF on a `macos-latest` runner and commits it, so no physical Mac is
needed. **You do not normally dispatch it yourself:** when a push to the default branch leaves
the reference stale, `verify.yml` goes red and auto-dispatches `baseline.yml`, which renders,
smoke-checks, commits the PDF, and then dispatches `deploy.yml` so the site stops serving the
old download. That first red verify run is expected — the commit `baseline.yml` pushes is the
green one. So the everyday flow for a content edit is just **commit and push `guide.md`**;
`make release` is for refreshing the reference by hand on a canonical host, and
`gh workflow run baseline.yml` is the repair path when a site drifted without a source change.

### The transforms hook (per-output)

If `transforms.py` exists next to `build.py`, the pipeline calls one entry point between pandoc
and the renderer, chosen by target: `post_pandoc_html_for_pdf` / `post_pandoc_html_for_web`, with
a single-entry `post_pandoc_html` fallback. `transforms.py` is always a `SOURCE_FILES` entry — a
missing file contributes no bytes — so **creating** it shifts the version stamp (refresh the
reference PDF afterward). Activate it only if the guide needs a substantive transform (the worked
example is the YouTube-embed split).

### The website (opt-in)

The PDF is the default output. A guide opts into a website (Cloudflare Workers Static Assets) at
bootstrap (`bootstrap.py --with-web`) or later with `adopt-web.py --target <guide>`. When enabled,
`make web` renders `app/dist/index.html` (screen HTML + a copy of the committed reference PDF) —
and **hard-fails** if the reference PDF is missing (a site must not ship a 404 download link).
`style-screen.css` is not a `SOURCE_FILES` entry. `verify_web.py` asserts the per-output embed
split and skips cleanly when there is no web layer or no embed island.

### The kit, the manifest, and `sync.py`

This guide is kept in sync with the kit (`guide-template`) by copy-and-checksum, not merge.
`kit-manifest.toml` classifies every kit file on **two independent axes**: source lifecycle
(`retained-in-kit` / `bootstrap-source` / `generated`) and destination policy (`identical` /
`templated` / `managed-region` / `never`). `sync.py <guide>` reports drift and writes nothing;
`sync.py <guide> --apply` writes transactionally and refuses a dirty tree or an unrecorded managed
file. **This `CLAUDE.md` is a `managed-region` file** — only the block between the markers is
synced; your own sections outside them are never touched.

First contact uses the **six-step adoption sequence**: (1) hand-write the guide's `guide.toml` and
insert the managed-region markers in this file; (2) review and commit; (3) confirm a clean
worktree; (4) `sync.py <guide> --adopt --source-repo <owner/repo> --kit-version <ref>` (both flags
are required; records pre-sync hashes; state `adopted_unapplied`); (5) commit `.template-version`;
(6) `sync.py <guide> --apply` (state → `applied`). A scheduled,
warn-only `kit-drift.yml` reports when the kit's managed content moves.

### When to run `make baseline` / `make release`

Refresh the reference PDF after any **intentional** change to a `SOURCE_FILES` entry, on the
canonical host. Commit source **first**: `make baseline` on an uncommitted tree produces a
`· dirty` stamp that future `make verify` runs won't match (and `make baseline` refuses a dirty
tree for exactly this reason). `make release MSG="…"` does commit-source → render → promote →
amend in one shot; `make baseline` + a plain PDF commit is the alternative when source is already
committed.

### After editing

```bash
# 1. Edit guide.md / style.css / build.py / transforms.py / guide.toml
# 2. make                          # render the working PDF (build/<slug>.pdf)
# 3. Open it and eyeball the render. Right? If not, fix and goto 2.
# 4. git commit && git push        # CI re-renders the reference PDF on macOS
```

Step 4 is a plain push from any platform. It leaves the committed reference stale, so `verify.yml`
goes red and auto-dispatches `baseline.yml`, which re-renders on a macOS runner, smoke-checks,
commits the refreshed PDF and redeploys the site. **Expect that one red verify run** — the commit
behind it is the green one, and `deploy.yml` is gated on the same staleness check, so it stays red
until the refreshed PDF lands. `make release MSG="…"` is the local equivalent of steps 2-4 and is
the right tool **on the canonical host only**; it refuses to run anywhere else.

`release.py` refuses to run with staged changes or modifications outside `SOURCE_FILES` — commit
those with a plain `git commit` first. Doc-only edits (`README.md`, this file, `LICENSE`,
`Makefile`, `pixi.toml`, workflows) do not bump the stamp and never need a baseline refresh.
Never `git add` anything under `build/` — that is the working render, and it is gitignored.

### The one thing verification cannot catch: dependency drift

`make verify` compares hashes over `SOURCE_FILES`. `pixi.lock` is **not** in that list, so a
dependency bump that changes how WeasyPrint or fontconfig lays out text will shift the rendered
PDF while `make verify` stays green — the source really is unchanged, so the staleness check is
answering its question correctly. Nothing in CI closes this gap either.

`make verify-render` is the closest thing to a backstop, but it is **not** a complete one: it
compares page count and stamp-stripped `pdftotext` output, so it catches drift that moves
pagination or extracted text and is blind to pure metric changes — kerning, justification, glyph
substitution that happens to preserve line breaks. It also needs a build, and while it is
*conventionally* run only on the canonical host, nothing enforces that (unlike `make baseline`,
which does check `sys.platform`).

So treat a `pixi.lock` change as a **rendering** change: run `make verify-render` on the canonical
host after one, **and eyeball the PDF** — the automated check alone is not sufficient. Re-baseline
if the layout moved, and pin tighter in `pixi.toml` if a guide needs a narrower window.
(`fontconfig` in particular already differs across this family, so a lock refresh can move one
guide's pagination and not another's.)

### Tone

Direct and friendly. Adult reader new to the topic. No singsong asides, no fake dialogue, no
narrative openers, no pep-talk endings.

<!-- kit:end -->
