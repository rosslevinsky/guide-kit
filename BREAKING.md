# Breaking changes

Changes to the kit that require a guide's maintainer to **do something by hand**.
`sync.py` reads this file and prints the entries a guide has not seen yet, before
it writes anything.

## What belongs here

Only changes that a sync cannot repair on its own. In practice that is almost
always the same shape: the kit stops accepting something a guide's own file still
says.

That shape exists because of where sync draws its line. Sync overwrites kit-owned
files and **never** touches target-owned ones — `guide.toml`, `style.css`,
`style-screen.css` belong to the guide. So a sync can deliver a stricter
`kitconfig.py` while leaving in place the `guide.toml` it now rejects. Every step
behaves correctly and the guide stops building, with an error naming a file the
sync did not touch. Nothing about that is detectable from inside sync, which is
why it is written down instead.

New features, fixes and rewording do **not** belong here. A file nobody needs to
read is a file nobody reads.

## Format, which is load-bearing

Each entry starts with a full 40-character commit SHA and a date:

```markdown
## <40-hex-sha> — YYYY-MM-DD
One-line summary.

What to do about it.
```

`sync.py` parses those headings, so the SHA has to be the real, full commit the
change landed in — that is how it works out which entries a given guide has
already passed. Newest first. `tests/test_breaking_changes.py` checks the format
and that every SHA resolves in this repository's history.

---

## bcdb317ede8e7a0090658afd30ece43c60027864 — 2026-08-02
`[kit] min_version` removed; a `guide.toml` declaring `[kit]` now fails to load.

Delete the `[kit]` table from your `guide.toml`. It had one key, `min_version`,
which was validated, stored on the config object and read by nothing — so
removing it changes no behaviour. The load now fails rather than ignoring the
table, because `kitconfig` rejects unknown keys by design: a setting that quietly
does nothing is worse than one that is gone, since the guide that set it believes
it has stated a requirement.

No guide in the family declared it, so this entry repaired nothing. It is here
because nothing would have warned the guide that did.
