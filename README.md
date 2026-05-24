# {{GUIDE_NAME}}

A single-document beginner-guide PDF, authored in Markdown (`guide.md`) and rendered to PDF via pandoc + WeasyPrint. Ships with a content-identicalness regression harness (`make verify`) that catches rendering regressions to zero-pixel tolerance.

The built PDF (`{{GUIDE_SLUG}}.pdf`) is regenerated locally by `make`. The committed `baseline.pdf` is the verified reference render — the harness fails any future build that diverges from it.

## Files

| File | Purpose |
|------|---------|
| `guide.md` | The guide itself, in Markdown. Real Markdown with HTML islands only where Markdown can't express the styling. |
| `style.css` | All visual styling (page layout, fonts, callouts, exercise boxes, tables, ASCII diagrams). |
| `build.py` | The build script: pandoc → optional `transforms.post_pandoc_html` → WeasyPrint → `qpdf` canonicalize. Substitutes `__TITLE__` and `__VERSION__` placeholders in `style.css`. |
| `verify_pdf.py` | Three-check harness (page count, text diff, per-page pixel diff at zero tolerance). |
| `baseline.pdf` | Committed reference render. Regenerate via `make baseline` after intentional content changes. |
| `transforms.py.example` | Hook template. Rename to `transforms.py` to activate per-guide HTML transforms. |
| `Makefile` | Convenience targets — thin wrappers around `pixi run`. |
| `pixi.toml` | All dependencies (pandoc, Python, WeasyPrint, poppler, imagemagick, qpdf) and build tasks. |
| `CLAUDE.md` | Project conventions, gotchas, and per-guide notes. Read before editing. |
| `LICENSE` / `LICENSE-CONTENT` | Apache 2.0 for code, CC BY 4.0 for content. |

## Quick start

### 1. Install pixi

[pixi](https://pixi.sh) is a cross-platform package manager that handles every dependency this project needs (pandoc, Python, WeasyPrint, poppler, ImageMagick, qpdf) in a single isolated environment. No `brew`, no `apt`, no virtualenvs.

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
make                 # PDF (default)
make html            # HTML preview
make verify          # confirm the fresh build matches baseline.pdf
make baseline        # overwrite baseline.pdf with the fresh build (USE DELIBERATELY)
make clean           # remove rendered PDF, HTML preview, verify-diff/
```

The PDF lands at `./{{GUIDE_SLUG}}.pdf` (regenerated; gitignored). The committed reference is `./baseline.pdf`. The HTML preview lands at `./{{GUIDE_SLUG}}.html` (gitignored).

## Workflow: editing content

For **intentional content changes** — anything that alters the rendered PDF — the workflow is precise. Out of order it produces spurious `make verify` failures across commits.

```
1. Edit guide.md / style.css / build.py / transforms.py
2. make                          # render the new PDF
3. Open {{GUIDE_SLUG}}.pdf and eyeball it. Right? If not, fix and goto 2.
4. git add <the source files you edited>
5. git commit -m "Your message"  # COMMIT SOURCE FIRST — this is load-bearing
6. make baseline                 # render again; cp to baseline.pdf (clean stamp)
7. git add baseline.pdf
8. git commit --amend --no-edit  # fold baseline.pdf into the source commit
```

Why amend? The version stamp in the PDF footer is derived from `git log` and `git status`. Rendering `baseline.pdf` BEFORE the source commit produces a footer with ` · dirty` and the *previous* commit's date — which will never match a future post-commit `make verify`. Committing source first makes the stamp stable; amend keeps source + baseline in one logical commit.

For **doc-only changes** (`README.md`, `CLAUDE.md`) — those files are NOT in the version-stamp input list, so the rendered PDF is unaffected. Commit them normally; no baseline refresh needed.

## Verify harness

`make verify` runs `verify_pdf.py baseline.pdf {{GUIDE_SLUG}}.pdf`, which checks:

1. **Page count** via `pdfinfo` — fails on mismatch.
2. **Text content** via `pdftotext -layout` — fails with a first-50-lines unified-diff snippet.
3. **Per-page pixel diff** via `pdftoppm` + ImageMagick `compare -metric AE -fuzz 0%` — fails if any pixel differs on any page. On failure, per-page diff PNGs land in `verify-diff/page-NN.png` for visual inspection.

A green `make verify` is the contract that your latest build is content-identical to the committed baseline. A red `make verify` either means a real regression OR that you intentionally changed source without refreshing baseline (run the workflow above).

## Getting started from this template

If you just created a new repo via `gh repo create my-new-guide --template rosslevinsky/guide-template`, here's the rename-your-fork checklist. Five files to edit:

1. **`build.py`** — change the constants at the top:
   - `TITLE = "Your Guide Name"`
   - `OUTPUT_SLUG = "your-guide-slug"` (drives the PDF filename: `{OUTPUT_SLUG}.pdf`)
   - `AUTHOR = "..."`, `DESCRIPTION = "..."`, `KEYWORDS = "..."` (PDF metadata)
2. **`Makefile`** — change `OUTPUT_SLUG := guide-template` at the top to match `OUTPUT_SLUG` in `build.py`. They must agree, otherwise `make verify` and `make baseline` look for the wrong filename and fail.
3. **`pixi.toml`** — change `name` and `description`.
4. **`README.md`** — replace `{{GUIDE_NAME}}` and `{{GUIDE_SLUG}}` throughout (e.g. with `sed -i '' 's/{{GUIDE_NAME}}/Your Guide Name/g; s/{{GUIDE_SLUG}}/your-guide-slug/g' README.md`).
5. **`CLAUDE.md`** — same `{{GUIDE_NAME}}` / `{{GUIDE_SLUG}}` substitutions, plus fill in the `<DESCRIBE YOUR GUIDE>` placeholder under "What this is" and any other guide-specific conventions.

After renaming: write your `guide.md`, run `make`, eyeball the PDF, then follow the amend workflow above to land your first content commit + baseline.

## License

This repository is dual-licensed:

- **Code** (build scripts, CSS, configuration) — [Apache License 2.0](LICENSE).
- **Content** (`guide.md` and the rendered PDF) — [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-CONTENT).

You're free to share, adapt, and reuse the guide content for any purpose, including commercially, as long as you give appropriate credit and link to the CC BY 4.0 license.
