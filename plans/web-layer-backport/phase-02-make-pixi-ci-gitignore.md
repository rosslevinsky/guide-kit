# Phase 2: Make/Pixi Targets + CI Re-gate + Gitignore

_Status: complete_

## Goal

Add the `web` / `dev` / `deploy` Make targets and the `web` pixi task, and re-gate `verify.yml`'s web build-smoke so adding the shared `web` target doesn't turn CI red.

## Entry Criteria

Before starting this phase, confirm:
- [x] Phase 1 committed, pushed, `make verify` green.
- [x] `build.py --web` exists and no-ops cleanly without web assets.

## Tasks

- [x] `Makefile`: add `web:` (→ `pixi run web`), `dev:` and `deploy:` (each errors with a clear message if `app/` is absent, e.g. `@test -d app || (echo "web layer not enabled; run bootstrap.py --with-web"; exit 1)` then `cd app && npx wrangler dev`/`deploy`). Add the three to `.PHONY` and the `help` text. Mirror japan-guide's targets. (Divergence from japan-guide, justified: dev/deploy guard on `app/` first — the template's PDF-only forks have no `app/` — whereas japan-guide uses an unguarded `dev: web`. Guard-first also avoids `make web` creating `app/dist` and making a bare `-d app` check pass spuriously.)
- [x] `pixi.toml`: add `web = "python build.py --web"` to `[tasks]`.
- [x] `.gitignore`: add `app/dist/` and `node_modules/`.
- [x] **Re-gate `.github/workflows/verify.yml`'s web build-smoke step.** The current guard is `if make -n web` — which passes on EVERY fork once this phase adds the shared `web` target, then the `test -s app/dist/index.html` fails on PDF-only forks (no-op `make web` creates nothing). Re-gate on actual web *enablement* instead, e.g. `if [ -f style-screen.css ]; then make web && test -s app/dist/index.html; else echo "web layer not enabled; skipping"; fi`. This MUST land in this phase (same one that adds the `web` target) or CI breaks.

## Tests

- [x] `make web` on the un-opted template no-ops (exit 0, no `app/dist`).
- [x] `make dev` (or `make -n dev`) without `app/` errors clearly, non-zero.
- [x] `verify.yml` parses as valid YAML and its web-smoke step is gated on `style-screen.css` presence, not `make -n web`.

## Verification

```bash
make web                                  # no-op, exit 0
make dev 2>&1 | grep -qi "not enabled" && echo "dev guard OK"
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/verify.yml')); print('yaml OK')"
make verify                               # still green (no SOURCE_FILES touched)
```

Also verify manually:
- Simulate the CI re-gate locally: with no `style-screen.css`, the web-smoke branch takes the "skipping" path (doesn't run `test -s app/dist/index.html`).

## Exit Criteria

This phase is complete only when ALL of the following are true:
- [x] Every task above is checked off.
- [x] `make web`/`dev`/`deploy` exist; `web` no-ops, `dev`/`deploy` error clearly without `app/`.
- [x] `verify.yml` web-smoke is re-gated on web enablement; YAML valid.
- [x] `make verify` still passes (no SOURCE_FILES changed → this is a plain commit).
- [x] Run the `cyw` skill — finds zero issues.
- [x] phases.md phase checkbox updated to `[x]`.

## Commit

No SOURCE_FILES touched — plain `git commit`:

```
Add web/dev/deploy make targets + pixi task; re-gate CI web smoke
```
