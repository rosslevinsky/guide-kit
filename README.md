<!-- front-matter:begin — REPLACED WHOLESALE by bootstrap.py, not placeholder-filled.

     This block is the difference between the KIT's README and a GUIDE's, and
     they are genuinely different documents: this repository is the toolkit, and
     a fork is a book. Writing the kit's own front page in `{{GUIDE_NAME}}` /
     `{{GUIDE_SLUG}}` placeholders made the public landing page open with an
     unsubstituted `# {{GUIDE_NAME}}` heading and a "Read the guide" link
     pointing at `{{GUIDE_SLUG}}.pdf`, which 404s for every visitor.

     Placeholders are still right for the REST of the file — `build/<slug>.pdf`
     in a command a reader adapts is a placeholder doing its job. A link target
     is not: it either resolves or it is broken. So only this block is swapped.
-->
# guide-kit

**The toolkit behind a family of single-document beginner guides.** One Markdown
source, up to three outputs — a downloadable PDF, a website, and a 16:9 slide
deck — built by pandoc + WeasyPrint, rendered from bundled fonts so the host does
not choose the typography, and kept honest by a version stamp that says which
source built the file you are holding.

> **Start here:** [Cold start](#cold-start-guide-kit) — `preflight`, then `init`.
>
> **See what it produces:** [The guide family](#the-guide-family) below.
>
> **Read this repo's own PDF:** [`guide-template.pdf`](guide-template.pdf) — the
> kit renders itself, so this file is also the worked example.
>
> **Working on the kit?** [CONTRIBUTING.md](CONTRIBUTING.md) — setup, the suite, and
> the one rule that surprises people (the reference PDFs are committed build artifacts).
<!-- front-matter:end -->

`make verify` is a fast, platform-independent **staleness check**: it confirms the
committed reference PDF is up to date with the source (no rendering), so a repo never
ships Markdown and a PDF that disagree.

## Cold start: `guide-kit`

**First** get the repository and its toolchain — [Quick start](#quick-start) has the
detail, and it is three commands:

```bash
git clone git@github.com:<you>/<your-fork>.git && cd <your-fork>
pixi install
```

**Then** check your preconditions and initialize:

```bash
# A PDF is the default output. This needs pixi and nothing else.
pixi run python guidekit.py preflight
pixi run python guidekit.py init "My Guide" my-guide --author "Your Name"

# Want a website too? Ask for the website's preconditions explicitly.
pixi run python guidekit.py preflight --with-web
pixi run python guidekit.py init "My Guide" my-guide --author "Your Name" --with-web
```

`--author` is **required**, and that is deliberate: it becomes the PDF's `/Author`
and the visible `© <year> <author>` line on the page. There is no value the kit
could guess for you, so it asks rather than inheriting one. `--description`,
`--keywords` and `--copyright-year` are optional and are derived from your title,
slug and the current year when you leave them off.

**The two preflights check different things, and that is the point.** A bare
`preflight` asks only what building a PDF needs, so a reader who wants a document is
never asked for a Cloudflare account. `--with-web` adds `gh`, `wrangler` and Node >= 22
(wrangler 4.x requires it), plus the Cloudflare facts that would otherwise fail
mid-deploy: account id, the Workers Scripts permission, and a configured workers.dev
subdomain.

It also checks that the slug is a valid DNS label — but read that one carefully. With no
`--worker-name` it validates the slug **`guide.toml` currently declares**, and in a fresh
clone that is still the kit's own, which is always valid. So on a cold start this line
passes without having seen your slug at all. Pass `--worker-name <your-slug>` to check the
real one; `guidekit.py init` validates whichever slug you give it regardless.

Add `--persona custom-domain --domain guide.example.com` to check zone and route
authority as well. The default web path deliberately asks for **no zone at all**,
because the cold-start reader does not have one.

## Getting started from this template

(This section is removed by `bootstrap.py` once you initialize a fork.)

### What this template is

`guide-kit` codifies the shape of a *single-document beginner-guide PDF project* — one Markdown source, one rendered PDF, a reproducible build, a per-guide `guide.toml`, and a copy-and-checksum sync engine that keeps the shared tooling up to date across the family. Concretely it gives you:

- **A render pipeline:** `guide.md` → pandoc → (optional `transforms.py`) → wrap in HTML → WeasyPrint → qpdf canonicalize → `build/{{GUIDE_SLUG}}.pdf`.
- **A reference PDF at the repo root** (`{{GUIDE_SLUG}}.pdf`) that readers download from GitHub directly. The committed reference IS the deliverable.
- **A deterministic version stamp in the footer** — `YYYY-MM-DD · <12-hex-sha256>` — pairing the artifact's authored *edition* date with a hash over that artifact's dependency closure. The hash tells a reader whether the PDF matches its source; the date tells them which edition they hold.
- **A verify split by question:** `make verify` is the staleness check (embedded stamp vs. a fresh content hash — no build); `make drift-canary` is the environmental check (PDF bytes + the `pdffonts` face list vs. the committed reference); `make smoke` asks whether each committed reference looks finished — the guide PDF and, when one is declared, the deck, each against its own assertions. CI runs all three.
- **A `make release` workflow** that bundles source commit + reference refresh into one atomic commit, eliminating "I forgot to update the baseline" mistakes.
- **A copy-and-checksum kit:** per-guide constants in `guide.toml`, a two-axis `kit-manifest.toml`, and `sync.py` to pull shared-tooling updates into guides created from the template (no `git subtree`, no merge).
- **A per-output `transforms.py` hook** for per-guide HTML rewrites, with separate PDF/web entry points driving the opt-in website's play-on-screen / link-in-print media split.
- **Pixi-managed deps + Apache 2.0 / CC BY 4.0 dual licensing + bundled CI** (build smoke + the staleness check + a scheduled kit-drift warning) so each guide starts reproducible and clean.

### Why this exists

The template was extracted in 2026 from three guides (`mac-terminal-guide`, `git-guide`, `accounting-guide`) that had each grown up independently and drifted into incompatible shapes: different env managers, different docs/license setups, no shared regression harness, hand-maintained CSS-in-Python in one and external `style.css` in the other two, no version-stamp convention. The shared shape was always *there*, but nobody was enforcing it. This template makes the shared shape the default, so the next guide starts on the right foot and the existing three can converge.

### Design choices worth knowing

- **Pixi**, not `pip` + `venv` + `brew`. Pandoc, WeasyPrint, poppler, and qpdf are all installed into a project-local conda env from `conda-forge`. No `brew install pango`. No system-wide state. `pixi install` from a fresh clone is sufficient on macOS and Linux, both of which render in CI and locally. **Windows (`win-64`) is declared and untested**: the environment solves and the whole render stack resolves for it — pango, pandoc, qpdf, fontconfig, poppler, weasyprint — so it is not known to be broken, but no guide has ever been rendered on native Windows. Since the faces are bundled and `fontconfig/fonts.conf` replaces the system config, there is no *expected* source of divergence; `make drift-canary` settles it for anyone who runs it there. WSL is the path with no open question.
- **WeasyPrint**, not LaTeX. Trades aesthetic ceiling for "you can debug it in a browser." `make html` writes a standalone HTML preview to `build/{{GUIDE_SLUG}}.html` for fast iteration before the slower PDF render.
- **pandoc** for Markdown → HTML, not a custom parser. Smart-quote conversion is **disabled** (`-smart`) so the literal characters in your source land in the PDF — important for ASCII diagrams and copy-pasteable command snippets.
- **A `transforms.py` hook**, not config files. If a fork needs to rewrite the HTML pandoc produces (turn `Debit / Credit` code blocks into ruled tables, inject TOC anchors, classify numeric vs. prose tables), it provides per-output `post_pandoc_html_for_pdf` / `post_pandoc_html_for_web` functions (or a single-entry `post_pandoc_html` fallback for PDF-only forks). The template ships `transforms.py.example` demonstrating the per-output YouTube-embed split (iframe on the site, watch-link in print); activate by copying to `transforms.py` and the build picks it up automatically. See [Website deploy](#website-deploy-cloudflare).
- **Staleness verification, computed not rendered.** `make verify` compares the content hash embedded in the committed PDF's footer stamp against a fresh hash over `SOURCE_FILES` — no build, no fonts, no platform sensitivity — so it runs identically everywhere, including CI. Whether the *rendering* reproduced is a separate question, answered by `make drift-canary`. `SOURCE_DATE_EPOCH` + `qpdf --deterministic-id` make repeated builds of identical source content-identical.
- **The render does not consult the host's fonts.** The repo bundles its own faces under `fonts/vendor/` and ships `fontconfig/fonts.conf` in place of the system config, so the host never selects a typeface and there is no canonical rendering host. `make baseline` / `make release` refuse a dirty-tree render; `.github/workflows/baseline.yml` renders on an `ubuntu-latest` runner, and `verify.yml` dispatches it for you when a push leaves the reference stale. A **drift canary** in `verify.yml` re-renders and compares bytes plus the embedded-face list against the committed reference, so agreement is measured rather than assumed. **What that measurement covers, stated plainly:** repeated Linux renders of identical source are byte-identical, and the canary re-checks that on every CI run and weekly. The macOS/Linux cross-platform result is *inherited* from an earlier measurement and is not re-run here — [`docs/determinism-evidence.md`](docs/determinism-evidence.md) says which half is proved and which is cited. Native Windows is declared and untested. So the honest claim is "the host cannot choose the typography, and drift is watched for", not "every platform is proven identical".
- **CI runs the staleness check, the build smoke and the drift canary, Ubuntu only.** Because `make verify` is platform-independent it gates in CI for real (the old "build-smoke only" rule is gone), and the drift canary reuses the render the build smoke already produced. Ubuntu-only + paths-filtered keeps Actions minutes low; a scheduled `kit-drift.yml` warns (never fails) when the kit's shared tooling moves ahead of this guide.
- **Dual licensing.** Guide content (your `guide.md` and everything rendered from it) is CC BY 4.0; everything else in the repository — tooling, configuration and documentation alike — is Apache 2.0. Both live as explicit `LICENSE*` files. GitHub's detector reads `LICENSE` only, so the sidebar says Apache-2.0 and the [License](#license) section below is where the split is actually stated.

### How to fork

```bash
gh repo create my-new-guide --template rosslevinsky/guide-kit --private
git clone git@github.com:<you>/my-new-guide.git
cd my-new-guide
pixi install
pixi run python bootstrap.py "My Guide Title" my-guide-slug \
  --author "Your Name" \
  --description "One sentence describing your guide" \
  --keywords "comma, separated, keywords"
```

`--author` is required. `--description` and `--keywords` are written **verbatim** —
nothing is appended to them — and default to text derived from your title and slug
when omitted. None of the four identity values falls back to the kit's: `AUTHOR`
reaches the reader as a copyright line, so inheriting one would publish your guide
under somebody else's name.

`bootstrap.py` writes your per-guide values into a new `guide.toml`; re-renders the `templated` files (`pixi.toml`, `verify.yml`, `kit-drift.yml`) with your identity; fills the `{{GUIDE_NAME}}` / `{{GUIDE_SLUG}}` placeholders in `README.md` and in `CLAUDE.md`'s text outside the managed region; deletes the inherited reference PDF (yours is not built yet); writes the initial `.template-version` record; removes both kit-only sections — "Cold start: `guide-kit`" and this entire "Getting started from this template" one — and deletes itself + the `.template-uninitialized` sentinel that suppresses the template-hygiene check.

`guidekit.py init` from [Cold start](#cold-start-guide-kit) is the same thing with the preconditions checked first: it runs `preflight`, then this exact `bootstrap.py` invocation, then writes `[deploy] domain` and regenerates the wrangler config if you passed `--domain`. Call `bootstrap.py` directly when you already know your environment is ready.

**Commit what bootstrap did before anything else.** It rewrote config, deleted the kit-only files and removed itself — changes outside the authorable set, which `make release` refuses to run alongside. So the order is:

```bash
git add -A && git commit -m "Initialize my-guide-slug"   # NOT optional
# write your guide.md, then:
make                                                     # render and eyeball it
make release MSG="Initial content"                       # source + reference, one commit
git push
```

`bootstrap.py` prints this same sequence when it finishes. Push, and your guide's PDF is downloadable from your fork's GitHub page.

### Staying in sync with the kit

A guide created from this template keeps its shared tooling up to date by **copy-and-checksum, not merge** — no `git subtree`, no upstream remote. The kit (`guide-kit`) is the source of truth for the shared files; each guide records what it last adopted in `.template-version`.

- `kit-manifest.toml` classifies every kit file on **two axes**: source lifecycle (`retained-in-kit` / `bootstrap-source` / `generated`) and destination policy (`identical` / `templated` / `managed-region` / `never`).
- `python sync.py <guide>` reports drift and writes nothing (the default is a dry run).
- `python sync.py <guide> --apply` writes the update transactionally (refusing a dirty tree or an unrecorded managed file, rolling back on any error).
- **`<guide>` is a bare directory name or a path.** A bare name is resolved as a **sibling of the kit** — the layout this family uses, guides checked out beside `guide-kit/` in one workspace root — which is an assumption the tool made silently until it was written down here. If your guide lives somewhere else, pass its path: `python sync.py ../../elsewhere/my-guide --apply`.
- `CLAUDE.md` is a `managed-region` file: only the block between the `kit:begin` / `kit:end` markers is synced; your own guide-specific sections outside them are never touched.
- A scheduled, warn-only `kit-drift.yml` reports (never fails) when the kit moves ahead of a guide.

Adding a web layer to an already-initialized guide is a separate transition, and it is **config-first**: declare `[outputs] site` in the guide's own `guide.toml` and commit that, then run `python guide-kit/adopt.py --target ../my-guide --output site --enable` to materialize what the declaration implies. `--disable` reverses it, and is config-first in the same direction — un-declare the output and commit that first, or it refuses. Neither writes `guide.toml`: it is target-owned, so the declaration stays reviewable in the guide's own history. See [Website deploy](#website-deploy-cloudflare).

### The guide family

This template is the kit behind seven guides, all collected by a hub site:
**<https://guides.speedytuna.com>**. Between them they exercise the template's full range — with
and without `transforms.py`, minimal and rich `style.css`, PDF-only and web-enabled.

| Guide | What it exercises | Read it |
|---|---|---|
| **macOS Terminal** | The structural model the others follow. No `transforms.py`, small island vocabulary. | [mac-terminal.speedytuna.com](https://mac-terminal.speedytuna.com) |
| **Linux Terminal** | Same shape, adapted; every command executed in a container and its output copied exactly. | [linux-terminal.speedytuna.com](https://linux-terminal.speedytuna.com) |
| **Windows PowerShell** | Written fresh around the object pipeline; split verification (executed in `pwsh`, cited where Windows-only). | [powershell.speedytuna.com](https://powershell.speedytuna.com) |
| **Windows Command Prompt** | Re-framed rather than translated; verified by per-command citation, since `cmd.exe` has no Linux runtime. | [cmd.speedytuna.com](https://cmd.speedytuna.com) |
| **Git & GitHub** | Richer `style.css` — CSS-counter TOC numbering, exercise blocks with difficulty pills, a separate `@page :first`. No `transforms.py`. | [git.speedytuna.com](https://git.speedytuna.com) |
| **Financial accounting** | The closest example of using every escape hatch: a substantive `transforms.py` doing journal-entry classification, prose/figures table classification and glossary line breaks. | [accounting.speedytuna.com](https://accounting.speedytuna.com) |
| **Japan trip advice** | The one guide that is not technical — proof the kit is not shaped around code samples. | [japan.speedytuna.com](https://japan.speedytuna.com) |

Each guide is its own repo, and every one now publishes a public site. The **sites** are public;
the **repos** that build them are private, with this one — the kit — the exception.

Why the family is shaped the way it is — what diverged from plan, and the defects that only ever
turned up by running things end to end — is in [`docs/family-as-built.md`](docs/family-as-built.md).

---

## Quick start

### 1. Install pixi

[pixi](https://pixi.sh) is a cross-platform package manager that handles every dependency the **build** needs (pandoc, Python, WeasyPrint, poppler, qpdf) in a single isolated environment. No `brew`, no `apt`, no virtualenvs.

Two things pixi does not supply, because they are the shell you drive it from rather than something it installs: **`make`** and **`awk`**. The `Makefile` is a convenience wrapper — `pixi run build`, `pixi run python verify_artifacts.py …` and friends work without it — but the everyday build and verify commands in this README spell the `make` form. The exceptions are the one-off setup scripts, which are run as `pixi run python …`: none of them has a `make` target, because none of them is run twice. macOS and Linux have both already. On Windows, use WSL: native PowerShell has neither, and `win-64` is declared but untested (see the design note above).

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
make drift-canary               # bytes + embedded-face list vs the reference; needs a build
make verify-render              # weaker local form: page count + stamp-excluded text; needs a build
make smoke                      # does each committed reference look finished? (no build)
make smoke ARTIFACT=slides      # ...just the deck (a deck is asked the deck's questions)
make baseline [ARTIFACT=pdf]    # promote a fresh render onto its committed reference (use deliberately)
make release MSG="..."          # stage source + refresh reference + amend, in one commit
make clean                      # remove build/

# Opt-in slide deck (only when [outputs] slides = true — see "Three outputs"):
make slides                     # 16:9 deck at build/{{GUIDE_SLUG}}-slides.pdf
make slides-coverage            # which chapters have no slide (a report; always exits 0)

# Opt-in web layer (after `bootstrap.py --with-web` or `adopt.py --output site
# --enable` — see "Website deploy"):
make web                        # build the website into app/dist/
make wrangler                   # regenerate app/wrangler.jsonc from guide.toml
make dev                        # build + serve locally via wrangler (needs Node ≥22)
make deploy                     # build + deploy to Cloudflare (manual one-off)
```

The working render (regenerated each build) lands at `./build/{{GUIDE_SLUG}}.pdf` (gitignored). The committed reference is `./{{GUIDE_SLUG}}.pdf` at the repo root — downloadable directly from GitHub.

The PDF is the default deliverable; the website is **opt-in**. On a PDF-only fork `make web` no-ops cleanly and `make dev`/`make deploy` exit with a "web layer not enabled" message — nothing under `app/` exists until you opt in. See [Website deploy (Cloudflare)](#website-deploy-cloudflare).

## Files

| File | Purpose |
|------|---------|
| `guide.md` | The guide itself, in Markdown. Real Markdown with HTML islands only where Markdown can't express the styling. |
| `guide.toml` | Every per-guide value: the six identity constants plus `[outputs]`, `[artifacts.*]`, `[theme]`, `[site]`, `[slides]`, `[deploy]` and `[fonts]`. Read and validated by `kitconfig.py`. See [Every key, in one config that loads](#every-key-in-one-config-that-loads). |
| `kitconfig.py` | The single strict loader/validator for `guide.toml`; owns the `ArtifactSpec` table every dependency closure is derived from — including `SOURCE_FILES` and the content hash the stamp and `make verify` use. |
| `style.css` | The PDF's guide-owned styling — structure, and the last word on anything it sets. Carries `__TITLE__` and `__VERSION__` placeholders substituted by `render_pdf.py`. |
| `style-slides.css` | The same role for the deck. `style-screen.css` is the site's, and is target-owned. |
| `themes/<name>/` | The token sets `style.css` reads through `var()`. Three layers, concatenated in order: `themes/<name>/…`, then `[theme.tokens]` from `guide.toml`, then the guide's own sheet. `screen.css` and `slides.css` layer **over** `print.css` rather than replacing it, so a palette change is made once. |
| `build.py` | The CLI only: parse the flags, dispatch to a renderer. Deliberately thin — it is a stamp input for every artifact, so pipeline code living here re-staled every reference PDF on a website change. |
| `buildcore.py` | The artifact-neutral pipeline: config and paths, the version stamp and determinism helpers, the transforms hook, the glyph-coverage gate, pandoc, the shared HTML wrapper, template hygiene. |
| `render_pdf.py` / `render_site.py` / `render_slides.py` | One renderer per artifact, each in exactly that artifact's closure. `pandoc → optional transforms → wrap in <html> → WeasyPrint → qpdf canonicalize` is `render_pdf.py`'s half. |
| `chapters.py` | Splits the Pandoc AST into chapter units for the `multipage` site, and builds the deck's body for `make slides`. A site **and slides** input, deliberately **not** a PDF one — so a multipage change never re-stales a reference PDF. |
| `cascadecheck.py` / `fontfaces.css` / `fontconfig/` / `fonts/vendor/` | The hermetic render floor: the cascade guard, the bundled `@font-face` declarations, the fontconfig that replaces the system one, and the faces themselves. All render inputs, so all in every artifact's closure. |
| `transforms.py.example` | Hook template. Copy → `transforms.py` to activate per-guide HTML transforms. |
| `transforms.py` | Optional — present only in forks that need post-pandoc HTML rewrites. |
| `verify_artifacts.py` | The verify engine: `--staleness` (embedded stamp hash vs. a fresh content hash — no build), `--smoke` (does this PDF look like a finished guide?) and `--render` (page count + stamp-excluded text). |
| `driftcanary.py` | The environmental check behind `make drift-canary`: a fresh render compared to the committed reference on bytes **and** the `pdffonts` face list. Skips on a stale reference; never auto-baselines. |
| `baseline.py` | Helper for `make baseline` — dirty-tree guard, then promotes the working render onto that artifact's committed reference. `--artifact` accepts every artifact name (`pdf\|site\|slides`), not just the two with references: `baseline.yml` loops over all of them, and the `site` branch deliberately prints why it has nothing to promote rather than erroring. |
| `release.py` | Helper for `make release` — stages source, commits, re-renders, promotes onto the reference, amends. Refuses a dirty tree, a staged change, or a release that is not a new edition. |
| `kit-manifest.toml` / `kitmanifest.py` | The two-axis file manifest (source lifecycle × destination policy) and its loader — the classification `sync.py` and `bootstrap.py` act on. |
| `sync.py` | Copy-and-checksum engine: reports drift (default) or, with `--apply`, transactionally updates a guide's shared files from the kit. |
| `adopt.py` | Turn a declared output on or off in an already-adopted guide (`--target <guide> --output site --enable\|--disable`). Config-first: it never writes `guide.toml`. |
| `cfadapter.py` | Generates `app/wrangler.jsonc` and `_headers` from `guide.toml` (`make wrangler`). The one Cloudflare-specific thing in the built tree. |
| `guidekit.py` | The cold-start CLI: `preflight` (are the preconditions met?) and `init` (preflight, then `bootstrap.py`, then bind `[deploy] domain` if one was given). |
| `hub.py` | Builds the family hub — the omnibus index site. Only meaningful for `[outputs] site = "hub"`, so an ordinary guide never runs it, and it still syncs into every target: a hub **is** a target, and scoping it out would mean `hub build` could only run from a kit checkout. A few unused KB is the price of an adopter's hub working at all. |
| `tools/subset-cjk.py` | Writes a CJK subset into `fonts/generated/` when `[fonts] cjk` names a locale. Target-owned output, and a render input hashed like any bundled face. |
| `pdfaudit.py` | Which face drew which glyph, anchored to source text. The evidence behind the font tests. |
| `.template-version` | Per-guide record of what was last adopted from the kit (`managed_digest`, `rendered_checksums`, `state`). Written by `bootstrap.py`; updated by `sync.py`. |
| `{{GUIDE_SLUG}}.pdf` | Committed reference PDF at the repo root — readers download this directly from GitHub. Regenerate via `make baseline` or `make release`. |
| `{{GUIDE_SLUG}}-slides.pdf` | Committed reference DECK at the repo root, when `[outputs] slides` is on. It has its own closure and its own stamp, so `make verify` reports it separately; `make baseline ARTIFACT=slides` refreshes it. |
| `bootstrap.py` | One-shot rename-your-fork script. Present in template; deleted after first run. |
| `.template-uninitialized` | Sentinel suppressing the template-hygiene check (in `buildcore.py`) while the template is in its un-substituted state. `bootstrap.py` removes it. |
| `Makefile` | Convenience targets — thin wrappers around `pixi run` plus a few amend-workflow helpers. |
| `pixi.toml` / `pixi.lock` | Dependency manifest + locked versions for reproducible builds. |
| `package.json` / `package-lock.json` | **Kit-only**, and not part of any build: a jsdom for `tests/nav_dom.js`, which runs the site's nav script over a real rendered page. Every CI step that touches them is guarded on this root manifest existing, so all of it is inert in a guide. |
| `.gitignore` | `build/` (the working render), `app/dist/`, `node_modules/`, pixi's env. The reference artifacts at the repo root are NOT ignored — they are the deliverable. |
| `CLAUDE.md` | Project conventions and per-guide notes; a `managed-region` file (shared policy between the `kit:begin`/`kit:end` markers is synced). Read before editing content. |
| `CONTRIBUTING.md` | How to work on **the kit itself** — setup, the suite, the re-baseline sequence, the ownership boundaries. Kit-only, so a fork does not inherit it. |
| `LICENSE` / `LICENSE-CONTENT` | Apache 2.0 for code, CC BY 4.0 for content. |
| `.github/workflows/verify.yml` | CI on Ubuntu, paths-filtered: the kit test suite, the PDF, web and hub build smokes, `make smoke`, `make verify` (the staleness check), the drift canary, and the `baseline.yml` dispatch when a push leaves the reference stale. Never runs `make verify-render`. |
| `.github/workflows/baseline.yml` | Renders the reference PDF on an `ubuntu-latest` runner and commits it, then redeploys the site. Auto-dispatched by `verify.yml` when a push leaves the reference stale; manual dispatch is the repair path. |
| `.github/workflows/kit-drift.yml` | Scheduled, warn-only: reports when the kit's shared tooling has moved ahead of this guide. |
| `style-screen.css.example` | Opt-in web layer: screen stylesheet starter. `bootstrap.py --with-web` copies it to `style-screen.css` (NOT a SOURCE_FILE — web-only, doesn't bump the PDF stamp). |
| `templates/hub/` | Seed for a HUB repo — `hub-template.html`, `registry.toml`, a starter snapshot. Copied once and then owned by the hub (`policy = "never"`); an ordinary guide never uses it. |
| `templates/assets/` | Empty `print/`, `web/`, `shared/` scaffolding for a guide's own images. The directory a file lands in decides which closures it is in — `shared/**` re-stales the PDF *and* redeploys the site. |
| `templates/web/` | Opt-in web layer: the `app/` scaffold staging dir (`wrangler.jsonc`, `package.json` + lockfile, `public/.gitkeep`). `--with-web` copies it to `app/` **verbatim** — a plain `copytree`, no templating pass — then regenerates `wrangler.jsonc` from `guide.toml` with `cfadapter.write_wrangler()` and removes the staging copy. The worker name is right because of that regeneration, not because anything substitutes into the template. |
| `.github/workflows/deploy.yml.example` | Opt-in web layer: inert deploy workflow (GitHub only runs `*.yml`). `--with-web` activates it as `deploy.yml`. |
| `verify_web.py` | Opt-in web layer: asserts the per-output embed split (iframe on the site, watch-link in print). Skips cleanly when the web layer isn't enabled. |
| `docs/` | Kit-only maintainer docs: [`family-as-built.md`](docs/family-as-built.md) (the family's decision record), [`determinism-evidence.md`](docs/determinism-evidence.md) (the committed byte-identity measurement), and [`typography-signoff.md`](docs/typography-signoff.md) (the human sign-off on the stage-0+1 re-baseline). Pruned from a fork. |

(The web-layer files above ship inert. A PDF-only fork has no `app/`, no `style-screen.css`, and no live `deploy.yml`. See [Website deploy (Cloudflare)](#website-deploy-cloudflare).)

## Workflow: editing content

For **intentional content changes** — anything that alters the rendered PDF:

```
1. Edit guide.md / style.css / build.py / transforms.py / guide.toml
2. make                                    # render to build/{{GUIDE_SLUG}}.pdf
3. Open build/{{GUIDE_SLUG}}.pdf and eyeball it. Right? If not, fix and goto 2.
4. git commit && git push                  # CI refreshes the reference PDF for you
```

**Step 4 is a plain push, from any platform.** The reference PDF is regenerated in CI: your push
leaves the committed reference stale, so `verify.yml` recognises that expected state, auto-dispatches
`baseline.yml` and **exits green with a notice**. `baseline.yml` re-renders on an `ubuntu-latest`
runner, smoke-checks the render, commits the refreshed PDF, and then dispatches `deploy.yml` so the
site stops serving the old download. **Nothing goes red on an ordinary content push** — red is
reserved for a dispatch that failed, a lockfile bump pushed alongside content, a failed render or a
failing test.

Steps 2–3 still matter. Once you push, the only thing that looks at the render is `make smoke`,
which checks that the PDF resembles a finished guide — never that it says what you meant.

### Refreshing the reference yourself

`make release` collapses steps 2–4 into one command and runs from any host — rendering is
hermetic, so there is no canonical machine to be at. The push path above is still the normal one
for a content edit; `make release` is for refreshing the reference by hand.

`make release` is a thin wrapper around `release.py`. It refuses to run if the index has any staged change, or if the working tree has modifications outside the **authorable set** — every artifact's inputs plus the bundled faces, which is wider than the PDF's own `SOURCE_FILES` closure — so commit those with plain `git commit` first.

It refuses one more thing: a release that is not a new edition. The artifact's content must differ from the committed reference (compared with the edition date normalised away, so hand-editing `[artifacts.pdf] date` cannot make an identical PDF look new), and if the reference's version stamp cannot be read at all it refuses rather than treating that as a first release — re-render the reference first. `release.py` writes the `date` key itself, from the release transaction's admission instant, so you should not set it by hand.

The manual equivalent of step 4, if you'd rather drive it yourself:

```bash
git add <the source files you edited>
git commit -m "Your message"     # COMMIT SOURCE FIRST — this is load-bearing
make baseline                    # render again with a clean stamp; copy to {{GUIDE_SLUG}}.pdf
git add {{GUIDE_SLUG}}.pdf
git commit --amend --no-edit     # fold {{GUIDE_SLUG}}.pdf into the source commit
```

Why amend? The stamp's hash covers the artifact's closure and its ` · dirty` marker comes from `git status`, so rendering the reference PDF *before* the source commit produces a footer marked dirty — which no future post-commit `make verify` can match. Committing source first makes the stamp stable; amend keeps source + reference in one logical commit. `make release` enforces the order; doing it by hand requires you to. (The stamp's DATE is not affected: it is the authored `[artifacts.<name>] date`, not a commit date.)

For **doc-only changes** — anything outside the authorable set — the rendered PDF is unaffected. Commit normally; no reference refresh needed. This covers `README.md`, `CLAUDE.md`, `LICENSE*`, `Makefile`, `pixi.toml`, `pixi.lock`, `verify_artifacts.py`, `driftcanary.py`, `baseline.py`, `release.py`, `bootstrap.py`, `guidekit.py`, `sync.py`, `adopt.py`, `hub.py`, `pdfaudit.py`, `kit-manifest.toml`, `kitmanifest.py`, `.template-version`, and `.github/workflows/`. `release.py` enforces this boundary — it refuses to run when modifications outside the authorable set are present, so a doc edit can never accidentally hitchhike into a release commit.

Note the authorable set is **wider** than the PDF's `SOURCE_FILES`: it is the union across every artifact, so `style-screen.css` and the slide source are in scope for staging even though neither is a PDF input. That is deliberate — an edit to one alongside a PDF edit used to be refused outright — and it does not change what re-stales the PDF, which is still its own closure and nothing else.

(One sneaky case: a `pixi.lock` update can drift rendering even though it is not a "source" file. It will **not** surface as a `make verify` failure — the lock is deliberately outside `SOURCE_FILES`, so the staleness check is answering its own question correctly. That gap is exactly what the **drift canary** exists for: `pixi.lock` is in `verify.yml`'s trigger paths, and the canary re-renders and compares bytes. Pin tighter in `pixi.toml` if you want to narrow the window.)

## Three outputs from one Markdown source

`guide.md` is the only content file. What gets built from it is **declared** in
`guide.toml` under `[outputs]`, never inferred from which files happen to exist:

```toml
[outputs]
pdf    = true          # the reference PDF readers download
site   = "multipage"   # "none" | "single" | "multipage" | "hub"
slides = true          # a 16:9 deck

# EVERY declared output carries its own authored EDITION date, and the loader
# refuses a guide that declares an output without one. The dates are separate
# because the outputs are: re-cutting the deck does not re-date the PDF.
# `make release` is the normal writer of these — editing one by hand cannot
# pass off an identical artifact as a new edition (see the release model).
[artifacts.pdf]
date = "2026-07-28"
[artifacts.site]
date = "2026-07-28"
[artifacts.slides]
date = "2026-07-28"
```

- **PDF** — the default. `make`.
- **Website** — `make web`. `single` is one long page; `multipage` splits on top-level
  headings into per-chapter pages with a server-rendered sidebar, and the split is done
  over the **Pandoc AST** rather than by rewriting rendered HTML, so a guide that *teaches*
  markup does not get its own code samples rewritten.
- **Slides** — `make slides`, into `build/<slug>-slides.pdf`. A deck is a **selection, not
  a mirror**: nothing becomes a slide unless you wrap it in a `::: slide` fenced div, because
  one-slide-per-heading turns a 34-chapter guide into a deck nobody presents.
  `make slides-coverage` reports which chapters have no slide — a report that always exits 0,
  since a gate on it would just get switched off.

Each output has its **own dependency closure and its own version stamp**, so a website change
does not re-stale the PDF, and editing a screen-only stylesheet cannot silently move the
document readers download.

### Every key, in one config that loads

`kitconfig.py` is the single strict loader and it **rejects unknown keys**, so this is the
whole vocabulary rather than a selection from it. The kit's own
`tests/test_documented_config_loads.py` feeds this block to the real loader, so it cannot
drift from the schema.

```toml
# --- identity: the six values every guide must have -------------------------
TITLE = "My Guide"
OUTPUT_SLUG = "my-guide"          # kebab-case; drives the PDF filename and the
                                  # worker name, and is INDEPENDENT of the repo name
AUTHOR = "A. Author"
DESCRIPTION = "One sentence describing this guide."   # written verbatim
KEYWORDS = "comma, separated"
COPYRIGHT_YEAR = 2026             # a stored constant, never a clock read, so
                                  # renders stay deterministic

# --- what this guide builds -------------------------------------------------
[outputs]
pdf = true
site = "multipage"                # "none" | "single" | "multipage" | "hub" | "app"
                                  # "app" LOADS but does not BUILD: it names an
                                  # externally-built SPA the kit only deploys, so
                                  # `make web` refuses it by name rather than
                                  # rendering one page under another shape's label
slides = true

# --- one authored EDITION date per declared output --------------------------
[artifacts.pdf]
date = "2026-07-28"
[artifacts.site]
date = "2026-07-28"
[artifacts.slides]
date = "2026-07-28"

# --- appearance: a theme is a TOKEN SET, not a stylesheet -------------------
[theme]
name = "editorial"                # themes/<name>/ — "classic-sans" | "editorial" | "technical"
                                  # EXPLICIT on purpose: no guide inherits a new
                                  # appearance from a kit change
[theme.tokens]                    # per-guide overrides of any theme value.
"--accent" = "#7a2e2e"            # KEYS ARE CSS CUSTOM PROPERTY NAMES — they are
                                  # emitted into the cascade verbatim, so a bare
                                  # `accent` is rejected rather than silently
                                  # producing a declaration nothing reads.

# --- the website ------------------------------------------------------------
[site]
canonical = "https://my-guide.example.com"   # absolute URL for <link rel=canonical>
chapter_level = 1                 # heading depth `multipage` splits on

# --- the deck ---------------------------------------------------------------
[slides]
source = "auto"                   # "auto" | "guide" | "file"
file = "slides.md"                # used when source resolves to "file"

# --- deployment -------------------------------------------------------------
[deploy]
domain = "my-guide.example.com"   # emits routes + custom_domain, and turns
                                  # workers_dev OFF. Omit it and workers.dev is
                                  # the whole publication story.
preview_urls = false              # a SECOND workers.dev surface, independent of
                                  # workers_dev, and the URLs do not expire

# --- CJK ---------------------------------------------------------------------
[fonts]
cjk = ["jp"]                      # a LIST, and it may name several: "jp", "sc",
                                  # "tc", "kr". Omit the table entirely for none.
                                  # `tools/subset-cjk.py` writes the subset into
                                  # fonts/generated/, which is a render input and
                                  # is hashed like any bundled face.

# --- what this guide requires OF THE KIT -------------------------------------
[kit]
min_version = ""                  # reserved; empty means "any version"
```

One table is missing above on purpose: `[hub]` (`registry`, `snapshot`) belongs to the family
hub — the omnibus index that `hub.py build` / `hub.py update` produces under
`[outputs] site = "hub"`. An ordinary guide never sets it.

Assets live in three declared directories, each in a different closure:
`assets/print/**` (PDF only), `assets/web/**` (site only) and `assets/shared/**` (both).
The site build copies the two it depends on into the built tree **at their own paths**, so the
path you write is the path both outputs resolve: `![](assets/shared/x.png)` works in the PDF
(whose base URL is the repo root) *and* on the site (whose root is the served tree). Write the
directory you mean; do not shorten it to `assets/x.png`. `assets/print/**` is deliberately not
published: shipping bytes the site's own closure hash does not cover is how a deploy stops
describing itself.

Two things here are easy to miss: **`make smoke`** asks whether each committed reference looks like a
finished guide — the question neither the staleness check nor the drift canary asks; and
**`adopt.py`** turns a declared output on or off in a guide that is already adopted, which is
the only supported way to add a site to a guide that started PDF-only.

## Publishing

A push to `main` that touches the site redeploys the site. That is the whole story — there is
no separate release step to remember.

**Past editions need no mechanism.** The reference PDF is committed, so `git log` on it is the
edition history and `git show <sha>:<slug>.pdf` retrieves any one of them.

The kit briefly carried a tag-triggered publication protocol — a journal on a git ref, a
publication lease, provider reconciliation, GitHub Release assets, and a per-deploy manifest of
every served path written into `.well-known/`. It was removed: no `release-*` tag was ever
pushed, and with the guide repositories private its assets would have been collaborator-only
while the public download is the site. It solved a distribution problem this family does not
have, and nothing survives it — the manifest included, since no tool, no page and no check ever
read it.

## Verify: what each command actually asks

Verification splits into a fast **staleness** check (did the source change?) and a render-based
**drift** check (did anything else change?). CI runs one of each: `make verify` and
`driftcanary.py`. `make verify-render` is the older, weaker local form of the drift question,
kept as a convenience. Nothing here compares rendered images.

**`make verify` — the staleness check (the one CI runs).** It runs `verify_artifacts.py --staleness` against the committed `{{GUIDE_SLUG}}.pdf`: read the content hash embedded in the PDF's footer stamp (one `pdftotext` call), compute a fresh hash over `SOURCE_FILES`, and compare. No build, no fonts, no rendering — milliseconds, and it produces the same answer on every machine. A mismatch means someone edited a source file without re-running `make release`, so the repo would ship Markdown and a PDF that disagree; the error names the stale file. A never-released guide (no reference PDF yet) passes with a `pre-first-release` notice.

A green `make verify` is the contract that the committed reference PDF is up to date with the committed source. A red one means either uncommitted/unreleased source changes (run the workflow above) or a `· dirty` stamp that a release would clear.

**`make drift-canary` — the environmental check (CI runs this one too).** It builds a fresh PDF and compares it to the committed reference on two axes: PDF **bytes** and the `pdffonts` embedded-face list. Its target is drift with no source change at all — a dependency bump, a rebuilt runner image — which the staleness check cannot see, because `pixi.lock` is deliberately outside `SOURCE_FILES`. Two properties make it trustworthy: it **skips** when the reference is stale (a fresh render is supposed to differ then, and that is `make verify`'s finding, not drift), and it **never** auto-baselines, because absorbing drift into the deliverable is exactly what it exists to prevent.

**`make verify-render` — the older, weaker local form.** Page count plus stamp-excluded `pdftotext` text against the committed reference. Being a text comparison it is blind to anything that preserves line breaks, including a metric change or a face substitution — which is why the canary compares bytes and faces instead. Kept as a fast pre-push convenience; CI does not run it.

Every PDF these touch is canonicalized through `qpdf --deterministic-id --normalize-content=y` so accidental non-determinism doesn't masquerade as a real diff.

A fourth command answers a question none of the three do: **`make smoke`** asks whether an artifact *looks finished* — the check that would have caught a footer wrapping onto a second line on every page. It covers every declared artifact that has a committed reference, and asks each its own question: a deck is a *selection*, so it is never asked for the guide's title and is asked for its version stamp instead. A guide that has not released yet passes with a pre-first-release notice, like `make verify`. Build-free and platform-independent, so CI runs it too.

## CI policy

CI (GitHub Actions) runs on `ubuntu-latest` only: the **kit test suite**, a **PDF build smoke** (`make` renders without crashing), a **web build smoke** (`make web`, when the guide declares a site), **`make smoke`** (does each committed reference look finished?), and **`make verify`** (the staleness check). Because staleness is computed from hashes rather than rendered, it reproduces identically on any machine, so — unlike the old image-comparison harness — it is a real gate in CI, not just a local one. CI runs `driftcanary.py` rather than `make verify-render`, reusing the PDF the build smoke already produced: it is the stronger of the two, comparing bytes and the embedded-face list rather than page count and text.

Which smokes apply is read from the declared shape in `guide.toml`, never probed from the filesystem — a PDF-only guide is not asked a web question, and a guide with no reference PDF yet skips the checks that need one with a notice rather than a red run.

Two cost controls keep Actions minutes low: CI is **Ubuntu only** (macOS runners bill at 10x and Windows at 2x the Linux rate), and the workflow is **paths-filtered** — pushes that only touch docs (`README.md`, `CLAUDE.md`, `LICENSE*`), `plans/`, or other non-source files skip it. The reference PDF is rendered by `.github/workflows/baseline.yml` on an `ubuntu-latest` runner, which you do not normally trigger by hand: when a push leaves the reference stale, `verify.yml` dispatches it — staying green, because staleness straight after a source push is the expected state — and it renders, commits the refreshed PDF and redeploys the site. Only a rebuild that fails is reported as a failure. `verify.yml` also carries the **drift canary**, which re-renders weekly and on any `pixi.lock` or workflow change; it fails loudly on a difference and never auto-baselines. It runs one build smoke per declared shape — the PDF, the site, and for a hub an offline `hub.py build`, which is the only check that the seed template and the registry still render together. A scheduled `.github/workflows/kit-drift.yml` warns — never fails — when the kit's shared tooling has moved ahead of this guide.

## Website deploy (Cloudflare)

The website is an **opt-in** second output. The PDF is the default; a PDF-only fork needs none of this.

**Enabling it at bootstrap** — pass `--with-web` when you initialize the fork. That materializes `style-screen.css`, copies the `app/` Cloudflare scaffold with your slug as the worker name, and activates a live `.github/workflows/deploy.yml`.

**Enabling it later** — this is the path a guide that already exists takes, and it is **config-first**: declare `[outputs] site` and its `[artifacts.site]` date in the guide's own `guide.toml` and commit that, then run

```bash
python guide-kit/adopt.py --target ../my-guide --output site --enable
```

It materializes the same web layer transactionally and records the new managed files in `.template-version`, so a later `sync.py --apply` does not refuse the files the kit just wrote. `--disable` reverses it, and is config-first in the same direction: **un-declare the output and commit that first**, or `adopt.py` refuses — it never writes `guide.toml`, which is target-owned.

`transforms.py` is **not** activated by either path unless you ask. It is a `SOURCE_FILES` entry, so creating it shifts the PDF's version stamp; pass `--with-transforms` if the guide needs it (the worked example is the YouTube-embed split — an iframe on the site, a watch-link in print), then refresh the reference with `make release`.

The built tree is **provider-neutral** and that is proven by serving it: the kit's `tests/test_static_portability.py` starts a plain `http.server` over the exact `app/dist/` output and exercises the routes, the PDF's media type and 404 semantics. The one Cloudflare-specific artifact is `_headers`, which `cfadapter.py` writes — so forced download is provider-*optional*. On a host that ignores `_headers` the PDF opens inline instead of downloading, and nothing else differs.

Once enabled, the site builds with `make web` (→ `app/dist/`) and deploys to Cloudflare Workers Static Assets. `make dev` serves it locally (requires **Node ≥22**; run `npm install` in `app/` first — wrangler is pinned in `app/package.json`). `.github/workflows/deploy.yml` deploys automatically on a push to `main`. `make deploy` is the manual one-off.

**A pull request builds; it does not deploy, and it is given no Cloudflare credentials.** That is deliberate and it is not a limitation of this kit. A same-repository pull request receives repository secrets, and for the `pull_request` event GitHub runs the workflow file *from the merge commit* — the pull request's own copy — so a PR can delete any guard the workflow adds in the same commit that adds a payload. There is no arrangement of jobs, artifacts or validation that closes that, so the token is kept off the path entirely. The PR still gets a real build check.

**The deploy is gated on `make verify`.** The site ships a *copy* of the reference PDF baked in at `make web` time, so `deploy.yml` refuses to publish while the committed reference is stale — otherwise a content push would put new HTML and an old download side by side.

**A content push is not a failure, and does not report as one.** Editing `guide.md` necessarily makes the committed reference stale — that is the normal state of a push, not a defect — so `verify.yml` recognises the expected case (a push to the default branch, reference stale) and exits **green** with a notice, having dispatched the rebuild. `deploy.yml` likewise **skips** its deploy steps rather than failing them. Red is reserved for things that are actually wrong: a stale reference the rebuild could not be dispatched for, a push that also moved `pixi.lock` (the drift canary re-renders and compares bytes — see [Verify](#verify-what-each-command-actually-asks)), a failed render, a broken test.

The whole chain, end to end:

```
push guide.md
  └─ verify.yml   GREEN — reference is stale as expected; dispatches ──┐
     deploy.yml   GREEN — deploy steps skipped, nothing shipped stale  │
                                                                       ▼
     baseline.yml  ubuntu-latest: make baseline → make verify → make smoke
                   └─ commits the refreshed PDF, then dispatches:
                      ├─ verify.yml   GREEN — reference now current
                      └─ deploy.yml   GREEN — site live with new HTML + PDF
```

The one thing to watch: if `verify.yml` goes green and **no `baseline` run appears**, the dispatch did not happen and the reference is stale with nothing coming to fix it. That case fails the run deliberately, so it reaches you as a red check rather than as silence.

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

### 4. Bind a custom domain (optional) — in config, not the dashboard

By default the site is reachable at `{{GUIDE_SLUG}}.<your-subdomain>.workers.dev`, and that is a complete, working setup: **no Cloudflare zone is required to publish a guide.**

To put it on your own domain, set it in `guide.toml` and regenerate:

```toml
[deploy]
domain = "guide.example.com"
```

```bash
make wrangler     # rewrites app/wrangler.jsonc from guide.toml
git add app/wrangler.jsonc && git commit -m "Bind the custom domain"
```

That writes a `routes` entry with `custom_domain: true`, so the next `wrangler deploy` binds the domain itself — **no dashboard step**. It also sets `workers_dev: false`, which matters more than it looks: Cloudflare re-asserts the workers.dev URL on every deploy unless config says otherwise, so a domain bound only in the dashboard leaves the guide published at *two* URLs, the second outside your zone and therefore outside its WAF, analytics and redirect rules.

The domain's zone must be in the same Cloudflare account. Do not hand-edit `app/wrangler.jsonc` — it is generated, and the kit's test suite fails when it drifts from `guide.toml`.
## Conventions

The conventions you'll most often want to know:

- **Allowed HTML islands** in `guide.md` are listed in [`CLAUDE.md`](CLAUDE.md). The defaults: `<div class="title-block">`, `<div class="callout warn|tip|accent">`, `<div class="exercise">`, `<pre class="diagram">`, `<div class="page-break"></div>`. Forks add or remove from this list and update `style.css` to match.
- **Source files that bump the PDF's version stamp** are whatever `kitconfig`'s `ArtifactSpec` for `pdf` declares, and the list is longer than the obvious four. Ask the kit rather than trusting a list in prose — that is what it is derived for:

  ```bash
  pixi run python -c "import kitconfig as k; print('\n'.join(k.stamp_pathspec('pdf', k.load())))"
  ```

  Pass the loaded config as shown: `kitconfig.SOURCE_FILES` is the static, config-free view, so it resolves `themes/<theme>/print.css` to the **default** theme and names the wrong sheet for a guide that selected another. Today the closure is `guide.md`, `guide.toml`, `style.css`, `themes/<theme>/print.css`, `transforms.py`, `build.py`, `buildcore.py`, `render_pdf.py`, `kitconfig.py`, `cascadecheck.py`, `fontfaces.css`, `fontconfig/fonts.conf` and `fonts/vendor/UPSTREAM-HASHES.json` — plus `fonts/{vendor,generated}/*` and `assets/{shared,print}/**` by content. Only changes to these require a reference refresh; everything else commits normally. The site and the deck have their **own** closures, which is why a `style-screen.css` edit cannot re-stale the PDF.
- **Per-guide values live in `guide.toml`**, not scattered through the scripts. The six identity constants — `TITLE`, `OUTPUT_SLUG`, `AUTHOR`, `DESCRIPTION`, `KEYWORDS`, `COPYRIGHT_YEAR` — plus the declared shape, the theme, and the site/slides/deploy/fonts tables. All read and validated by `kitconfig.py`, which rejects unknown keys. `OUTPUT_SLUG` is independent of the repo name.
- **The footer version stamp** is `YYYY-MM-DD · <sha256[:12]>`: the artifact's authored `[artifacts.<name>] date` from `guide.toml`, and a hash over that artifact's own dependency closure. ` · dirty` appears when the working tree has uncommitted changes to those inputs. The hash is the load-bearing half — `make verify` compares exactly it against fresh source. The date is an *edition* date and moves only at release, which is what lets a content refresh re-baseline automatically without a human choosing a date.

## License

This repository is dual-licensed, and the split is by **what a file is**, not by file type:

- **Guide content** — `guide.md` and the rendered PDF, slide deck and website — is [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-CONTENT). Share, adapt and reuse it for any purpose including commercially, with appropriate credit and a link to the licence.
- **Everything else in the repository** — build scripts, stylesheets, themes, configuration, workflows, any test suite **and all documentation that is not the guide itself**, this file and `CLAUDE.md` included — is [Apache License 2.0](LICENSE).

"Everything else" is stated that way on purpose, and by **category** rather than by filename. An earlier wording scoped Apache 2.0 to "build scripts, CSS, configuration" and CC BY to "`guide.md` and the rendered PDF", which left the largest prose files in the repository named by neither grant; the wording that replaced it listed those files by name, which was accurate in the kit and wrong in every guide built from it — the kit's `bootstrap.py` prunes `CONTRIBUTING.md`, `docs/**` and `tests/**` from every fork, so a fork's own licence section named three things it does not contain. A category covers both repositories. `LICENSE` governs the repository by default, so nothing was ever actually unlicensed — but a licence statement that does not cover its own document, or that inventories files that are not there, is not one a re-user should have to reason about.

The bundled typefaces under `fonts/vendor/` carry their own upstream licences (SIL OFL 1.1 for the Source families; Bitstream Vera, plus Tavmjong Bah's Arev additions, for DejaVu), and those licence texts are committed alongside the faces because redistribution requires them to travel with the files. See [`fonts/vendor/README.md`](fonts/vendor/README.md).

GitHub's licence detector reads `LICENSE` alone, so the repository is labelled Apache-2.0 in its sidebar; `LICENSE-CONTENT` is a second file it does not surface. That is why the split is spelled out here rather than left to the badge.
