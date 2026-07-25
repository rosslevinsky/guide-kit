# Guide family: as-built

_The decision record for the guide family — what was built, what diverged from the plan, what broke
and how it was caught. **Kit-only:** `bootstrap.py` prunes `docs/` from a fork, so this never lands
in a guide repo._

**Why it lives here.** This began as `as-built.md` inside the workspace-level
`plans/guide-family-expansion/` directory, which is not under version control — the one account of
*why* the family is shaped this way existed on a single machine's disk. The kit is versioned,
public, and the thing every guide already points at, so the record moved to it. The plan documents
it refers to (`plan.md`, `execution.md`, the phase docs) stayed behind and are cited by name below;
nothing here depends on being able to open them.

---

## Outcome

All 22 phases of the guide-family-expansion plan complete. `guide-template` is a reusable kit;
seven guides are synced to it with zero drift; every guide has a public site collected by a hub;
every reference PDF in the family is macOS-rendered and current.

### Final gate results (as recorded at the Phase 22 gate)

| Assertion | Result |
|---|---|
| Kit suite | **216 passed** |
| Guide-local suites (3) | **9 passed** |
| Seven sync targets: zero drift, `state=applied` | **all 7** |
| `make verify` across eight PDF-building repos | **all 8 green** |
| `guide-template` still a template repo | **true** |
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
`baseline_platform = "darwin"` guard passes natively), proves it fresh, and commits it.

**Consequence:** Handoffs 0, 1 and 2 were all completed in-run, so **no phase ended blocked** and
the plan ran to completion without a Mac. The eight PDF commits attributed to "the human at the
gate" were made by CI.

### 2. `workers.dev` was never the deployment target

`plan.md:166` set "a `workers.dev` subdomain exists on the account" as a prerequisite. Verified
live: the account's existing Workers have `workers.dev` **disabled** and serve on custom domains in
the `speedytuna.com` zone. The real prerequisite is the zone, which already existed. Every site
follows the family convention — custom domain bound against the zone, `workers.dev` disabled
per-script.

### 3. The kit freeze was lifted twice, deliberately

`execution.md` froze `guide-template` from Stage 9 through Stage 11, with kit defects to be fixed in
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

`linux-terminal.speedytuna.com` (the user chose `linux-terminal` over `linux`),
`powershell.speedytuna.com`, `cmd.speedytuna.com`. The hub was
`terminal-guides.speedytuna.com` and is now `guides.speedytuna.com`. The zone apex was already in
use, so the hub takes a subdomain matching its repo name.

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
| 12 | The `speedytuna.com` zone has a **wildcard DNS record**: every subdomain resolves and answers 200 with a "Speedy Tuna" placeholder, *including names bound to nothing*. Any deploy check asserting a 200 on a `*.speedytuna.com` hostname therefore verifies nothing — only page **content** distinguishes a bound worker from the placeholder | Probing `definitely-not-bound-xyz.speedytuna.com` while diagnosing #13 |
| 13 | The zone's **managed WAF blocks GitHub Actions runner IPs**. A runner gets 403 on every request while the identical request from elsewhere gets 200 — so a workflow cannot read its own deployed site back. Diagnosed only after two wrong guesses (unset secret, then first-time domain provisioning) and a pointless retry-window widening | 15 CI attempts over 5 minutes all 403, against 10/10 200s from outside |

Nos. 3–8 are all the same shape: **a green check that verified nothing.** None was reachable by the
test suite, because each lived in workflow trigger semantics, exit-code plumbing, or rendered
layout.

Nos. 12–13 are the mirror image and worth naming separately: **a red check that means nothing.** A
check that fails for a reason unrelated to the code teaches people to ignore it just as thoroughly
as one that passes without looking. The resolution in both cases was to move the assertion to where
it can actually run — the hub's content is now asserted against `dist/index.html` *before* the
deploy, and reading the live page back is a bonus that strengthens the check when the runner is not
blocked, rather than a gate that fails when it is.

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
| `git-guide` gained a site | <https://git.speedytuna.com> — `adopt-web.py`, secrets, deploy, custom domain, `workers.dev` disabled. |
| `accounting-guide` gained a site | <https://accounting.speedytuna.com> — same sequence, plus accounting-specific screen CSS (`table.journal`, `pre.ledger` with `overflow-x`, `table.figures`) so the 14 journal tables and 11 ledger panels are styled on screen, not just in the PDF. `transforms.py` was untouched, so `make verify` stayed green and no re-baseline was needed. |
| Hub renamed and widened | `terminal-guides` → `guides` (GitHub repo, local clone, and worker name moved together, per the workspace rule that all three match). The page now covers **all eight** public sites: the four terminal guides as one group, then Git & GitHub, accounting, Japan, and romance-languages as sections of their own. New host: `guides.speedytuna.com`. |
| `romance-languages` joined the hub | It is **not** kit-built — a React quiz app, not a single document — so it is linked site-only with no PDF. Its worker sets `not_found_handling: single-page-application`, so *every* path under it returns 200 with the app's HTML; a PDF link there would have passed a link check while serving HTML. Recorded in the hub's README so it is not re-added later. |
| Hub deploy moved into CI | The hub was the only site deployed by hand. It now has `.github/workflows/deploy.yml`, and its custom domain is declared in `wrangler.jsonc` (`routes` + `custom_domain: true`) instead of being bound out of band — a deliberate divergence from the guides, which each had their domain bound by hand, and the reason `guides.speedytuna.com` needed no separate API call. Verification is split because of defects 12–13: content is asserted against `dist/index.html` before the deploy, and reading the live page back afterwards strengthens the check when the runner is not WAF-blocked. |
| Hub went live | <https://guides.speedytuna.com> — verified serving the hub (not the zone's wildcard placeholder), all 18 authored links returning 200, and every PDF link returning `application/pdf`. |
| wrangler 4.103.0 → 4.114.0 | Cleared Dependabot's high-severity `sharp < 0.35.0` finding (four inherited libvips CVEs) across all eight kit repos at once — see [The Dependabot position](#the-dependabot-position). |

**Repo visibility is unchanged and deliberate:** all eight guide *sites* are public; the *repos*
that build them stay private, with `guide-template` the single public exception. The hub page may
therefore link **only** `guide-template` — a guide's own repo link would 404 for every visitor.

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

1. **Cloudflare API token rotation (user action).** The token used throughout was passed via a
   `--body` flag and is in the session transcript. It is live and scoped to Workers Scripts + the
   `speedytuna.com` zone. Eight repos hold Cloudflare secrets, and `japan-guide` /
   `romance-languages` carry values predating this work — so at least two distinct tokens are in
   play. Minting one fresh token and rolling it across all of them would consolidate and retire the
   leaked value.
2. **The old `terminal-guides` worker still exists.** The hub is live at
   <https://guides.speedytuna.com>, but the superseded worker and its
   `terminal-guides.speedytuna.com` binding were never removed — they still serve the old
   four-guide page, so the family currently publishes two hubs, one of them stale. Removing it
   needs a write-scoped Cloudflare token: the OAuth-backed Cloudflare MCP is **read-only** for
   Workers (it enumerates scripts and domains but is refused `10000` on `assets-upload-session`,
   and cannot mint a token — `9109`), so this is a `wrangler delete --name terminal-guides` for
   whoever holds the token.
3. **`romance-languages` has 17 open Dependabot alerts, 6 high** (`ws`, `brace-expansion`,
   `fast-uri`, `@babel/plugin-transform-modules-systemjs`, plus medium `vite` and low `undici`). It
   is not a kit target — its own Vite/React toolchain — so `sync.py` cannot reach it and it needs
   its own bump plus a real build-and-test run. It is a public site linked from the hub.
4. **The command inventory is self-declared.** Each guide's `COMMANDS` list is in its own test file
   and is not cross-checked against the guide's Quick Reference table. Empty lists are rejected,
   which closes the worst case, but a guide could still under-declare.
5. **`guide.md` hygiene check has a blind spot.** `build.py`'s template-hygiene check scans only
   `README.md` and `CLAUDE.md`, so it cannot catch a `guide.md` still carrying the kit's
   placeholder content. It did not bite here — all three new guides were fully authored — but the
   check looks stronger than it is.
6. **`verify-render` is not a complete backstop.** It compares page count and stamp-stripped text,
   so it is blind to pure metric drift (kerning, justification, glyph substitution preserving line
   breaks), and its canonical-host-only status is convention, not enforced. Documented in the kit's
   managed region.
