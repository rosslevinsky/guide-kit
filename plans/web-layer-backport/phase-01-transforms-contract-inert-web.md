# Phase 1: Transforms Contract + Inert `--web`

_Status: pending_

## Goal

Port japan-guide's two-entry transforms contract and a `build.py --web` target that gracefully no-ops when no web assets are present — so the PDF flow is unchanged and web is inert until opted in.

## Entry Criteria

Before starting this phase, confirm:
- [ ] On branch `web-layer-backport`, working tree clean, `make verify` green.
- [ ] `build.py` already has the merged license/colophon constants (`COPYRIGHT`, `LICENSE_*`, `_pdf_colophon()`) — this phase REUSES them, does not re-add.

## Tasks

- [ ] Replace `_apply_transforms_hook(html_body)` with the per-output pair from japan-guide:
  - `_load_transforms()` — import `transforms.py` if present, else return None.
  - `_apply_transforms(html_body, target)` — prefer `post_pandoc_html_for_<target>`, fall back to single-entry `post_pandoc_html`, else identity.
- [ ] **Update the `render_html()` call site (currently build.py:238) to `body = _apply_transforms(_pandoc_body(), "pdf") + _pdf_colophon()`** — PRESERVE the `+ _pdf_colophon()` so the merged colophon is not regressed.
- [ ] Add helpers `_pandoc_body()` and `_wrap_html(body, css)` (factor the pandoc call + HTML shell out of `render_html`, matching japan-guide).
- [ ] Add `render_web_html()` and `build_web()` + path constants `STYLE_SCREEN = ROOT / "style-screen.css"` and `WEB_DIR = ROOT / "app" / "dist"`.
- [ ] **Add the no-asset guard** (japan-guide's `build_web` lacks one): at the top of `build_web()`, if `STYLE_SCREEN` does not exist, print a clear "web layer not enabled — run `bootstrap.py --with-web` to enable it" message and `return` (exit 0, create nothing).
- [ ] Add `--web` to `main()`'s argparse as a mutually-exclusive option alongside `--html-preview`; dispatch to `build_web()`.
- [ ] Create `style-screen.css.example` — the generic screen stylesheet starter (port japan-guide's `style-screen.css`, keep `__TITLE__`/`__VERSION__` placeholders, no japan-specific content).
- [ ] Refactor `transforms.py.example` to demonstrate the per-output split (`post_pandoc_html_for_pdf` / `_for_web`) with the YouTube embed as the worked example, plus a note that PDF-only forks can keep the single-entry `post_pandoc_html`.

## Tests

_No pytest suite; verification is command-based (project convention)._

- [ ] `python build.py --web` on the un-opted template (no `style-screen.css`) exits 0 with the "web layer not enabled" message and creates no `app/dist`.
- [ ] `make` + `make verify` still produce the PDF and pass (colophon intact, page count unchanged).

## Verification

```bash
python build.py --web        # graceful no-op, exit 0, NO app/dist created
test ! -e app/dist && echo "no app/dist OK"

# Commit ordering — release.py REJECTS a tree with non-SOURCE_FILES changes,
# so plain-commit the non-source files FIRST, then release the source file:
git add style-screen.css.example transforms.py.example
git commit -m "Add web screen-CSS starter + per-output transforms example"

# build.py is a SOURCE_FILE → release.py re-renders + re-baselines guide-template.pdf:
pixi run python release.py -m "Add two-entry transforms contract + inert build.py --web"
make verify                  # 4/4, text identical, zero pixel diff
```

Also verify manually:
- The PDF colophon still renders (the `+ _pdf_colophon()` was preserved): `pixi run pdftotext guide-template.pdf - | grep -c "Creative Commons"` ≥ 1.

## Exit Criteria

This phase is complete only when ALL of the following are true:
- [ ] Every task above is checked off.
- [ ] `python build.py --web` no-ops cleanly (exit 0, no `app/dist`) on the un-opted template.
- [ ] `make verify` passes against the re-baselined `guide-template.pdf`; colophon intact.
- [ ] Bare `make` still builds the PDF as before.
- [ ] Run the `cyw` skill — finds zero issues.
- [ ] phases.md phase checkbox updated to `[x]`.

## Commit

Two commits, in order (release.py rejects a tree with non-source changes):

1. Plain commit — `style-screen.css.example`, `transforms.py.example`:
   ```
   Add web screen-CSS starter + per-output transforms example
   ```
2. `release.py` for the SOURCE_FILE (`build.py`) — folds the re-baselined PDF in:
   ```
   Add two-entry transforms contract + inert build.py --web
   ```
