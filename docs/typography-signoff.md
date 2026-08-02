# Typography sign-off — the boundary's single re-baseline

_Recorded 2026-07-26, at the close of the guide-kit stage-0+1 promotion boundary. The
rule it closes: **the family is re-baselined exactly once, here** — one deliberate
movement of every reference PDF, reviewed by a human, rather than a drip of
unexamined re-renders._

The planning documents behind this work were never version-controlled and are not
in this repository. Nothing here points at them: where a decision matters it is
stated in full below, because a record that can only be read alongside a document
nobody else has is not a record.

The same rule applies to the guide repositories this sign-off covers. They are
named — the measurement was across the family and saying so is the point — but no
command in this file is written as though it could be run here against them, and
no commit in one of them is cited by SHA. A citation a reader cannot resolve is
worse than a description they can understand.

This is the artifact that exists to make someone **look**. Every automated gate in
this family passed on the render that shipped [recorded defect
8](family-as-built.md) — footer text wrapped onto a second line on every page of
three guides — and it was found by opening the PDF. So the machine checks below
are recorded as *supplements*; the inspection table is the sign-off.

## What is being approved

Not a font migration. The move onto bundled faces already happened, before this
plan began executing, and every reference in the family was already free of
proprietary faces. What this boundary added is a **theme layer**, and what a reader is
being asked to approve here is each guide's **theme selection** — a
typography choice over an already-bundled family, compared theme-to-theme.

Alongside it: the closure and stamp changes from phases 1–3 (the stamp grammar
moved from `YYYY-MM-DD HH:MM:SS · <hash>` to `YYYY-MM-DD · <hash>`, an *edition*
date rather than a commit timestamp), the flat `fonts/` → `fonts/vendor/` move,
hermetic rendering via `fontconfig/fonts.conf`, and the colophon line naming the
bundled families.

## The result in one line

**Seven of the eight guides are typographically unchanged.** `classic-sans` was
built to approximate the family's existing appearance — serif-versus-sans is a
per-guide theme choice, not a family-wide one — and it does: identical page counts, identical embedded-face sets, identical
extracted text. The kit itself is the one guide whose appearance genuinely moved,
by design.

## Per-guide record

Page counts are old → new. "Faces" is the `pdffonts` embedded-face set with
subset prefixes stripped. Digests are sha256, first 16 hex.

| Guide | Theme | Pages | Faces | Appearance |
|---|---|---|---|---|
| `guide-kit` | **editorial** | 4 → 4 | Guide-Serif (+Bold, Italic), Guide-Mono (+Bold) | **CHANGED** — body face moved sans → serif; `Guide-Sans`/`Guide-Sans-Bold` no longer embedded |
| `accounting-guide` | classic-sans | 51 → 51 | Guide-Sans (+Bold, Italic, Bold-Italic) | unchanged |
| `git-guide` | **editorial** | 28 → 28 | Guide-Serif (+Bold, Italic), Guide-Sans (+Bold, Italic), Guide-Mono | unchanged — it was already serif-bodied; the theme names what it already was |
| `japan-guide` | classic-sans | 8 → 8 | Guide-Sans (+Bold, Italic) | unchanged |
| `linux-terminal-guide` | classic-sans | 13 → 13 | Guide-Sans (+Bold, Italic), Guide-Mono (+Bold) | unchanged |
| `mac-terminal-guide` | classic-sans | 11 → 11 | Guide-Sans (+Bold, Italic), Guide-Mono (+Bold) | unchanged |
| `windows-cmd-guide` | classic-sans | 11 → 11 | Guide-Sans (+Bold, Italic), Guide-Mono (+Bold, Italic) | unchanged |
| `windows-powershell-guide` | classic-sans | 16 → 16 | Guide-Sans (+Bold, Italic, Bold-Italic), Guide-Mono (+Bold) | unchanged |

| Guide | old sha256 | new sha256 |
|---|---|---|
| `guide-kit` | `2a09da6dcb1576a2` | `b33bbd432829d41e` |
| `accounting-guide` | `b298d4ed34b223a2` | `58d89bc0376d34f2` |
| `git-guide` | `1125b112c22386ef` | `ad44b36837e403fc` |
| `japan-guide` | `e1b385175d3debff` | `ddaf30a8b8e058c2` |
| `linux-terminal-guide` | `5ad88124096d452b` | `90d16e484515af9e` |
| `mac-terminal-guide` | `56f343af07348fe2` | `400461355fd9f1c8` |
| `windows-cmd-guide` | `e4a53c3fd7035cf1` | `2e41bdf3cf096833` |
| `windows-powershell-guide` | `8ed43b8235b7a0d5` | `ab1306c92bc11703` |

Every digest changed even where appearance did not, because the footer stamp
grammar changed and the colophon gained a line. That is the expected shape of a
re-baseline that is mostly *not* a redesign.

## Pages actually inspected

Rendered at 100 dpi with `pdftoppm` and looked at. Anchors were chosen by
measurement, not by eye: the widest laid-out line per guide (excluding the
colophon, whose long licence URL is always the widest line in the document), the
page with the most table rules, and the page with the most non-ASCII symbols.

| What | Where | Finding |
|---|---|---|
| Title page + title block | `guide-kit` p1, `accounting-guide` p1, `japan-guide` p1 | Correct. Title, tagline, rules all in place. |
| Footer stamp, not wrapped | every inspected page, all 8 guides | `<title> · YYYY-MM-DD · <hash12> · Page N` on **one line** in all 8. This is recorded defect 8's failure mode and it does not recur. |
| Longest table | `guide-kit` p2 (markup table), `accounting-guide` p16 (Income Statement), `accounting-guide` p50 (cheat-sheet tables), `git-guide` p6 | Header fills, rules, alternating tint and column alignment all correct. Numeric columns right-aligned; `(24,000)` parentheses intact. |
| Widest code block | `linux-terminal-guide` p6, `windows-powershell-guide` p9, `git-guide` p6 | Monospace panel, grey background, correct advance widths — column-aligned `Name`/`Length` output stays aligned. |
| Inline SVG diagram | `git-guide` p6 (working directory → staging area → repository) | Renders. Boxes, arrows, and the U+00A0-separated labels all present and legible. |
| Callouts | `guide-kit` p2 (warn / tip / accent, all three), `windows-powershell-guide` p9 (accent) | Backgrounds, left bars, bold headers correct in all variants. |
| Non-Latin text | `japan-guide` p5, `accounting-guide` p50 | See the note below — the family has **no CJK**. What it has renders: `Ryōanji`, `Togetsukyō` (U+014D), and accounting's `± × ÷ ↑ → − ≈ ≠ ≥ ✓ § ¢`. |
| Colophon | all 8, last page | The new "Typeset in DejaVu Sans, DejaVu Sans Mono, Source Sans 3 and Source Serif 4" line is present and correct. |

### The "non-Latin text" anchor, corrected

The phase asked for anchored pages covering "any non-Latin text". Measured: **no
guide in this family contains a single CJK codepoint**, and all eight declare
`cjk = []`. `japan-guide` is an English guide *about* Japan, not a Japanese-language
one. So the anchor was read as its real intent — codepoints outside plain ASCII,
which are the ones a bundled face is most likely to lack — and satisfied against
`japan-guide`'s macron vowels and `accounting-guide`'s 509 mathematical, currency
and arrow symbols. Both render.

## Machine checks (supplements, not the sign-off)

| Check | Result |
|---|---|
| Blank pages, title present, no placeholders | `make smoke` PASS on all 8 committed references |
| Footer stamp not wrapped | geometric detector inside `make smoke` — PASS on all 8 |
| Horizontal overflow past the text column | 0 words in 7 guides. **3 in `windows-powershell-guide`** — see below |
| Box-drawing advance widths | Not applicable: **zero** U+2500–257F codepoints survive in any guide (all diagrams are inline SVG). The kit keeps `line-height: 1` as a preventive rule asserted against a fixture. |
| Proprietary faces | 0 matches for `Hiragino\|Andale\|Helvetica\|Georgia\|Menlo\|Times` across all 8 |
| Stamp-excluded text, old vs new | Identical in all 8 except the one added colophon line |
| Fresh render vs committed reference | `make drift-canary` PASS, byte-identical, in all 8 |

### Pre-existing defect, NOT introduced here

`windows-powershell-guide` has **three words that overflow the 558 pt text
column**: `"/root/practice/notes".` on p8 (xMax 564.6) and `Name` on p9 and p13
(xMax 576.8 and 577.5) — long unwrappable code lines running past the right
margin. Verified against the pre-re-baseline reference at identical coordinates:
**3 before, 3 after, same pages, same x-positions.** It is a content defect in
that guide, unchanged by the theme migration, and deliberately left for its own
change rather than fixed inside the promotion boundary.

## A defect this re-baseline DID catch

`accounting-guide` would not baseline at all. `make baseline` refused with
"fresh render has no readable version stamp", and the fresh render was **A4, 47
pages** against a committed reference of **Letter, 51 pages**.

Cause: a phase-8 commit in `accounting-guide` ("Migrate the override font stacks
to the bundled families") over-deleted. Its SHA is deliberately not cited: it
names a commit in a DIFFERENT repository, so `git cat-file -t <sha>` here answers
"Not a valid object name" — a citation that looks checkable and is not. Its intended change was removing the
`@font-face` block from the guide's `style.css`, but the hunk ran on and also took
`@page { size: Letter; margin: …; @bottom-left { … } }`, replacing it with the
explanatory comment. That left `@bottom-center` and `@bottom-right` orphaned
outside any `@page` block — so the page size fell back to WeasyPrint's A4 default
and **no footer stamp was emitted at all**.

Three things are worth recording about it:

- **It was latent for two phases.** Nothing re-rendered `accounting-guide`
  between the re-baseline and here, and inside this boundary a stale reference is the
  expected state, so no check was in a position to notice.
- **Brace balance would not have caught it.** The deletion removed a matched
  `{`/`}` pair; the file parsed as balanced CSS the whole time. Only rendering
  revealed it.
- **The guard worked.** `promotable_stamp` refused to promote a render whose stamp
  it could not read, rather than blessing a stampless 47-page A4 PDF as the
  reader-facing deliverable.

The `@page` block was restored byte-identically from that guide's own `main` —
`git show main:style.css` **run in `accounting-guide`**, which is worth spelling
out because the same command in this repository silently reads a different file
and reports agreement about nothing — and the guide re-rendered to 51 pages,
Letter, stamp present.

## What this sign-off does not cover

- **Cross-platform agreement.** Everything above was measured on Linux. The
  macOS/Linux byte-identity result is inherited from an earlier measurement made
  outside this repository, and is cited rather than re-measured here — see
  [determinism-evidence.md](determinism-evidence.md), which is careful about the
  same distinction and says exactly which half is proved.
- **Content correctness.** This is a typography sign-off. It says the pages look
  right; it does not say the guides are right.
