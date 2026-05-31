# Phase 4: bootstrap `--with-web`

_Status: pending_

## Goal

Wire the opt-in into initialization: `bootstrap.py --with-web` materializes the screen CSS, `app/` scaffold (slug-substituted), and live `deploy.yml`; without the flag the fork stays PDF-only.

## Entry Criteria

Before starting this phase, confirm:
- [ ] Phase 3 committed, pushed, `make verify` green.
- [ ] The opt-in assets exist (`style-screen.css.example`, `templates/web/` scaffold, `deploy.yml.example`).

## Tasks

- [ ] **GUARD: never run `bootstrap.py` in the template repo itself** — it ends with `SENTINEL.unlink()` + `Path(__file__).unlink()` (self-deletes + removes `.template-uninitialized`). All verification uses a throwaway copy (see Verification).
- [ ] Add `--with-web` flag to `bootstrap.py`'s argparse.
- [ ] Implement web materialization, run BEFORE the self-delete / sentinel-removal block, fail-safe (leave bootstrap in place on error):
  - copy `style-screen.css.example` → `style-screen.css`;
  - copy `templates/web/` → `app/` (i.e. `app/wrangler.jsonc`, `app/package.json`, `app/package-lock.json`, `app/public/.gitkeep`), substituting `{{GUIDE_SLUG}}` → slug in `app/wrangler.jsonc` (+ `app/package.json` name if templated);
  - copy `.github/workflows/deploy.yml.example` → `.github/workflows/deploy.yml`.
- [ ] Keep the no-flag path byte-for-byte as today (PDF-only: none of the above appear).
- [ ] Update `bootstrap.py` docstring + `--help` to document `--with-web`.
- [ ] NOTE: `templates/web/` is the staging source — after `--with-web` copies it into `app/`, decide whether to also remove `templates/web/` from the materialized fork (optional cleanup; not required for correctness since it's harmless and `app/dist/` is what gets served).

## Tests

- [ ] `--with-web` in a throwaway copy materializes `style-screen.css`, `app/wrangler.jsonc` (slug-substituted), and `deploy.yml`.
- [ ] No-flag run in a throwaway copy leaves the fork PDF-only (no `app/`, no `deploy.yml`, no `style-screen.css`).
- [ ] The template repo's own `bootstrap.py` and `.template-uninitialized` are untouched by all testing.

## Verification

```bash
# bootstrap.py is NON-SOURCE → commit it FIRST, then test the committed state in a
# throwaway copy. (git archive snapshots HEAD, so the new --with-web code must be
# committed before archiving, or the archive won't contain it.)
git add bootstrap.py && git commit -m "Add bootstrap --with-web flag"

tmp=$(mktemp -d); git archive HEAD | tar -x -C "$tmp"
( cd "$tmp" && python bootstrap.py "Test Guide" test-guide --with-web \
    && ls app/wrangler.jsonc style-screen.css .github/workflows/deploy.yml \
    && grep -q "test-guide" app/wrangler.jsonc && echo "with-web OK (slug substituted)" )

tmp2=$(mktemp -d); git archive HEAD | tar -x -C "$tmp2"
( cd "$tmp2" && python bootstrap.py "Test Guide" test-guide \
    && ! test -e app && ! test -e style-screen.css \
    && ! test -e .github/workflows/deploy.yml && echo "no-flag stays PDF-only OK (no app/)" )

# repo untouched:
test -f bootstrap.py && test -f .template-uninitialized && echo "template repo intact"
make verify                                # still green (no SOURCE_FILES touched)
```

Also verify manually:
- The materialized `deploy.yml` (in the throwaway) is a valid workflow (YAML parses).

## Exit Criteria

This phase is complete only when ALL of the following are true:
- [ ] Every task above is checked off.
- [ ] `--with-web` materializes the web layer (slug-substituted) in a throwaway copy; no-flag path stays PDF-only.
- [ ] The template repo's `bootstrap.py` + `.template-uninitialized` are intact (never run in-repo).
- [ ] `make verify` still passes (plain commit).
- [ ] Run the `cyw` skill — finds zero issues.
- [ ] phases.md phase checkbox updated to `[x]`.

## Commit

No SOURCE_FILES touched — plain `git commit` (the `bootstrap.py` commit in Verification IS this phase's commit):

```
Add bootstrap --with-web flag
```
