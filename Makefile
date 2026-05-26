# The output slug — drives the filenames `make`, `make verify`, `make baseline`,
# and `make clean` operate on. Single source of truth is `OUTPUT_SLUG` in
# build.py; the awk one-liner below scrapes it so the Makefile and build.py
# can never drift. Falls back to `guide-template` only if the scrape fails
# (e.g. build.py was edited into an unparseable shape).
OUTPUT_SLUG := $(shell awk -F'"' '/^OUTPUT_SLUG[[:space:]]*=/{print $$2; exit}' build.py)
ifeq ($(OUTPUT_SLUG),)
OUTPUT_SLUG := guide-template
endif

# Paths the workflow operates on. The WORKING render lands under build/
# (gitignored). The COMMITTED REFERENCE is <slug>.pdf at the repo root —
# named for the guide so readers can download it directly from GitHub
# without a generic "baseline.pdf" filename. `make verify` compares the
# two; `make baseline` promotes the working render to the reference.
WORKING_PDF := build/$(OUTPUT_SLUG).pdf
REFERENCE_PDF := $(OUTPUT_SLUG).pdf

.PHONY: build help all install html verify baseline release clean

# `build` is the FIRST non-.PHONY target, so bare `make` builds.
# Intentional divergence from mac-terminal-guide / git-guide, which default to `help`.
# Rationale: the most common operation in a guide repo is "render after edit"; bare
# `make` should do that without ceremony. `make help` still works for discovery.
build:
	pixi run build

help:
	@echo "Targets:"
	@echo "  make                       Build the PDF (default; writes $(WORKING_PDF))"
	@echo "  make html                  Render a standalone HTML for browser preview (in build/)"
	@echo "  make verify                Check that the freshly-built PDF matches the committed $(REFERENCE_PDF)"
	@echo "  make baseline              Promote $(WORKING_PDF) onto $(REFERENCE_PDF) (use deliberately)"
	@echo "  make release MSG=\"...\"     Stage source + refresh reference + amend, in one commit"
	@echo "  make install               Install all dependencies via pixi"
	@echo "  make clean                 Remove build/ and verify-diff/"
	@echo ""
	@echo "All targets delegate to pixi. Install pixi first: https://pixi.sh"

all: build

install:
	pixi install

html:
	pixi run html

# verify depends on build so a fresh render is always compared to the reference.
verify: build
	pixi run python verify_pdf.py $(REFERENCE_PDF) $(WORKING_PDF)

# baseline overwrites the committed reference PDF with the fresh render. `cp`
# (not `mv`) so the just-built PDF stays under build/ for visual review. Use
# deliberately, only after eyeballing — this silently re-blesses any rendering
# regression. After running, commit $(REFERENCE_PDF) together with the source
# files that changed it via the amend workflow (see CLAUDE.md), or use
# `make release MSG="..."` which does the whole dance in one shot.
baseline: build
	cp $(WORKING_PDF) $(REFERENCE_PDF)
	@echo "  reference -> $(REFERENCE_PDF) (commit it together with source changes)"

# release automates the after-editing dance: stage source files, commit with
# MSG, re-render with a clean version stamp, copy to $(REFERENCE_PDF), amend.
# Refuses to run if the working tree has staged changes or modifications
# outside the SOURCE_FILES set — handle those with plain `git commit` first.
release:
	@test -n "$(MSG)" || (echo "usage: make release MSG=\"your commit message\""; exit 1)
	pixi run python release.py -m "$(MSG)"

clean:
	rm -rf build/ verify-diff/
