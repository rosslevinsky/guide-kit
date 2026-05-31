# Plan: web-layer backport into guide-template

## Status

| Field | Value |
|---|---|
| State | Planning |
| Branch | `web-layer-backport` |
| Source of truth | `japan-guide` (the dual-output pattern proven there) |
| Last updated | 2026-05-31 |

## Goal

Graduate the dual-output (website + PDF) machinery from `japan-guide` into
`guide-template`, so a new fork can produce a Cloudflare-deployed website
alongside its PDF — **without forcing the web layer on PDF-only guides**.

## The load-bearing design decision: web is OPT-IN

The template's identity is "the committed PDF at the repo root IS the
deliverable," and it was extracted from three PDF-only guides. The web layer
also drags in a new toolchain (Node ≥22 + npm + wrangler) that PDF-only forks
must not inherit. Therefore:

- **PDF stays the default.** `make`, `make verify`, `make release`, and the
  whole existing flow are untouched for a fork that never touches web.
- **Web activates by presence, not by default.** `build.py --web` exists in
  the template but is inert until a fork opts in by copying the web assets into
  place (screen CSS + `app/` scaffold). No `app/` dir, no `style-screen.css` →
  `make web` prints a friendly "web layer not enabled" message and exits 0.
- **`transforms.py` stays optional.** The two-entry contract
  (`post_pandoc_html_for_pdf` / `_for_web`, with single-entry `post_pandoc_html`
  fallback) is supported by `build.py`, but the template still ships only
  `transforms.py.example`. A PDF-only fork needs no transforms at all.
- **`deploy.yml` ships disabled-by-default.** It must not run (and fail) on a
  fork that has no Cloudflare secrets. Options to decide in implementation:
  ship it as `deploy.yml.example`, or gate it on a repo variable / the presence
  of `app/`. Leaning toward `.example` (mirrors `transforms.py.example`).

This mirrors how `transforms.py` is already opt-in: the capability is present
and documented; the fork chooses to turn it on.

## What graduates (from japan-guide)

| Piece | Template form |
|---|---|
| Two-entry transforms contract in `build.py` | Always present (back-compatible: falls back to `post_pandoc_html`, then identity) |
| `build.py --web` target + `render_web_html()` + `build_web()` | Present but inert without web assets |
| `style-screen.css` | Ships as `style-screen.css.example` (per-guide content; generic convention) |
| `Makefile` `web` / `dev` / `deploy` targets | Present; `web` no-ops without assets; `dev`/`deploy` require `app/` |
| `pixi.toml` `web` task | Present |
| `verify.yml` web smoke | Already guarded with `make -n web` (landed in the CI backport PR) |
| `app/wrangler.jsonc`, `app/package.json` (+ lockfile), `app/public/` | Ship as an `app/` scaffold the fork copies/renames, OR documented in CONTRIBUTING; decide in impl |
| `.github/workflows/deploy.yml` | Ships as `deploy.yml.example` (opt-in) |
| `verify_web.py` | Ships as-is (no-op / skip when web not enabled) |
| `.gitignore`: `app/dist/`, `node_modules/` | Always present (harmless on PDF-only forks) |
| Embed vocabulary (`<div class="embed youtube">`) | Documented in CLAUDE.md as an optional island the web transform handles |
| Docs: README "Website deploy", CLAUDE "The website", deploy-secrets walkthrough | Added, **generalized** with `{{GUIDE_SLUG}}` placeholders (no japan/speedytuna specifics) |

## What must NOT leak from japan-guide

- The slug `japan-guide`, domain `japan.speedytuna.com`, the `speedytuna`
  Cloudflare account/worker name, the `E01x6ClIiuc` embed id, the CI secrets.
- All per-fork values use the template's existing placeholder convention
  (`{{GUIDE_NAME}}` / `{{GUIDE_SLUG}}`) and/or are set by `bootstrap.py`.

## bootstrap.py

`bootstrap.py` should optionally enable the web layer — e.g. a `--with-web`
flag that copies `style-screen.css.example` → `style-screen.css`, the `app/`
scaffold into place, and `deploy.yml.example` → `deploy.yml`, substituting the
slug. Without the flag, the fork is PDF-only and none of those files exist.
(Exact mechanism TBD in implementation.)

## Proposed phasing (each independently committable, PDF flow never broken)

1. **Transforms contract + `--web` (inert).** Port the two-entry contract and
   `build.py --web` so it runs but no-ops without web assets. `make`/`verify`
   unchanged. Ship `style-screen.css.example`.
2. **Makefile/pixi targets + `.gitignore`.** `web`/`dev`/`deploy` targets,
   `web` pixi task, ignore `app/dist/` + `node_modules/`. `dev`/`deploy` error
   clearly if `app/` absent.
3. **`app/` scaffold + `deploy.yml.example` + `verify_web.py`.** The opt-in
   files a fork copies in. Generalized, placeholdered.
4. **bootstrap `--with-web`.** Wire the opt-in into initialization.
5. **Docs.** README "Website deploy" (generalized secrets walkthrough),
   CLAUDE "The website" + embed vocabulary, CONTRIBUTING note.

## Verification per phase

- After every phase: `make` + `make verify` still pass on the (PDF-only)
  template itself — the template ships PDF-only, so web stays inert here.
- A manual end-to-end web test happens in a throwaway fork (or by temporarily
  enabling web in the template), not in the committed template state.

## Open questions (resolve before/while implementing)

- `app/` scaffold: ship committed (inert) vs. `.example` vs. bootstrap-copied?
- `deploy.yml`: `.example` vs. gated-in-place?
- Does the template grow a `CONTRIBUTING.md` for the web deploy flow, or fold
  it into README?

---

_This is the starting plan for #3 (web-layer backport). Implementation not yet begun._
