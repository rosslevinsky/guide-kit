# Bundled fonts

These files are committed so a rendered PDF does **not** depend on what the host OS has
installed. That is the whole point: with system-font stacks the same `guide.md` renders
differently on macOS (Helvetica Neue), Windows (Segoe UI) and Linux (DejaVu/Liberation),
which is why reference PDFs were historically pinned to one canonical host recorded in
`guide.toml`. Bundling removed the variable, and that key is now retired — CI's drift
canary measures host agreement rather than a config key asserting it.

`build.py` calls WeasyPrint with `base_url=ROOT`, so the relative `url()` references in
`style.css`'s `@font-face` block resolve against this directory.

## Provenance

Every file below was extracted from an upstream release archive, unmodified.

| Family | Version | Archive | SHA-256 of archive |
|---|---|---|---|
| Source Serif 4 | 4.005R | [`source-serif-4.005_Desktop.zip`](https://github.com/adobe-fonts/source-serif/releases/download/4.005R/source-serif-4.005_Desktop.zip) | `549fdb8f9a682bd06944298621404969f6de77c2e422ff3b8244a1dcd6a0c425` |
| Source Sans 3 | 3.052R | [`OTF-source-sans-3.052R.zip`](https://github.com/adobe-fonts/source-sans/releases/download/3.052R/OTF-source-sans-3.052R.zip) | `a4ebbdea20b08ccbd7bf3665a9462454eefdd01d9a6307129d3b3d4672981074` |
| DejaVu | 2.37 | [`dejavu-fonts-ttf-2.37.zip`](https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip) | `7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a` |

## The faces, and why each one is here

| File | Role |
|---|---|
| `SourceSerif4-Regular.otf` / `-It` / `-Bold` / `-BoldIt` | Body text. Four real faces rather than two — WeasyPrint will synthesize (skew for italic, smear for bold) if a face is missing, and synthesis is deterministic but ugly. |
| `SourceSans3-Regular.otf` / `-Semibold` / `-It` / `-SemiboldIt` | Headings, callout headers, footers — and BODY text in six of the seven guides, which is why all four Roman/Italic × Regular/Bold faces ship rather than three. An `<em>` inside a CSS-bolded run (a table header, a callout header) asks for 700 italic; without that face WeasyPrint matches style first, lands on the 400 italic and smears a synthetic bold over it. Semibold (not Bold) is the heading weight. |
| `DejaVuSansMono.ttf` / `-Bold` / `-Oblique` | Code and `<pre class="diagram">`. Chosen over the Source family because it has **complete box-drawing coverage (U+2500–257F) at exact monospace advance width** — the diagram panels depend on adjacent box characters connecting seamlessly, and most programming fonts have gaps there. |
| `DejaVuSans.ttf` / `-Bold` | Last-resort fallback for arrows (U+2190–21FF) and miscellaneous symbols, where the Source families thin out. Every font stack in `style.css` terminates here rather than in a generic `serif`/`sans-serif`, so the cascade can never reach a system font. |

## Licenses

- Source Serif 4 — SIL OFL 1.1 (`LICENSE-SourceSerif4-OFL.md`)
- Source Sans 3 — SIL OFL 1.1 (`LICENSE-SourceSans3-OFL.md`)
- DejaVu — Bitstream Vera + Public domain (`LICENSE-DejaVu.txt`)

All three permit redistribution. The OFL requires the license text to travel with the
font files, which is why these are committed alongside rather than linked.

## Changing anything in here

These files are inputs to the rendered PDF, so they belong to the artifact's source
closure: swapping a font must re-stale the reference PDF exactly as editing `guide.md`
does. Add or replace a face and the version stamp must move.
