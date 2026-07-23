<div class="title-block">

# Guide Template

*A starter for single-document beginner-guide PDFs — exercising every styled element so the stylesheet has surface area to eyeball.*

</div>

# Welcome

This placeholder guide is shipped with `guide-template`. It exists for two reasons:

1. The build pipeline has something to render before you replace it with your own content.
2. Every styled element in `style.css` is exercised at least once, so a styling change is easy to spot when you eyeball the rendered PDF.

Edit `guide.md` to write your own guide. Run `make` to render the PDF (output lands at `build/<slug>.pdf`). Run `make verify` to confirm the committed reference PDF (`<slug>.pdf` at the repo root) is up to date with the source — a fast, platform-independent staleness check that does no rendering.

## What this section is for

This is an `h2` heading. If you change its color, weight, or margin, you'll see it when you eyeball the render; the `make verify-render` canary flags a resulting page-count or text shift.

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

The `<div class="page-break"></div>` element forces a page break before this section. The `make verify-render` canary checks page count, so this forced break is exercised by that check too.

## More content here

Any text you put on this page lives on its own physical page in the PDF, separated from the prior section by the forced break.

# How verification works

There are two commands, and they answer different questions:

- **`make verify`** — the staleness check, and the one CI runs. It compares the content hash embedded in the committed reference PDF's footer stamp against a freshly computed hash over the source files, using a single `pdftotext` call. No build, no rendering, no platform sensitivity — milliseconds, and correct on any machine. A mismatch means someone edited source and did not re-run `make release`, so the repo ships Markdown and a PDF that disagree. It names the stale file.
- **`make verify-render`** — a secondary canary for the canonical host only, never wired into CI. It builds a fresh PDF and compares page count plus `pdftotext` output (with the version-stamp line excluded) against the committed reference. Because font substitution shifts line wrapping across platforms, this is meaningful only on the host the reference was rendered on; its one genuine catch is environmental drift, such as a dependency update that changes layout with no source change.

If you change source intentionally, the workflow is: edit → `make` → eyeball the PDF → `make release MSG="..."` to land source + refreshed reference in one commit. (Or the manual dance: `git commit` source first, then `make baseline`, then `git commit --amend` to fold the refreshed reference PDF in. Doing it in the other order produces a dirty-stamp PDF that future verify runs will reject.)
