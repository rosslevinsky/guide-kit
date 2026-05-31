# Phase 3: Opt-in Assets (app/ scaffold, deploy.yml.example, verify_web.py)

_Status: pending_

## Goal

Add the inert, generalized opt-in files a fork will materialize: the `app/` Cloudflare scaffold, the example deploy workflow, and the per-output verifier — all placeholdered, none active until `--with-web`.

## Entry Criteria

Before starting this phase, confirm:
- [ ] Phase 2 committed, pushed, `make verify` green.
- [ ] `make web`/`dev`/`deploy` targets exist; CI re-gated and green.

## Tasks

- [ ] **Settle the storage layout** (open question from plan): recommend shipping the scaffold as committed source files that `bootstrap --with-web` copies/renames — `app/wrangler.jsonc`, `app/package.json`, `app/package-lock.json`, `app/public/.gitkeep`. (Decide: are these live `app/` files, or staged under e.g. `templates/web/`? Live `app/` is simplest but means the un-opted template carries `app/` — acceptable since `app/dist/` is gitignored and nothing runs it. Document the choice in the phase commit.)
- [ ] Create `app/wrangler.jsonc` — Workers Static Assets config, `name` = `{{GUIDE_SLUG}}`, `assets.directory: "./dist"`, `preview_urls: true`, NO `not_found_handling` (single static page), NO custom domain. (Bootstrap substitutes the slug.)
- [ ] Create `app/package.json` (private; `wrangler` devDependency `^4.x`) + `app/package-lock.json` (generate via `cd app && npm install`); `app/public/.gitkeep`.
- [ ] Create `.github/workflows/deploy.yml.example` — generalized port of japan-guide's deploy.yml: `actions/checkout@v4` with `fetch-depth: 0`, `cloudflare/wrangler-action@v3`, `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` secrets, push→deploy / PR→versions-upload + preview-URL comment. NO japan/speedytuna values; worker name resolves from `app/wrangler.jsonc`.
- [ ] Create `verify_web.py` — port japan-guide's: asserts `<iframe>` + embed id in `app/dist/index.html` and the watch-link in `build/<slug>.html`; skip cleanly (exit 0, message) when `style-screen.css` absent.
- [ ] Grep the new files for japan-specific leakage (`japan-guide`, `speedytuna`, `E01x6ClIiuc`) — must be clean; use `{{GUIDE_SLUG}}` or wrangler-derived values.

## Tests

- [ ] `python verify_web.py` on the un-opted template skips cleanly (exit 0).
- [ ] `grep -rE "japan-guide|speedytuna|E01x6ClIiuc" app/ .github/workflows/deploy.yml.example verify_web.py` returns nothing.
- [ ] `app/wrangler.jsonc` is valid JSONC (parses after comment strip).

## Verification

```bash
python verify_web.py                       # skips cleanly, exit 0
grep -rE "japan-guide|speedytuna|E01x6ClIiuc" app/ .github/workflows/deploy.yml.example verify_web.py || echo "grep-clean OK"
node -e "const fs=require('fs');JSON.parse(fs.readFileSync('app/wrangler.jsonc','utf8').replace(/\/\/.*/g,''))" && echo "wrangler.jsonc valid"
make verify                                # still green (no SOURCE_FILES touched)
```

Also verify manually:
- `app/dist/` and `node_modules/` are gitignored (from Phase 2) — `git status` shows neither after a `cd app && npm install`.

## Exit Criteria

This phase is complete only when ALL of the following are true:
- [ ] Every task above is checked off.
- [ ] Opt-in assets present, inert, and grep-clean of japan values.
- [ ] `verify_web.py` skips cleanly when web not enabled.
- [ ] `make verify` still passes (plain commit).
- [ ] Run the `cyw` skill — finds zero issues.
- [ ] phases.md phase checkbox updated to `[x]`.

## Commit

No SOURCE_FILES touched — plain `git commit`:

```
Add opt-in web assets: app/ scaffold, deploy.yml.example, verify_web.py
```
