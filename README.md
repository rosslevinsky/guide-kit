# {{GUIDE_NAME}}

> _This README is a minimal-viable skeleton. The full content — install / build / edit walkthrough, rename-your-fork checklist, baseline workflow, verify harness section — lands in phase 5._

A single-document beginner-guide PDF, authored in Markdown (`guide.md`) and rendered to PDF via pandoc + WeasyPrint.

## Quick start

```bash
pixi install     # one-time dependency setup
make             # render the PDF
make html        # render a standalone HTML preview (faster than PDF for iteration)
```

The rendered PDF lands at `{{GUIDE_SLUG}}.pdf` at the repo root.

## Getting started from this template

If you just created a new repo from this template via `gh repo create --template rosslevinsky/guide-template`, see the full rename-your-fork checklist in `CLAUDE.md`. (Coming in phase 5 of the template bootstrap.)

## License

Dual-licensed:

- **Code** (build scripts, CSS, configuration) — [Apache License 2.0](LICENSE).
- **Content** (`guide.md` and the rendered PDF) — [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-CONTENT).
