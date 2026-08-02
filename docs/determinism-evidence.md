# Determinism evidence

_Committed evidence, not a gate._ Actions logs and artifacts expire at 90 days, so
a claim that lives only in a CI run does not survive. Before this file, the
family's central determinism result existed only as prose in an unrelated plan's
as-built.

Captured 2026-07-26 on the `guide-kit/stage-0-1` integration branch, and
**re-measured after the boundary's single re-baseline** — see "What the
re-baseline changed" below.

## What is claimed here, and by whom

**The macOS/Linux byte-identity result is INHERITED, not re-measured.** It was
established by earlier work outside this repository, which rendered all eight
guides on both platforms and compared them; the owner then acted on it, moving
`baseline.yml` in all eight repositories to `ubuntu-latest`. **No macOS runner
was used for anything recorded in this file**, so that result is cited, not
asserted — and the document establishing it is not in version control, which is
precisely why the distinction is drawn here rather than glossed over.
(The `baseline_platform` config key that recorded the decision has since been
retired; what replaced it is `driftcanary.py`, which measures agreement instead
of declaring it.)

That distinction is the point of writing it down. Restating the result as though
this phase proved it would launder provenance, and the next person to question the
claim would have no route back to the run that actually supports it.

**The Linux half IS proved here, freshly and locally.** For each repository, two
fresh renders of the same committed source were produced back-to-back and their
sha256 compared. All eight pairs are byte-identical, and both digests are recorded
below so the comparison can be reconstructed rather than taken on trust.

## What the re-baseline changed

Every digest below moved, and the reason is worth stating rather than leaving as
an unexplained edit.

When this file was first written, every reference in the family was
**deliberately stale** — that is what the stage-0+1 promotion boundary is — so
the file explicitly did **not** claim that a fresh render matched the committed
reference. It could not: the comparison was not yet meaningful, and claiming it
would have been the kind of overclaim this file exists to avoid.

The re-baseline is what makes the comparison meaningful, and it
is recorded here as a third measurement per repository: **all eight fresh renders
are byte-identical to their committed references.** That is the same comparison
`driftcanary.py` makes on every CI run; this file is its first, dated result.

The two-render pair was re-measured at each repository's new commit rather than
carried forward, so the whole record is one coherent snapshot instead of digests
from two different trees. It has been re-measured the same way once since, when
the boundary review's fixes added `fonts/vendor/UPSTREAM-HASHES.json` to the PDF
closure and every reference moved. Recording digests rather than prose is what
made that visible at the time; the row is a dated measurement now, not a gate. The `deliberately stale` note that appeared on every
reference row is gone because it is no longer true.

### Why there is no "commit rendered" SHA — and what recovers the tree instead

The re-measurement was taken on the tree that **this commit creates**, and a
commit cannot contain its own SHA. The previous round could record one because it
changed no render input, so its parent rendered identically; this round changes `kitconfig.py`,
`guide.toml` and one guide's `style.css`, so a parent SHA here would name a tree
that produces a *different* PDF — a coordinate pointing at the wrong place, which
is worse than none.

Two identities are recorded instead, and the second exists because the obvious
first attempt was **not durable**:

- the **sha256 of the committed reference**. It identifies the artifact rather than the
  commit, and anyone holding that exact PDF can check it with `sha256sum` alone.
  The automated check that used to run here could not verify it that way — the file at that
  path is refreshed by `baseline.yml` after any content edit, so it read the bytes of the
  **recorded blob** out of git instead. That is a real limitation to state rather than
  gloss — the automated check needs the object database, and it establishes that the record
  is internally consistent and that the blob really was this repository's reference PDF,
  not that any file on disk today matches.
- the reference PDF's **git blob OID**, with `git log --all --format=%H
  --find-object=<blob>`. The first draft said `git log -1 --format=%H --
  <slug>.pdf`, which is wrong the moment there is a *later* re-baseline: that
  command returns the newest commit touching the path, not the one this record
  describes, and it degrades silently. `--find-object` searches for the exact
  blob, so it stays anchored to that artifact however many re-baselines follow —
  and if the blob is ever gone, it returns nothing rather than something
  plausible and false.

  **Read its output carefully: it lists every commit whose diff touches that
  blob, which means the commit that ADDED it and also the commit that later
  replaced it, newest first.** For the kit's own record the first
  line is `0fbc886c`, and that is the *removal* — the commit that superseded the
  recorded PDF. The one you want is the last line. So the OID is an anchor to an
  artifact, not by itself a coordinate for the tree that was measured; recovering
  that tree means picking the introducing commit out of the list.

One thing that surfaced while measuring, worth recording because it looks like a
determinism failure and is not: the version stamp carries a `· dirty` marker
derived from `git status` over the artifact's own closure. Two renders taken
either side of a `git add` therefore differ legitimately. The pairs below were
taken from a settled tree.

## Toolchain — TWO COHORTS, not one

`git-guide` and `mac-terminal-guide` differ from the other six in **both** Python
and fontconfig: `git-guide`, `mac-terminal-guide` run Python 3.14.4 with
fontconfig 2.17.1, while `guide-kit`, `accounting-guide`, `japan-guide`, `linux-terminal-guide`, `windows-cmd-guide`, `windows-powershell-guide` run Python
3.14.5 with fontconfig 2.18.0.

Each guide owns its own `pixi.lock` and it is never synced, because the lock is a
rendering input. Recording a single global toolchain would assert more uniformity
than the family has — and would be simply false for two of the eight. Per-repo
versions are in the table for each.

## Per-repository record

**Each record describes the tree it names — not `main` as it stands today.** That is why
every record leads with a blob OID: it is a coordinate you walk back from
(`git log --all --find-object=<oid>`), and it stays valid after the reference PDF has moved
on. Reference PDFs move often and legitimately — any content edit stales one, and
`baseline.yml` re-renders and commits a fresh one with no human involved — so a record that
still matched the current file would only mean nobody had edited anything since.

Do not "update" these digests to track the current reference. A record is refreshed only by
**re-running the measurement**, and then the whole row changes together: blob, both fresh
renders, and the committed-reference digest.

**THIS RECORD IS NO LONGER MACHINE-CHECKED, and deleting the tests that checked it was
the point rather than a concession.** `tests/test_determinism_evidence.py` verified that
each row's blob OID still resolved and that the three digests agreed with that blob's bytes.
Thirteen test functions — 62 cases once parametrised over every repository — and between them
they were policing the internal consistency of a historical note.

Two things made that worth stopping:

- **A live check had superseded it.** `driftcanary.py` renders afresh and compares PDF bytes
  plus the `pdffonts` face list against the committed reference — weekly on a schedule and on
  any `pixi.lock` change, in every repo. That is this document's claim, asked continuously,
  of the artifact that actually ships. A snapshot cannot compete with a standing measurement.
- **One row could not survive its own repository's rules.** The kit's own row names itself, and
  the kit is kept as a single amended commit, so every amend orphans its objects and the
  recorded OID stops resolving in a fresh clone. It duly did. The check passed for months only
  on machines whose clones still held pre-squash objects, and the first CI run after the
  squash found it — which is a fair description of a guard that was not doing any work.

So what remains here is **provenance prose**: what was measured, when, on which toolchain, and
why rendering became host-independent. Read it as a dated record, not as a live assertion. The
OIDs are still the honest coordinates they always were; some of them no longer resolve, and
nothing depends on whether they do.

**Each row used to carry a recovery command — `git log --all --find-object=<oid>` — and it has
been removed rather than corrected, because there is nothing to correct it to.** It does not
work even where the object survives: the kit's own blob still resolves with `git cat-file -t`,
and `--find-object` for it returns nothing, because the commit that introduced it was amended
away. For the other six rows the object is not in this repository at all. A command that names
a real technique and produces no output on every row in the table teaches the reader that the
document is unreliable, which is the opposite of what a provenance record is for.

**Six of the seven rows describe OTHER repositories**, which are private and which a reader of
this kit cannot open. They are kept because the cross-repository *agreement* is the measurement
— seven independent renders, one toolchain, one result each — and dropping them would leave a
claim about a family evidenced by one member. Read them as a dated note about how the
conclusion was reached, not as something you can re-run.

**Do not "update" a digest to track the current reference.** A record is refreshed only by
re-running the measurement, and then the whole row changes together — blob, both fresh
renders, and the committed-reference digest. A row edited to match today's file would name one
artifact and describe another.

### `guide-kit`

| field | value |
|---|---|
| reference PDF blob (git object) | `a52fa757aa1c1f0321e8956174c636f50cf88387` |
| theme | `editorial` |
| fresh render, sha256 | `b33bbd432829d41eb12cb8dabcfc28c1a6ed5f40ec093b2a4a7af487ae96a02d` |
| second render, sha256 | `b33bbd432829d41eb12cb8dabcfc28c1a6ed5f40ec093b2a4a7af487ae96a02d` — **identical** |
| committed reference `guide-template.pdf` | `b33bbd432829d41eb12cb8dabcfc28c1a6ed5f40ec093b2a4a7af487ae96a02d` — **identical to both fresh renders** |
| embedded faces | `Guide-Mono`, `Guide-Mono-Bold`, `Guide-Serif`, `Guide-Serif-Bold`, `Guide-Serif-Italic` |
| WeasyPrint / pandoc / qpdf | 67.0 / 3.9.0.2 / 12.3.2 |
| Python / fontconfig / fontTools | **3.14.5** / **2.18.0** / 4.63.0 |

### `accounting-guide`

| field | value |
|---|---|
| reference PDF blob (git object) | `a358b6fd4738916a0443f14f9178b6137c1f5c75` |
| theme | `classic-sans` |
| fresh render, sha256 | `81d6d923e1087fade0c20b57b548fb003ca0f71426f205b7bf7eb77aad0fd760` |
| second render, sha256 | `81d6d923e1087fade0c20b57b548fb003ca0f71426f205b7bf7eb77aad0fd760` — **identical** |
| committed reference `accounting-guide.pdf` | `81d6d923e1087fade0c20b57b548fb003ca0f71426f205b7bf7eb77aad0fd760` — **identical to both fresh renders** |
| embedded faces | `Guide-Sans`, `Guide-Sans-Bold`, `Guide-Sans-Bold-Italic`, `Guide-Sans-Italic` |
| WeasyPrint / pandoc / qpdf | 67.0 / 3.9.0.2 / 12.3.2 |
| Python / fontconfig / fontTools | **3.14.5** / **2.18.0** / 4.63.0 |

### `git-guide`

| field | value |
|---|---|
| reference PDF blob (git object) | `b54f837ccb711cde9f4bee6774786ba02a414973` |
| theme | `editorial` |
| fresh render, sha256 | `ad44b36837e403fc3640e469a71d0f4fa0a6c71c8fcb93d08eb30ad7970a178a` |
| second render, sha256 | `ad44b36837e403fc3640e469a71d0f4fa0a6c71c8fcb93d08eb30ad7970a178a` — **identical** |
| committed reference `git-github-for-beginners.pdf` | `ad44b36837e403fc3640e469a71d0f4fa0a6c71c8fcb93d08eb30ad7970a178a` — **identical to both fresh renders** |
| embedded faces | `Guide-Mono`, `Guide-Sans`, `Guide-Sans-Bold`, `Guide-Sans-Italic`, `Guide-Serif`, `Guide-Serif-Bold`, `Guide-Serif-Italic` |
| WeasyPrint / pandoc / qpdf | 67.0 / 3.9.0.2 / 12.3.2 |
| Python / fontconfig / fontTools | **3.14.4** / **2.17.1** / 4.63.0 |

### `japan-guide`

| field | value |
|---|---|
| reference PDF blob (git object) | `831bc45d9eff63d98b37e1641a4b45eeebdc384e` |
| theme | `classic-sans` |
| fresh render, sha256 | `e1857f4f5d51ca1d5e9a85f36e192e61fb8d723a2bff1c32cc5833003e035af5` |
| second render, sha256 | `e1857f4f5d51ca1d5e9a85f36e192e61fb8d723a2bff1c32cc5833003e035af5` — **identical** |
| committed reference `japan-guide.pdf` | `e1857f4f5d51ca1d5e9a85f36e192e61fb8d723a2bff1c32cc5833003e035af5` — **identical to both fresh renders** |
| embedded faces | `Guide-Sans`, `Guide-Sans-Bold`, `Guide-Sans-Italic` |
| WeasyPrint / pandoc / qpdf | 67.0 / 3.9.0.2 / 12.3.2 |
| Python / fontconfig / fontTools | **3.14.5** / **2.18.0** / 4.63.0 |

### `linux-terminal-guide`

| field | value |
|---|---|
| reference PDF blob (git object) | `4627e86f4fb998a05fe6074e84c7143900726188` |
| theme | `classic-sans` |
| fresh render, sha256 | `90d16e484515af9e74f22e20089d389dc861f570086ed6f588491233a0e31e40` |
| second render, sha256 | `90d16e484515af9e74f22e20089d389dc861f570086ed6f588491233a0e31e40` — **identical** |
| committed reference `linux-terminal-guide.pdf` | `90d16e484515af9e74f22e20089d389dc861f570086ed6f588491233a0e31e40` — **identical to both fresh renders** |
| embedded faces | `Guide-Mono`, `Guide-Mono-Bold`, `Guide-Sans`, `Guide-Sans-Bold`, `Guide-Sans-Italic` |
| WeasyPrint / pandoc / qpdf | 67.0 / 3.9.0.2 / 12.3.2 |
| Python / fontconfig / fontTools | **3.14.5** / **2.18.0** / 4.63.0 |

### `mac-terminal-guide`

| field | value |
|---|---|
| reference PDF blob (git object) | `a2978ccd35803e0926534f1d17338707dcaf5023` |
| theme | `classic-sans` |
| fresh render, sha256 | `400461355fd9f1c8cd91ff31fe116d30c1de14c463958fdc59d90bffaa6bfc47` |
| second render, sha256 | `400461355fd9f1c8cd91ff31fe116d30c1de14c463958fdc59d90bffaa6bfc47` — **identical** |
| committed reference `mac-terminal-guide.pdf` | `400461355fd9f1c8cd91ff31fe116d30c1de14c463958fdc59d90bffaa6bfc47` — **identical to both fresh renders** |
| embedded faces | `Guide-Mono`, `Guide-Mono-Bold`, `Guide-Sans`, `Guide-Sans-Bold`, `Guide-Sans-Italic` |
| WeasyPrint / pandoc / qpdf | 67.0 / 3.9.0.2 / 12.3.2 |
| Python / fontconfig / fontTools | **3.14.4** / **2.17.1** / 4.63.0 |

### `windows-cmd-guide`

| field | value |
|---|---|
| reference PDF blob (git object) | `d6b014254f6eccf3373d5e387c639625003ee708` |
| theme | `classic-sans` |
| fresh render, sha256 | `b364d802333eda53927139dfc7d1546ec6a10652377201ec7d63ffe2c4f26be9` |
| second render, sha256 | `b364d802333eda53927139dfc7d1546ec6a10652377201ec7d63ffe2c4f26be9` — **identical** |
| committed reference `windows-cmd-guide.pdf` | `b364d802333eda53927139dfc7d1546ec6a10652377201ec7d63ffe2c4f26be9` — **identical to both fresh renders** |
| embedded faces | `Guide-Mono`, `Guide-Mono-Bold`, `Guide-Mono-Italic`, `Guide-Sans`, `Guide-Sans-Bold`, `Guide-Sans-Italic` |
| WeasyPrint / pandoc / qpdf | 67.0 / 3.9.0.2 / 12.3.2 |
| Python / fontconfig / fontTools | **3.14.5** / **2.18.0** / 4.63.0 |

### `windows-powershell-guide`

| field | value |
|---|---|
| reference PDF blob (git object) | `a74dda1f14158b4f37f703375d5c06168e285859` |
| theme | `classic-sans` |
| fresh render, sha256 | `fc965bb6e4d8747d4daa39b7f494d61ff0f04bf5eb522158a79c00e13d15438b` |
| second render, sha256 | `fc965bb6e4d8747d4daa39b7f494d61ff0f04bf5eb522158a79c00e13d15438b` — **identical** |
| committed reference `windows-powershell-guide.pdf` | `fc965bb6e4d8747d4daa39b7f494d61ff0f04bf5eb522158a79c00e13d15438b` — **identical to both fresh renders** |
| embedded faces | `Guide-Mono`, `Guide-Mono-Bold`, `Guide-Sans`, `Guide-Sans-Bold`, `Guide-Sans-Bold-Italic`, `Guide-Sans-Italic` |
| WeasyPrint / pandoc / qpdf | 67.0 / 3.9.0.2 / 12.3.2 |
| Python / fontconfig / fontTools | **3.14.5** / **2.18.0** / 4.63.0 |

## Residual — what nothing permanently audits

The one-time PDF font-table audit (`pdfaudit.py`) proves which face each
**anchored** run actually selected. Nothing runs it on every build.

That gap is real and worth stating plainly. The permanent checks cover *coverage*
(is every codepoint drawable by a face the cascade reaches) and *computed
families* (does every box resolve to a bundled family). Neither notices a run
selecting the **wrong bundled face** — a heading falling back to the body face, or
a bold run resolving to the regular weight. Both satisfy `pdffonts`, and both
satisfy coverage, because the wrong face usually contains the glyph. After the
theme layer changed the cascade that is the live risk, and it is checked here once
rather than continuously.

The audit also reports, rather than assumes, what it cannot decode: non-`Identity-H`
encodings, simple (non-Type0) fonts, and a non-identity `/CIDToGIDMap`. On this
family it currently reports none — every font is Type0/Identity-H with an identity
CID→GID mapping.
