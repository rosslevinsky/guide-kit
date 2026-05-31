# {{GUIDE_NAME}}

A single-document beginner-guide PDF, authored in Markdown and rendered to PDF via pandoc + WeasyPrint. The reference PDF — `{{GUIDE_SLUG}}.pdf` — lives at the repo root, so anyone can download it directly from GitHub without cloning, installing, or building. Local `make verify` enforces zero-pixel-diff against that reference so a rebuild is guaranteed to match what readers actually downloaded.

> **Read the guide:** [`{{GUIDE_SLUG}}.pdf`]({{GUIDE_SLUG}}.pdf) (downloadable directly from this repo).
>
> **Build it yourself:** [Quick start](#quick-start) below — `pixi install && make`.
>
> **Edit / contribute:** [Workflow](#workflow-editing-content) — `make release MSG="..."` does source-commit + reference-refresh + amend in one shot.

## Getting started from this template

(This section is removed by `bootstrap.py` once you initialize a fork.)

### What this template is

`guide-template` codifies the shape of a *single-document beginner-guide PDF project*: one Markdown source, one rendered PDF, a reproducible build, a content-identicalness regression harness, and a per-fork HTML transforms hook. Concretely it gives you:

- **A render pipeline:** `guide.md` → pandoc → (optional `transforms.py`) → wrap in HTML → WeasyPrint → qpdf canonicalize → `build/{{GUIDE_SLUG}}.pdf`.
- **A reference PDF at the repo root** (`{{GUIDE_SLUG}}.pdf`) that readers can download from GitHub directly. The committed reference IS the deliverable.
- **A deterministic version stamp in the footer** — `YYYY-MM-DD HH:MM:SS · <12-hex-sha256>` — derived from `git log` over your source files. Readers can see exactly which commit a PDF was built from.
- **A `make verify` harness** that compares the freshly-built PDF against the committed reference (page count + text content + per-page pixel diff at zero tolerance), so accidental rendering regressions can't ship.
- **A `make release` workflow** that bundles source commits + reference refresh into one atomic commit, eliminating an entire class of "I forgot to update the baseline" mistakes.
- **A `transforms.py` hook** for per-guide HTML rewrites (custom code-block classification, link injection, table styling) without forking the build script.
- **Pixi-managed deps + Apache 2.0 / CC BY 4.0 dual licensing + a bundled CI workflow** so each new guide starts with reproducible builds, clean licensing for both code and content, and Ubuntu CI smoke (paths-filtered, to keep Actions minutes low) from day one.

### Why this exists

The template was extracted in 2026 from three guides (`mac-terminal-guide`, `git-guide`, `accounting-guide`) that had each grown up independently and drifted into incompatible shapes: different env managers, different docs/license setups, no shared regression harness, hand-maintained CSS-in-Python in one and external `style.css` in the other two, no version-stamp convention. The shared shape was always *there*, but nobody was enforcing it. This template makes the shared shape the default, so the next guide starts on the right foot and the existing three can converge.

### Design choices worth knowing

- **Pixi**, not `pip` + `venv` + `brew`. Pandoc, WeasyPrint, poppler, qpdf, and pillow are all installed into a project-local conda env from `conda-forge`. No `brew install pango`. No system-wide state. `pixi install` from a fresh clone is sufficient on macOS / Linux / Windows.
- **WeasyPrint**, not LaTeX. Trades aesthetic ceiling for "you can debug it in a browser." `make html` writes a standalone HTML preview to `build/{{GUIDE_SLUG}}.html` for fast iteration before the slower PDF render.
- **pandoc** for Markdown → HTML, not a custom parser. Smart-quote conversion is **disabled** (`-smart`) so the literal characters in your source land in the PDF — important for ASCII diagrams and copy-pasteable command snippets.
- **A `transforms.py` hook**, not config files. If a fork needs to rewrite the HTML pandoc produces (turn `Debit / Credit` code blocks into ruled tables, inject TOC anchors, classify numeric vs. prose tables), it provides a single function `post_pandoc_html(html: str) -> str`. The template ships `transforms.py.example`; activate by copying to `transforms.py` and the build picks it up automatically.
- **Content-identicalness, not byte-identicalness.** The verify harness checks page count + text + per-page pixels. Two consecutive builds of the same committed source produce content-identical PDFs even though the raw bytes can differ slightly (font subset prefixes, etc.). `SOURCE_DATE_EPOCH` is pinned from the most recent source commit and the output is run through `qpdf --deterministic-id` to make this hold.
- **CI is build-smoke only**, not verify, and **Ubuntu only**. Strict pixel-exact rendering doesn't reproduce reliably across machines (HarfBuzz/Cairo/FreeType differences across OSes, and even between macOS minor versions). CI's job is to confirm `make` runs without crashing; local pre-push `make verify` is the real regression gate. macOS/Windows smoke was dropped to save Actions minutes (macOS bills 10x, Windows 2x the Linux rate), and the trigger is paths-filtered so doc-only pushes skip CI.
- **Dual licensing.** Code (build scripts, CSS, configuration) is Apache 2.0. Content (your `guide.md` and the rendered PDF) is CC BY 4.0. Both live as explicit `LICENSE*` files so GitHub auto-detects them correctly and downstream re-users see clear, separate terms.

### How to fork

```bash
gh repo create my-new-guide --template rosslevinsky/guide-template --private
git clone git@github.com:<you>/my-new-guide.git
cd my-new-guide
pixi install
pixi run python bootstrap.py "My Guide Title" my-guide-slug \
  --author "Your Name" \
  --description "One-sentence description; bootstrap auto-appends the CC-BY license boilerplate" \
  --keywords "comma, separated, keywords"
```

`bootstrap.py` substitutes your title and slug into `build.py`, `pixi.toml`, `README.md`, and `CLAUDE.md`; removes this entire "Getting started from this template" section; and deletes itself + the `.template-uninitialized` sentinel that suppresses `build.py`'s template-hygiene check.

Then write your `guide.md`, eyeball with `make`, and `make release MSG="Initial content"` to land the first source + reference commit. Push, and your guide's PDF is downloadable from your fork's GitHub page.

### Optional: examples in the wild

Real guides have been built from this template:

- A 52-page beginner's guide to financial accounting, with a substantive `transforms.py` (journal-entry classification, prose/figures table classification, glossary line breaks). Closest example of using every escape hatch.
- An 11-page beginner's guide to the macOS Terminal. Minimal — no `transforms.py`, small HTML-island vocabulary.
- A 28-page curriculum-style guide to Git and GitHub. Richer `style.css` (CSS-counter TOC numbering, exercise blocks with difficulty pills, separate `@page :first` at-rules) but no `transforms.py`.

These currently live in private repos so the actual sources aren't linked here, but they exercise the template's full range (one with transforms, two without; one with minimal CSS, one with richer CSS).

---

## Quick start

### 1. Install pixi

[pixi](https://pixi.sh) is a cross-platform package manager that handles every dependency this project needs (pandoc, Python, WeasyPrint, poppler, Pillow, qpdf) in a single isolated environment. No `brew`, no `apt`, no virtualenvs.

```bash
# macOS / Linux
curl -fsSL https://pixi.sh/install.sh | sh
# Windows (PowerShell)
iwr -useb https://pixi.sh/install.ps1 | iex
```

See <https://pixi.sh/latest/installation/> for other install methods.

### 2. Install project dependencies

From this directory:

```bash
pixi install
```

### 3. Build

```bash
make                            # PDF (default) — writes build/{{GUIDE_SLUG}}.pdf
make html                       # standalone HTML preview at build/{{GUIDE_SLUG}}.html
make verify                     # check the fresh build matches the committed {{GUIDE_SLUG}}.pdf
make baseline                   # promote build/{{GUIDE_SLUG}}.pdf onto {{GUIDE_SLUG}}.pdf (use deliberately)
make release MSG="..."          # stage source + refresh reference + amend, in one commit
make clean                      # remove build/ and verify-diff/

# Opt-in web layer (only after `bootstrap.py --with-web` — see "Website deploy"):
make web                        # build the website into app/dist/
make dev                        # build + serve locally via wrangler (needs Node ≥22)
make deploy                     # build + deploy to Cloudflare (manual one-off)
```

The working render (regenerated each build) lands at `./build/{{GUIDE_SLUG}}.pdf` (gitignored). The committed reference is `./{{GUIDE_SLUG}}.pdf` at the repo root — downloadable directly from GitHub.

The PDF is the default deliverable; the website is **opt-in**. On a PDF-only fork `make web` no-ops cleanly and `make dev`/`make deploy` exit with a "web layer not enabled" message — nothing under `app/` exists until you opt in. See [Website deploy (Cloudflare)](#website-deploy-cloudflare).

## Files

| File | Purpose |
|------|---------|
| `guide.md` | The guide itself, in Markdown. Real Markdown with HTML islands only where Markdown can't express the styling. |
| `style.css` | All visual styling (page layout, fonts, callouts, exercise boxes, tables, ASCII diagrams). Carries `__TITLE__` and `__VERSION__` placeholders substituted by `build.py`. |
| `build.py` | The build pipeline: pandoc → optional `transforms.post_pandoc_html` → wrap in `<html>` → WeasyPrint → `qpdf` canonicalize. Holds `TITLE` / `OUTPUT_SLUG` / `AUTHOR` / `DESCRIPTION` / `KEYWORDS` constants. |
| `transforms.py.example` | Hook template. Copy → `transforms.py` to activate per-guide HTML transforms. |
| `transforms.py` | Optional — present only in forks that need post-pandoc HTML rewrites. |
| `verify_pdf.py` | Three-check harness (page count, text diff, per-page pixel diff at zero tolerance). |
| `release.py` | Helper for `make release` — stages source files, commits, re-renders, promotes the working render onto `{{GUIDE_SLUG}}.pdf`, amends. |
| `{{GUIDE_SLUG}}.pdf` | Committed reference PDF at the repo root — readers download this directly from GitHub. Regenerate via `make baseline` or `make release`. |
| `bootstrap.py` | One-shot rename-your-fork script. Present in template; deleted after first run. |
| `.template-uninitialized` | Sentinel suppressing `build.py`'s template-hygiene check while the template is in its un-substituted state. `bootstrap.py` removes it. |
| `Makefile` | Convenience targets — thin wrappers around `pixi run` plus a few amend-workflow helpers. |
| `pixi.toml` / `pixi.lock` | Dependency manifest + locked versions for reproducible builds. |
| `CLAUDE.md` | Project conventions, gotchas, and per-guide notes. Read before editing content. |
| `LICENSE` / `LICENSE-CONTENT` | Apache 2.0 for code, CC BY 4.0 for content. |
| `.github/workflows/verify.yml` | CI: build-smoke on Ubuntu only, paths-filtered. (Strict `make verify` runs only locally — see CLAUDE.md's "CI policy".) |
| `style-screen.css.example` | Opt-in web layer: screen stylesheet starter. `bootstrap.py --with-web` copies it to `style-screen.css` (NOT a SOURCE_FILE — web-only, doesn't bump the PDF stamp). |
| `templates/web/` | Opt-in web layer: the `app/` scaffold staging dir (`wrangler.jsonc`, `package.json` + lockfile, `public/.gitkeep`). `--with-web` copies it to `app/` with the slug substituted, then removes the staging copy. |
| `.github/workflows/deploy.yml.example` | Opt-in web layer: inert deploy workflow (GitHub only runs `*.yml`). `--with-web` activates it as `deploy.yml`. |
| `verify_web.py` | Opt-in web layer: asserts the per-output embed split (iframe on the site, watch-link in print). Skips cleanly when the web layer isn't enabled. |

(The web-layer files above ship inert. A PDF-only fork has no `app/`, no `style-screen.css`, and no live `deploy.yml`. See [Website deploy (Cloudflare)](#website-deploy-cloudflare).)

## Workflow: editing content

For **intentional content changes** — anything that alters the rendered PDF:

```
1. Edit guide.md / style.css / build.py / transforms.py
2. make                                    # render to build/{{GUIDE_SLUG}}.pdf
3. Open build/{{GUIDE_SLUG}}.pdf and eyeball it. Right? If not, fix and goto 2.
4. make release MSG="Your commit message"  # stage source, commit, refresh reference, amend
```

`make release` is a thin wrapper around `release.py`. It refuses to run if the working tree has staged changes or modifications to files outside the version-stamp input list (`SOURCE_FILES` in `build.py`: `guide.md` / `style.css` / `build.py` / `transforms.py`) — commit those with plain `git commit` first.

The manual equivalent of step 4, if you'd rather drive it yourself:

```bash
git add <the source files you edited>
git commit -m "Your message"     # COMMIT SOURCE FIRST — this is load-bearing
make baseline                    # render again with a clean stamp; copy to {{GUIDE_SLUG}}.pdf
git add {{GUIDE_SLUG}}.pdf
git commit --amend --no-edit     # fold {{GUIDE_SLUG}}.pdf into the source commit
```

Why amend? The version stamp in the PDF footer is derived from `git log` and `git status`. Rendering the reference PDF *before* the source commit produces a footer with ` · dirty` and the previous commit's date — which will never match a future post-commit `make verify`. Committing source first makes the stamp stable; amend keeps source + reference in one logical commit. `make release` enforces the order; doing it by hand requires you to.

For **doc-only changes** — anything outside `SOURCE_FILES` — the rendered PDF is unaffected. Commit normally; no reference refresh needed. This covers `README.md`, `CLAUDE.md`, `LICENSE*`, `Makefile`, `pixi.toml`, `pixi.lock`, `verify_pdf.py`, `release.py`, `bootstrap.py`, and `.github/workflows/`. `release.py` enforces this boundary — it refuses to run when modifications outside `SOURCE_FILES` are present, so a doc edit can never accidentally hitchhike into a release commit.

(One sneaky case: a `pixi.lock` update can drift rendering even though it's not a "source" file. That'll surface as a `make verify` failure on the next build — correct behavior. Pin tighter in `pixi.toml` if you want to narrow the window.)

## Verify harness

`make verify` runs `verify_pdf.py {{GUIDE_SLUG}}.pdf build/{{GUIDE_SLUG}}.pdf`, which checks:

1. **Page count** via `pdfinfo` — fails on mismatch.
2. **Text content** via `pdftotext` (no `-layout`) — fails with a first-50-lines unified diff snippet. Catches added / removed / reordered text, not visual position drift.
3. **Per-page pixel diff** via `pdftoppm -r 150 -png` + Pillow `ImageChops.difference` at zero tolerance — fails if any channel of any pixel differs on any page. On failure, per-page diff PNGs land in `verify-diff/page-NN.png` for visual inspection.

Both PDFs are canonicalized through `qpdf --deterministic-id --normalize-content=y` first so accidental non-determinism in the inputs doesn't masquerade as a real diff.

A green `make verify` is the contract that your latest build is content-identical to the committed reference. A red `make verify` either means a real regression OR that you intentionally changed source without refreshing the reference (run the workflow above).

**A known fragility:** the pixel-exact check can be sensitive to fontconfig cache state outside `.pixi/`. A `rm -rf .pixi && pixi install` on the same machine can occasionally produce a slightly different glyph rendering for pages heavy in non-ASCII characters (we've hit it on `→` arrows). Pixi.lock pins package versions but not your system's font-cache state. If you see a one-page pixel diff after a fresh install, refresh the reference (`make release MSG="Refresh reference"`) and recommit. Page count + text content checks remain reliable across this.

## CI policy

CI (GitHub Actions) runs `make` build-smoke on `ubuntu-latest` only. It does **not** run `make verify`. Why: strict pixel-exact rendering doesn't reproduce across machines (HarfBuzz/Cairo/FreeType drift across OSes, and even between macOS minor versions ship different fonts). CI's job is to confirm the pipeline doesn't crash; local pre-push `make verify` is what catches rendering regressions.

Two cost controls keep Actions minutes low: CI is **Ubuntu only** (macOS runners bill at 10x and Windows at 2x the Linux rate, and the cross-platform smoke rarely caught anything Ubuntu didn't), and the workflow is **paths-filtered** — pushes that only touch docs (`README.md`, `CLAUDE.md`, `LICENSE*`), `plans/`, or other non-build files skip CI entirely. Trigger a run manually from the Actions tab (`workflow_dispatch`) if you ever need one outside those paths.

## Website deploy (Cloudflare)

The website is an **opt-in** second output. The PDF is the default; a PDF-only fork needs none of this. To enable the web layer, pass `--with-web` when you bootstrap:

```bash
pixi run python bootstrap.py "My Guide Title" my-guide-slug --with-web
```

That materializes `style-screen.css`, activates `transforms.py` (the per-output YouTube embed split, so embeds work on the site and degrade to links in the PDF), copies the `app/` Cloudflare scaffold (with your slug as the worker name), and activates a live `.github/workflows/deploy.yml`. (Already initialized without it? Copy `style-screen.css.example` → `style-screen.css` and `transforms.py.example` → `transforms.py`, copy `templates/web/` → `app/` and set the `name` field in `app/wrangler.jsonc` to your slug, and rename `.github/workflows/deploy.yml.example` → `deploy.yml`. Note `transforms.py` is a SOURCE_FILE — re-baseline with `make release` afterward.)

Once enabled, the site builds with `make web` (→ `app/dist/`) and deploys to Cloudflare Workers Static Assets. `make dev` serves it locally (requires **Node ≥22**; run `npm install` in `app/` first — wrangler is pinned in `app/package.json`). `.github/workflows/deploy.yml` deploys automatically (push to `main` → production; PR → preview URL posted as a comment). `make deploy` is the manual one-off.

CI deploys need two **GitHub Actions secrets**. Local `wrangler` auth on your machine does **not** carry into GitHub Actions — you must store these in the repo.

### 1. Get a Cloudflare API token

1. Go to the [Cloudflare dashboard](https://dash.cloudflare.com/) → **My Profile**
   (top-right avatar) → **API Tokens** → **Create Token**
   (direct link: <https://dash.cloudflare.com/profile/api-tokens>).
2. Use the **"Edit Cloudflare Workers"** template (or a Custom Token with, at
   minimum, **Account → Workers Scripts → Edit**). For a custom token, scope
   *Account Resources* to your account; if you'll bind a custom domain, also
   scope *Zone Resources* to that domain's zone.
3. Click **Continue to summary → Create Token**, then **copy the token value
   now** — Cloudflare shows it only once. Treat it like a password.

### 2. Get your Cloudflare account ID

- Dashboard → **Workers & Pages** → the **Account ID** is in the right-hand
  sidebar (also on any domain's overview page), **or**
- run `cd app && npx wrangler whoami` (after `npm install` in `app/`).

### 3. Store both as GitHub Actions secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**.
Create exactly these two names (the workflow references them verbatim):

| Secret name | Value |
|---|---|
| `CLOUDFLARE_API_TOKEN` | the token from step 1 |
| `CLOUDFLARE_ACCOUNT_ID` | the account ID from step 2 |

Or from the CLI (prompts for the value; never put a token in your shell history
or a committed file):

```bash
gh secret set CLOUDFLARE_API_TOKEN   --repo <owner>/<repo>   # paste token at prompt
gh secret set CLOUDFLARE_ACCOUNT_ID  --repo <owner>/<repo>   # paste account ID at prompt
```

Verify they exist (names only; values are write-only and never shown):

```bash
gh secret list --repo <owner>/<repo>
```

**Security notes.** These are repository secrets — never commit them to
`wrangler.jsonc`, `.env`, or any tracked file. Rotate the API token if it's ever
exposed (dashboard → API Tokens → Roll). Scope the token to Workers-edit only;
do not use a Global API Key. For local `make deploy`, `wrangler` uses your own
interactive login (`wrangler login`), not these secrets.

### 4. Bind a custom domain (optional, one-time, manual)

By default the site is reachable at `{{GUIDE_SLUG}}.<your-subdomain>.workers.dev`. To put it on your own domain, bind it in the Cloudflare dashboard (NOT in `wrangler.jsonc`): **Workers & Pages → {{GUIDE_SLUG}} → Settings → Domains & Routes → Add → Custom Domain**. The domain's zone must be in the same Cloudflare account.

## Conventions

The conventions you'll most often want to know:

- **Allowed HTML islands** in `guide.md` are listed in [`CLAUDE.md`](CLAUDE.md). The defaults: `<div class="title-block">`, `<div class="callout warn|tip|accent">`, `<div class="exercise">`, `<pre class="diagram">`, `<div class="page-break"></div>`. Forks add or remove from this list and update `style.css` to match.
- **Source files that bump the version stamp:** `guide.md`, `style.css`, `build.py`, `transforms.py`. Only changes to these require a reference refresh (everything else commits normally).
- **The footer version stamp** is derived from `git log` + `git status` over the source files. ` · dirty` appears when the working tree has uncommitted source changes. Treat it as a load-bearing signal that the PDF in your hand matches a real commit.

## License

This repository is dual-licensed:

- **Code** (build scripts, CSS, configuration) — [Apache License 2.0](LICENSE).
- **Content** (`guide.md` and the rendered PDF) — [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-CONTENT).

You're free to share, adapt, and reuse the guide content for any purpose, including commercially, as long as you give appropriate credit and link to the CC BY 4.0 license.
