# Phase 6: End-to-End Verification Gate

_Status: pending_

## Goal

Prove the whole opt-in path works end-to-end in a throwaway clone, and walk every success criterion in `plan.md`.

## Entry Criteria

Before starting this phase, confirm:
- [ ] Phase 5 committed, pushed, `make verify` green.
- [ ] All prior phases complete.

## Tasks

- [ ] **PDF-only path (in-repo, safe):** confirm the un-opted template is clean — `make`, `make verify` pass; `python build.py --web` no-ops; **no `app/` dir exists** (`! test -e app`); `git status` clean.
- [ ] **Web path (throwaway clone only — bootstrap self-deletes):** `git archive HEAD` → tmp dir; in the copy: run `bootstrap.py "Test" test-guide --with-web` (copies `templates/web/`→`app/`), **add a YouTube embed to `guide.md`**, then `make web` and confirm `app/dist/index.html` is nonzero with an `<iframe>`; run `python verify_web.py` (must PASS, not skip). `npm install` in `app/` + `make dev` (browser serve) is a separate, optional manual check — needed only for wrangler, not for the `make web` / `verify_web.py` assertion path.
- [ ] Walk all 10 success criteria from `plan.md` and record pass/fail for each.
- [ ] Final grep-clean across the whole template for japan leakage.

## Tests

- [ ] All 10 `plan.md` success criteria pass.
- [ ] `make`, `make verify`, `make web` (no-op) succeed on the PDF-only template.

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
- [ ] Every task above is checked off.
- [ ] All 10 `plan.md` success criteria confirmed pass.
- [ ] PDF-only template still fully works; web path proven in a throwaway clone.
- [ ] No japan-specific value leaks into the template (outside `plans/`).
- [ ] Run the `cyw` skill — finds zero issues.
- [ ] phases.md phase checkbox updated to `[x]`.

## Commit

Verification-only — likely no code commit. If the walk surfaces fixes, commit them under their own message and note here. Otherwise update phases.md status to complete and (optionally) open the PR to `main`.
