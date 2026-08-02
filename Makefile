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

.PHONY: build help all install html web slides slides-coverage wrangler dev deploy verify verify-render drift-canary smoke baseline release clean

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
	@echo "  make slides                Build the 16:9 deck into build/$(OUTPUT_SLUG)-slides.pdf (opt-in)"
	@echo "  make slides-coverage       Report which chapters have no slide (always exits 0)"
	@echo "  make wrangler              Regenerate app/wrangler.jsonc from guide.toml (needs a declared site)"
	@echo "  make dev                   Build the site and serve it locally (wrangler dev; needs app/)"
	@echo "  make deploy                Build and deploy the site to Cloudflare (manual; needs app/)"
	@echo "  make verify                Staleness check: is $(REFERENCE_PDF) up to date with source? (no build; CI-safe)"
	@echo "  make verify-render         Local render canary: page count + stamp-excluded text (needs a build)"
	@echo "  make drift-canary          Drift canary: PDF bytes + embedded-face list vs the reference (needs a build)"
	@echo "  make smoke [ARTIFACT=x]    Does each committed reference look finished? (no build; CI-safe)"
	@echo "                             (PDF=<path> inspects one file instead)"
	@echo "  make baseline [ARTIFACT=x] Promote a fresh render onto its committed reference (pdf|slides)"
	@echo "  make release MSG=\"...\"     Stage source + refresh reference + amend, in one commit"
	@echo "                             (add ARTIFACT=slides to release the deck)"
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
# On a guide that DECLARES no site, `build.py --web` no-ops cleanly. The trigger
# is the `[outputs] site` declaration, not the presence of style-screen.css —
# that stylesheet is target-owned, so it survives a site being switched off.
web:
	pixi run web

# slides builds the deck into build/<slug>-slides.pdf. Opt-in: no-ops with a
# notice when [outputs] slides is false.
slides:
	pixi run python build.py --slides

# slides-coverage reports which chapter units have no slide. A REPORT, not a
# gate — it always exits 0, because a deck is a selection rather than a mirror
# of the guide, and a report that failed the build would just get turned off.
slides-coverage:
	pixi run python build.py --slides-coverage

# wrangler regenerates app/wrangler.jsonc from guide.toml. It is target-owned
# (`policy = "never"`), so sync will never write it — run this after changing
# [deploy] domain, and commit the result. The kit's own test suite fails when a
# guide's committed file has drifted from what this produces.
wrangler:
	pixi run python -c "import pathlib, cfadapter, kitconfig; cfg = kitconfig.load(); \
	print('  WRANGLER ->', cfadapter.write_wrangler(pathlib.Path('.' if cfg.outputs.site == 'hub' else 'app'), cfg))"

# dev serves the site locally via wrangler. The app/ scaffold (package.json +
# wrangler config) only exists once the web layer is enabled, so guard on it and
# error clearly on PDF-only guides before building or invoking wrangler.
# Requires Node >=22 and `npm install` in app/ (wrangler is pinned there).
#
# THE REMEDY NAMES A COMMAND THAT EXISTS WHERE THE MESSAGE FIRES. It used to say
# "run bootstrap.py --with-web", and this message can only ever appear in an
# initialized guide — where `bootstrap.py` has deleted itself and `adopt.py` was
# pruned. The reachable path is the kit checkout beside the guide, which is how
# `adopt.py` is documented everywhere else.
#
# NO BACKTICKS in the message: it is expanded into a `sh` command line, where a
# backtick opens a command substitution. The first draft shipped a guard whose
# error message ran `site` as a program and printed "site: not found" above
# itself.
WEB_OFF_MSG := web layer not enabled. Declare 'site' in [outputs] (and add an \
[artifacts.site] table) in guide.toml, commit that, then from a guide-kit \
checkout: python guide-kit/adopt.py --target . --output site --enable
dev:
	@test -d app || { echo "$(WEB_OFF_MSG)"; exit 1; }
	pixi run web
	cd app && npx wrangler dev

# deploy pushes the current build to Cloudflare (manual one-off; CI deploy is
# handled by .github/workflows/deploy.yml on web-enabled forks). Same app/
# guard as dev.
deploy:
	@test -d app || { echo "$(WEB_OFF_MSG)"; exit 1; }
	pixi run web
	cd app && npx wrangler deploy

# verify is the STALENESS check only: is the committed reference PDF up to date
# with the source? It compares the hash embedded in the PDF's version stamp
# against a fresh content hash over SOURCE_FILES — NO build, NO rendering,
# platform-independent (milliseconds). This is the sole `verify` CI runs.
# NO `build` prerequisite (intentional divergence from the old pixel harness).
verify:
	pixi run python verify_artifacts.py --staleness

# verify-render is the LOCAL, weaker form of the drift question: it builds and
# compares page count + stamp-excluded text against the committed reference.
# Being a text comparison, it is blind to a change that preserves line breaks —
# including a face substitution with identical pagination.
verify-render: build
	pixi run python verify_artifacts.py --render $(REFERENCE_PDF) $(WORKING_PDF)

# drift-canary is the STRONGER form, and the one CI runs: PDF bytes plus the
# `pdffonts` embedded-face list. It exists because `verify` hashes SOURCE_FILES
# and `pixi.lock` is not in that list, so a dependency bump moves the deliverable
# while the staleness check stays correctly green. It SKIPS (does not fail) when
# the reference is stale — a fresh render is supposed to differ then, and that is
# `verify`'s finding, not drift. It must never trigger a re-baseline.
#
# EVERY declared artifact with a committed reference, not just the PDF. The deck
# shares `_COMMON_FILES` with it, so the drift class this exists for reaches both.
# `--fresh` hands over the render `build` just made, so only the deck is built here.
drift-canary: build
	pixi run python driftcanary.py --fresh $(WORKING_PDF)

# smoke asks the question the other two do not: does this PDF look like a
# finished guide? `verify` compares hashes (a question about bytes) and
# `verify-render` compares against the reference (useless on an intentional
# content edit, where the text is SUPPOSED to differ). Neither would have caught
# the footer wrapping on every page of three shipped guides.
#
# Platform-independent and build-free, so unlike verify-render this IS safe in
# CI. Checks EVERY declared artifact's committed reference — `--smoke` used to
# ignore `--artifact` and resolve the guide PDF whatever it was asked for, so the
# slide deck was committed, pushed and published having never been inspected.
# ARTIFACT=<pdf|slides|site> narrows it; PDF=<path> checks one file instead,
# which is how `make baseline` and `make release` inspect a FRESH render before
# promoting it. The two PAIR UP: a deck named by path still needs ARTIFACT=slides,
# or it is judged against the guide's assertions and fails on a title a deck is
# not supposed to carry.
#
# A guide with no reference artifact yet PASSES with a pre-first-release notice,
# matching `verify`. It used to exit 2 on the missing file, which made this the
# one command in the README's build block a brand-new fork could not run.
smoke:
	pixi run python verify_artifacts.py --smoke $(PDF) --artifact $(or $(ARTIFACT),all)

# baseline promotes the fresh render onto the committed reference PDF, guarded:
# baseline.py refuses a dirty SOURCE_FILES tree BEFORE building or copying,
# then asserts the rendered stamp is not `· dirty`. After it runs, commit
# $(REFERENCE_PDF) together with the source that changed it (see CLAUDE.md), or
# use `make release MSG="..."` which does the whole dance in one shot.
# ARTIFACT selects which reference to refresh (pdf | slides). The site has none —
# it is deployed, not blessed into the repo — and says so rather than failing.
baseline:
	pixi run python baseline.py --artifact $(or $(ARTIFACT),pdf) $(BASELINE_ARGS)

# release automates the after-editing dance: stage source files, commit with
# MSG, re-render with a clean version stamp, copy to $(REFERENCE_PDF), amend.
# Refuses to run if the working tree has staged changes or modifications
# outside the SOURCE_FILES set — handle those with plain `git commit` first.
release:
	@test -n "$(MSG)" || (echo "usage: make release MSG=\"your commit message\""; exit 1)
	pixi run python release.py -m "$(MSG)" --artifact $(or $(ARTIFACT),pdf) $(RELEASE_ARGS)

clean:
	rm -rf build/
