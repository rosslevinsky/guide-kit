<!-- claude-front:begin — REPLACED WHOLESALE by bootstrap.py, not placeholder-filled.

     Same reasoning as README.md's front-matter block, and the same defect it was
     written for. This repository is the KIT; a fork is a book. Writing the kit's
     own opening in `{{GUIDE_NAME}}` placeholders left the kit's copy headed
     "## What this is / <DESCRIBE YOUR GUIDE>" — an unfilled blank, in the file
     that is supposed to explain the project, on a public repository.

     A fork's opening describes ITS guide, so bootstrap swaps the whole block
     rather than substituting into it. Everything below the marker — including
     the kit:begin/kit:end managed region — is untouched by that swap.
-->
# Project notes for Claude

This file documents the conventions of this project so you can make good edits.

## What this is

**This repository is `guide-kit` — the toolkit, not a guide.** It builds the guides;
it is not one of them. What it renders (`guide.md` → `guide-template.pdf`) is a
worked example that exercises every styled element, so the pipeline always has
something to build and a stylesheet change is easy to eyeball.

The shared policy below is what gets synced into every guide in the family. Change
it **here** — editing a guide's copy is overwritten on the next sync.

| Working on… | Read |
|---|---|
| The kit's own build, sync or CI | [`README.md`](README.md) |
| Contributing to the kit | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Why the family looks like this | [`docs/family-as-built.md`](docs/family-as-built.md) |
<!-- claude-front:end -->

<!-- Add your GUIDE-SPECIFIC sections (conventions, doc structure, exercise format, …) here, ABOVE the managed-region markers below. Everything between them is shared kit policy synced from guide-kit — do not edit it per-guide. -->

<!-- kit:begin -->

## Shared kit policy (synced — do not edit per-guide)

Everything between these markers is **shared across the guide family** and is kept up to
date from the kit (`guide-kit`) by `sync.py`. Do **not** edit it here for one guide —
change it in the kit and re-sync. Your guide-specific sections belong **outside** the markers.

### Per-guide values: `guide.toml`

Everything a guide states about itself lives in `guide.toml`, read and validated by
`kitconfig.py` — the single strict loader, which **rejects unknown keys**, so a retired or
misspelled key fails loudly instead of silently doing nothing. Six identity constants:
`TITLE`, `OUTPUT_SLUG`, `AUTHOR`, `DESCRIPTION`, `KEYWORDS` and `COPYRIGHT_YEAR`. Alongside
them the declared shape and its supporting tables: `[outputs]`, one `[artifacts.<name>]`
edition date per declared output, `[theme]`, `[site]`, `[slides]`, `[deploy]` and `[fonts]`.
The README's "Every key, in one config that loads" block is the whole vocabulary, and a test
feeds it to the real loader so it cannot drift from the schema.

No renderer holds a guide-specific literal — they all read through kitconfig. The four
`LICENSE_*` constants stay in `buildcore.py` because they are family-fixed, not per-guide.
`OUTPUT_SLUG` drives the PDF filename and the worker name and is **independent of the repo
name** (e.g. a repo can render `git-github-for-beginners.pdf`). `COPYRIGHT` is derived as
`© {COPYRIGHT_YEAR} {AUTHOR}` — a stored constant, never a clock read, so renders stay
deterministic.

### Build pipeline

```
guide.md  --pandoc-->  HTML body  --transforms.py?-->  HTML'  --wrap-->  styled HTML  --WeasyPrint-->  PDF  --qpdf-->  PDF (canonical)
                                                                                ^
                                                              themes/<theme>/print.css + style.css
```

`build.py` is only the CLI: it parses the flags and dispatches. `buildcore.py` is the
artifact-neutral pipeline — config and paths, the version stamp, the transforms hook, the
glyph-coverage gate, pandoc, the shared HTML wrapper — and one `render_*.py` owns each output
(`render_pdf.py`, `render_site.py`, `render_slides.py`). That split is not tidiness: pipeline
code used to live in `build.py`, which is a stamp input for **every** artifact, so a
website-only change re-staled every reference PDF in the family. The renderers are imported
lazily, per branch, so the isolation the closures declare is real at run time too.

Run `make` to build (writes the working render to `build/<slug>.pdf`). `make html` renders
a standalone HTML preview. The pipeline pins WeasyPrint's timestamp via `SOURCE_DATE_EPOCH`
— midnight UTC of the artifact's **authored** `[artifacts.<name>] date`, never a clock or a
commit time — and canonicalizes with `qpdf --deterministic-id --normalize-content=y`, so two
builds of identical committed source produce content-identical PDFs.

### Markdown vs. HTML conventions

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

### The version stamp

The PDF footer carries `YYYY-MM-DD · <sha256[:12]>`. The date is the artifact's authored
`[artifacts.<name>] date` in `guide.toml` — an *edition* date, not a commit date. The hash is
over that artifact's own dependency closure (`kitconfig.ArtifactSpec`), so the site's stamp and
the PDF's move independently.

The render path reads **no git history**. The date used to be `%ad` of the most recent commit
touching a pathspec, which meant a `[deploy]`-only commit moved the PDF's displayed date even
though the PDF renders nothing from `[deploy]` — git cannot scope to a key inside a file. The
only git call left in the render path is `git status --porcelain`, for the dirty marker: a
` · dirty` segment is appended when the working tree has uncommitted changes to that artifact's
own inputs.

### Verification: which command asks which question

Four commands, three questions. **Is the reference stale?** (`make verify`) — **has the
toolchain drifted?** (`make drift-canary`, with `make verify-render` as its older, weaker local
form) — **does each artifact look finished?** (`make smoke`, which covers the deck as well as
the PDF and asks each its own questions). CI runs all but `verify-render`.

- **`make verify`** — the **staleness check**, and the one a red run usually means. It compares the
  content hash embedded in the committed reference PDF's stamp against a freshly computed hash
  over `SOURCE_FILES` (one `pdftotext` call). No build, no rendering, platform-independent —
  milliseconds. It has three outcomes, not two: **stale** (the stamp parses, the hashes differ —
  someone edited source without re-running `make release`, and the error names the stale file);
  **unreadable stamp** (the stamp cannot be parsed at all, so freshness cannot be established and
  the check fails closed rather than guessing — no file is named; a reference PDF rendered before
  a stamp-format change lands here, and a re-render clears it); and **pre-first-release** (no
  reference PDF yet — passes with a notice). Note a red `make verify` also blocks `deploy.yml`,
  which gates on it.
- **`make drift-canary`** — the **environmental** check, and CI runs it as well. It builds a fresh
  PDF and compares **bytes plus the `pdffonts` embedded-face list** against the committed
  reference. Its target is drift with no source change at all — a dependency bump, a rebuilt
  runner image — which `make verify` cannot see, because `pixi.lock` is deliberately outside
  `SOURCE_FILES`. See "Dependency drift, and the canary that catches it" below for the two
  properties that make it trustworthy (it stays silent when the reference is stale, and it never
  auto-baselines).
- **`make verify-render`** — the older, weaker form of the drift question: page count plus
  stamp-excluded `pdftotext`. Kept as a local convenience. Being a text comparison it is blind to
  any change that preserves line breaks, including a face substitution — which is exactly why the
  canary above compares bytes and faces instead.

A fourth command asks something none of those three do. **`make smoke`** asks whether an
artifact *looks finished*: the other three compare bytes, hashes or text against a reference,
and on an intentional content edit the text is **supposed** to differ, so none of them would have
caught the footer wrapping onto a second line on every page of three shipped guides. It is
build-free and platform-independent, so CI runs it and `baseline.yml` gates the refreshed
reference on it.

**It covers EVERY declared artifact that has a reference, and asks each one its own question.**
It used to ignore `--artifact` outright — resolving `<slug>.pdf` whatever it was asked for — so
`make smoke ARTIFACT=slides` printed a pass for the guide PDF and the deck was committed, pushed
and published having never been inspected. Making it honour the selector showed why that had gone
unnoticed: **a deck fails the guide's assertions correctly and uselessly.** Nothing is projected
into a deck unless it is wrapped in a `::: slide` fence, so a perfectly good deck may never name
the guide. So the deck is not asked for the title, one slide is a legitimate deck, and it **is**
asked for its version stamp — the measured failure, since a full-bleed `margin: 0` makes
WeasyPrint drop every `@bottom-*` box and produce a deck that cannot say what built it.

`ARTIFACT=<pdf|slides|site>` narrows it; `PDF=<path>` inspects one file instead, which is how
`make baseline` and `make release` check a **fresh** render before promoting it — pair it with
`ARTIFACT=` for a deck, or the guide's assertions are the ones that run. Both promotion paths do
exactly that now; they used to exempt the deck, on the reasoning above, back when that reasoning
was true.

**A guide with no reference artifact yet PASSES with a notice**, matching `make verify`. It used
to exit 2 on the missing file, which made it the one command in the README's build block a
brand-new fork could not run. The discriminator is the same one staleness uses — git history for
the reference path — so a deliverable that WAS released and has gone missing still fails.

There is no image comparison anywhere anymore, and there is no canonical host: the bundled faces
make the render host-independent.

### Reference PDFs render anywhere — the drift canary is what keeps that true

Every guide's reference PDF is the reader-facing deliverable, and it renders identically on any
host: the repo bundles its own faces under `fonts/vendor/` and ships `fontconfig/fonts.conf` in
place of the system config, so nothing about the render consults the OS's font stack.
`.github/workflows/baseline.yml` renders it on an `ubuntu-latest` runner and commits it.

**There is no recorded platform and no platform guard.** `guide.toml` used to carry
`baseline_platform`, and `make baseline` / `make release` refused off the recorded host, with
`--allow-platform-mismatch` as the escape hatch. All of that is retired. It was written for a
family that shipped system-font stacks, where the host genuinely chose the typeface; once
rendering became hermetic the key recorded an intention that nothing could violate, and a
leftover `baseline_platform` in a fork's `guide.toml` is now rejected as an unknown key.

**What replaced it is a measurement, not a declaration.** `verify.yml` runs a **drift canary**:
it renders afresh and compares **PDF bytes plus the `pdffonts` embedded-face list** against the
committed reference. It runs weekly on a schedule and whenever `pixi.lock` or a workflow changes,
because those are the inputs `make verify` cannot see. If the staleness check passes — the source
really is unchanged — and the canary still differs, that is toolchain drift by definition: it
fails loudly and **never** auto-baselines, because auto-baselining drift is how it would get
silently absorbed into the deliverable.

`make baseline` still **refuses a dirty `SOURCE_FILES` tree** (a `· dirty` baseline could never
be matched by `make verify`); `make release` instead **commits** your source edits itself and then
refuses to promote a render whose stamp is `· dirty` or stale, so neither command can bless an
unmatchable reference. **You do not normally dispatch a baseline yourself:** when a push to the
default branch leaves the reference stale, `verify.yml` dispatches `baseline.yml`, which renders,
smoke-checks, commits the PDF, and then dispatches `deploy.yml` so the site stops serving the old
download.

**That push stays GREEN, and the reason is worth stating.** A reference PDF is a build artifact
committed to the repo and stamped with a hash of its own sources, so any source push makes it
stale *by construction*. Reporting the expected intermediate state as a failed run emailed the
maintainer on every content edit about something the next step was already repairing — and this
family's own record says a red check that means nothing teaches people to ignore it exactly as
thoroughly as a green one that checked nothing. So the verdict still drives the rebuild; only who
it is reported to changed. **If the rebuild cannot produce a good render, `baseline.yml` fails —
and that is the notification worth having.**

Staleness still FAILS where nothing can repair it: on a pull request (actionable by the author,
and nothing can auto-commit to their branch), on a scheduled or dispatched run (no push to repair
it, so it is a standing defect), and whenever the check itself is broken rather than merely
red — blessing a baseline on a check that did not work is how a wrong PDF ships. `deploy.yml`
SKIPS rather than fails, so a stale PDF still never reaches the site.

So the everyday flow for a content edit is just **commit and push `guide.md`**; `make release`
refreshes the reference by hand from any host, and `gh workflow run baseline.yml` is the repair
path when a site drifted without a source change.

### The transforms hook (per-output)

If `transforms.py` exists next to `build.py`, the pipeline calls one entry point between pandoc
and the renderer, chosen by target: `post_pandoc_html_for_pdf` / `post_pandoc_html_for_web`, with
a single-entry `post_pandoc_html` fallback. `transforms.py` is always a `SOURCE_FILES` entry — a
missing file contributes no bytes — so **creating** it shifts the version stamp (refresh the
reference PDF afterward). Activate it only if the guide needs a substantive transform (the worked
example is the YouTube-embed split).

### The website's navigation chrome (script-built, screen only)

`render_site.py` appends a small script to the **web** output only. It never authors prose, and
the PDF never sees it. This is not a divergence between the outputs — the PDF already carries an
`/Outlines` tree over the same headings, so this restores the site to parity in the medium's own
idiom.

**The sidebar is ONE list, and its two levels come from two places.** The top level — parts and
chapters — is `.guide-chapters`, **server-rendered** from the chapter set and moved into the
panel by the script. The second level is the sub-headings of whichever chapters are on the page,
read from the DOM and nested under their chapter's entry. Only the chapter being read is
expanded.

It was two flat lists stacked in one panel until 2026-07-30, and the reason it could not simply
be halved is worth keeping: **neither source has both facts.** `.guide-chapters` knows every
chapter in the *document* and nothing about the page in front of the reader; `h1[id], h2[id]`
knows the page and has no idea another chapter exists. Measured on the one-page view before the
change:

| guide | headings | chapter list | overlap |
|---|---|---|---|
| accounting (`chapter_level = 2`) | 49 | 43 chapters + 6 parts | the same content twice |
| git (`chapter_level = 1`) | 43 | 34 chapters + 8 parts | the same, plus the document title |
| mac-terminal (`chapter_level = 1`) | 21 | 7 chapters | 14 of the 21 are sub-sections |

So at `chapter_level = 2` the two lists were near-duplicates and at `chapter_level = 1` the
heading list was strictly richer — "just use the chapter list" costs mac-terminal 14 of its 21
entries. Nesting is what keeps both.

The class names below are a **contract**: each guide's `style-screen.css` is target-owned
(`policy = "never"`), so renaming one here does not break a build — it silently unstyles every
site. `tests/test_web_nav_and_favicon.py` in the kit pins nineteen of the twenty;
`.guide-chapter-part` is pinned by `tests/test_parts.py` instead, which is where the part label
is built. Worth naming precisely, since the point of the paragraph is that an unpinned rename
goes unnoticed.

**Two tests, and the split matters.** That file searches the script's SOURCE for literals, which
catches deletion and renaming — most of what happens to it. It cannot catch wrong *logic*: a
cross-model review found an `aria-current` regression that every literal assertion passed
through, because the literal was there and the code around it was wrong. So
the kit's `tests/test_nav_dom.py` **runs** the script, in jsdom, over a real rendered site
(`npm ci` in `verify.yml`; kit-only — `tests/**` never syncs, and the step is guarded on a root
`package-lock.json` that no target has). jsdom does no layout, so the scroll-spy threshold, the
drawer's live header bottom and `display: none` on a collapsed sub-list are still verified by
driving a real browser by hand — everything structural is now executed rather than grepped.

| Class | What it is |
|---|---|
| `header.guide-header` | Sticky header, inserted as the body's first child. |
| `.guide-nav-toggle` | The panel control. Carries `aria-expanded`, and `is-open` when the mobile drawer is open. |
| `.guide-header-title` | The running title inside the header. |
| `nav#guide-nav.guide-nav` | The nav itself. Gains `is-open` on mobile, `is-collapsed` on desktop. |
| `.guide-chapters` / `.guide-chapter-list` | The server-rendered list, and its `<ol>`. The sidebar's top level. |
| `.guide-chapter-item` / `.guide-chapter-part` | A chapter entry, and a part's label (no anchor — a part has no page). |
| `.guide-nav-sub` + `.guide-nav-item` `.guide-nav-l2` | The nested sub-headings of one chapter, and an entry in them. |
| `.guide-nav-list` + `.guide-nav-l1` | The heading-derived top level, used **only** where there is no chapter list (`site = "single"`). |
| `.download-btn` / `.guide-mode-link` | The two server-rendered top controls the script MOVES into the header — download, and the one-page/by-chapter switch. |
| `.guide-pager` | The previous/next chapter control at the foot of a chapter page. |
| `.is-current` | On the `<a>` for the section currently in view. |
| `.is-expanded` | On the `.guide-chapter-item` whose sub-headings are showing. |

**The panel has two states and they are not the same class**, because reusing one for the other
inverts a default:

| State | Written on | Meaning |
|---|---|---|
| `.is-open` | the nav, and the toggle | **Mobile.** A transient overlay, closed by default, which closes itself when a link inside it is clicked — on a phone it covers the page you just chose. |
| `.is-collapsed` | the nav | **Desktop.** A persistent panel, *shown* by default, hidden only because the reader asked — so it must **not** auto-close on a link click. Persisted in `localStorage`, wrapped because Safari private mode throws on access. |

Reusing `is-open` for both would invert the desktop default: anyone whose JavaScript failed to
run would lose the sidebar entirely, and everyone else would see it flash closed-then-open on
every load. The desktop state is *also* published as `:root.guide-nav-is-collapsed` alongside
`--guide-nav-width` / `--guide-nav-space`, so a guide's own stylesheet can reclaim the space —
the kit never restyles `body`, because the prose measure is guide-owned and a test enforces
that boundary.

Properties worth not breaking:

- **The nav lists `h1` and `h2` only**, never `h3`: a sidebar of all ~88 id-carrying headings
  is unusable. The `h3` ids still exist and still resolve as fragment links — pandoc emits them
  server-side — they simply are not listed. (There used to be a hover-revealed `#` anchor on
  every id-carrying heading so a reader could copy such a link. It was removed: beside a heading
  in a document meant to be read straight through, it read as a stray character rather than as an
  affordance. Nothing about linking changed — only the way to discover it.)
- **The download link, the view switch and the chapter list are MOVED, not re-created.** All
  three are emitted server-side and relocated by the script. That is the whole reason they are
  moves: without JavaScript there is no header and no panel, and *nothing is lost* — the reader
  gets a complete page with a contents list at the foot of it. Re-creating the chapter list is
  also impossible, not merely inelegant: the script reads the headings on the page, and a chapter
  page has exactly one chapter's worth.
- **`data-anchor` is the heading's pandoc id, never the route slug.** The two grammars disagree —
  `Node.js basics` is id `node.js-basics` and slug `node-js-basics` — and deriving one from the
  other gives a fragment that scrolls nowhere and reports nothing.
- **Entries point into the view they are on.** One-page: every entry is an in-page anchor, because
  the whole document is there and a chapter URL would move a reader out of the mode they chose.
  Chapter page: chapter URLs, except the current chapter's, which is an anchor.
- **A part label carries `data-anchor` and is still not a link.** Its heading is an `h1[id]` like
  any other, so the script meets it mid-walk; the id is what lets a part *close* the open chapter
  instead of its title and blurb being filed as sub-sections of the chapter before it.

The favicon is the one thing in this section the PDF pipeline also sees — it comes from
`buildcore`'s shared HTML wrapper, not from the nav script, so both outputs' HTML carries it
and only the site has anywhere to show it. It is a `data:` URI built from up to two initials of
`OUTPUT_SLUG`, the word "guide" skipped (`mac-terminal-guide` → `MT`). Two initials rather than
one because `windows-cmd-guide` and `windows-powershell-guide` would otherwise ship the same
icon, which defeats the only reason to derive it from the guide. Inline rather than a file
because the resource then cannot 404 — it *is* the markup — where a `href="favicon.svg"`
satisfies a grep for `rel="icon"` whether or not anything ever writes the file. The test
decodes the URI accordingly, instead of checking that the markup mentions it.

### The website (opt-in)

The PDF is the default output. A guide opts into a website (Cloudflare Workers Static Assets) at
bootstrap (`bootstrap.py --with-web`) or later with
`adopt.py --target <guide> --output site --enable` — which is **config-first**: you declare
`[outputs] site` and its `[artifacts.site]` date and commit that, and `--enable` then
materializes what the declaration implies. The tool never writes `guide.toml`, because
`guide.toml` is `policy = "never"` — target-owned.

Opting in is a **declaration, not a file**: `build_web()` keys on `[outputs] site`, so a guide
that switches its site off does not keep rendering one because `style-screen.css` happens to
still be on disk. When enabled, `make web` writes into `app/dist/`: `index.html`, the per-chapter
pages when `site = "multipage"`, a `guide.json` manifest of the page set, `_headers`, the bundled
faces, the declared `assets/{shared,web}/**`, and a copy of the committed reference PDF. It
**hard-fails** if that reference PDF is missing, before writing anything — a site must not ship a
404 download link. `style-screen.css` is not a `SOURCE_FILES` entry, so a screen-only edit cannot
re-stale the PDF. `verify_web.py` asserts the per-output embed split and skips cleanly when there
is no web layer or no embed island.

**The built tree is provider-neutral, and that is proven by serving it.** `make web` emits a
plain static directory that any host can serve; the kit's `tests/test_static_portability.py` starts
`http.server` over the exact output and exercises the routes, the PDF's media type and 404
semantics. The one Cloudflare-specific artifact is `_headers`, which `cfadapter.py` writes.
Forced download is therefore **provider-optional**: on a host that ignores `_headers` the PDF
opens inline instead of downloading, and nothing else differs.

**`app/wrangler.jsonc` is GENERATED from `guide.toml`, not hand-edited and not synced.** It is
`policy = "never"` — target-owned — and `make wrangler` (`cfadapter.py`) writes it. Two facts in
it are derived rather than authored:

- **`workers_dev`** is `false` when `[deploy] domain` is set and `true` when it is not. It is not
  authorable, and an authored key is rejected. Cloudflare's default is to serve every worker at
  `<name>.<account>.workers.dev` and `wrangler deploy` **re-asserts that default on every run**
  unless config says otherwise, so turning it off in the dashboard does not stick — which is how
  eight sites in this family were quietly dual-published for weeks, each at its custom domain and
  at a workers.dev URL outside the zone, hence outside its WAF, analytics and redirect rules.
- **`routes` + `custom_domain: true`** are emitted from `[deploy] domain`, so `wrangler deploy`
  binds the domain with **no dashboard step**. A guide with no domain gets no routes block at all
  — that is the cold-start case, where workers.dev is the whole publication story.

`[deploy] preview_urls` is the one deploy fact a guide **authors**, and it defaults to
`false`. Preview URLs are a *second, independent* workers.dev surface —
`<version>-<worker>.<subdomain>.workers.dev` — and turning `workers_dev` off does nothing to
them. Two properties make the default matter: **every** version gets one (a production
`wrangler deploy` as much as a PR's `versions upload`), and they **do not expire** — the
documented retention rule covers aliased previews only. So a guide that has deliberately left
workers.dev would otherwise accrue public, un-WAF'd URLs serving the same content forever.
Cloudflare reached the same conclusion: since wrangler 4.44.0 their default is
`preview_urls = workers_dev`.

**It no longer buys a PR preview from CI, and that is deliberate.** `deploy.yml` used to
upload a preview version on every pull request and comment the URL; that path is gone. A
same-repository PR receives repository secrets, and for the `pull_request` event GitHub runs
the workflow file from the **merge commit** — the PR's own copy — so a pull request can delete
any guard the workflow adds in the same commit that adds a payload. Nothing arranged inside
that file closes it, so the Cloudflare token is kept off the pull-request path entirely and a
PR gets a build check instead. `preview_urls` still controls whether Cloudflare mints preview
URLs for versions at all, which is what the setting is actually about.

Because sync never writes the file, the kit stays in control through a check rather than an
overwrite: the kit's `tests/test_wrangler_generated.py` fails when a guide's committed
`app/wrangler.jsonc` differs from what the generator produces. Change `guide.toml`, run
`make wrangler`, commit.

### The slide deck (opt-in)

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

### Deploying, and the release protocol that was removed instead

`deploy.yml` is the whole publication story: a push to `main` that touches the site
redeploys the site. There is no separate tag-triggered release, and the machinery for one —
an append-only journal on a git ref, a per-artifact publication lease, provider
reconciliation — was **removed** rather than left armed.

Worth recording why, because it was a considerable amount of careful code:

- **It never ran.** It was materialized into every web-enabled guide and no `release-*` tag
  was ever pushed, in the family's entire history.
- **Its output would have been invisible.** GitHub Release assets follow repository
  visibility, and the guide repositories are private — so the assets would have been
  collaborator-only while the public download is, and always was, the site.
- **The archive it offered already exists.** The reference PDF is committed, so every past
  edition is retrievable with `git show <sha>:<slug>.pdf`. A Release would have added a
  nicer URL and release notes, not the archival.

**Nothing survives it.** A `relmanifest.py` wrote a per-deploy manifest of every served
path into `.well-known/guide-kit-release.json`, so anyone could fetch it and check the bytes
themselves. It was deleted once it was clear nobody did: no tool, no page and no check ever
read it — only its own test — so it was a receipt written for a reader who never came.

**A tag is still a tag.** Nothing stops you tagging a commit; `git show <tag>:<slug>.pdf`
gives you that edition. What no longer happens is a workflow reacting to it.

### The kit, the manifest, and `sync.py`

This guide is kept in sync with the kit (`guide-kit`) by copy-and-checksum, not merge.
`kit-manifest.toml` classifies every kit file on **two independent axes**: source lifecycle
(`retained-in-kit` / `bootstrap-source` / `generated`) and destination policy (`identical` /
`templated` / `managed-region` / `never`). `sync.py <guide>` reports drift and writes nothing;
`sync.py <guide> --apply` writes transactionally and refuses a dirty tree or an unrecorded managed
file. **This `CLAUDE.md` is a `managed-region` file** — only the block between the markers is
synced; your own sections outside them are never touched.

First contact uses the **six-step adoption sequence**: (1) hand-write the guide's `guide.toml` and
insert the managed-region markers in this file; (2) review and commit; (3) confirm a clean
worktree; (4) `sync.py <guide> --adopt --source-repo <owner/repo> --kit-version <ref>` (both flags
are required; records pre-sync hashes; state `adopted_unapplied`); (5) commit `.template-version`;
(6) `sync.py <guide> --apply` (state → `applied`). A scheduled,
warn-only `kit-drift.yml` reports when the kit's managed content moves.

### When to run `make baseline` / `make release`

Refresh a reference after any **intentional** change to that artifact's closure, from whatever
host you have. Both commands take `ARTIFACT=` — `pdf` (the default) or `slides` for the two that HAVE a
reference, and `site`, which is accepted and prints why it has none, because `baseline.yml` loops over
every artifact name and must not error on the one that is deployed rather than committed. The two with
references need separate refreshes because they
have separate references and separate closures — but they also *share* `_COMMON_FILES`, so a
`buildcore.py` or `kitconfig.py` edit stales both and both need refreshing.

Commit source **first**: `make baseline` on an uncommitted tree produces a `· dirty` stamp that
future `make verify` runs won't match (and `make baseline` refuses a dirty tree for exactly this
reason). `make release MSG="…"` does commit-source → render → promote → amend in one shot;
`make baseline` + a plain PDF commit is the alternative when source is already committed.

Not sure what is in the closure? Ask the kit rather than a list in prose. Pass the loaded
config — `kitconfig.SOURCE_FILES` is the static, config-free view, so it resolves
`themes/<theme>/print.css` to the **default** theme and would name the wrong sheet for any
guide that selected another one:

```bash
pixi run python -c "import kitconfig as k; print('\n'.join(k.stamp_pathspec('pdf', k.load())))"
```

The result is a git pathspec as well as a list, which is what `make verify`'s dirty check and
`make baseline`'s refusal both scope themselves to. Swap `'pdf'` for `'slides'` or `'site'`.

### After editing

```bash
# 1. Edit guide.md / style.css / guide.toml / transforms.py / a theme — or any
#    other SOURCE_FILES entry (the command above lists them)
# 2. make                          # render the working PDF (build/<slug>.pdf)
# 3. Open it and eyeball the render. Right? If not, fix and goto 2.
# 4. git commit && git push        # CI re-renders the reference PDF on Linux
```

Step 4 is a plain push from any platform. It leaves the committed reference stale, so `verify.yml`
dispatches `baseline.yml`, which re-renders on a Linux runner, smoke-checks, commits the refreshed
PDF and redeploys the site. **The push stays green** — staleness straight after a source push is
the expected state, not a fault, and only a rebuild that cannot produce a good render is reported
as a failure. `deploy.yml` skips that one deploy rather than failing it, so nothing ships stale. `make release MSG="…"` is the local equivalent of steps 2-4 and
runs from any host — rendering is hermetic, so there is no recorded platform to be on.

`release.py` refuses to run with **any** staged change, or with modifications outside the
**authorable set** (every artifact's inputs plus the bundled faces — wider than `SOURCE_FILES`,
which is the PDF's closure alone, so a `style-screen.css` edit alongside a PDF edit no longer
kills the release) — commit those with a plain `git commit` first. Doc-only edits (`README.md`,
this file, `LICENSE`, `Makefile`, `pixi.toml`, workflows) do not bump the stamp and never need a
baseline refresh. Never `git add` anything under `build/` — that is the working render, and it is
gitignored.

It also refuses unless the artifact is genuinely new (the **edition-date predicate**): the
content must differ from the last released reference, compared with the date normalised away, so
editing `[artifacts.pdf] date` by hand cannot pass off an identical PDF as a new edition.
`release.py` is the sole normal writer of that key — it assigns the release transaction's
**admission instant**, captured once and persisted on a git ref under `refs/guide-kit/`, so a
release that crosses midnight or is retried the next day keeps the date it was admitted with.
A reference whose stamp cannot be read is a **refusal**, not a first release: re-render it
(`make baseline`, or let `baseline.yml` do it) first. A retry after a failed build resumes the
same transaction and amends into the same source commit.

### Dependency drift, and the canary that catches it

`make verify` compares hashes over `SOURCE_FILES`. `pixi.lock` is **not** in that list, so a
dependency bump that changes how WeasyPrint or fontconfig lays out text shifts the rendered PDF
while `make verify` stays green — the source really is unchanged, so the staleness check is
answering its own question correctly. This used to be an open gap with nothing in CI closing it.

**`driftcanary.py`, wired into `verify.yml`, closes it.** It renders afresh and compares the
result against the committed reference on two axes: **PDF bytes** (strictly stronger than a text
diff — it sees kerning, justification and metric changes that preserve line breaks) and the
**`pdffonts` embedded-face list** (which catches a face substitution that happens to produce
identical text and pagination, and which a byte comparison alone would report without naming).
It runs weekly and on any `pixi.lock` or workflow change, since a rebuilt runner image has no
push event of its own.

Two properties are load-bearing, not incidental:

- **It only speaks when staleness is silent.** If the reference is stale the canary skips —
  a stale reference is `make verify`'s finding to report, and a difference then says nothing
  about the toolchain. A difference on a *fresh* reference is drift by definition.
- **It never auto-baselines.** The stale path auto-dispatches `baseline.yml`; the drift path
  must not, or the drift would be committed into the deliverable and the check would have
  laundered exactly what it exists to surface.

`make verify-render` remains as the local, pre-push version of the same question — page count
plus stamp-stripped text, weaker than the canary and needing a build. Still treat a `pixi.lock`
change as a **rendering** change: run it, **eyeball the PDF**, re-baseline if the layout moved,
and pin tighter in `pixi.toml` if a guide needs a narrower window. (`fontconfig` in particular
already differs across this family, so a lock refresh can move one guide's pagination and not
another's.)

### Tone

Direct and friendly. Adult reader new to the topic. No singsong asides, no fake dialogue, no
narrative openers, no pep-talk endings.

<!-- kit:end -->
