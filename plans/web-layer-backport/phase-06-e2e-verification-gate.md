# Phase 6: End-to-End Verification Gate

_Status: pending_

## Goal

Prove the whole opt-in path works end-to-end in a throwaway clone, and walk every success criterion in `plan.md`.

## Entry Criteria

Before starting this phase, confirm:
- [ ] Phase 5 committed, pushed, `make verify` green.
- [ ] All prior phases complete.

## Tasks

- [ ] **PDF-only path (in-repo, safe):** confirm the un-opted template is clean — `make`, `make verify` pass; `python build.py --web` no-ops; no `app/`-driven behavior; `git status` clean.
- [ ] **Web path (throwaway clone only — bootstrap self-deletes):** `git archive HEAD` → tmp dir; in the copy run `bootstrap.py "Test" test-guide --with-web`, then `cd app && npm install`, `make web` (from copy root), confirm `app/dist/index.html` is nonzero and contains an `<iframe>` once a YouTube embed is added to that copy's `guide.md`; run `python verify_web.py` (passes); `make dev` serves locally (manual, optional).
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

# Web path in a throwaway copy:
tmp=$(mktemp -d); git archive HEAD | tar -x -C "$tmp"
( cd "$tmp" && python bootstrap.py "Test" test-guide --with-web \
    && cd app && npm install && cd .. && make web \
    && test -s app/dist/index.html && python verify_web.py )

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
