# Decomposition of the kit-managed `CLAUDE.md` region

What the managed region of `guide-kit/CLAUDE.md` contains, and where each part belongs once
it is apportioned between text that must load every session and text that should not.

Produced by Phase 1 of the `claude-md-consolidation` plan. `tests/test_claude_md_region.py`
pins the **measurements** below — the region bounds, each subsection's span, and that every
subsection has exactly one row carrying a destination — so an edit to `CLAUDE.md` that moves
a boundary fails rather than silently invalidating them. It deliberately does **not** pin
*which* destination a subsection is assigned, nor the budget totals: both splits divide a
subsection by judgement (~8/~30 and ~6/~25 lines), and asserting approximate figures exactly
would be false precision. Those are review's job, not the test's.

## Measured

- region_begin: 36
- region_end: 69
- region_lines: 34
- subsections: 3

Thirty-five lines of `CLAUDE.md` sit outside the region — its own content, untouched by the
split. These bounds come from matching the marker **comments**
(`<!-- kit:begin -->` / `<!-- kit:end -->`), not a substring search for `kit:begin`, which
also matches prose naming the markers earlier in the file.

**The scan must be fence-aware**, even though nothing in the region is fenced today. When it
was 690 lines a `## ` heading sat inside a fenced `::: slide` example; a naive heading scan
treated it as a section boundary, stopped there, and reported a 462-line region with 10
subsections — 228 lines and seven subsections short. That reading was made during planning
and drove a wrong apportionment before this record existed. The property is kept because the
next fence added to the region would reintroduce it silently.

## Apportionment

The question for each subsection is **when is this needed** — every session, only while
editing certain files, only while running a procedure, or never by a runtime at all.

| Lines | Subsection | Destination |
|---:|---|---|
| 10 | Shared kit policy (synced — do not edit per-guide) | resident |
| 5 | Tone | resident |
| 16 | Where the rest is | resident |

A second pass on 2026-08-07 asked the same question of the four subsections this table used
to call resident, and none of them survived it. `Per-guide values: guide.toml` is true while
`guide.toml` is open. `Build pipeline` and `The version stamp` are true while a build file
is open. `The kit, the manifest, and sync.py` was already mostly in the README; the one
sentence a session needs — the region is the kit's and a per-guide edit is overwritten —
folded into the preamble that was already saying it.

## What moved, and where

The split is done, in two passes. The region was **690 lines across 17 subsections**; the
first pass took it to 83 across 7, and the second to **31 across 3**. Those three are the
table above. The other fourteen went here:

| Was | Now |
|---|---|
| Markdown vs. HTML conventions (98) | `.claude/rules/guide-markdown-conventions.md` |
| The website's navigation chrome (110) + The website (64) | `.claude/rules/website.md` |
| The slide deck (71) | `.claude/rules/slide-deck.md` |
| The transforms hook (9) | `.claude/rules/transforms-hook.md` |
| Dependency drift — the instruction half (~6) | `.claude/rules/dependency-drift.md` |
| Verification: which command asks which question (60) | the `guide-build` skill |
| When to run `make baseline` / `make release` (31) | the `guide-build` skill |
| After editing (35) | the `guide-build` skill |
| Reference PDFs / the drift canary (49) | `README.md` |
| Deploying, and the release protocol removed instead (26) | `README.md` |
| Dependency drift — the rationale half (~25) | `README.md` |
| The kit/manifest/`sync.py` detail (~30 of 38) | `README.md` |
| The version-stamp rationale (~7) | `README.md` |
| Per-guide values: `guide.toml` (18) | `.claude/rules/guide-config.md` |
| Build pipeline (22) + The version stamp (8) | `.claude/rules/build-pipeline.md` |
| The kit, the manifest, and `sync.py` — the rest (8 of 11) | the preamble, and `README.md` |

**Three subsections were split**, each wrapping a rule a runtime must act on around material
that only explains why. The version stamp joined the other two during execution: its statement
of what the footer contains is resident, and its account of why the render path reads no git
history is README material by the same test.

*The kit, the manifest, and `sync.py`* carries the single most consequential sentence in the
file — the managed region is owned by the kit, and a per-guide edit is overwritten on the next
sync — around a description of the manifest's two classification axes that only matters when
changing the manifest. ~8 lines stay resident; ~30 go to the README.

*Dependency drift, and the canary that catches it* ends in direct instruction: treat a
`pixi.lock` change as a rendering change — run `make verify-render`, eyeball the PDF,
re-baseline if the layout moved, pin tighter in `pixi.toml` (`CLAUDE.md:713-718`). That is
something a runtime does, not something it reads about, so filing the whole subsection under
README would contradict the criterion above. ~6 lines become a rule scoped to `pixi.lock` and
`pixi.toml`; the remaining ~25 lines of rationale go to the README.

## Resulting budget

Measured after the split, not projected before it. The earlier projection is kept in *What
moved, and where* above; these are the files as they now stand.

| Where it went | Lines |
|---|---:|
| resident, in the managed region | **31** (+3 framing = 34) |
| `.claude/rules/` — seven files | 490 |
| `.claude/skills/guide-build/SKILL.md` | 136 |
| the kit's `README.md` | the remainder |

The rule and skill files are larger than the source subsections they carry: each gained
frontmatter, a heading and a sentence saying why it lives where it does. That cost is paid
only when the rule fires.

**What that produces:**

| | Lines |
|---|---:|
| `guide-kit/CLAUDE.md` (35 own + 34) | **69** |
| `accounting-guide/CLAUDE.md` (96 own + 34) | **130** |
| `git-guide/CLAUDE.md` — the largest (97 own + 34) | **131** |
| a guide session: 22 user + 6 exe.dev + 23 workspace + 130 | **181** |
| the same for `git-guide` | **182** |

Against limits of 200 per file and 250 per session, from 980.

The first pass left a two-line margin on the worst guide, and it did not hold: `git-guide`
reached 251 and nobody saw it, because the check was only ever run against three directories
someone typed by hand. That is fixed at both ends — the check now enumerates every repo, and
the margin here is 68 lines rather than 2. The remaining weight is the guides' **own** halves,
96 and 97 lines of rules about editing `guide.md` and `style.css`, which are per-guide content
and cannot move from the kit.

## Note on the path-scoped rules

490 lines sit in `.claude/rules/*.md` with `paths:` frontmatter. They load only when Claude
opens a matching file, so they do not count toward the startup total above — but they are not
free. Opening `guide.md` adds **184** lines to that session, because both the Markdown
conventions (106) and the slide-deck rules (78) are scoped to it; touching a site source adds
184 on its own; opening `style.css` now adds the 56-line build-pipeline rule. That is the
intended trade, and it is why the criterion measures **unconditional startup** rather than a
session's peak.

The two rules added in the second pass are the smallest so far — 35 and 56 lines — because
they carry one subject each. A rule that fires on `build.py` and also explains `guide.toml`
would cost every build session the config vocabulary it does not need, which is the same
mistake one level down.
