---
paths:
  - "guide.md"
---

# Markdown vs. HTML conventions

_Loads when you open `guide.md`. Moved out of `CLAUDE.md` by the claude-md-consolidation
plan: these are authoring rules, and a session that is not editing the guide pays nothing._


`guide.md` is real Markdown for almost everything. Inline HTML is reserved for elements
Markdown cannot express — the fixed, allowed island vocabulary (each recognized and styled by
`style.css`):

| HTML | Purpose |
|------|---------|
| `<div class="title-block">` | Document title (h1) + tagline at the top of page 1. |
| `<div class="callout warn">` | Amber warning box. First paragraph's leading `**bold**` becomes the header. |
| `<div class="callout tip">` | Green tip box. Same bold-becomes-header convention. |
| `<div class="callout accent">` | Light-blue mental-model callout; plain prose. |
| `<div class="exercise">` | Green-bordered exercise box; first paragraph becomes the title strip. |
| `<pre class="diagram">…</pre>` | Monospace ASCII-diagram panel (`<pre>` required — pandoc collapses whitespace in a plain `<div>`). |
| `<div class="page-break"></div>` | Forces a page break. |
| `<div class="embed youtube" data-id="VIDEO_ID">label</div>` | (Opt-in web layer) A YouTube embed; `transforms.py` rewrites it per output. Inert without an active `transforms.py`. |
| `<svg viewBox="…">…</svg>` | Hand-authored inline diagram. See the constraints below — they are not style preferences, they are what WeasyPrint can actually render and what makes one drawing serve both outputs. |

**Inside ANY island, `<` starts a tag — escape it as `&lt;`.** The content of these blocks is
HTML, not Markdown, so a literal angle bracket is markup wherever it appears. A `<pre
class="diagram">` panel whose last line read `<slug>.pdf` rendered as ` .pdf`: `<slug>` was
emitted as an unknown element and dropped, silently, leaving a diagram that pointed at a
filename with no name. The same text one paragraph above, inside Markdown backticks, was
fine — which is what makes it easy to miss. This is the same failure family as the
`<text>`-ending backslash below: the island is parsed by a different set of rules than the
prose around it.

**Inline `<svg>` — the constraints, and why each exists.** Measured against the pinned
renderer (WeasyPrint 69), not assumed.

- **`viewBox` required; no hard-coded `width`/`height`.** One drawing has to serve a fixed
  Letter page and a 390px phone screen. A `viewBox` scales; fixed dimensions do not. Note
  what this does *not* mean: a `viewBox` supplies an intrinsic **aspect ratio**, and
  WeasyPrint already sizes such an element to the containing width and keeps the ratio
  (measured: `viewBox="0 0 800 400"` in a 600px container renders 600×300). So the drawing
  is not broken without CSS. Still give it an explicit box in **both** `style.css` and
  `style-screen.css` — `max-width: 100%; height: auto;` plus whatever width cap the page
  wants — because the tag-specific `pre.diagram` rules do not reach an `<svg>`, and relying
  on the container's width alone leaves the size at the mercy of unrelated layout changes.
- **Keep to the constructs the renderer actually implements.** WeasyPrint 69 handles
  `path`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`, `text`, `tspan`,
  `textPath`, `use`, `clipPath`, `image` and `a`. Use the shape elements — a box-and-arrow
  diagram written with `<rect>` and `<line>` is far easier to edit than the same drawing
  flattened into `<path>` data, and both render. **Avoid** filters (partial at best) and
  anything not in that list; unsupported constructs degrade quietly instead of erroring,
  which is the failure mode worth designing around.
- **`<title>` and `<desc>` mandatory — with their real scope stated.** They give the
  **website** an accessible name and description. They do **not** reach the PDF: this build
  emits an untagged PDF, so a PDF reader gets no description from them. That is a known gap,
  not a promise being made. Add `role="img"` alongside them for robust browser support.
- **Inline for a DIAGRAM; `assets/` is fine for an image.** This rule used to say "never
  `<img src="assets/…">`", on two premises that were true when it was written and are both
  false now: `build_web()` copies no asset directory, and `kitconfig` tracks `assets/`
  neither in the closure nor in `content_hash()`. Today `render_site._publish_assets()`
  copies them into the built tree, and `assets/print/**`, `assets/web/**` and
  `assets/shared/**` are declared closure members hashed by content — so an asset edit moves
  the stamp and `make verify` goes red exactly as it should. **Leaving the old rule in place
  was the worse failure: it told authors to avoid a feature that works.**

  What survives is narrower and still worth following. Keep a **hand-authored diagram**
  inline, because it is text you will edit alongside the prose it explains, and a `viewBox`
  drawing in `guide.md` is reviewable in the same diff as the paragraph it belongs to. Put
  **photographs, screenshots and generated figures** in `assets/` — inlining those is
  base64 noise in a Markdown file. Choose the directory by which outputs need it:
  **Write the path in full** — `![](assets/shared/x.png)`, not `assets/x.png`. The site
  publishes each namespace at its own path, so the one spelling resolves in both outputs; a
  shortened one resolves in neither. `assets/print/**` is a PDF input and not a site one,
  `assets/web/**` the reverse, and
  `assets/shared/**` is in both closures, so a shared file re-stales the PDF *and* redeploys
  the site.
- **Text stays real text.** Labels belong in `<text>`, never converted to paths, so
  `pdftotext` still finds them and the PDF stays searchable.
- **No blank lines anywhere inside the element.** Pandoc ends a raw-HTML block at the first
  blank line, so an `<svg>` with one is torn in half: everything after it is parsed as
  Markdown, `<desc>` comes back wrapped in a `<p>`, and the page renders the drawing's
  markup as flowed prose instead of a picture. Found the hard way; it looks like the SVG
  simply "did not work".
- **Separate words inside `<text>` with a non-breaking space (U+00A0), not a plain space.**
  WeasyPrint's SVG text layout drops or collapses ordinary inter-word spaces
  unpredictably — measured: in one drawing `BALANCE SHEET` and `= Net income` lost their
  spaces while `Retained earnings` and `Ending cash` kept theirs, and adding
  `word-spacing` fixed those two while breaking the other two. U+00A0 has a fixed advance
  and is immune to it. The labels still extract: `pdftotext` returns them with U+00A0
  where the space is, which normalises to a space.
- **Never end a `<text>` with a backslash — write `&#92;`.** Pandoc parses the content of
  these islands as inlines, so `\<` is read as a Markdown backslash-escape: it eats the
  backslash AND turns the `<` into a literal, and `<text …>C:\</text>` comes out as
  `<text …>C:&lt;/text&gt;`. The element is then never closed, every later `<text>` nests
  inside it, and browsers render no nested text at all — measured in windows-cmd-guide,
  where all eight tree labels vanished from the site while WeasyPrint tolerated the
  nesting and shipped a PDF that was correct except for the one mangled label. The two
  renderers disagreeing is what let it ship. `&#92;` (or `\\`) survives both; `&#92;` is
  preferred because it cannot be mistaken for a typo and re-"corrected" back.

Do **not** add other island types. Do **not** convert Markdown that already works into HTML.
Smart quotes are disabled in pandoc (`markdown+raw_html-smart`) so `---`, `'`, and `"` stay
literal for ASCII diagrams and copy-pasteable snippets.
