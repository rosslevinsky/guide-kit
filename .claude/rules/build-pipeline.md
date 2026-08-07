---
paths:
  - "build.py"
  - "buildcore.py"
  - "render_pdf.py"
  - "Makefile"
  - "style.css"
  - "themes/**"
---

# How a guide is built, and why the pieces are split up

```
guide.md  --pandoc-->  HTML body  --transforms.py?-->  HTML'  --wrap-->  styled HTML
  --WeasyPrint-->  PDF  --qpdf-->  PDF (canonical)
                     ^
   themes/<theme>/print.css + style.css
```

Run `make` to build; the working render lands in `build/<slug>.pdf`. `make html` renders a
standalone HTML preview.

## The split is not tidiness

`build.py` is **only the CLI**: it parses flags and dispatches. `buildcore.py` is the
artifact-neutral pipeline — config and paths, the version stamp, the transforms hook, the
glyph-coverage gate, pandoc, the shared HTML wrapper. One `render_*.py` owns each output:
`render_pdf.py`, `render_site.py`, `render_slides.py`.

That separation exists because of a specific failure. Pipeline code used to live in
`build.py`, and `build.py` is a stamp input for **every** artifact — so a website-only
change re-staled every reference PDF in the family. Renderers are imported lazily, per
branch, so the isolation the structure claims is real at run time and not just on paper.

Putting shared pipeline code back into `build.py` reintroduces that, quietly.

## Builds are reproducible on purpose

The pipeline pins WeasyPrint's timestamp via `SOURCE_DATE_EPOCH` — midnight UTC of the
artifact's **authored** `[artifacts.<name>] date`, never a clock read and never a commit
time — then canonicalizes with `qpdf --deterministic-id --normalize-content=y`. Two builds
of identical committed source produce content-identical PDFs. Anything that introduces a
clock read or a git read into the render path breaks that.

## The version stamp

The PDF footer carries `YYYY-MM-DD · <sha256[:12]>`.

The date is the artifact's authored `[artifacts.<name>] date` in `guide.toml` — an *edition*
date, not a commit date. The hash covers that artifact's own dependency closure, so the
site's stamp and the PDF's move independently.

A ` · dirty` segment is appended when the working tree has uncommitted changes to that
artifact's inputs.

Why the render path reads no git history is in the kit's `README.md`.
