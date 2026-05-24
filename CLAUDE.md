# Project notes for Claude

> _This CLAUDE.md is a minimal-viable skeleton. The 9 full sections (What this is, Build pipeline, Markdown vs. HTML conventions, Version stamp, Verify harness, Transforms hook, Critical gotchas, Tone, After editing) land in phase 5._

## What this is

<DESCRIBE YOUR GUIDE>

A single-document Markdown → PDF project. Source in `guide.md`; styling in `style.css`; pipeline in `build.py`.

## Build pipeline

```
guide.md  --pandoc-->  HTML body  --wrap-->  styled HTML  --WeasyPrint-->  PDF
                                       ^
                                  style.css
```

Run `make` to build. Run `make html` for a fast HTML preview without the PDF render.

## After editing

Run `make` and visually check the rendered PDF. (Once the verify harness lands in phase 4: also run `make verify` for no-change edits or `make baseline && git add baseline.pdf <source files> && git commit` for intentional content changes.)
