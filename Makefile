# The output slug — drives the filenames `make`, `make verify`, `make baseline`,
# and `make clean` operate on. Must match `OUTPUT_SLUG` in build.py; if you
# change one, change the other. Fork-author edit point (see README's
# "Getting started from this template" section).
OUTPUT_SLUG := guide-template

.PHONY: build help all install html verify baseline clean

# `build` is the FIRST non-.PHONY target, so bare `make` builds.
# Intentional divergence from mac-terminal-guide / git-guide, which default to `help`.
# Rationale: the most common operation in a guide repo is "render after edit"; bare
# `make` should do that without ceremony. `make help` still works for discovery.
build:
	pixi run build

help:
	@echo "Targets:"
	@echo "  make            Build the PDF (default; writes $(OUTPUT_SLUG).pdf at repo root)"
	@echo "  make html       Render a standalone HTML for browser preview"
	@echo "  make verify     Check that the freshly-built PDF matches baseline.pdf"
	@echo "  make baseline   Overwrite baseline.pdf with the freshly-built PDF (use deliberately)"
	@echo "  make install    Install all dependencies via pixi"
	@echo "  make clean      Remove the rendered PDF and HTML preview"
	@echo ""
	@echo "All targets delegate to pixi. Install pixi first: https://pixi.sh"

all: build

install:
	pixi install

html:
	pixi run html

# verify depends on build so a fresh render is always compared to the baseline.
verify: build
	pixi run python verify_pdf.py baseline.pdf $(OUTPUT_SLUG).pdf

# baseline overwrites the committed reference PDF with the fresh render. `cp`
# (not `mv`) so the just-built PDF stays on disk for visual review. Use
# deliberately, only after eyeballing the new PDF — this silently re-blesses
# any rendering regression. After running, commit baseline.pdf together with
# the source files that changed it via the amend workflow (see CLAUDE.md).
baseline: build
	cp $(OUTPUT_SLUG).pdf baseline.pdf
	@echo "  baseline -> baseline.pdf (commit it together with source changes)"

clean:
	rm -f $(OUTPUT_SLUG).pdf $(OUTPUT_SLUG).html
	rm -rf verify-diff/
