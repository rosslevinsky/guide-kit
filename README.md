# {{GUIDE_NAME}}

A single-document beginner-guide PDF, authored in Markdown and rendered to PDF via pandoc + WeasyPrint. The reference PDF — `{{GUIDE_SLUG}}.pdf` — lives at the repo root, so anyone can download it directly from GitHub without cloning, installing, or building. `make verify` is a fast, platform-independent **staleness check**: it confirms the committed reference PDF is up to date with the source (no rendering), so the repo never ships Markdown and a PDF that disagree.

> **Read the guide:** [`{{GUIDE_SLUG}}.pdf`]({{GUIDE_SLUG}}.pdf) (downloadable directly from this repo).
>
> **Build it yourself:** [Quick start](#quick-start) below — `pixi install && make`.
>
> **Edit / contribute:** [Workflow](#workflow-editing-content) — `make release MSG="..."` does source-commit + reference-refresh + amend in one shot.

## Getting started from this template

(This section is removed by `bootstrap.py` once you initialize a fork.)

### What this template is

`guide-template` codifies the shape of a *single-document beginner-guide PDF project* — one Markdown source, one rendered PDF, a reproducible build, a per-guide `guide.toml`, and a copy-and-checksum sync engine that keeps the shared tooling up to date across the family. Concretely it gives you:

- **A render pipeline:** `guide.md` → pandoc → (optional `transforms.py`) → wrap in HTML → WeasyPrint → qpdf canonicalize → `build/{{GUIDE_SLUG}}.pdf`.
- **A reference PDF at the repo root** (`{{GUIDE_SLUG}}.pdf`) that readers download from GitHub directly. The committed reference IS the deliverable.
- **A deterministic version stamp in the footer** — `YYYY-MM-DD HH:MM:SS · <12-hex-sha256>` — over the `SOURCE_FILES` list. Readers can see exactly which commit a PDF was built from.
- **A two-command verify split:** `make verify` is a platform-independent staleness check (embedded stamp vs. a fresh content hash — no build, runs in CI); `make verify-render` is a canonical-host-only page-count + stamp-excluded-text canary.
- **A `make release` workflow** that bundles source commit + reference refresh into one atomic commit, eliminating "I forgot to update the baseline" mistakes.
- **A copy-and-checksum kit:** per-guide constants in `guide.toml`, a two-axis `kit-manifest.toml`, and `sync.py` to pull shared-tooling updates into guides created from the template (no `git subtree`, no merge).
- **A per-output `transforms.py` hook** for per-guide HTML rewrites, with separate PDF/web entry points driving the opt-in website's play-on-screen / link-in-print media split.
- **Pixi-managed deps + Apache 2.0 / CC BY 4.0 dual licensing + bundled CI** (build smoke + the staleness check + a scheduled kit-drift warning) so each guide starts reproducible and clean.

### Why this exists

The template was extracted in 2026 from three guides (`mac-terminal-guide`, `git-guide`, `accounting-guide`) that had each grown up independently and drifted into incompatible shapes: different env managers, different docs/license setups, no shared regression harness, hand-maintained CSS-in-Python in one and external `style.css` in the other two, no version-stamp convention. The shared shape was always *there*, but nobody was enforcing it. This template makes the shared shape the default, so the next guide starts on the right foot and the existing three can converge.

### Design choices worth knowing

- **Pixi**, not `pip` + `venv` + `brew`. Pandoc, WeasyPrint, poppler, and qpdf are all installed into a project-local conda env from `conda-forge`. No `brew install pango`. No system-wide state. `pixi install` from a fresh clone is sufficient on macOS / Linux / Windows.
- **WeasyPrint**, not LaTeX. Trades aesthetic ceiling for "you can debug it in a browser." `make html` writes a standalone HTML preview to `build/{{GUIDE_SLUG}}.html` for fast iteration before the slower PDF render.
- **pandoc** for Markdown → HTML, not a custom parser. Smart-quote conversion is **disabled** (`-smart`) so the literal characters in your source land in the PDF — important for ASCII diagrams and copy-pasteable command snippets.
- **A `transforms.py` hook**, not config files. If a fork needs to rewrite the HTML pandoc produces (turn `Debit / Credit` code blocks into ruled tables, inject TOC anchors, classify numeric vs. prose tables), it provides per-output `post_pandoc_html_for_pdf` / `post_pandoc_html_for_web` functions (or a single-entry `post_pandoc_html` fallback for PDF-only forks). The template ships `transforms.py.example` demonstrating the per-output YouTube-embed split (iframe on the site, watch-link in print); activate by copying to `transforms.py` and the build picks it up automatically. See [Website deploy](#website-deploy-cloudflare).
- **Staleness verification, computed not rendered.** `make verify` compares the content hash embedded in the committed PDF's footer stamp against a fresh hash over `SOURCE_FILES` — no build, no fonts, no platform sensitivity — so it runs identically everywhere, including CI. Whether the *rendering* reproduced is a separate, canonical-host-only concern (`make verify-render`). `SOURCE_DATE_EPOCH` + `qpdf --deterministic-id` still make repeated builds of identical source content-identical.
- **Reference PDFs are rendered on one canonical host.** They embed system fonts, which differ across OSes, so the family renders its downloadable PDFs on a single platform (recorded in `guide.toml` as `baseline_platform`) for consistent typography. `make baseline` / `make release` refuse a wrong-platform or dirty-tree render; `.github/workflows/baseline.yml` renders on a macOS runner so you don't need a Mac locally.
- **CI runs the staleness check and build smoke, Ubuntu only.** Because `make verify` is platform-independent it gates in CI for real (the old "build-smoke only" rule is gone). CI never runs `make verify-render` (it needs a build and is platform-sensitive). Ubuntu-only + paths-filtered keeps Actions minutes low; a scheduled `kit-drift.yml` warns (never fails) when the kit's shared tooling moves ahead of this guide.
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

`bootstrap.py` writes your per-guide values into a new `guide.toml`; re-renders the `templated` files (`pixi.toml`, `verify.yml`, `kit-drift.yml`) with your identity; fills the `{{GUIDE_NAME}}` / `{{GUIDE_SLUG}}` placeholders in `README.md` and in `CLAUDE.md`'s text outside the managed region; deletes the inherited reference PDF (yours is not built yet); writes the initial `.template-version` record; removes this entire "Getting started from this template" section; and deletes itself + the `.template-uninitialized` sentinel that suppresses `build.py`'s template-hygiene check.

Then write your `guide.md`, eyeball with `make`, and `make release MSG="Initial content"` to land the first source + reference commit. Push, and your guide's PDF is downloadable from your fork's GitHub page.

### Staying in sync with the kit

A guide created from this template keeps its shared tooling up to date by **copy-and-checksum, not merge** — no `git subtree`, no upstream remote. The kit (`guide-template`) is the source of truth for the shared files; each guide records what it last adopted in `.template-version`.

- `kit-manifest.toml` classifies every kit file on **two axes**: source lifecycle (`retained-in-kit` / `bootstrap-source` / `generated`) and destination policy (`identical` / `templated` / `managed-region` / `never`).
- `python sync.py <guide>` reports drift and writes nothing (the default is a dry run).
- `python sync.py <guide> --apply` writes the update transactionally (refusing a dirty tree or an unrecorded managed file, rolling back on any error).
- `CLAUDE.md` is a `managed-region` file: only the block between the `kit:begin` / `kit:end` markers is synced; your own guide-specific sections outside them are never touched.
- A scheduled, warn-only `kit-drift.yml` reports (never fails) when the kit moves ahead of a guide.

Adding a web layer to an already-initialized guide is a separate one-shot: `python guide-template/adopt-web.py --target ../my-guide` (see [Website deploy](#website-deploy-cloudflare)).

### The guide family

This template is the kit behind six guides. Four of them are terminal guides, collected by a hub
site: **<https://terminal-guides.speedytuna.com>**. Between them they exercise the template's full
range — with and without `transforms.py`, minimal and rich `style.css`, PDF-only and web-enabled.

| Guide | What it exercises | Read it |
|---|---|---|
| **macOS Terminal** | The structural model the others follow. No `transforms.py`, small island vocabulary. | [mac-terminal.speedytuna.com](https://mac-terminal.speedytuna.com) |
| **Linux Terminal** | Same shape, adapted; every command executed in a container and its output copied exactly. | [linux-terminal.speedytuna.com](https://linux-terminal.speedytuna.com) |
| **Windows PowerShell** | Written fresh around the object pipeline; split verification (executed in `pwsh`, cited where Windows-only). | [powershell.speedytuna.com](https://powershell.speedytuna.com) |
| **Windows Command Prompt** | Re-framed rather than translated; verified by per-command citation, since `cmd.exe` has no Linux runtime. | [cmd.speedytuna.com](https://cmd.speedytuna.com) |
| **Git & GitHub** | Richer `style.css` — CSS-counter TOC numbering, exercise blocks with difficulty pills, a separate `@page :first`. No `transforms.py`. | [git.speedytuna.com](https://git.speedytuna.com) |
| **Financial accounting** | The closest example of using every escape hatch: a substantive `transforms.py` doing journal-entry classification, prose/figures table classification and glossary line breaks. | private repo |

Each guide is its own repo. Five publish public sites; only the accounting guide is unlinked, as
it has no site yet.

---

## Quick start

### 1. Install pixi

[pixi](https://pixi.sh) is a cross-platform package manager that handles every dependency this project needs (pandoc, Python, WeasyPrint, poppler, qpdf) in a single isolated environment. No `brew`, no `apt`, no virtualenvs.

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
make verify                     # staleness check: committed {{GUIDE_SLUG}}.pdf is up to date with source (no build)
make verify-render              # canonical-host-only render canary (page count + text); needs a build
make baseline                   # promote build/{{GUIDE_SLUG}}.pdf onto {{GUIDE_SLUG}}.pdf (canonical host; use deliberately)
make release MSG="..."          # stage source + refresh reference + amend, in one commit (canonical host)
make clean                      # remove build/

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
| `guide.toml` | The seven per-guide values (`TITLE`, `OUTPUT_SLUG`, `AUTHOR`, `DESCRIPTION`, `KEYWORDS`, `COPYRIGHT_YEAR`, `baseline_platform`). Read and validated by `kitconfig.py`. |
| `kitconfig.py` | The single strict loader/validator for `guide.toml`; owns the canonical `SOURCE_FILES` list and the content-hash used by the stamp and `make verify`. |
| `style.css` | All visual styling (page layout, fonts, callouts, exercise boxes, tables, ASCII diagrams). Carries `__TITLE__` and `__VERSION__` placeholders substituted by `build.py`. |
| `build.py` | The build pipeline: pandoc → optional `transforms.post_pandoc_html` → wrap in `<html>` → WeasyPrint → `qpdf` canonicalize. Reads the per-guide values through `kitconfig`; holds no guide-specific literal. |
| `transforms.py.example` | Hook template. Copy → `transforms.py` to activate per-guide HTML transforms. |
| `transforms.py` | Optional — present only in forks that need post-pandoc HTML rewrites. |
| `verify_pdf.py` | The verify engine: `--staleness` (embedded stamp hash vs. a fresh content hash — no build) and a separate `--render` canary (page count + stamp-excluded text). |
| `baseline.py` | Helper for `make baseline` — platform + dirty-tree guards, then promotes the working render onto `{{GUIDE_SLUG}}.pdf`. Refuses off the canonical host. |
| `release.py` | Helper for `make release` — stages source, commits, re-renders, promotes onto `{{GUIDE_SLUG}}.pdf`, amends. Refuses off the canonical host or with a dirty tree. |
| `kit-manifest.toml` / `kitmanifest.py` | The two-axis file manifest (source lifecycle × destination policy) and its loader — the classification `sync.py` and `bootstrap.py` act on. |
| `sync.py` | Copy-and-checksum engine: reports drift (default) or, with `--apply`, transactionally updates a guide's shared files from the kit. |
| `adopt-web.py` | One-shot: add the opt-in web layer to an already-initialized guide (`--target <guide>`). Runs from the kit, writes only into the target. |
| `.template-version` | Per-guide record of what was last adopted from the kit (`managed_digest`, `rendered_checksums`, `state`). Written by `bootstrap.py`; updated by `sync.py`. |
| `{{GUIDE_SLUG}}.pdf` | Committed reference PDF at the repo root — readers download this directly from GitHub. Regenerate via `make baseline` or `make release`. |
| `bootstrap.py` | One-shot rename-your-fork script. Present in template; deleted after first run. |
| `.template-uninitialized` | Sentinel suppressing `build.py`'s template-hygiene check while the template is in its un-substituted state. `bootstrap.py` removes it. |
| `Makefile` | Convenience targets — thin wrappers around `pixi run` plus a few amend-workflow helpers. |
| `pixi.toml` / `pixi.lock` | Dependency manifest + locked versions for reproducible builds. |
| `CLAUDE.md` | Project conventions and per-guide notes; a `managed-region` file (shared policy between the `kit:begin`/`kit:end` markers is synced). Read before editing content. |
| `LICENSE` / `LICENSE-CONTENT` | Apache 2.0 for code, CC BY 4.0 for content. |
| `.github/workflows/verify.yml` | CI on Ubuntu, paths-filtered: build smoke + `make verify` (the staleness check). Never runs `make verify-render`. |
| `.github/workflows/baseline.yml` | Renders the reference PDF on a `macos-latest` runner and commits it — dispatch it instead of needing a physical canonical host. |
| `.github/workflows/kit-drift.yml` | Scheduled, warn-only: reports when the kit's shared tooling has moved ahead of this guide. |
| `style-screen.css.example` | Opt-in web layer: screen stylesheet starter. `bootstrap.py --with-web` copies it to `style-screen.css` (NOT a SOURCE_FILE — web-only, doesn't bump the PDF stamp). |
| `templates/web/` | Opt-in web layer: the `app/` scaffold staging dir (`wrangler.jsonc`, `package.json` + lockfile, `public/.gitkeep`). `--with-web` copies it to `app/` with the slug substituted, then removes the staging copy. |
| `.github/workflows/deploy.yml.example` | Opt-in web layer: inert deploy workflow (GitHub only runs `*.yml`). `--with-web` activates it as `deploy.yml`. |
| `verify_web.py` | Opt-in web layer: asserts the per-output embed split (iframe on the site, watch-link in print). Skips cleanly when the web layer isn't enabled. |

(The web-layer files above ship inert. A PDF-only fork has no `app/`, no `style-screen.css`, and no live `deploy.yml`. See [Website deploy (Cloudflare)](#website-deploy-cloudflare).)

## Workflow: editing content

For **intentional content changes** — anything that alters the rendered PDF:

```
1. Edit guide.md / style.css / build.py / transforms.py / guide.toml
2. make                                    # render to build/{{GUIDE_SLUG}}.pdf
3. Open build/{{GUIDE_SLUG}}.pdf and eyeball it. Right? If not, fix and goto 2.
4. make release MSG="Your commit message"  # stage source, commit, refresh reference, amend
```

`make release` is a thin wrapper around `release.py`. It refuses to run if the working tree has staged changes or modifications to files outside the version-stamp input list (`SOURCE_FILES` in `kitconfig.py`: `guide.md` / `style.css` / `build.py` / `transforms.py` / `guide.toml` / `kitconfig.py`) — commit those with plain `git commit` first. It also refuses off the canonical host recorded in `guide.toml` as `baseline_platform`.

The manual equivalent of step 4, if you'd rather drive it yourself:

```bash
git add <the source files you edited>
git commit -m "Your message"     # COMMIT SOURCE FIRST — this is load-bearing
make baseline                    # render again with a clean stamp; copy to {{GUIDE_SLUG}}.pdf
git add {{GUIDE_SLUG}}.pdf
git commit --amend --no-edit     # fold {{GUIDE_SLUG}}.pdf into the source commit
```

Why amend? The version stamp in the PDF footer is derived from `git log` and `git status`. Rendering the reference PDF *before* the source commit produces a footer with ` · dirty` and the previous commit's date — which will never match a future post-commit `make verify`. Committing source first makes the stamp stable; amend keeps source + reference in one logical commit. `make release` enforces the order; doing it by hand requires you to.

For **doc-only changes** — anything outside `SOURCE_FILES` — the rendered PDF is unaffected. Commit normally; no reference refresh needed. This covers `README.md`, `CLAUDE.md`, `LICENSE*`, `Makefile`, `pixi.toml`, `pixi.lock`, `verify_pdf.py`, `baseline.py`, `release.py`, `bootstrap.py`, `sync.py`, `adopt-web.py`, `kit-manifest.toml`, `kitmanifest.py`, `.template-version`, and `.github/workflows/`. `release.py` enforces this boundary — it refuses to run when modifications outside `SOURCE_FILES` are present, so a doc edit can never accidentally hitchhike into a release commit.

(One sneaky case: a `pixi.lock` update can drift rendering even though it's not a "source" file. That'll surface as a `make verify` failure on the next build — correct behavior. Pin tighter in `pixi.toml` if you want to narrow the window.)

## Verify: two commands, not one

Verification is split into a fast, platform-independent staleness check and a slower, canonical-host-only render canary. Neither compares rendered images.

**`make verify` — the staleness check (the one CI runs).** It runs `verify_pdf.py --staleness` against the committed `{{GUIDE_SLUG}}.pdf`: read the content hash embedded in the PDF's footer stamp (one `pdftotext` call), compute a fresh hash over `SOURCE_FILES`, and compare. No build, no fonts, no rendering — milliseconds, and it produces the same answer on every machine. A mismatch means someone edited a source file without re-running `make release`, so the repo would ship Markdown and a PDF that disagree; the error names the stale file. A never-released guide (no reference PDF yet) passes with a `pre-first-release` notice.

A green `make verify` is the contract that the committed reference PDF is up to date with the committed source. A red one means either uncommitted/unreleased source changes (run the workflow above) or a `· dirty` stamp that a release would clear.

**`make verify-render` — the render canary (canonical host only).** It builds a fresh PDF and compares page count plus stamp-excluded `pdftotext` text against the committed reference. It needs a build and is platform-sensitive (font substitution changes line wrapping), so it is **never** wired into CI. Its one genuine catch is *environmental* drift — a dependency bump that shifts layout with no source change — which the computed staleness check can't see.

Both PDFs it touches are canonicalized through `qpdf --deterministic-id --normalize-content=y` so accidental non-determinism doesn't masquerade as a real diff.

## CI policy

CI (GitHub Actions) runs on `ubuntu-latest` only: the **kit test suite**, a **PDF build smoke** (`make` renders without crashing), a **web build smoke** (`make web`, when the guide has a web layer), and **`make verify`** (the staleness check). Because staleness is computed from hashes rather than rendered, it reproduces identically on any machine, so — unlike the old image-comparison harness — it is a real gate in CI, not just a local one. CI never runs `make verify-render`: that needs a build and is platform-sensitive, so it stays a canonical-host command.

Two cost controls keep Actions minutes low: CI is **Ubuntu only** (macOS runners bill at 10x and Windows at 2x the Linux rate), and the workflow is **paths-filtered** — pushes that only touch docs (`README.md`, `CLAUDE.md`, `LICENSE*`), `plans/`, or other non-source files skip it. The reference PDF itself is rendered on the canonical host: dispatch `.github/workflows/baseline.yml` (a `macos-latest` runner) to refresh it without a physical Mac. A scheduled `.github/workflows/kit-drift.yml` warns — never fails — when the kit's shared tooling has moved ahead of this guide.

## Website deploy (Cloudflare)

The website is an **opt-in** second output. The PDF is the default; a PDF-only fork needs none of this. To enable the web layer, pass `--with-web` when you bootstrap:

```bash
pixi run python bootstrap.py "My Guide Title" my-guide-slug --with-web
```

That materializes `style-screen.css`, activates `transforms.py` (the per-output YouTube embed split, so embeds work on the site and degrade to links in the PDF), copies the `app/` Cloudflare scaffold (with your slug as the worker name), and activates a live `.github/workflows/deploy.yml`. (Already initialized without it? Run `python guide-template/adopt-web.py --target ../my-guide` — it materializes the same web layer transactionally and records the new managed files in `.template-version` so `sync.py` doesn't later refuse them. `transforms.py` is **not** activated by default, since it is a SOURCE_FILE and would shift the version stamp; pass `--with-transforms` if the guide needs it, then re-baseline with `make release`.)

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
- **Source files that bump the version stamp:** `guide.md`, `style.css`, `build.py`, `transforms.py`, `guide.toml`, `kitconfig.py` (the canonical `SOURCE_FILES` list lives in `kitconfig.py`). Only changes to these require a reference refresh (everything else commits normally).
- **Per-guide values live in `guide.toml`**, not scattered through the scripts — `TITLE`, `OUTPUT_SLUG`, `AUTHOR`, `DESCRIPTION`, `KEYWORDS`, `COPYRIGHT_YEAR`, `baseline_platform` — read and validated by `kitconfig.py`. `OUTPUT_SLUG` is independent of the repo name.
- **The footer version stamp** is `YYYY-MM-DD HH:MM:SS · <sha256[:12]>` over the `SOURCE_FILES` bytes (author date of the most recent commit touching any of them). ` · dirty` appears when the working tree has uncommitted source changes. Treat it as a load-bearing signal that the PDF in your hand matches a real commit — `make verify` compares exactly this embedded hash against fresh source.

## License

This repository is dual-licensed:

- **Code** (build scripts, CSS, configuration) — [Apache License 2.0](LICENSE).
- **Content** (`guide.md` and the rendered PDF) — [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-CONTENT).

You're free to share, adapt, and reuse the guide content for any purpose, including commercially, as long as you give appropriate credit and link to the CC BY 4.0 license.
