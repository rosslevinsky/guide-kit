---
paths:
  - "guide.md"
  - "render_slides.py"
  - "style-slides.css"
---

# The slide deck (opt-in)


`[outputs] slides = true` adds a third output: a 16:9 PDF deck at
`build/<slug>-slides.pdf`, built by `make slides`. Off by default, and a no-op with a notice
when off.

**The deck is a SELECTION, not a mirror of the guide.** A 34-chapter guide rendered
one-slide-per-heading is a 200-slide deck nobody presents, so nothing is projected unless it
is marked. Wrap a region in a `::: slide` fenced div and only that region becomes a slide:

```markdown
::: slide
## What this template gives you

- One Markdown source, three outputs
:::
```

`[slides] source` chooses where the deck comes from — `auto` (the default: use `[slides] file`
if it exists, else project from `guide.md`), `guide`, or `file`. Explicit `guide` does **not**
fall back to a deck file that happens to exist, and an explicit-but-missing `file` is a named
refusal rather than a quiet fall back to projection — rendering a different source under the
requested name is worse than stopping.

`make slides-coverage` reports which chapters have no slide. It is a **report and always exits
0**: coverage was never the goal, and a gate that failed the build on an uncovered chapter
would just get switched off. It counts chapters from the pandoc AST, not by grepping `##` —
`git-guide` has zero `##` headings and a literal-`##` count would report "0 of 0" for 34
chapters.

Two things that look like details and are not:

- **The page is 254mm × 142.875mm.** That is 16:9 as arithmetic. The 143mm someone writes when
  they round gives 1.7762 against 1.7778 — visibly letterboxed on a projector and invisible in
  review, so the test asserts the ratio rather than matching the CSS text.
- **The page keeps a 6mm bottom margin** purely so the version stamp has somewhere to live.
  WeasyPrint drops every `@bottom-*` margin box when the page margin is `0`, so the obvious
  full-bleed `margin: 0` produced a deck carrying no stamp at all — which `verify --staleness`
  correctly refuses, since freshness cannot be established from a file that does not say what
  built it. The strip comes out of the content area; the sheet stays exactly 16:9.

**The deck HAS a committed reference — `<slug>-slides.pdf` at the repo root — and gaining one
was a change of fact, not of opinion.** It could not have one while `baseline.yml` refreshed
the PDF and nothing else: the deck shares `_COMMON_FILES` with the PDF, so any `buildcore` or
`kitconfig` edit stales both, and a refresher that only knew about the PDF would have left the
deck permanently red. `baseline.py --artifact` plus a `baseline.yml` that loops over every
artifact with a reference is what made it safe, and both landed first.

So `ArtifactSpec.reference` is `"<slug>-slides.pdf"` for slides, staleness IS asked of it, and
`make verify` reports the deck by its own filename. The kit's
`tests/test_slides_source_resolution.py`
pins both halves: `test_the_deck_has_a_committed_reference` and
`test_the_refresh_path_that_makes_that_safe_exists`, the second of which fails if
`baseline.yml` stops refreshing per artifact — because that is the precondition, and without
it the reference becomes a permanently red `verify`.

**The site stays `reference = None`, and for a different, permanent reason:** a site is
deployed rather than blessed into the repo, so there are no committed bytes for staleness to
be a question about.

**One slide is one page.** The renderer emits `break-after: page` / `break-inside: avoid` on
`.slide` alongside the `@page` geometry — kit-emitted, not left to `style-slides.css`, which
is target-owned and would therefore be missing the rule in every new guide. The deck also
gets a bundled-family floor (`--body-font`, `--head-font`, `--mono-font`) from the same place,
so a guide that empties its slides stylesheet still renders in bundled faces rather than
falling through to a generic `serif` that names no bundled family at all.

A deck from a separate `[slides] file` is grouped into slides on the way in: its `::: slide`
fences if it has them, otherwise one slide per top-level heading. Without that grouping a file
deck carried no `.slide` at all, so every rule above silently did nothing to it.
