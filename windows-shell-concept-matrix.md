# Cross-guide concept matrix: PowerShell vs Command Prompt

**Audience:** maintainers of `windows-powershell-guide` and `windows-cmd-guide`.
**Status:** authoritative. If a guide disagrees with this table, the guide is wrong.

Two Windows guides written by the same author disagreeing with each other is worse
than either being incomplete — a reader who consults both loses confidence in both.
This table fixes the shared semantics so they cannot drift apart, and it is the
**forcing function**: it was written by comparing the guides, and every gap it
exposed was closed by editing them, not by weakening a row.

This file is **kit-only** (`retained-in-kit`, no destination policy), so `sync.py`
never projects it into a guide and `bootstrap.py` prunes it from a fork. It is a
maintainer document, not reader-facing content.

---

## The matrix

| Concept | PowerShell guide says | cmd guide says | Agreed? |
|---|---|---|---|
| **Home / user folder** | `$HOME` and `~` in paths; `$env:USERPROFILE` for the environment variable | `%USERPROFILE%`; **no `~`** — cmd has no tilde notion | ✅ same folder, different spellings, each stated in its own guide's syntax |
| **Environment variable syntax** | `$env:NAME` | `%NAME%` | ✅ **never interchanged** — the PowerShell guide names `%USERPROFILE%` only inside a warning telling readers not to paste it |
| **Changing drive** | `Set-Location D:\Backups` — one step, drive and folder together | `cd /d D:\Backups`; plain `cd` will **not** cross drives, and `D:` alone switches drive | ✅ each guide notes the other's behaviour, so a reader moving between windows is not surprised |
| **Quoting** | Double quotes expand `$variables`; single quotes are literal | **Double quotes only**; `'` has no quoting meaning and is an ordinary filename character | ✅ both guides state that double quotes are the habit that is safe in either window |
| **Destructive delete** | `Remove-Item` — **no Recycle Bin, no undo**; `-Recurse` deletes a folder and contents; `-Confirm` prompts | `del` — **no Recycle Bin, no undo**; wildcards (`del *.txt`, `del *`) are the specific hazard; `/p` prompts; `rd /s` removes a folder and contents | ✅ identical warning in substance; each names its own hazard |

---

## Enforced mechanically

These are pinned by tests rather than left to review, because they are the rows
most likely to rot:

- `windows-powershell-guide/tests/test_topic_coverage.py::test_cmd_expansion_syntax_is_never_taught_as_powershell`
  — `%NAME%` may appear **only** inside a warning callout, and **never** inside a
  fenced example where a reader would copy it.
- `windows-cmd-guide/tests/test_topic_coverage.py::test_no_tilde_home_notation`
  — `~` appears nowhere in the cmd guide.
- The join's verification asserts the split directly: no `%USERPROFILE%` in the
  PowerShell guide's examples, no `$env:USERPROFILE` anywhere in the cmd guide.

## Disagreements this matrix exposed, and how they were resolved

Both were genuine gaps, found by writing the table rather than by reading:

1. **Quoting was in neither guide.** Not a disagreement so much as a shared blind
   spot — and quoting is where a beginner first meets a path with a space. Added
   to both, each in its own terms, with the cross-reference that double quotes
   are safe in both windows.
2. **Drive switching was only in the cmd guide.** The cmd guide correctly warned
   that `cd` alone will not cross drives; the PowerShell guide never mentioned
   drive switching at all, so a reader could not tell whether the same trap
   applied. Added to the PowerShell guide, stating plainly that `Set-Location`
   has no such trap, and cross-referencing the cmd behaviour.

## Verification status of the rows

The two guides were verified by different means, and the matrix must not launder
one into the other:

- **PowerShell guide** — cmdlets, the pipeline and quoting were executed in a
  PowerShell 7 container. Drive letters, `$env:USERPROFILE`'s Windows value, the
  Start Menu launch and the Unix-style aliases are **cited**, because the
  container runs on Linux.
- **cmd guide** — **nothing executed.** `cmd.exe` is Windows-only with no Linux
  runtime, so every command is cited to Microsoft's `windows-commands`
  documentation.

Accordingly, the **Changing drive** row is cited on both sides, and the
**Quoting** row is executed on the PowerShell side and cited on the cmd side.
