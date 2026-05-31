# Phase 6: End-to-End Verification Gate

_Status: complete_

## Goal

Prove the whole opt-in path works end-to-end in a throwaway clone, and walk every success criterion in `plan.md`.

## Entry Criteria

Before starting this phase, confirm:
- [x] Phase 5 committed, pushed, `make verify` green.
- [x] All prior phases complete.

## Tasks

- [x] **PDF-only path (in-repo, safe):** confirm the un-opted template is clean — `make`, `make verify` pass; `python build.py --web` no-ops; **no `app/` dir exists** (`! test -e app`); `git status` clean.
- [x] **Web path (throwaway clone only — bootstrap self-deletes):** `git archive HEAD` → tmp dir; in the copy: run `bootstrap.py "Test" test-guide --with-web` (copies `templates/web/`→`app/`), **add a YouTube embed to `guide.md`**, then build the web output and confirm `app/dist/index.html` is nonzero with an `<iframe>`; run `verify_web.py` (PASSED, not skipped). The throwaway's web build was run via the repo's pixi env (build.py uses `__file__`-relative paths) to avoid provisioning a fresh pixi env in /tmp. `npm install` + `make dev` browser serve is the optional manual wrangler check (not run).
- [x] Walk all 10 success criteria from `plan.md` and record pass/fail for each. **All 10 PASS** (recorded in the close-out note below).
- [x] Final grep-clean across the whole template for japan leakage. **Clean** (zero hits outside `plans/`).

> **Phase 6 surfaced one fix (committed `3e5f7fa`):** the web path failed `verify_web.py` initially because `bootstrap --with-web` materialized `style-screen.css`/`app/`/`deploy.yml` but NOT `transforms.py` — so the embed island rendered as a raw `<div>`, no iframe. The plan's Phase 6 "must PASS" verification implies `--with-web` should activate the hook (the embed split is the web layer's worked example and lives solely in `transforms.py.example`). Fixed: `_materialize_web` now also copies `transforms.py.example` → `transforms.py` (guarded; won't clobber a user hook). README + CLAUDE.md updated. After the fix, `verify_web.py` PASSES end-to-end.
>
> **10 success criteria:** all PASS. #4's reference-PDF copy + download link verified by seeding a slug-named PDF in the throwaway; live `make dev`/`deploy` wrangler invocation (needs `npm install`) left as the documented optional manual check.

## Tests

- [x] All 10 `plan.md` success criteria pass.
- [x] `make`, `make verify`, `make web` (no-op) succeed on the PDF-only template.

## Verification

```bash
# In-repo (PDF-only) — must stay clean:
make && make verify && python build.py --web && git status --porcelain
echo "--- success criteria walk ---"   # tick each item from plan.md by hand

# Web path in a throwaway copy (make web / verify_web need NO npm — that's only for wrangler):
tmp=$(mktemp -d); git archive HEAD | tar -x -C "$tmp"
( cd "$tmp" && python bootstrap.py "Test" test-guide --with-web \
    # Add a YouTube embed so verify_web.py actually ASSERTS the split (else it skips):
    && printf '\n<div class="embed youtube" data-id="dQw4w9WgXcQ">demo</div>\n' >> guide.md \
    && make web \
    && test -s app/dist/index.html && python verify_web.py )   # must PASS, not skip
# Optional browser check (needs Node): ( cd "$tmp/app" && npm install && cd .. && make dev )

# Whole-template leak check:
grep -rE "japan-guide|speedytuna|E01x6ClIiuc" --include='*.py' --include='*.md' \
  --include='*.css' --include='*.toml' --include='*.yml*' --include='*.jsonc' . \
  | grep -v '^./plans/' || echo "template grep-clean OK"
```

Also verify manually:
- The throwaway site's embed plays in a browser (`make dev`), and the PDF download link resolves.

## Exit Criteria

This phase is complete only when ALL of the following are true:
- [x] Every task above is checked off.
- [x] All 10 `plan.md` success criteria confirmed pass.
- [x] PDF-only template still fully works; web path proven in a throwaway clone.
- [x] No japan-specific value leaks into the template (outside `plans/`).
- [x] Run the `cyw` skill — finds zero issues (one fix surfaced + applied: `transforms.py` activation).
- [x] phases.md phase checkbox updated to `[x]`.

## Commit

Verification-only — likely no code commit. If the walk surfaces fixes, commit them under their own message and note here. Otherwise update phases.md status to complete and (optionally) open the PR to `main`.
