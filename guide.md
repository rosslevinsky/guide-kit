<div class="title-block">

# Guide Template

*A starter for single-document beginner-guide PDFs — exercising every styled element so the verify harness has surface area to check.*

</div>

# Welcome

This placeholder guide is shipped with `guide-template`. It exists for two reasons:

1. The build pipeline has something to render before you replace it with your own content.
2. Every styled element in `style.css` is exercised at least once, so the verify harness's per-page pixel diff catches any future regression to those rules.

Edit `guide.md` to write your own guide. Run `make` to render the PDF. Run `make verify` to confirm a rebuilt PDF matches the committed `baseline.pdf`.

## What this section is for

This is an `h2` heading. The verify harness will notice if its color, weight, or margin changes between renders.

### And this is an h3

Used for subsections within a section. Smaller than `h2`, same family.

You can use **bold**, *italic*, and `inline code` in paragraphs. Lists work too:

- Unordered bullet one
- Unordered bullet two with `code`
- Unordered bullet three with **bold**

And ordered lists:

1. First step
2. Second step
3. Third step

# Tables

Pipe tables get the template's table styling — blue header, alternating row tint, thin gray borders.

| Element | Source markup | Renders as |
|---------|---------------|------------|
| Heading | `# Title` | `<h1>` |
| Callout | `<div class="callout warn">` | warning box |
| Exercise | `<div class="exercise">` | green-bordered box |
| Diagram | `<pre class="diagram">` | monospace panel |

# Fenced code blocks

```
$ make
$ make verify
$ make baseline
```

Code blocks render in a light gray panel with `Courier`-family monospace.

# Blockquotes

> A blockquote renders with a left border and slightly muted italic text. Use it for pull-quotes, source attributions, or short asides that don't warrant a full callout.

# Callouts

The template knows three callout variants.

<div class="callout warn">

**Warning** Amber background, orange border, bold-orange "Warning" header. Use for genuinely dangerous operations.

</div>

<div class="callout tip">

**Tip** Green tint with a green left bar. Use for advisory content that isn't quite a warning.

</div>

<div class="callout accent">

A blue accent callout has no bold header — just a light-blue background with a blue left bar. Good for mental-model notes.

</div>

# Exercise boxes

Exercises render in a green-bordered box with the title strip on top.

<div class="exercise">

**Exercise 1 — Hello world**

Run `make` from this directory. Confirm `guide-template.pdf` appears at the repo root.

You should see this exact text rendered in the green box.

</div>

# ASCII diagrams

The `<pre class="diagram">` element renders ASCII art in a tan-bordered monospace panel, sized to its content.

<pre class="diagram">guide.md  --pandoc-->  HTML  --transforms?-->  HTML'  --WeasyPrint-->  PDF
                                                              |
                                                              v
                                                          qpdf canonicalize
                                                              |
                                                              v
                                                       guide-template.pdf
</pre>

<div class="page-break"></div>

# Section after a forced page break

The `<div class="page-break"></div>` element forces a page break before this section. The verify harness checks page count as well as content, so this forced break is exercised by the page-count check too.

## More content here

Any text you put on this page lives on its own physical page in the PDF, separated from the prior section by the forced break.

# How verification works

`make verify` runs `verify_pdf.py` against the committed `baseline.pdf`. Three checks at zero tolerance:

1. **Page count** via `pdfinfo` — fails if the PDFs disagree on page count.
2. **Text content** via `pdftotext -layout` — fails on any text difference, with a first-50-lines unified-diff snippet.
3. **Per-page pixel** via `pdftoppm` + ImageMagick `compare -metric AE` — fails if any pixel differs.

When verify fails, per-page diff PNGs land in `verify-diff/page-NN.png` so you can see what changed.

If you change source intentionally, the workflow is: edit → `make` → eyeball the PDF → `make baseline` → commit `baseline.pdf` together with the source change in **one** commit. Splitting them causes the version stamp to disagree between commits and triggers spurious verify failures.
