# Plan: Web-layer backport into guide-template (opt-in)

## Status

| Field | Value |
|---|---|
| Phase | Not yet broken down |
| State | Planning |
| Branch | `web-layer-backport` |
| Reference impl | `japan-guide` (proven dual-output) |
| Last updated | 2026-05-31 |

## Goal

Graduate japan-guide's dual-output (website + PDF) machinery into `guide-template`
as an **opt-in web layer**, so a fork can produce a Cloudflare-deployed website
alongside its PDF. PDF stays the default: a PDF-only fork remains pure pixi/Python
with **no `app/`, no live deploy workflow, no Node/wrangler footprint** until it
explicitly opts in via `bootstrap.py --with-web`.

## Settled design decisions (from interview)

1. **`app/` scaffold ships opt-in via `bootstrap.py --with-web`** — not committed-inert,
   not loose `.example` files the user hand-copies. PDF-only forks have no `app/` at
   all; `--with-web` materializes `app/wrangler.jsonc`, `app/package.json` (+ lockfile),
   `app/public/.gitkeep` with the slug substituted.
2. **`deploy.yml` ships opt-in via the same `--with-web` flag** — as
   `.github/workflows/deploy.yml.example` (inert; GitHub only runs `*.yml`), renamed to
   `deploy.yml` by bootstrap. No PDF-only fork ever gets a live workflow that fails on
   missing Cloudflare secrets.
3. **No CONTRIBUTING.md** — the web deploy + secrets flow is documented in README's
   "Website deploy" section and CLAUDE.md, mirroring japan-guide.
4. **Full 5-phase backport** (not a partial slice).

Storage form for the bootstrap-materialized assets: the `app/` scaffold and
`style-screen.css` and `deploy.yml` ship as `.example` source files (or a
`templates/web/` staging dir — settled in Phase 3) that `--with-web` copies into place
with `{{GUIDE_SLUG}}` substituted. They are NOT live in an un-bootstrapped fork.

## Success Criteria

- [ ] On the un-bootstrapped template (and any PDF-only fork): `make` and `make verify` pass unchanged; no `app/` dir, no `deploy.yml`, no Node required.
- [ ] `build.py` supports the two-entry transforms contract (`post_pandoc_html_for_pdf` / `_for_web`) with single-entry `post_pandoc_html` fallback and identity fallback — a PDF-only build with no `transforms.py` still renders correctly.
- [ ] `python build.py --web` on the un-opted template exits 0 with a clear "web layer not enabled" message (no traceback, no partial `app/dist`).
- [ ] After opt-in, `make web` produces nonzero `app/dist/index.html` + a copy of the reference PDF; `make dev`/`make deploy` invoke wrangler from `app/`.
- [ ] `bootstrap.py --with-web my-slug` materializes `style-screen.css`, the `app/` scaffold (slug-substituted), and `deploy.yml`; without the flag none of those appear and the fork is PDF-only.
- [ ] `bootstrap.py` (no flag) still works exactly as today; `--with-web` is purely additive and the `.template-uninitialized` hygiene flow is intact.
- [ ] `make verify` passes after every phase; `guide-template.pdf` re-baselined where SOURCE_FILES changed.
- [ ] `verify.yml` (Ubuntu-only, `make -n web`-guarded) stays green on the PDF-only template.
- [ ] README + CLAUDE.md document the opt-in web layer, the embed vocabulary, and a **generalized** Cloudflare deploy-secrets walkthrough.
- [ ] Grep-clean: no japan-specific value (`japan-guide`, `speedytuna`, `E01x6ClIiuc`, real secret names) leaks into the template.

## Technical Constraints

- **PDF flow is sacrosanct.** `make`, `make verify`, `make release`, `make baseline` behave identically for PDF-only forks. Web code paths are inert/guarded when web assets are absent.
- **SOURCE_FILES discipline.** `build.py`, `guide.md`, `style.css`, `transforms.py` are SOURCE_FILES (bump the PDF stamp → need `make release` re-baseline). `style-screen.css`/`.example`, `app/`, workflows, `bootstrap.py`, docs are NOT — plain commits. Phases touching SOURCE_FILES must re-baseline `guide-template.pdf`.
- **Generalize, don't copy.** Port from japan-guide but replace every japan-specific value with the template placeholder convention (`{{GUIDE_NAME}}`/`{{GUIDE_SLUG}}`) or bootstrap substitution. Worker name = slug; the custom domain is dashboard-bound, never hardcoded.
- **Node ≥22 + wrangler 4.x** enter only via the opt-in `app/package.json`; the template base toolchain stays pixi/Python-only.
- **`bootstrap.py` self-deletes and removes `.template-uninitialized`** as its last steps; `--with-web` must run before that and fail safe (leave bootstrap in place on error).
- **Don't regress the merged CI cost controls** (Ubuntu-only, paths-filtered, guarded web smoke) already on `main`.
- **Reference fidelity:** the japan-guide implementation is the source of truth for `build.py` web functions (`_load_transforms`, `_apply_transforms`, `_pandoc_body`, `_wrap_html`, `render_web_html`, `build_web`), the Makefile `web`/`dev`/`deploy` targets, `app/wrangler.jsonc`, `app/package.json` (wrangler ^4.x), and `verify_web.py`.

## Non-Goals

- No Cloudflare deployment of the template itself (it ships PDF-only; web is exercised in forks).
- No migration of existing PDF-only forks (mac-terminal-guide, git-guide, accounting-guide).
- No new web features beyond what japan-guide proved (YouTube embed is the worked example; no maps/analytics/SPA/multi-page).
- No change to the merged PDF colophon / footer-stamp / CI work.
- No CONTRIBUTING.md.

## Affected Areas

**Will change (SOURCE_FILES — require `make release` re-baseline):**
- `build.py` — add license/transforms two-entry contract (`_load_transforms`, `_apply_transforms(target)`, `_pandoc_body`, `_wrap_html`); `--web` arg; `render_web_html()` + `build_web()`; guarded no-op + message when `style-screen.css`/`app/` absent. Add `STYLE_SCREEN`/`WEB_DIR` path constants.
- `transforms.py.example` — refactor to demonstrate the per-output split with the YouTube embed worked example (keep single-entry note for PDF-only forks).

**Will change (non-SOURCE_FILES — plain commits):**
- `Makefile` — `web` / `dev` / `deploy` targets; `web` no-ops cleanly without assets, `dev`/`deploy` error clearly without `app/`. Help text updated.
- `pixi.toml` — `web = "python build.py --web"` task.
- `bootstrap.py` — `--with-web` flag: copy `style-screen.css.example` → `style-screen.css`, materialize `app/` scaffold (slug-substituted), rename `deploy.yml.example` → `deploy.yml`. Help/docstring updated.
- `.gitignore` — `app/dist/`, `node_modules/`.
- `README.md` — "Website deploy" section (generalized secrets walkthrough), opt-in framing, new make targets, files-table rows.
- `CLAUDE.md` — "The website" section, `embed youtube` island in the allowed-HTML table, per-output transform contract, opt-in note.

**Will add:**
- `style-screen.css.example` — screen stylesheet starter (generic), copied to `style-screen.css` by `--with-web`.
- `app/` scaffold templates: `wrangler.jsonc(.example)`, `package.json(.example)`, `package-lock.json`, `public/.gitkeep` — stored inert; materialized by bootstrap. Exact storage layout settled in Phase 3.
- `.github/workflows/deploy.yml.example` — inert deploy workflow, generalized (`fetch-depth: 0`, wrangler-action, PR-preview comment; secret names `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`).
- `verify_web.py` — per-output split assertion (iframe in web HTML, watch-link in print HTML); skips cleanly when web not enabled.

**Must stay consistent:**
- `verify_pdf.py`, `release.py` — unchanged; PDF harness/flow intact.
- `.github/workflows/verify.yml` — already has the guarded web smoke; keep green.
- `guide-template.pdf` — re-baseline only via `make release` when SOURCE_FILES change.

**Tests / verification:**
- After each phase: `make` + `make verify` on the PDF-only template.
- `python build.py --web` graceful-no-op check on the un-opted template.
- Manual (throwaway `--with-web` fork or temporary opt-in): `make web` → playable-embed site; `verify_web.py` passes; `make dev` serves locally.

---

_Phases: not yet broken down — run `/plan-phase plans/web-layer-backport/plan.md` to generate phase documents._
