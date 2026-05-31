#!/usr/bin/env python3
"""One-shot rename-your-fork script.

After `gh repo create my-new-guide --template rosslevinsky/guide-template`,
run this from the new repo's root:

    pixi run python bootstrap.py "My Guide Title" my-guide-slug
    # full form:
    pixi run python bootstrap.py "My Guide Title" my-guide-slug \\
        --author "Author Name" \\
        --description "Short description for PDF metadata + pixi.toml" \\
        --keywords "kw1, kw2, kw3"
    # opt into the website output (PDF + Cloudflare-deployed site):
    pixi run python bootstrap.py "My Guide Title" my-guide-slug --with-web

What it does:
  * build.py:   sets TITLE, OUTPUT_SLUG, and (when provided) AUTHOR /
                DESCRIPTION / KEYWORDS.
  * pixi.toml:  sets name + description.
  * README.md:  substitutes {{GUIDE_NAME}} / {{GUIDE_SLUG}}, and removes the
                "## Getting started from this template" section (it no
                longer applies to an initialized fork).
  * CLAUDE.md:  substitutes {{GUIDE_NAME}} / {{GUIDE_SLUG}} and
                <DESCRIBE YOUR GUIDE>.
  * --with-web: materializes the opt-in web layer — copies
                style-screen.css.example → style-screen.css, activates
                transforms.py.example → transforms.py (the per-output YouTube
                embed split), copies the templates/web/ scaffold → app/ (with the
                slug substituted in wrangler.jsonc), and activates
                .github/workflows/deploy.yml.example → deploy.yml. WITHOUT the
                flag the fork stays PDF-only: no app/, no deploy.yml, no
                transforms.py, no Node footprint.
  * Deletes `.template-uninitialized` so build.py's template-hygiene check
    starts catching un-substituted placeholders going forward.
  * Deletes itself.

It refuses to run twice (it checks for the sentinel file first).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
SENTINEL = ROOT / ".template-uninitialized"

# Opt-in web layer staging sources (materialized only by --with-web). The
# un-bootstrapped template ships these inert; a PDF-only fork never copies them
# into place. See plans/web-layer-backport/.
STYLE_SCREEN_EXAMPLE = ROOT / "style-screen.css.example"
TRANSFORMS_EXAMPLE = ROOT / "transforms.py.example"
TEMPLATES_WEB = ROOT / "templates" / "web"
DEPLOY_EXAMPLE = ROOT / ".github" / "workflows" / "deploy.yml.example"


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _validate(title: str, slug: str) -> None:
    if not SENTINEL.exists():
        sys.exit(
            "bootstrap.py: this repo has already been initialized "
            "(`.template-uninitialized` is gone). Refusing to run."
        )
    if not title.strip():
        sys.exit("bootstrap.py: title cannot be empty.")
    if '"' in title:
        sys.exit("bootstrap.py: title must not contain double quotes.")
    if not SLUG_RE.match(slug):
        sys.exit(
            f"bootstrap.py: slug {slug!r} must be kebab-case "
            "(lowercase letters, digits, dashes; must start and end alphanumeric)."
        )


def _sub_build_py(
    title: str, slug: str,
    author: str | None, description: str | None, keywords: str | None,
) -> None:
    p = ROOT / "build.py"
    text = p.read_text(encoding="utf-8")
    text = re.sub(r'^TITLE\s*=\s*"[^"]*"', f'TITLE = "{title}"', text, count=1, flags=re.M)
    text = re.sub(r'^OUTPUT_SLUG\s*=\s*"[^"]*"', f'OUTPUT_SLUG = "{slug}"', text, count=1, flags=re.M)
    if author is not None:
        text = re.sub(r'^AUTHOR\s*=\s*"[^"]*"', f'AUTHOR = "{author}"', text, count=1, flags=re.M)
    if description is not None:
        # DESCRIPTION is a parenthesized multi-line string in the template; replace
        # the whole assignment in one shot.
        new_block = (
            f'DESCRIPTION = (\n'
            f'    "{description} "\n'
            f'    "Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0): "\n'
            f'    "https://creativecommons.org/licenses/by/4.0/"\n'
            f')'
        )
        # Match `DESCRIPTION = ( ... )` as a multi-line block. The block ends
        # at a `)` on its own line — required because the standard body of
        # DESCRIPTION contains a literal `)` inside "(CC BY 4.0)" that breaks
        # any naive `\([^)]*\)` pattern.
        text = re.sub(
            r'^DESCRIPTION\s*=\s*\(.*?\n\)',
            new_block,
            text, count=1, flags=re.M | re.S,
        )
    if keywords is not None:
        text = re.sub(r'^KEYWORDS\s*=\s*"[^"]*"', f'KEYWORDS = "{keywords}"', text, count=1, flags=re.M)
    p.write_text(text, encoding="utf-8")
    print("  build.py        updated")


def _sub_pixi_toml(slug: str, description: str | None) -> None:
    p = ROOT / "pixi.toml"
    text = p.read_text(encoding="utf-8")
    text = re.sub(r'^name\s*=\s*"[^"]*"', f'name = "{slug}"', text, count=1, flags=re.M)
    if description is not None:
        text = re.sub(
            r'^description\s*=\s*"[^"]*"',
            f'description = "{description}"',
            text, count=1, flags=re.M,
        )
    p.write_text(text, encoding="utf-8")
    print("  pixi.toml       updated")


def _sub_readme(title: str, slug: str) -> None:
    p = ROOT / "README.md"
    text = p.read_text(encoding="utf-8")
    text = text.replace("{{GUIDE_NAME}}", title).replace("{{GUIDE_SLUG}}", slug)
    # Strip the "Getting started from this template" section — it doesn't apply
    # post-bootstrap. The section runs from its heading to (but not including)
    # the next H2 heading.
    text = re.sub(
        r"\n## Getting started from this template\n.*?(?=\n## )",
        "\n",
        text, count=1, flags=re.S,
    )
    p.write_text(text, encoding="utf-8")
    print("  README.md       updated")


def _sub_claude(title: str, slug: str) -> None:
    p = ROOT / "CLAUDE.md"
    text = p.read_text(encoding="utf-8")
    text = text.replace("{{GUIDE_NAME}}", title).replace("{{GUIDE_SLUG}}", slug)
    text = text.replace("<DESCRIBE YOUR GUIDE>\n\n", "")
    p.write_text(text, encoding="utf-8")
    print("  CLAUDE.md       updated")


def _materialize_web(slug: str) -> None:
    """Materialize the opt-in web layer (only for --with-web).

    Called BEFORE the sentinel removal / self-delete in main(), so any failure
    here leaves bootstrap.py and `.template-uninitialized` in place for a retry.
    Turns the inert staging assets into a live web layer:
      * style-screen.css.example          → style-screen.css
      * transforms.py.example              → transforms.py (per-output embed split)
      * templates/web/ (slug-substituted)  → app/
      * .github/workflows/deploy.yml.example → deploy.yml (GitHub runs *.yml)
    The templates/web/ staging dir is removed afterward — its job is done once
    copied into app/."""
    app_dir = ROOT / "app"

    # 1. Screen stylesheet (drives `make web`; its presence is the web-enabled
    #    signal build.py / the Makefile / CI all key on). Idempotent.
    shutil.copyfile(STYLE_SCREEN_EXAMPLE, ROOT / "style-screen.css")

    # 1b. Activate the per-output transforms hook. transforms.py.example ships
    #     the YouTube embed worked example (iframe on the web, watch-link in
    #     print) — the web layer's headline rich-media feature — so a --with-web
    #     fork gets working embeds out of the box. transforms.py is a SOURCE_FILE
    #     (it bumps the PDF stamp), which is fine: a fresh fork baselines on its
    #     first `make release`. Guarded so we never clobber a hook the user may
    #     have already written.
    transforms = ROOT / "transforms.py"
    if not transforms.exists():
        shutil.copyfile(TRANSFORMS_EXAMPLE, transforms)

    # 2-4. Copy the staging scaffold into app/, substitute the slug, activate the
    #      deploy workflow, then remove the staging dir. The whole block is
    #      gated on the staging dir's presence (rmtree is its last step), which
    #      makes the fail-safe retry path correct in every reachable state:
    #        * staging present  → a fresh run or a retry after partial failure;
    #                             dirs_exist_ok lets copytree merge onto a
    #                             half-copied app/, the rename is guarded, and
    #                             rmtree finishes the cleanup.
    #        * staging gone, app/ present → a completed run; clean no-op.
    #        * staging gone, app/ absent  → a genuinely broken template; error.
    if TEMPLATES_WEB.exists():
        shutil.copytree(TEMPLATES_WEB, app_dir, dirs_exist_ok=True)
        wrangler = app_dir / "wrangler.jsonc"
        wrangler.write_text(
            wrangler.read_text(encoding="utf-8").replace("{{GUIDE_SLUG}}", slug),
            encoding="utf-8",
        )
        if DEPLOY_EXAMPLE.exists():
            DEPLOY_EXAMPLE.rename(DEPLOY_EXAMPLE.with_name("deploy.yml"))
        shutil.rmtree(TEMPLATES_WEB)
        try:
            TEMPLATES_WEB.parent.rmdir()  # remove templates/ if now empty
        except OSError:
            pass
    elif not (app_dir / "wrangler.jsonc").exists():
        sys.exit(
            "bootstrap.py: web staging dir templates/web/ is missing and app/ "
            "is not materialized — cannot enable the web layer. Restore "
            "templates/web/ (or drop --with-web)."
        )

    print("  web layer       materialized (style-screen.css, transforms.py, app/, deploy.yml)")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Initialize a fork of guide-template with your own title, slug, and metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("title", help='Guide title, e.g. "A Beginner\'s Guide to Foo".')
    p.add_argument("slug", help="Kebab-case slug; drives the PDF filename and pixi project name.")
    p.add_argument("--author", help="Author name (overrides build.py AUTHOR).")
    p.add_argument("--description", help="Short description (build.py DESCRIPTION + pixi.toml description).")
    p.add_argument("--keywords", help='Comma-separated keywords (build.py KEYWORDS).')
    p.add_argument("--with-web", action="store_true",
                   help="Also materialize the opt-in web layer (style-screen.css, app/ scaffold, deploy.yml). "
                        "Without it the fork is PDF-only.")
    args = p.parse_args()

    _validate(args.title, args.slug)

    print(f"Initializing fork as {args.title!r} (slug: {args.slug})...")
    _sub_build_py(args.title, args.slug, args.author, args.description, args.keywords)
    _sub_pixi_toml(args.slug, args.description)
    _sub_readme(args.title, args.slug)
    _sub_claude(args.title, args.slug)

    # Web materialization runs BEFORE the sentinel removal / self-delete below,
    # so a failure here leaves bootstrap.py in place for a retry.
    if args.with_web:
        _materialize_web(args.slug)

    SENTINEL.unlink()
    print("  .template-uninitialized  removed")

    # Self-delete LAST so a failure in any earlier step leaves bootstrap.py in
    # place for a retry.
    Path(__file__).unlink()
    print("  bootstrap.py    removed")

    print()
    print("Done. Next steps:")
    print(f"  1. Write your guide in `guide.md`.")
    print(f"  2. `make` to render, eyeball `{args.slug}.pdf`.")
    print(f"  3. `make release MSG=\"Initial content\"` to commit source + baseline.")
    print(f"  4. `git push` to publish.")
    if args.with_web:
        print("  5. Web layer enabled: `cd app && npm install`, then `make dev` to preview.")
        print("     For deploys, add CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID repo")
        print("     secrets (see README \"Website deploy\"). `make deploy` for a manual push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
