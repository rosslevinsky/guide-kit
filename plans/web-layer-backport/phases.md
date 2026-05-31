# Phases: Web-layer backport into guide-template (opt-in)

_Execution tracker for [`plan.md`](./plan.md)_

## Status

| Field | Value |
|---|---|
| Phase | Phase 1 of 6 — Transforms Contract + Inert `--web` |
| State | Ready to execute |
| Blocker | None |
| Last updated | 2026-05-31 |

## Phases

- [ ] [Phase 1: Transforms Contract + Inert `--web`](./phase-01-transforms-contract-inert-web.md)
- [ ] [Phase 2: Make/Pixi Targets + CI Re-gate + Gitignore](./phase-02-make-pixi-ci-gitignore.md)
- [ ] [Phase 3: Opt-in Assets (app/ scaffold, deploy.yml.example, verify_web.py)](./phase-03-opt-in-assets.md)
- [ ] [Phase 4: bootstrap `--with-web`](./phase-04-bootstrap-with-web.md)
- [ ] [Phase 5: Docs](./phase-05-docs.md)
- [ ] [Phase 6: End-to-End Verification Gate](./phase-06-e2e-verification-gate.md)

## Notes

- **No pytest suite.** Verification is command-based: `make` / `make verify` / `make web` no-op / `verify_web.py` / CI build-smoke.
- **Commit discipline.** Phase 1 touches `build.py` (a SOURCE_FILE) → two commits: plain-commit the `.example` non-source files FIRST, then `make release`/`release.py` for `build.py` (release.py rejects a tree with out-of-scope changes). Phases 2–5 touch only non-SOURCE_FILES → plain `git commit`. Phase 6 is verification-only.
- **Never run `bootstrap.py` in the template repo** — it self-deletes and removes `.template-uninitialized`. Phases 4 and 6 test it only in a throwaway `git archive HEAD` copy (commit bootstrap first so the archive contains the new code).
- **CI re-gate is sequencing-critical** — `verify.yml`'s web-smoke must be re-gated on `style-screen.css` presence in the SAME phase that adds the shared `web` target (Phase 2), or CI goes red on PDF-only forks.
- **PDF-only flow is sacrosanct** — every phase keeps `make` + `make verify` green on the un-opted template.
