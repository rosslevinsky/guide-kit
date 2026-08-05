---
paths:
  - "pixi.lock"
  - "pixi.toml"
---

# A dependency change is a rendering change

Treat a `pixi.lock` change as a **rendering** change: run `make verify-render`, **eyeball
the PDF**, re-baseline if the layout moved, and pin tighter in `pixi.toml` if a guide needs
a narrower window. `fontconfig` already differs across this family, so a lock refresh can
move one guide's pagination and not another's.

`make verify` compares hashes over `SOURCE_FILES`, and `pixi.lock` is **not** in that list —
so a dependency bump that changes how WeasyPrint or fontconfig lays out text shifts the
rendered PDF while `make verify` stays green. The reasoning behind that gap, and the canary
that closes it, are in `README.md`.
