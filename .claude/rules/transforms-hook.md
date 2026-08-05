---
paths:
  - "transforms.py"
---

# The transforms hook (per-output)


If `transforms.py` exists next to `build.py`, the pipeline calls one entry point between pandoc
and the renderer, chosen by target: `post_pandoc_html_for_pdf` / `post_pandoc_html_for_web`, with
a single-entry `post_pandoc_html` fallback. `transforms.py` is always a `SOURCE_FILES` entry — a
missing file contributes no bytes — so **creating** it shifts the version stamp (refresh the
reference PDF afterward). Activate it only if the guide needs a substantive transform (the worked
example is the YouTube-embed split).
