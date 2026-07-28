# Guide family: as-built

_The decision record for the guide family — what was built, what diverged from the plan, what broke
and how it was caught. **Kit-only:** `bootstrap.py` prunes `docs/` from a fork, so this never lands
in a guide repo._

**Why it lives here.** This began as `as-built.md` inside a workspace-level plans directory that is
not under version control — the one account of *why* the family is shaped this way existed on a
single machine's disk. The kit is versioned and is the thing every guide already points at, so the
record moved to it. The plan documents it refers to (`plan.md`, `execution.md`, the phase docs)
stayed behind and are cited by name below; nothing here depends on being able to open them.

> **This repository is PUBLIC, and this file is written for that.** It is the record of *what the
> engineering was*, not of *what the infrastructure is*. Production hostnames, DNS and WAF
> behaviour tied to a named zone, resource counts, credential distribution and repository
> visibility are deliberately absent — an as-built that doubles as a deployment map is a finding,
> not a document. The unredacted original stays on the maintainer's machine, outside version
> control. **When you extend this file, write the lesson and leave out the coordinates.**

---

## Outcome

All 22 phases of the guide-family-expansion plan complete. `guide-kit` is a reusable kit;
seven guides are synced to it with zero drift; every guide has a public site collected by a hub;
every reference PDF in the family is current. (As recorded at the gate the references were
**macOS**-rendered, against a `baseline_platform` guard. Both are gone: rendering became
hermetic — bundled faces plus `fontconfig/fonts.conf` — so there is no canonical host left to
be off, `baseline.yml` runs on `ubuntu-latest`, and the guard is a rejected key. See
[outstanding item 6](#outstanding-items).)

### Final gate results (as recorded at the Phase 22 gate)

| Assertion | Result |
|---|---|
| Kit suite | **216 passed** |
| Guide-local suites (3) | **9 passed** |
| Seven sync targets: zero drift, `state=applied` | **all 7** |
| `make verify` across eight PDF-building repos | **all 8 green** |
| `guide-kit` still a template repo | **true** |
| Hub: authored links returning 200 | **11 / 11** |
| Eight required guide + PDF URLs present on the hub | **8 / 8** |
| Non-terminal guides absent from the hub | **confirmed** |

The last row was **deliberately reversed** after the plan closed — the hub now covers every guide.
See [Post-plan changes](#post-plan-changes). The table is left as recorded because it is the state
at the gate, not a claim about today.

---

## Deviations from plan.md

### 1. macOS handoffs were automated, not manual (affects Phases 3, 15, 20)

`plan.md` specified three `[macos-only]` handoffs requiring a physical Mac, and three phases were
designed to end `blocked` pending them. Mid-run the user chose to add a `baseline.yml`
`workflow_dispatch` job running on `macos-latest`, which renders the reference PDF (the
`baseline_platform = "darwin"` guard passed natively), proved it fresh, and committed it.
(Both have since moved on: the runner is `ubuntu-latest` and the guard is retired — see the
guide-kit stage-0+1 boundary. This paragraph records the state at the time.)

**Consequence:** Handoffs 0, 1 and 2 were all completed in-run, so **no phase ended blocked** and
the plan ran to completion without a Mac. The eight PDF commits attributed to "the human at the
gate" were made by CI.

### 2. `workers.dev` was never the deployment target

the plan set "a `workers.dev` subdomain exists on the account" as a prerequisite. Verified
live: the account's existing Workers have `workers.dev` **disabled** and serve on custom domains in
a zone the account already held. The real prerequisite is therefore the zone, not a `workers.dev`
subdomain. Every site follows the family convention — custom domain bound against the zone,
`workers.dev` disabled per-script.

### 3. The kit freeze was lifted twice, deliberately

`execution.md` froze `guide-kit` from Stage 9 through Stage 11, with kit defects to be fixed in
the join. Two were fixed **during lane A** instead, with the user's approval, because only one lane
had adopted at that point — so the rule's actual purpose (never leave a converged lane behind) was
preserved, and fixing at the join would have propagated both defects to four lanes first. Every
subsequent kit change was re-applied to **all** targets in the same round.

### 4. Only three guide-local suites exist, not five

`phase-20` expected suites in `accounting-guide` and `japan-guide`; neither has a `tests/` directory
and nothing in this plan adds one. Naming absent suites was worse than omitting them — pytest
collected nothing and `-q | tail` masked the exit code, so the command passed while verifying zero.
Corrected to name the three that exist, and to assert a nonzero collected count.

### 5. A family-wide test run needs `--import-mode=importlib`

All three new guides name their file `tests/test_topic_coverage.py`. Under pytest's default import
mode the second and third collide with the first and the run aborts. Each guide's own CI runs a
single suite, so this surfaces only when something runs them together.

### 6. Hostnames

Each guide takes a subdomain of the family's zone, named for the guide rather than for its repo
where the two differ (the Linux guide is published under a name the author preferred over the repo
slug). The hub was renamed once, and takes a subdomain matching its repo name because the zone apex
was already in use. The convention is what generalises; the specific names are operational detail
and are not recorded in this public file.

---

## Defects found and fixed that the plan did not anticipate

Each of these was found by **running the thing end to end**, not by a test — and most were invisible
to CI by construction.

| # | Defect | How it was found |
|---|---|---|
| 1 | Kit-only files (`tests/`, `sync.py`, the manifest, `plans/`) were copied into every `--template` fork, so each new repo ran the **kit's** suite against itself — 15 failures, red default branch from the first commit | Independent review of Phase 16 |
| 2 | The topic-coverage module was simultaneously **too loose** (one line of keyword soup passed) and **too tight** (a good PowerShell guide failed 6 of 9 subjects because the markers encoded Unix vocabulary) | Independent review of Phase 16 |
| 3 | `baseline.yml` refreshed the reference PDF but **never redeployed the sites** — a `GITHUB_TOKEN` push does not re-trigger workflows | Handoff 1 |
| 4 | `workflow_dispatch` deploys were a **silent no-op**: the job built the site, skipped both deploy steps, and reported success | Handoff 1, by comparing the served PDF's stamp against the committed one |
| 5 | Fixing #4 left `Resolve deployed URL` untouched, so a real production deploy was logged as an **empty-URL preview** — the same lying-log defect one step below | Independent review of the Stage 11 join |
| 6 | `baseline.yml` could **never create a guide's first reference PDF**: it read verify's exit 0 as "already fresh", but that is also the pre-first-release state | Handoff 2 — three green runs, three skipped renders |
| 7 | Reading exit codes from `make verify` is unsound — **GNU make flattens any recipe failure to exit 2**, so a stale PDF was misread as a broken environment | Re-running Handoff 2 after a footer fix |
| 8 | The page footer **wrapped on every page** of all three new PDFs; the version stamp split at its middle dot, orphaning the hash | Manual PDF inspection in Phase 21 |
| 9 | Silent commands (`cd`, `mkdir`, `cp`, `mv`, `rm` — half a terminal guide's inventory) were **unsatisfiable** under the "records output" rule | Writing the first real command inventory |
| 10 | A cmdlet used **downstream in a pipeline** counted as never invoked, so PowerShell's two most characteristic cmdlets failed a guide that teaches them properly | Writing the PowerShell guide |
| 11 | `cloudflare/wrangler-action` installs **wrangler 3.90.0** when a repo has no local wrangler to detect — it predates assets-only Workers and fails with `Missing entry-point`. Node version is irrelevant; only `wranglerVersion` fixes it | First CI deploy of the hub, which has no `package.json` |
| 12 | The family's zone carries a **wildcard DNS record**: every subdomain resolves and answers 200 with a generic placeholder page, *including names bound to nothing*. Any deploy check asserting a 200 on a hostname in such a zone therefore verifies nothing — only page **content** distinguishes a bound worker from the placeholder | Probing a deliberately unbound subdomain while diagnosing #13 |
| 13 | A **managed WAF can block GitHub Actions runner IPs**. A runner gets 403 on every request while the identical request from elsewhere gets 200 — so a workflow cannot read its own deployed site back. Diagnosed only after two wrong guesses (unset secret, then first-time domain provisioning) and a pointless retry-window widening | Every CI attempt over a 5-minute window 403, against consistent 200s from outside |
| 14 | **`workers.dev` was on for nearly every worker in the family**, publishing each guide at a second URL outside the zone. Cloudflare defaults it ON and `wrangler deploy` **re-asserts that default on every run** unless the config says `workers_dev: false` — so disabling it in the dashboard never sticks. The family's convention was recorded in prose (this file said workers.dev was disabled) and in nothing else, so the default silently won every deploy | Checking whether a runner could reach a site at all, which surfaced one repo's CI verifying against a `workers.dev` URL |
| 15 | **"Download as PDF" did not download.** Cloudflare serves the PDF as `application/pdf` with no `Content-Disposition`, so a plain `<a href>` handed off to the browser's PDF viewer. Compounding it, the only download link was in the **footer** — ~50 pages of scrolling on the longest guide, so most readers never reached it | User report from actual use; no automated check covers "does this control do what its label says" |
| 16 | The sticky site header **aligned its download link to nothing.** `.guide-header` was capped to no width, which is not the same as full width: as a child of `body` it took its left edge from the text column and its right edge from the window, so the link stood 267px past the last character of text at 1920px and 587px at 2560px — unremarkable on a laptop, adrift on a wide monitor. The same bar printed each guide's **title twice**, its running head directly above the identical `<h1>` | User report, reading a live site on a wide monitor |
| 17 | A `<text>` ending in a backslash **ate its own closing tag.** These islands are parsed as inlines, so `\<` is a Markdown backslash-escape: `<text …>C:\</text>` became `<text …>C:&lt;/text&gt;`, the element never closed, and every later `<text>` nested inside it. Browsers render no nested SVG text, so all eight labels of the C: drive tree were missing from two live sites — while WeasyPrint tolerates the nesting and shipped a PDF that was correct but for the one mangled root label | User report, looking at the drawing on the live site |
| 18 | The download button was **styled by where it starts, not by what it is.** `.site-topbar .download-btn` stopped applying the moment WEB_NAV_JS moved the button into the sticky header, so the same control rendered as a bare blue text link at the top of every page (`border: 0px none`, `padding: 0px`, `font-weight: 400`) and as a bordered button in the footer. The footer copy carried no class at all and was styled by position in seven target-owned sheets | User report, comparing the top and bottom of one page |

Nos. 3–8 are all the same shape: **a green check that verified nothing.** None was reachable by the
test suite, because each lived in workflow trigger semantics, exit-code plumbing, or rendered
layout.

Nos. 12–13 are the mirror image and worth naming separately: **a red check that means nothing.** A
check that fails for a reason unrelated to the code teaches people to ignore it just as thoroughly
as one that passes without looking. The resolution in both cases was to move the assertion to where
it can actually run — the hub's content is now asserted against `dist/index.html` *before* the
deploy, and reading the live page back is a bonus that strengthens the check when the runner is not
blocked, rather than a gate that fails when it is.

No. 14 is a third shape: **an intention recorded only in prose.** "workers.dev is disabled" was
written in this file and described in the template's own comments, and was true at the moment
someone typed it — but the setting lived where a tool re-asserts a default on every run, so the
convention decayed silently and nothing noticed for weeks. A convention that a tool can overwrite
has to live in that tool's config, not in documentation about it.

No. 15 is a fourth: **nothing in the family checks that a control does what its label says.** The
PDF link returned 200, served the right bytes, and passed every automated gate — while the button
labelled "Download as PDF" did not download. That class of defect is only reachable by using the
thing, which is how it was found.

No. 16 is No. 15 again, one layer out: **the layout was only ever looked at where it happened to be
right.** Both defects were in the same 46px strip, both shipped to seven live sites, and both passed
every gate — the header is chrome, so no stamp covers it, no test asserts its geometry, and the PDF
never sees it at all. What made the alignment defect invisible for so long is that its size is a
function of window width: it is 27px on a 1440px laptop, which reads as a margin, and 587px on a
2560px monitor, which reads as a mistake. A layout that is checked at one width has been checked at
one width.

The fix is measured rather than asserted — the bar and the reveal are both keyed to values the page
computes for itself (`--max-width`, and a view timeline on the heading), so neither carries a number
that is right for the guide it was measured in and wrong for the other six. The reveal completes at
60px in japan-guide and 240px in git-guide, from the same rule.

Nos. 16–18 arrived together, from one reader looking at one page, and they share a fifth shape:
**the site is the output nothing checks.** The PDF has a stamp, a staleness gate, a smoke check, a
byte-and-face drift canary and a recorded determinism digest. The site has `verify_web.py` — which
asserts one embed split and skips when there is no embed — and a build that must not 404. So the
chrome around the page, the layout of the page, and even a drawing torn in half by the Markdown
parser can all ship green. No. 17 is the sharpest case: the SAME source defect was fatal on the site
and nearly invisible in the PDF, and it was the PDF the family had instrumented.

None of the three was subtle once seen. All three needed someone to look.

### The generalisation

Nine of these eighteen are the same underlying error in different costumes: **the check and the
claim were about different things.** `make verify` answers "is the stamp fresh", not "is the PDF
right". A 200 answers "did something respond", not "is the right worker bound". A green
`wrangler deploy` answers "did the upload succeed", not "is the site serving this". Whenever a
check is cheap and the claim is broad, assume the gap is there and go look for it.

---

## Verification paths, stated honestly

The three new guides were verified by **different means**, and no phase upgraded a cited claim into
an executed one:

| Guide | Path | Evidence |
|---|---|---|
| `linux-terminal-guide` | **Executed** | Its own fenced examples extracted in order and replayed as two sequential sessions in a clean `ubuntu:24.04` container as a normal user — **50/50 claims matched exactly**. Only `xdg-open` skipped (needs a desktop session), and the guide says so in its own text. |
| `windows-powershell-guide` | **Split** | Every cmdlet, alias check and pipeline example executed in a PowerShell 7.4.2 container. The Windows-only surface — Start Menu launch, drive letters, `$env:USERPROFILE`'s value, the Unix-style aliases — **cited** to Microsoft docs. The guide states the split and flags that printed paths are Linux-shaped. |
| `windows-cmd-guide` | **Cited only** | `cmd.exe` is Windows-only with no Linux runtime, so **nothing was executed**. Every command carries a per-command citation to Microsoft's `windows-commands` docs, and the guide's first screen says the outputs are illustrative of documented behaviour rather than transcripts — with a test asserting it never claims execution. |

The container replay earned its keep: it found that the Linux guide's `cd` examples walked the
reader to `/home` and never brought them back, so every following command in that section failed
for anyone following along. It also confirmed three genuine macOS→Linux traps — `ls -G` means
`--no-group` on Linux (not colour), GNU `rm -i` prompts differently, and `less` is absent from a
base Ubuntu image.

---

## Post-plan changes

Work done after the Phase 22 gate closed, so this file stays the single account of what shipped.

| Change | Detail |
|---|---|
| Two more guides gained sites | `adopt-web.py`, secrets, deploy, custom domain, `workers.dev` disabled. One of them also needed topic-specific screen CSS (`table.journal`, `pre.ledger` with `overflow-x`, `table.figures`) so its ledger panels are styled on screen, not just in the PDF. `transforms.py` was untouched, so `make verify` stayed green and no re-baseline was needed. |
| Hub renamed and widened | GitHub repo, local clone, and worker name moved together, per the workspace rule that all three match. The page now covers every published site rather than the terminal guides alone. |
| A non-kit site joined the hub | A React quiz app rather than a single document, so it is linked site-only with no PDF. Its worker sets `not_found_handling: single-page-application`, so *every* path under it returns 200 with the app's HTML; a PDF link there would have passed a link check while serving HTML. Recorded in the hub's README so it is not re-added later. |
| Hub deploy moved into CI | The hub was the only site deployed by hand. It now has `.github/workflows/deploy.yml`, and its custom domain is declared in `wrangler.jsonc` (`routes` + `custom_domain: true`) instead of being bound out of band — a deliberate divergence from the guides, which each had their domain bound by hand, and the reason the hub's host needed no separate API call. Verification is split because of defects 12–13: content is asserted against `dist/index.html` before the deploy, and reading the live page back afterwards strengthens the check when the runner is not WAF-blocked. |
| Hub went live | Verified serving the hub (not the zone's wildcard placeholder), every authored link returning 200, and every PDF link returning `application/pdf`. |
| `workers.dev` turned off in config | `workers_dev: false` added to `templates/web/wrangler.jsonc` and synced to every guide. `preview_urls` is an independent toggle and was left alone. Verified: every guide now 404s on `*.workers.dev`, and every custom domain still serves 200. (The clause that used to sit here — "`deploy.yml`'s pull_request path depends on it for PR previews" — was true when written and is not now: the credentialed PR path has since been removed entirely, because a same-repository PR both receives secrets and controls the workflow file the run uses.) |
| PDF download fixed | `download` on both links, plus a new `.site-topbar` above the guide text. Chrome CSS is emitted from the build and concatenated *before* each guide's `style-screen.css`, because that file is target-owned and the alternative was the same rules hand-copied into every stylesheet. Cost at the time: it lived in `build.py`, a `SOURCE_FILES` entry, so every repo was re-baselined — content unchanged, stamp only. That cost is what motivated the `build.py` → `buildcore.py` + `render_*.py` split; the chrome now lives in `render_site.py`, outside the PDF's closure, and a screen-only change re-stales nothing. |
| Hub PDF links relabelled | Browsers **ignore `download` cross-origin**, and every PDF on the hub is on a different origin from the hub itself. The attribute would have been inert while the label kept promising a download, so the links now say "PDF" — what clicking actually does — and the honest download lives one click further in, on the guide's own page. |
| wrangler 4.103.0 → 4.114.0 | Cleared Dependabot's high-severity `sharp < 0.35.0` finding (four inherited libvips CVEs) across every kit repo at once — see [The Dependabot position](#the-dependabot-position). |
| Sidebar unified into one tree | The panel carried two flat lists — the server-rendered chapter list above a heading-derived one — and neither source had both facts, so neither could simply be dropped. Measured on the one-page view: at `chapter_level = 2` the two were near-duplicates (accounting, 49 headings vs 43 chapters + 6 parts) and at `chapter_level = 1` the heading list was strictly richer (mac-terminal, 14 of its 21 entries were sub-sections the chapter list has no notion of). They are now nested: the server list is the top level on **both** views, carrying each heading's pandoc id as `data-anchor`, and the script nests the current page's sub-headings under their chapter. On the one-page view every entry became an in-page anchor, which fixes a contents entry silently moving a reader into chapter mode. |
| A part label carries an anchor and is still not a link | Its heading is an `h1[id]` like any other, so it reaches the script's heading walk. Without the id the walk cannot tell a division from a sub-section, and the part's title and blurb are filed under whichever chapter preceded it. |
| Chapter-heading promotion moved to the AST | It was two string operations on rendered HTML and only one was anchored: `^\s*<h2` for the opening tag, then an unanchored `replace("</h2>", "</h1>", 1)` for the closing one. On a chapter that OPENS A PART the body begins with the part's own `<h1 class="part">`, so the anchored half matched nothing while the other rewrote the closing tag anyway — six of accounting-guide's 43 chapter pages shipped `<h2 id="…">…</h1>`. Invisible, because browsers discard the stray end tag. Promoting the `Header` block instead makes the two tags incapable of disagreeing, and deleted `_close_promoted_heading`. |
| The nav script is now EXECUTED by a test, not grepped | Every assertion about `WEB_NAV_JS` searched its source for literals, which catches deletion and renaming and not wrong logic. A cross-model review found an `aria-current` regression — scroll-spy overwriting the chapter page's `page` with the weaker `location` — that every literal assertion passed through. `tests/nav_dom.js` + `tests/test_nav_dom.py` run the real script in jsdom over a real rendered site; mutation-tested against three reintroduced defects, each caught by the case written for it. jsdom over a browser because it needs no binaries (11 MB vs chromium's 379 MB) and no `pixi.lock` change, which is a drift-canary trigger path. Its blind spot is layout, so the scroll-spy threshold and the drawer geometry stay hand-verified. |

**Repo visibility is deliberate.** The guide *sites* are public; `guide-kit` is public because
it is the kit. Whether any individual guide's *source* repo is public is an operational fact and is
not recorded here. The consequence that shapes the code is: the hub page links only repos known to
be publicly readable, because a link to a private repo 404s for every visitor.

---

## The Dependabot position

**Bump in the kit and sync down.** `app/package.json` and `app/package-lock.json` are
`bootstrap-source → identical`, so a guide does not own them. Merging a per-repo Dependabot PR
against either file puts that repo in permanent sync drift; the fix is made once in
`templates/web/` and copied out with `sync.py --apply`, and the superseded per-repo PRs are closed.

Applied twice so far: once for the original wrangler bump, once for wrangler 4.114.0 clearing the
`sharp`/libvips CVEs.

`deploy.yml`'s deploy job also skips `dependabot[bot]`. GitHub withholds repository secrets from
those PRs by design, so `CLOUDFLARE_API_TOKEN` is empty and the deploy can only ever fail — which
trains everyone to ignore a red check on exactly the PRs worth reading. `verify.yml` still runs on
them and needs no secrets, so the bump is still validated.

---

## Outstanding items

1. **A credential passed on a command line is a credential you have disclosed.** During this work a
   Cloudflare API token was supplied to a tool as a `--body` argument, which put it into a place
   neither the secret store nor the repository controls. **The lesson, which is the part that
   belongs in a public file:** an API token belongs in an environment variable read by the process
   that needs it, never in `argv`, never in a log, and never in a transcript. If one does escape,
   rotation is the only remedy — redacting the record does not un-disclose the value, and a
   document that *describes* a live credential's scope is itself a finding. Rotation status,
   token scopes, and which repositories hold which secrets are operational facts and are tracked
   outside this repository.
2. **Retiring a hostname in a wildcard zone does not 404 it.** Deleting a worker and its domain
   binding removes the binding, but because of defect 12 the retired hostname keeps answering
   **200 with the zone's generic placeholder** rather than telling anyone it moved — so every
   bookmark and inbound link silently lands somewhere wrong. A **Redirect Rule** from the retired
   name to its replacement is the fix, and it applies to any hostname this family retires.
3. ~~**One repo had open Dependabot alerts.**~~ **Resolved.** `npm audit` 12 → 0.
   Most cleared by resolving in-range (only the lockfile pinned the old versions). The rest was a
   transitive chain with no direct dependency to bump — `vite-plugin-pwa → workbox-build → ejs →
   jake → filelist` pulling `minimatch@5` and a vulnerable `brace-expansion@2` — fixed with an
   override **scoped to `filelist`**, since a tree-wide one would silently change resolution for
   `glob`. Two traps worth remembering: `npm audit fix --force` "fixed" this by *downgrading*
   `vite-plugin-pwa`, and `npm install --package-lock-only` silently ignored the override until the
   lock was rebuilt from scratch. Every repo in the family now reports **0 open alerts.**
4. **The command inventory is self-declared.** Each guide's `COMMANDS` list is in its own test file
   and is not cross-checked against the guide's Quick Reference table. Empty lists are rejected,
   which closes the worst case, but a guide could still under-declare.
5. **`guide.md` hygiene check has a blind spot.** The template-hygiene check
   (`buildcore._check_template_hygiene`, run on every build) scans only `README.md` and
   `CLAUDE.md`, so it cannot catch a `guide.md` still carrying the kit's placeholder content.
   It did not bite here — all three new guides were fully authored — but the check looks
   stronger than it is.
6. **`verify-render` is not a complete backstop.** It compares page count and stamp-stripped text,
   so it is blind to pure metric drift (kerning, justification, glyph substitution preserving line
   breaks), and its canonical-host-only status was convention, not enforced. **Superseded at the
   guide-kit stage-0+1 boundary:** `driftcanary.py` compares PDF bytes plus the `pdffonts` face
   list, runs in CI, and there is no canonical host left to be off. Kept here as the record of why
   the stronger check exists.
