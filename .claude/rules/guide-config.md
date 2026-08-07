---
paths:
  - "guide.toml"
  - "kitconfig.py"
---

# Everything a guide says about itself

`guide.toml` is the only place a guide states its own values. It is read and validated by
`kitconfig.py`, the single strict loader, which **rejects unknown keys** — so a retired or
misspelled key fails loudly instead of quietly doing nothing.

Six identity constants: `TITLE`, `OUTPUT_SLUG`, `AUTHOR`, `DESCRIPTION`, `KEYWORDS`,
`COPYRIGHT_YEAR`. Alongside them the declared shape and its supporting tables: `[outputs]`,
one `[artifacts.<name>]` edition date per declared output, `[theme]`, `[site]`, `[slides]`,
`[deploy]` and `[fonts]`.

The kit README's "Every key, in one config that loads" block is the whole vocabulary, and a
test feeds that block to the real loader, so the documentation cannot drift away from the
schema without failing.

## Three things that look like mistakes and are not

**No renderer holds a guide-specific literal.** They all read through `kitconfig`. If you
are about to type a guide's name into a `render_*.py`, the value belongs in `guide.toml`.

**The four `LICENSE_*` constants stay in `buildcore.py`.** They are family-fixed, not
per-guide, so they are deliberately not in this file.

**`OUTPUT_SLUG` is independent of the repo name.** It names the file a reader downloads and
the deployed worker — a repo directory called `git-guide` can correctly render
`git-github-for-beginners.pdf`. Do not "fix" one to match the other.

`COPYRIGHT` is derived as `© {COPYRIGHT_YEAR} {AUTHOR}` — a stored constant, never a clock
read, so renders stay deterministic.
