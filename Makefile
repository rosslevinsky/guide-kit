.PHONY: build help all install html verify baseline clean

# `build` is the FIRST non-.PHONY target, so bare `make` builds.
# Intentional divergence from mac-terminal-guide / git-guide, which default to `help`.
# Rationale: the most common operation in a guide repo is "render after edit"; bare
# `make` should do that without ceremony. `make help` still works for discovery.
build:
	pixi run build

help:
	@echo "Targets:"
	@echo "  make            Build the PDF (default; writes guide-template.pdf at repo root)"
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
	pixi run python verify_pdf.py baseline.pdf guide-template.pdf

# baseline overwrites the committed reference PDF with the fresh render. `cp`
# (not `mv`) so the just-built guide-template.pdf stays on disk for visual
# review. Use deliberately, only after eyeballing the new PDF — this silently
# re-blesses any rendering regression. After running, commit baseline.pdf
# together with the source files that changed it in a single commit.
baseline: build
	cp guide-template.pdf baseline.pdf
	@echo "  baseline -> baseline.pdf (commit it together with source changes)"

clean:
	rm -f guide-template.pdf guide-template.html
	rm -rf verify-diff/
