# {{GUIDE_NAME}}

A single-document beginner-guide PDF, authored in Markdown (`guide.md`) and rendered to PDF via pandoc + WeasyPrint. Ships with a local `make verify` regression harness (page count + text content + zero-pixel diff against a committed `baseline.pdf`). CI runs build-smoke only on Ubuntu / macOS / Windows; local pre-push `make verify` is the real gate (see CLAUDE.md).

The built PDF (`{{GUIDE_SLUG}}.pdf`) is regenerated locally by `make`. The committed `baseline.pdf` is the verified reference render — the harness fails any future build that diverges from it.

## Files

| File | Purpose |
|------|---------|
| `guide.md` | The guide itself, in Markdown. Real Markdown with HTML islands only where Markdown can't express the styling. |
| `style.css` | All visual styling (page layout, fonts, callouts, exercise boxes, tables, ASCII diagrams). |
| `build.py` | The build script: pandoc → optional `transforms.post_pandoc_html` → WeasyPrint → `qpdf` canonicalize. Substitutes `__TITLE__` and `__VERSION__` placeholders in `style.css`. |
| `verify_pdf.py` | Three-check harness (page count, text diff, per-page pixel diff at zero tolerance). |
| `release.py` | Helper for `make release` — stages source files, commits, re-renders, copies to `baseline.pdf`, amends. |
| `baseline.pdf` | Committed reference render. Regenerate via `make baseline` after intentional content changes (or `make release` to do source + baseline + amend in one shot). |
| `transforms.py.example` | Hook template. Rename to `transforms.py` to activate per-guide HTML transforms. |
| `bootstrap.py` | One-shot rename-your-fork script. Run once after creating a repo from this template; deletes itself when done. |
| `.template-uninitialized` | Sentinel that suppresses `build.py`'s template-hygiene check while the template is still in its un-substituted state. `bootstrap.py` removes it. |
| `Makefile` | Convenience targets — thin wrappers around `pixi run`. |
| `pixi.toml` | All dependencies (pandoc, Python, WeasyPrint, poppler, Pillow, qpdf) and build tasks. |
| `CLAUDE.md` | Project conventions, gotchas, and per-guide notes. Read before editing. |
| `LICENSE` / `LICENSE-CONTENT` | Apache 2.0 for code, CC BY 4.0 for content. |

## Quick start

### 1. Install pixi

[pixi](https://pixi.sh) is a cross-platform package manager that handles every dependency this project needs (pandoc, Python, WeasyPrint, poppler, Pillow, qpdf) in a single isolated environment. No `brew`, no `apt`, no virtualenvs.

**macOS / Linux:**

```
curl -fsSL https://pixi.sh/install.sh | sh
```

See <https://pixi.sh/latest/installation/> for other install methods.

### 2. Install project dependencies

From this directory:

```
pixi install
```

### 3. Build

```
pixi run build       # PDF (or just `make`)
pixi run html        # standalone HTML preview (faster iteration)
```

Or, via the Makefile:

```
make                            # PDF (default)
make html                       # HTML preview
make verify                     # confirm the fresh build matches baseline.pdf
make baseline                   # overwrite baseline.pdf with the fresh build (USE DELIBERATELY)
make release MSG="..."          # stage source + render baseline + amend, in one commit (see Workflow below)
make clean                      # remove rendered PDF, HTML preview, verify-diff/
```

The PDF lands at `./{{GUIDE_SLUG}}.pdf` (regenerated; gitignored). The committed reference is `./baseline.pdf`. The HTML preview lands at `./{{GUIDE_SLUG}}.html` (gitignored).

## Workflow: editing content

For **intentional content changes** — anything that alters the rendered PDF:

```
1. Edit guide.md / style.css / build.py / transforms.py
2. make                          # render the new PDF
3. Open {{GUIDE_SLUG}}.pdf and eyeball it. Right? If not, fix and goto 2.
4. make release MSG="Your message"   # stage source, render baseline, amend, in one commit
```

`make release` is a thin wrapper around `release.py`. It refuses to run if the working tree has staged changes or modifications to files outside the version-stamp input list (`guide.md` / `style.css` / `build.py` / `transforms.py`) — commit those with plain `git commit` first.

The manual equivalent of step 4, if you'd rather drive it yourself:

```
git add <the source files you edited>
git commit -m "Your message"     # COMMIT SOURCE FIRST — this is load-bearing
make baseline                    # render again with a clean stamp; copy to baseline.pdf
git add baseline.pdf
git commit --amend --no-edit     # fold baseline.pdf into the source commit
```

Why amend? The version stamp in the PDF footer is derived from `git log` and `git status`. Rendering `baseline.pdf` BEFORE the source commit produces a footer with ` · dirty` and the *previous* commit's date — which will never match a future post-commit `make verify`. Committing source first makes the stamp stable; amend keeps source + baseline in one logical commit. `make release` enforces the order; doing it by hand requires you to.

For **doc-only changes** — anything outside the version-stamp input list (`SOURCE_FILES` in `build.py`: `guide.md` / `style.css` / `build.py` / `transforms.py`) — the rendered PDF is unaffected. Commit normally; no baseline refresh needed. This covers `README.md`, `CLAUDE.md`, `LICENSE*`, `Makefile`, `pixi.toml`, `pixi.lock`, `verify_pdf.py`, `release.py`, `bootstrap.py`, and `.github/workflows/`. `release.py` enforces this boundary — it refuses to run when modifications outside `SOURCE_FILES` are present, so a doc edit can never accidentally hitchhike into a release commit.

(One sneaky case: a `pixi.lock` update can drift rendering even though it's not a "source" file. That'll surface as a `make verify` failure on the next build — correct behavior. Pin tighter in `pixi.toml` if you want to narrow the window.)

## Verify harness

`make verify` runs `verify_pdf.py baseline.pdf {{GUIDE_SLUG}}.pdf`, which checks:

1. **Page count** via `pdfinfo` — fails on mismatch.
2. **Text content** via `pdftotext -layout` — fails with a first-50-lines unified-diff snippet.
3. **Per-page pixel diff** via `pdftoppm` + Pillow `ImageChops.difference` at zero tolerance — fails if any channel of any pixel differs on any page. On failure, per-page diff PNGs land in `verify-diff/page-NN.png` for visual inspection.

A green `make verify` is the contract that your latest build is content-identical to the committed baseline. A red `make verify` either means a real regression OR that you intentionally changed source without refreshing baseline (run the workflow above).

## Getting started from this template

After `gh repo create my-new-guide --template rosslevinsky/guide-template`, clone the new repo and run:

```
pixi install
pixi run python bootstrap.py "My Guide Title" my-guide-slug
```

The bootstrap script substitutes your title and slug into `build.py`, `pixi.toml`, `README.md`, and `CLAUDE.md`; removes this section from the README; and deletes itself (plus the `.template-uninitialized` sentinel that suppresses the template-hygiene check in `build.py`). Optional flags: `--author "..."`, `--description "..."`, `--keywords "kw1, kw2"`.

After bootstrap: write your `guide.md`, then `make release MSG="Initial content"` to land the first source + baseline commit in one go.

(If you'd rather edit the files by hand, delete `.template-uninitialized` and `bootstrap.py` yourself when you're done — `build.py` refuses to build while any `{{GUIDE_NAME}}` / `{{GUIDE_SLUG}}` / `<DESCRIBE YOUR GUIDE>` placeholders or the default `TITLE = "Guide Template"` / `OUTPUT_SLUG = "guide-template"` remain.)

## License

This repository is dual-licensed:

- **Code** (build scripts, CSS, configuration) — [Apache License 2.0](LICENSE).
- **Content** (`guide.md` and the rendered PDF) — [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-CONTENT).

You're free to share, adapt, and reuse the guide content for any purpose, including commercially, as long as you give appropriate credit and link to the CC BY 4.0 license.
