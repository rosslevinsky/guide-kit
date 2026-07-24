# The output slug — drives the filenames `make`, `make verify`, `make baseline`,
# and `make clean` operate on. The single source of truth is `OUTPUT_SLUG` in
# guide.toml (validated by kitconfig); the awk one-liner reads it directly so the
# Makefile resolves a filename without needing a pixi env. There is NO fallback:
# a wrong-but-plausible default (e.g. `guide-template` for git-guide, whose slug
# is `git-github-for-beginners`) is worse than a hard error, so an empty result
# stops the build immediately. guide.toml uses double-quoted strings by
# convention (kitconfig is the validating reader); a non-double-quoted OUTPUT_SLUG
# yields an empty scrape and the hard error below — never a silent mis-resolve.
OUTPUT_SLUG := $(shell awk -F'"' '/^OUTPUT_SLUG[[:space:]]*=/{print $$2; exit}' guide.toml)
ifeq ($(strip $(OUTPUT_SLUG)),)
$(error OUTPUT_SLUG not found in guide.toml — is guide.toml present and well-formed?)
endif

# Paths the workflow operates on. The WORKING render lands under build/
# (gitignored). The COMMITTED REFERENCE is <slug>.pdf at the repo root —
# named for the guide so readers can download it directly from GitHub
# without a generic "baseline.pdf" filename. `make verify` compares the
# two; `make baseline` promotes the working render to the reference.
WORKING_PDF := build/$(OUTPUT_SLUG).pdf
REFERENCE_PDF := $(OUTPUT_SLUG).pdf

.PHONY: build help all install html web dev deploy verify verify-render baseline release clean

# `build` is the FIRST non-.PHONY target, so bare `make` builds.
# Rationale: the most common operation in a guide repo is "render after edit"; bare
# `make` should do that without ceremony. `make help` still works for discovery.
# (This file is family-shared and lands verbatim in every guide, so it must not
# describe any individual guide's behaviour — an earlier note here claimed the
# guides "default to help", which became self-contradictory once synced.)
build:
	pixi run build

help:
	@echo "Targets:"
	@echo "  make                       Build the PDF (default; writes $(WORKING_PDF))"
	@echo "  make html                  Render a standalone HTML for browser preview (in build/)"
	@echo "  make web                   Build the deployable website into app/dist/ (opt-in web layer)"
	@echo "  make dev                   Build the site and serve it locally (wrangler dev; needs app/)"
	@echo "  make deploy                Build and deploy the site to Cloudflare (manual; needs app/)"
	@echo "  make verify                Staleness check: is $(REFERENCE_PDF) up to date with source? (no build; CI-safe)"
	@echo "  make verify-render         Render canary: page count + stamp-excluded text (needs a build; canonical host only)"
	@echo "  make baseline              Promote $(WORKING_PDF) onto $(REFERENCE_PDF), with platform + clean-tree guards"
	@echo "  make release MSG=\"...\"     Stage source + refresh reference + amend, in one commit"
	@echo "  make install               Install all dependencies via pixi"
	@echo "  make clean                 Remove build/"
	@echo ""
	@echo "All targets delegate to pixi. Install pixi first: https://pixi.sh"

all: build

install:
	pixi install

html:
	pixi run html

# web builds the deployable website into app/dist/ (index.html with inlined
# screen CSS + a copy of the committed reference PDF). Served by Cloudflare
# Workers Static Assets. Does NOT touch the PDF pipeline or the reference PDF.
# On a PDF-only fork (no style-screen.css) `build.py --web` no-ops cleanly.
web:
	pixi run web

# dev serves the site locally via wrangler. The app/ scaffold (package.json +
# wrangler config) only exists after `bootstrap.py --with-web`, so guard on it
# and error clearly on PDF-only forks before building or invoking wrangler.
# Requires Node >=22 and `npm install` in app/ (wrangler is pinned there).
dev:
	@test -d app || { echo "web layer not enabled; run bootstrap.py --with-web"; exit 1; }
	pixi run web
	cd app && npx wrangler dev

# deploy pushes the current build to Cloudflare (manual one-off; CI deploy is
# handled by .github/workflows/deploy.yml on web-enabled forks). Same app/
# guard as dev.
deploy:
	@test -d app || { echo "web layer not enabled; run bootstrap.py --with-web"; exit 1; }
	pixi run web
	cd app && npx wrangler deploy

# verify is the STALENESS check only: is the committed reference PDF up to date
# with the source? It compares the hash embedded in the PDF's version stamp
# against a fresh content hash over SOURCE_FILES — NO build, NO rendering,
# platform-independent (milliseconds). This is the sole `verify` CI runs.
# NO `build` prerequisite (intentional divergence from the old pixel harness).
verify:
	pixi run python verify_pdf.py --staleness

# verify-render is the secondary canary: it builds and compares page count +
# stamp-excluded text against the committed reference. It REQUIRES a build and
# is PLATFORM-SENSITIVE (font substitution shifts line wrapping), so it runs on
# the canonical host ONLY and is NEVER wired into CI. Its one genuine catch is
# environmental drift (a `pixi update` that shifts layout with no source change).
verify-render: build
	pixi run python verify_pdf.py --render $(REFERENCE_PDF) $(WORKING_PDF)

# baseline promotes the fresh render onto the committed reference PDF, guarded:
# baseline.py refuses a platform mismatch (sys.platform != guide.toml's
# baseline_platform) and a dirty SOURCE_FILES tree BEFORE building or copying,
# then asserts the rendered stamp is not `· dirty`. After it runs, commit
# $(REFERENCE_PDF) together with the source that changed it (see CLAUDE.md), or
# use `make release MSG="..."` which does the whole dance in one shot.
baseline:
	pixi run python baseline.py $(BASELINE_ARGS)

# release automates the after-editing dance: stage source files, commit with
# MSG, re-render with a clean version stamp, copy to $(REFERENCE_PDF), amend.
# Refuses to run if the working tree has staged changes or modifications
# outside the SOURCE_FILES set — handle those with plain `git commit` first.
release:
	@test -n "$(MSG)" || (echo "usage: make release MSG=\"your commit message\""; exit 1)
	pixi run python release.py -m "$(MSG)" $(RELEASE_ARGS)

clean:
	rm -rf build/
