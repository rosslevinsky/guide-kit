# Phase 3: Opt-in Assets (templates/web scaffold, deploy.yml.example, verify_web.py)

_Status: complete_

## Goal

Add the inert, generalized opt-in files a fork will materialize: the `app/` Cloudflare scaffold, the example deploy workflow, and the per-output verifier — all placeholdered, none active until `--with-web`.

## Entry Criteria

Before starting this phase, confirm:
- [x] Phase 2 committed, pushed, `make verify` green.
- [x] `make web`/`dev`/`deploy` targets exist; CI re-gated and green.

## Tasks

- [x] **Storage layout — SETTLED: the `app/` scaffold must NOT ship as a live `app/` dir.** Plan success criterion #1 and settled-decision #1 require the un-bootstrapped template to have **no `app/` at all**, and Phase 4's no-flag test asserts `! test -e app`. So stage the scaffold under a non-`app/` path — **`templates/web/`** — that `bootstrap --with-web` copies into `app/` with the slug substituted. (`style-screen.css.example` and `.github/workflows/deploy.yml.example` are fine as inert `.example` files at their natural paths — neither creates an `app/` dir nor a live `deploy.yml`, so neither violates criterion #1.)
- [x] Create `templates/web/wrangler.jsonc` — Workers Static Assets config, `name` = `{{GUIDE_SLUG}}`, `assets.directory: "./dist"`, `preview_urls: true`, NO `not_found_handling` (single static page), NO custom domain. (Bootstrap substitutes the slug when copying to `app/wrangler.jsonc`.)
- [x] Create `templates/web/package.json` (private; `wrangler` devDependency `^4.x`) + `templates/web/package-lock.json` (generated via `npm install --package-lock-only` so NO throwaway `node_modules` is created); `templates/web/public/.gitkeep`. NOTE: package `name` is a static generic `guide-web-app` (NOT slug-substituted) — `{{GUIDE_SLUG}}` is not a valid npm package name and would make the lockfile invalid; the deployed worker name comes from `wrangler.jsonc`, not here.
- [x] Create `.github/workflows/deploy.yml.example` — generalized port of japan-guide's deploy.yml: `actions/checkout@v4` with `fetch-depth: 0`, `cloudflare/wrangler-action@v3`, `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` secrets, push→deploy / PR→versions-upload + preview-URL comment. NO japan/speedytuna values; worker name resolves from `app/wrangler.jsonc` at deploy time.
- [x] Create `verify_web.py` — port japan-guide's, but **derive the embed id from `guide.md`** (scan for `<div class="embed youtube" data-id="...">` and extract the id) rather than hardcoding japan's `E01x6ClIiuc`. Assert the derived id appears as an `<iframe>` in `app/dist/index.html` and as a `youtube.com/watch?v=<id>` link in `build/<slug>.html`. Skip cleanly (exit 0, message) when `style-screen.css` is absent OR when `guide.md` has no embed.
- [x] Grep the new files for japan-specific leakage (`japan-guide`, `speedytuna`, `E01x6ClIiuc`) — must be clean; use `{{GUIDE_SLUG}}` or values derived at runtime.

## Tests

- [x] `python verify_web.py` on the un-opted template skips cleanly (exit 0) — no `style-screen.css`, no `app/`.
- [x] `grep -rE "japan-guide|speedytuna|E01x6ClIiuc" templates/ .github/workflows/deploy.yml.example verify_web.py` returns nothing.
- [x] `templates/web/wrangler.jsonc` is valid JSONC (parses after comment strip).
- [x] The un-opted template still has NO `app/` dir (`! test -e app`).

## Verification

```bash
python verify_web.py                       # skips cleanly, exit 0
test ! -e app && echo "no app/ dir OK"     # criterion #1: un-opted template has no app/
grep -rE "japan-guide|speedytuna|E01x6ClIiuc" templates/ .github/workflows/deploy.yml.example verify_web.py || echo "grep-clean OK"
node -e "const fs=require('fs');JSON.parse(fs.readFileSync('templates/web/wrangler.jsonc','utf8').replace(/\/\/.*/g,''))" && echo "wrangler.jsonc valid"
make verify                                # still green (no SOURCE_FILES touched)
```

Also verify manually:
- `templates/web/package-lock.json` is committed but no `node_modules/` is tracked (Phase 2 ignores it).

## Exit Criteria

This phase is complete only when ALL of the following are true:
- [x] Every task above is checked off.
- [x] Opt-in assets staged under `templates/web/` (+ `deploy.yml.example`); the un-opted template has **no `app/` dir**; all grep-clean of japan values.
- [x] `verify_web.py` skips cleanly when web not enabled.
- [x] `make verify` still passes (plain commit).
- [x] Run the `cyw` skill — finds zero issues.
- [x] phases.md phase checkbox updated to `[x]`.

## Commit

No SOURCE_FILES touched — plain `git commit`:

```
Add opt-in web assets: templates/web scaffold, deploy.yml.example, verify_web.py
```
