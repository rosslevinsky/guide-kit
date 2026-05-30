# Project notes for Claude

This file documents the conventions of this project so you can make good edits.

## What this is

<DESCRIBE YOUR GUIDE>

A single-document Markdown → PDF project for `{{GUIDE_NAME}}`. Source lives in `guide.md`; styling in `style.css`; build pipeline in `build.py`. The committed reference PDF `{{GUIDE_SLUG}}.pdf` is the verified reference render; `make verify` checks that any rebuild matches it to zero pixel tolerance.

## Build pipeline

```
guide.md  --pandoc-->  HTML body  --transforms.py?-->  HTML'  --wrap-->  styled HTML  --WeasyPrint-->  PDF  --qpdf-->  PDF (canonical)
                                                                                ^
                                                                            style.css
```

Run `make` to build. Run `make html` for a fast HTML preview. Run `make verify` to check the fresh build matches `{{GUIDE_SLUG}}.pdf`.

### Determinism layer

The pipeline pins WeasyPrint's PDF creation timestamp via `SOURCE_DATE_EPOCH` (derived from the most-recent source commit), then pipes the rendered PDF through `qpdf --deterministic-id --normalize-content=y --object-streams=preserve`. Two consecutive builds of identical committed source produce content-identical PDFs (often byte-identical too, though the harness's contract is content-only).

## Markdown vs. HTML conventions

`guide.md` is **real Markdown** for almost everything: prose, headers (`#`, `##`, `###`), lists, pipe tables, fenced code blocks, inline backticks for code, `**bold**`, `*italic*`, `[links](url)`.

Inline HTML is reserved for elements Markdown cannot express. The full list of allowed HTML islands (each is recognized and styled by `style.css`):

| HTML | Purpose |
|------|---------|
| `<div class="title-block">` | Wraps the document title (h1) + tagline at the top of page 1. |
| `<div class="callout warn">` | Amber warning box. The first paragraph's leading `**bold**` becomes the orange header. |
| `<div class="callout tip">` | Green tip box. Same first-paragraph-bold-becomes-header convention. |
| `<div class="callout accent">` | Light-blue mental-model callout. No bold header convention; plain prose. |
| `<div class="exercise">` | Green-bordered exercise box. The first paragraph (e.g. `**Exercise 1**`) becomes the title strip. |
| `<pre class="diagram">…</pre>` | Monospace ASCII-diagram panel. `<pre>` is required because pandoc collapses whitespace inside a plain `<div>`. |
| `<div class="page-break"></div>` | Forces a page break. |

Do **not** add other HTML. Do **not** convert Markdown that already works into HTML.

## The version stamp

The PDF footer shows an auto-generated stamp in the form `YYYY-MM-DD HH:MM:SS · <12-hex-chars>`, derived from:

- **Date + time**: `git log -1 --format=%ad --date=format:'%Y-%m-%d %H:%M:%S' -- guide.md style.css build.py transforms.py` — the author date/time of the most-recent commit touching any of those files. `%ad` (author date), not `%cd` (committer date), because `git commit --amend` inside `release.py` updates the committer time by ~1s and would break the verify cycle.
- **Hash**: first 12 hex chars of `sha256` over the concatenated bytes of every file in that list that exists on disk.

When `git status --porcelain` reports uncommitted changes to any of those files, the stamp gains a trailing ` · dirty` segment so a reader can see the PDF was rendered from working-tree state, not committed source.

The `transforms.py` file is included in the input list unconditionally; git silently ignores nonexistent paths in `log` / `status`, so the same query works whether or not the hook has been activated.

## The verify harness

`make verify` runs `verify_pdf.py {{GUIDE_SLUG}}.pdf build/{{GUIDE_SLUG}}.pdf`. Three checks:

1. **Page count** via `pdfinfo`.
2. **Text content** via `pdftotext` (no `-layout`; first-50-lines unified-diff snippet on failure). Catches added / removed / reordered text, not visual position drift.
3. **Per-page pixel** via `pdftoppm -r 150 -png` + Pillow `ImageChops.difference` at zero tolerance. On failure, per-page diff PNGs land in `verify-diff/page-NN.png`.

Both PDFs are canonicalized through `qpdf --deterministic-id --normalize-content=y` first so accidental non-determinism in the inputs doesn't masquerade as a real diff.

**CI policy:** `.github/workflows/verify.yml` runs `make` (build smoke) on Ubuntu / macOS / Windows. It does **not** run `make verify` — strict pixel-exact rendering doesn't reproduce reliably across machines (HarfBuzz/Cairo/FreeType differences across OSes, and even between macOS minor versions). Local pre-push `make verify` is the sole real regression gate. See the pixi.toml comment block for the longer story.

### When to run `make baseline`

After any **intentional** change to `guide.md`, `style.css`, `build.py`, or activating/deactivating `transforms.py`. Follow the amend workflow in *After editing* — running `make baseline` BEFORE `git commit` of the source produces a dirty-stamp baseline that future verify runs won't match.

## The transforms hook

If `transforms.py` exists next to `build.py`, the build pipeline imports it and calls `transforms.post_pandoc_html(html: str) -> str` exactly once, between the pandoc step and WeasyPrint. The hook receives the raw HTML body emitted by pandoc and returns a transformed HTML body.

Activate the hook by copying `transforms.py.example` → `transforms.py` and replacing the identity stub with your transform.

**Version-stamp gotcha**: activating the hook (creating `transforms.py`) adds it to the version-stamp input list, so the footer hash changes even when `post_pandoc_html` is the identity function. After activating OR deactivating, refresh `{{GUIDE_SLUG}}.pdf` via the *After editing* workflow.

## Critical gotchas

1. **Commit source before `make baseline`** (the *After editing* workflow). Running `make baseline` with uncommitted source produces a baseline that carries ` · dirty` in the footer; subsequent `make verify` against clean-tree builds will fail across every page because the footers don't match. The amend workflow ensures source + baseline land in one logical commit with a stable stamp.

2. **`make baseline` without inspection is a footgun**. It silently re-blesses whatever the current render is. If you ran `make` after a CSS edit that broke something and immediately ran `make baseline`, the broken state becomes the new reference and verify will pass forever against the broken baseline. Always eyeball the rendered PDF before `make baseline`.

3. **Two PDFs, two roles.** The committed reference PDF lives at the repo root as `{{GUIDE_SLUG}}.pdf` (downloadable directly from GitHub — that's its job). The working render goes to `build/{{GUIDE_SLUG}}.pdf` (gitignored — regenerated every `make`). `make verify` diffs the two. `make baseline` (or `make release`) promotes the working render to the root reference. Don't `git add` anything under `build/`.

4. **Don't commit `transforms.py`** unless your guide actually uses a substantive transform. The file is intended to be present in working trees of guides that need it; the template ships only `transforms.py.example`.

5. **Smart-quote conversion is disabled in pandoc** (`-smart` in the format string). Keeps `---`, `'`, and `"` literal so ASCII diagrams and code snippets don't get mangled.

## Tone

Direct and friendly. Adult reader new to the topic. No singsong asides, no fake dialogue, no narrative openers, no pep-talk endings.

## After editing

Use `make release` to do the source-commit + baseline + amend dance in one shot:

```bash
# 1. Edit guide.md / style.css / build.py / transforms.py
# 2. make                                    # render the new PDF
# 3. Open {{GUIDE_SLUG}}.pdf and visually inspect. Right? If not, fix and goto 2.
# 4. make release MSG="Your commit message"  # stages source, commits, re-renders, amends baseline
```

`make release` refuses to run if the working tree has staged changes or modifications to files outside the SOURCE_FILES set (the version-stamp input list). Handle those with plain `git commit` first.

The manual equivalent, if you ever need to drive the steps yourself:

```bash
git add <the source files you edited>
git commit -m "Your message"     # COMMIT SOURCE FIRST — clean stamp depends on it
make baseline                    # render again; cp to {{GUIDE_SLUG}}.pdf
git add {{GUIDE_SLUG}}.pdf
git commit --amend --no-edit     # fold {{GUIDE_SLUG}}.pdf into the source commit
```

## What affects the rendered PDF

The version stamp (`_content_hash` + `_git_last_source_change_date` + `_is_dirty`) reads only `SOURCE_FILES`: **`guide.md`, `style.css`, `build.py`, `transforms.py`**. Anything else can change without bumping the stamp or breaking `make verify`:

| Edits to… | Bumps stamp? | Needs `make release` / baseline refresh? |
|---|---|---|
| `guide.md` / `style.css` / `build.py` / `transforms.py` | yes | yes |
| `README.md` / `CLAUDE.md` / `LICENSE` / `LICENSE-CONTENT` | no | no — plain `git commit` |
| `Makefile` / `pixi.toml` / `pixi.lock` | no | no — but watch verify: a lock change can drift rendering |
| `verify_pdf.py` / `release.py` / `bootstrap.py` | no | no — but a stricter `verify_pdf.py` can fail an existing baseline |
| `.github/workflows/` / `.gitignore` / `.template-uninitialized` | no | no |

`release.py` enforces this boundary: it refuses to run if the working tree has modifications outside `SOURCE_FILES`, so a doc edit can never accidentally hitchhike into a release commit. Commit doc-only changes with plain `git commit -m "..."`.

**One sneaky case**: `pixi.lock` isn't a source file, but a dependency bump that changes how WeasyPrint or fonts render *will* break `make verify` on the next build. That's correct behavior — you'd notice. The fix is to either pin tighter in `pixi.toml` or refresh the baseline once the new render is what you want.
