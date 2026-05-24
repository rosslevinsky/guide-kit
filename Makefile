.PHONY: build help all install html clean

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
	@echo "  make install    Install all dependencies via pixi"
	@echo "  make clean      Remove the rendered PDF and HTML preview"
	@echo ""
	@echo "All targets delegate to pixi. Install pixi first: https://pixi.sh"

all: build

install:
	pixi install

html:
	pixi run html

clean:
	rm -f guide-template.pdf guide-template.html
