# Phase 5: Docs

_Status: complete_

## Goal

Document the opt-in web layer in README and CLAUDE.md — generalized (placeholdered), so a fork knows how to enable web, deploy it, and set up secrets.

## Entry Criteria

Before starting this phase, confirm:
- [x] Phase 4 committed, pushed, `make verify` green.
- [x] `bootstrap.py --with-web` works.

## Tasks

- [x] `README.md`: add a "Website deploy (Cloudflare)" section — generalized port of japan-guide's: how to enable (`bootstrap.py --with-web`), `make web`/`dev`/`deploy`, the Node ≥22 requirement, and the **Cloudflare API-token + account-ID secrets walkthrough** (dashboard steps, `gh secret set`, security notes, custom-domain binding). Use `<owner>/<repo>` and `{{GUIDE_SLUG}}` placeholders — NO japan/speedytuna specifics.
- [x] `README.md`: add the new make targets to the build list and the new files to the files table; frame web as opt-in (PDF stays default).
- [x] `CLAUDE.md`: add a "The website" section (opt-in, `make web`/`dev`/`deploy`, `style-screen.css` not a SOURCE_FILE, Node 22 note); add the `embed youtube` island to the allowed-HTML table; document the per-output transforms contract; note the hook is optional for PDF-only forks.
- [x] Grep the docs for japan-specific leakage; confirm clean.

## Tests

- [x] `grep -rE "japan-guide|speedytuna|japan\.speedytuna|E01x6ClIiuc" README.md CLAUDE.md` returns nothing.
- [x] Any workspace doc-link checker (if present) passes; internal anchors resolve. (No checker in this standalone repo; all 4 in-page anchor links verified to resolve.)

## Verification

```bash
grep -rE "japan-guide|speedytuna|E01x6ClIiuc" README.md CLAUDE.md || echo "docs grep-clean OK"
make verify                                # still green (no SOURCE_FILES touched)
```

Also verify manually:
- README "Website deploy" section reads correctly standalone — secrets steps are followable by someone with no japan-guide context.
- CLAUDE.md allowed-HTML table lists `embed youtube` with the per-output behavior.

## Exit Criteria

This phase is complete only when ALL of the following are true:
- [x] Every task above is checked off.
- [x] README + CLAUDE.md document the opt-in web layer, embed vocabulary, and generalized secrets walkthrough.
- [x] Docs grep-clean of japan values.
- [x] `make verify` still passes (plain commit).
- [x] Run the `cyw` skill — finds zero issues.
- [x] phases.md phase checkbox updated to `[x]`.

## Commit

No SOURCE_FILES touched — plain `git commit`:

```
Document opt-in web layer (README Website deploy + CLAUDE The website)
```
