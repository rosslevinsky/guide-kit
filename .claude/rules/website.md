---
paths:
  - "site/**"
  - "hub.py"
  - "render_site.py"
  - "style-screen.css"
  - "templates/**"
---

# The website

_Loads when you touch a site source. Two subsections, both site-only._


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
