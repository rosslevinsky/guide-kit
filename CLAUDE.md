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
| `<div class="embed youtube" data-id="VIDEO_ID">label</div>` | (Opt-in web layer) A YouTube embed. `transforms.py` rewrites it **per output**: a responsive `<iframe>` on the website, a plain `youtube.com/watch?v=VIDEO_ID` link in the PDF. The inner text is the PDF link label / iframe title. Requires an active `transforms.py` (see "The transforms hook"); inert without one. |

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

**CI policy:** `.github/workflows/verify.yml` runs `make` (build smoke) on **Ubuntu only**, and only when source/build files change (paths-filtered — doc-only and `plans/` pushes skip CI). It does **not** run `make verify` — strict pixel-exact rendering doesn't reproduce reliably across machines (HarfBuzz/Cairo/FreeType differences across OSes, and even between macOS minor versions). Local pre-push `make verify` is the sole real regression gate. (macOS/Windows smoke was dropped to save Actions minutes — macOS bills 10x and Windows 2x the Linux rate. Re-add a matrix in `verify.yml` if cross-platform breakage becomes a real risk.) See the pixi.toml comment block for the longer story.

### When to run `make baseline`

After any **intentional** change to `guide.md`, `style.css`, `build.py`, or activating/deactivating `transforms.py`. Follow the amend workflow in *After editing* — running `make baseline` BEFORE `git commit` of the source produces a dirty-stamp baseline that future verify runs won't match.

## The transforms hook (per-output)

If `transforms.py` exists next to `build.py`, the build pipeline imports it and calls ONE entry point between the pandoc step and the renderer, chosen by the output target:

- `post_pandoc_html_for_pdf(html: str) -> str` — PDF build (WeasyPrint)
- `post_pandoc_html_for_web(html: str) -> str` — web build (`build.py --web`)

`build.py` resolves per target as: prefer `post_pandoc_html_for_<target>`, else the single-entry `post_pandoc_html`, else identity. A **PDF-only fork** can define just `post_pandoc_html` (or no hook at all); a fork with the opt-in website keeps the PDF and web logic in **separate functions** so rich media that plays on the site (a YouTube iframe) degrades to a plain link in print. The worked example is the `embed youtube` island → iframe (web) / link (PDF).

Activate the hook by copying `transforms.py.example` → `transforms.py` (it ships the per-output split with the YouTube embed as the worked example) and adapting it.

**Version-stamp gotcha**: activating the hook (creating `transforms.py`) adds it to the version-stamp input list, so the footer hash changes even when the hook is the identity transform — and editing it later bumps the stamp too, **even for a web-only transform change**. After activating OR deactivating, refresh `{{GUIDE_SLUG}}.pdf` via the *After editing* workflow.

## The website (opt-in)

The PDF is the default output. A fork can **opt in** to a second output — a website deployed to Cloudflare Workers Static Assets — by bootstrapping with `--with-web` (`pixi run python bootstrap.py "Title" {{GUIDE_SLUG}} --with-web`). Without it, the fork is PDF-only: no `app/`, no `style-screen.css`, no `deploy.yml`, no Node footprint.

When enabled:

- **Build**: `make web` runs `build.py --web` → pandoc → `post_pandoc_html_for_web` → wrap with `style-screen.css` → `app/dist/index.html`, plus a copy of the committed `{{GUIDE_SLUG}}.pdf` for the download link. `app/dist/` is gitignored. On a PDF-only fork `make web` no-ops cleanly (it prints "web layer not enabled" and creates nothing).
- **Local preview**: `make dev` (builds, then `wrangler dev` from `app/`). Requires **Node ≥22** — the only non-pixi/Python dependency; `wrangler` is pinned in `app/package.json`. `make dev`/`make deploy` error clearly when `app/` is absent.
- **Deploy**: `.github/workflows/deploy.yml` deploys on push to `main` (production) and posts a preview URL on PRs. Needs repo secrets `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` (see README "Website deploy"). `make deploy` is the manual one-off. A custom domain is bound in the Cloudflare dashboard, not in `app/wrangler.jsonc`.
- **`style-screen.css` is NOT a `SOURCE_FILE`** — it affects only the website, so editing it does not bump the PDF stamp or require `make release`. Plain `git commit`. (But `transforms.py` IS a SOURCE_FILE, so a web-only embed-transform change still triggers a re-baseline — see the hook's version-stamp gotcha above.)
- **`verify_web.py`** asserts the per-output embed split (iframe in the web HTML, watch-link in the print HTML); it skips cleanly when the web layer isn't enabled or `guide.md` has no embed.

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
| `style-screen.css` / `app/` / `verify_web.py` / `*.example` (opt-in web layer) | no | no — web-only; never affects the PDF |

`release.py` enforces this boundary: it refuses to run if the working tree has modifications outside `SOURCE_FILES`, so a doc edit can never accidentally hitchhike into a release commit. Commit doc-only changes with plain `git commit -m "..."`.

**One sneaky case**: `pixi.lock` isn't a source file, but a dependency bump that changes how WeasyPrint or fonts render *will* break `make verify` on the next build. That's correct behavior — you'd notice. The fix is to either pin tighter in `pixi.toml` or refresh the baseline once the new render is what you want.
