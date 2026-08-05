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
- region_end: 725
- region_lines: 690
- subsections: 17

Only 35 lines of `CLAUDE.md` sit outside the region; the managed block is effectively the
whole file. These bounds come from matching the marker **comments**
(`<!-- kit:begin -->` / `<!-- kit:end -->`), not a substring search for `kit:begin`, which
also matches prose naming the markers earlier in the file.

**The scan must be fence-aware.** A `## ` heading sits inside a fenced `::: slide` example at
line 500. A naive heading scan treats it as a section boundary, stops there, and reports a
462-line region with 10 subsections — 228 lines and seven subsections short. That reading was
made during planning and drove a wrong apportionment before this record existed.

## Apportionment

The question for each subsection is **when is this needed** — every session, only while
editing certain files, only while running a procedure, or never by a runtime at all.

| Lines | Subsection | Destination |
|---:|---|---|
| 6 | Shared kit policy (synced — do not edit per-guide) | resident |
| 18 | Per-guide values: `guide.toml` | resident |
| 22 | Build pipeline | resident |
| 14 | The version stamp | resident |
| 5 | Tone | resident |
| 98 | Markdown vs. HTML conventions | rule — `guide.md` |
| 9 | The transforms hook (per-output) | rule — `transforms.py` |
| 110 | The website's navigation chrome (script-built, screen only) | rule — site sources |
| 64 | The website (opt-in) | rule — site sources |
| 71 | The slide deck (opt-in) | rule — `guide.md`, slide sources |
| 60 | Verification: which command asks which question | skill |
| 31 | When to run `make baseline` / `make release` | skill |
| 35 | After editing | skill |
| 49 | Reference PDFs render anywhere — the drift canary is what keeps that true | README |
| 26 | Deploying, and the release protocol that was removed instead | README |
| 38 | The kit, the manifest, and `sync.py` | split — resident + README |
| 31 | Dependency drift, and the canary that catches it | split — rule + README |

**Two subsections split.** In both cases a rule a runtime must act on is wrapped around
material that only explains why.

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

| Destination | Lines |
|---|---:|
| resident (incl. one split's resident half) | **73** |
| path-scoped rules | 358 |
| skill | 126 |
| README | 130 |
| | 687 |

The 687 accounted for against a 690-line region is three lines the subsection spans do not
cover: the `kit:begin` comment at 36, the blank line at 37 before the first heading at 38, and
the `kit:end` comment at 725.

**What that produces:**

The three framing lines stay in the file, so they count toward every total below.

- `guide-kit/CLAUDE.md` — 35 own + 3 framing + 73 resident = **~111 lines**, under the
  200-line target.
- A guide's `CLAUDE.md` — ~96 own + 3 framing + 73 resident = **~172 lines**, under it.
- A guide session's unconditional startup — ~50 user + ~5 exe.dev rule + ~12 workspace + 172
  = **~239 lines**, under the plan's 250 limit, down from 980.

The margin on the session total is 11 lines, which is thin. If the resident core grows during
Phase 6, the session total is what breaks first — not the per-file limits, which have ~89
lines of headroom in the kit and ~28 in a guide.

## Note on the path-scoped rules

358 lines move into `.claude/rules/*.md` with `paths:` frontmatter. They load only when Claude
opens a matching file, so they do not count toward the startup total above — but they are not
free. Opening `guide.md` adds 169 lines to that session, because the Markdown conventions and
the slide-deck rules are both scoped to it; a session touching site sources adds 174. That is
the intended trade, and it is why the plan's criterion measures **unconditional startup**
rather than a session's peak.
