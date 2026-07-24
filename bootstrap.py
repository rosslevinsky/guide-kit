#!/usr/bin/env python3
"""One-shot initialize-your-fork script.

After `gh repo create my-new-guide --template rosslevinsky/guide-template`,
run this from the new repo's root:

    pixi run python bootstrap.py "My Guide Title" my-guide-slug \\
        --baseline-platform darwin          # REQUIRED (no default; see below)
    # full form:
    pixi run python bootstrap.py "My Guide Title" my-guide-slug \\
        --baseline-platform darwin \\
        --author "Author Name" \\
        --description "Short description for PDF metadata" \\
        --keywords "kw1, kw2, kw3" \\
        --source-repo rosslevinsky/guide-template \\
        --kit-version 2026-07 \\
        --with-web                            # opt into the website output
        # --with-transforms                   # opt into the transforms.py hook

What it does:
  * guide.toml:        WRITES the seven per-guide values (TITLE, OUTPUT_SLUG,
                       AUTHOR, DESCRIPTION, KEYWORDS, COPYRIGHT_YEAR,
                       baseline_platform). build.py reads these via kitconfig —
                       no build.py literals are substituted anymore.
  * templated files:   re-renders every `templated` destination (pixi.toml,
                       verify.yml, kit-drift.yml) with the FORK's identity via the
                       same path sync uses, so the fork does not silently inherit
                       the kit's slug / paths filter.
  * README / CLAUDE.md: fills {{GUIDE_NAME}} / {{GUIDE_SLUG}} (and drops the
                       "getting started from this template" section / the
                       <DESCRIBE YOUR GUIDE> placeholder).
  * inherited PDF:     DELETES the kit's reference PDF — a fresh fork has ZERO
                       root PDFs until its own first macOS release.
  * .template-version: WRITES the managed-state record {schema_version,
                       source_repo, kit_version, managed_digest, state,
                       rendered_checksums} so the fork starts in sync.
  * --with-web:        materializes the opt-in web layer. transforms.py is NOT
                       activated unless --with-transforms is also given.
  * Deletes `.template-uninitialized` and itself.

--baseline-platform has NO default: it must be `darwin` / `linux` / `win32`, is
REQUIRED in non-interactive use, and is prompted (with no preselection) on a TTY.
The guard is validated BEFORE any file is written.

Initialization commit sequence (the closing message repeats it): make an ordinary
`git commit` of the bootstrap changes FIRST (they touch files outside SOURCE_FILES,
which `make release` would reject), then run `make release` for the content baseline.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import kitconfig
import kitmanifest
import sync

ROOT = Path(__file__).parent.resolve()
SENTINEL = ROOT / ".template-uninitialized"

STYLE_SCREEN_EXAMPLE = ROOT / "style-screen.css.example"
TRANSFORMS_EXAMPLE = ROOT / "transforms.py.example"
TEMPLATES_WEB = ROOT / "templates" / "web"
DEPLOY_EXAMPLE = ROOT / ".github" / "workflows" / "deploy.yml.example"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _validate(title: str, slug: str) -> None:
    if not SENTINEL.exists():
        sys.exit(
            "bootstrap.py: this repo has already been initialized "
            "(`.template-uninitialized` is gone). Refusing to run. For an existing "
            "guide that wants the web layer, use adopt-web.py instead."
        )
    if not title.strip():
        sys.exit("bootstrap.py: title cannot be empty.")
    if '"' in title:
        sys.exit("bootstrap.py: title must not contain double quotes.")
    if not SLUG_RE.fullmatch(slug):
        sys.exit(
            f"bootstrap.py: slug {slug!r} must be kebab-case "
            "(lowercase letters, digits, dashes; must start and end alphanumeric)."
        )


def _resolve_platform(cli_value: str | None) -> str:
    """Return a validated baseline_platform. No default: required non-interactively,
    prompted with no preselection on a TTY. Validated before any file is written."""
    value = cli_value
    if value is None:
        if sys.stdin.isatty():
            value = input(f"baseline_platform ({'/'.join(kitconfig._PLATFORM_ENUM)}): ").strip()
        else:
            sys.exit(
                "bootstrap.py: --baseline-platform is required (no default). It records the "
                "host the reference PDF is rendered on; the three new guides take theirs on "
                "macOS (`darwin`), a public Linux fork would use `linux`."
            )
    if value not in kitconfig._PLATFORM_ENUM:
        sys.exit(f"bootstrap.py: baseline_platform {value!r} must be one of {list(kitconfig._PLATFORM_ENUM)}.")
    return value


def _toml_str(s: str) -> str:
    out = (s.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return '"' + out + '"'


def _write_guide_toml(title, slug, author, description, keywords, copyright_year, platform) -> None:
    (ROOT / "guide.toml").write_text(
        "# Per-guide constants — written by bootstrap.py. kitconfig.py validates these.\n"
        f"TITLE = {_toml_str(title)}\n"
        f"OUTPUT_SLUG = {_toml_str(slug)}\n"
        f"AUTHOR = {_toml_str(author)}\n"
        f"DESCRIPTION = {_toml_str(description)}\n"
        f"KEYWORDS = {_toml_str(keywords)}\n"
        f"COPYRIGHT_YEAR = {int(copyright_year)}\n"
        f"baseline_platform = {_toml_str(platform)}\n",
        encoding="utf-8",
    )
    print("  guide.toml       written")


def _render_templated_files(kit_cfg, fork_cfg, shape: str) -> None:
    """Re-render every `templated` destination with the FORK's identity, exactly
    as sync would — so the fork does not inherit the kit's slug / paths filter,
    and a fresh fork reports zero drift against sync."""
    manifest = kitmanifest.load(ROOT)
    for proj in manifest.projections(shape, slug=fork_cfg.OUTPUT_SLUG):
        # web-only (bootstrap-source) templated files are materialized + rendered
        # by _materialize_web; here we render only the retained-in-kit templated
        # files (pixi.toml, verify.yml, kit-drift.yml).
        if proj.policy != "templated" or proj.web_only:
            continue
        src_text = (ROOT / proj.source).read_bytes().decode("utf-8")
        rendered = sync._render_templated(src_text, kit_cfg, fork_cfg)
        # write bytes (no newline translation) so the result is byte-identical to
        # what sync produces — otherwise a non-Linux host could emit CRLF and drift.
        (ROOT / proj.dest).write_bytes(rendered.encode("utf-8"))
    print("  templated files  rendered (pixi.toml, verify.yml, kit-drift.yml)")


def _sub_readme(title: str, slug: str) -> None:
    p = ROOT / "README.md"
    text = p.read_text(encoding="utf-8")
    text = text.replace("{{GUIDE_NAME}}", title).replace("{{GUIDE_SLUG}}", slug)
    text = re.sub(r"\n## Getting started from this template\n.*?(?=\n## )", "\n", text, count=1, flags=re.S)
    p.write_text(text, encoding="utf-8")
    print("  README.md        updated")


def _sub_claude(title: str, slug: str) -> None:
    p = ROOT / "CLAUDE.md"
    text = p.read_text(encoding="utf-8")

    def _fill(s: str) -> str:
        return (s.replace("{{GUIDE_NAME}}", title)
                 .replace("{{GUIDE_SLUG}}", slug)
                 .replace("<DESCRIBE YOUR GUIDE>\n\n", ""))

    # Fill placeholders ONLY outside the managed region, so bootstrap never alters
    # the shared block — it must stay byte-identical to the kit's, or the fork's
    # managed-region checksum diverges and it drifts immediately. If markers are
    # absent (pre-Phase-9) fall back to whole-file substitution.
    if (text.count(sync.MARK_BEGIN) == 1 and text.count(sync.MARK_END) == 1
            and text.index(sync.MARK_BEGIN) < text.index(sync.MARK_END)):
        b = text.index(sync.MARK_BEGIN)
        e = text.index(sync.MARK_END) + len(sync.MARK_END)
        text = _fill(text[:b]) + text[b:e] + _fill(text[e:])
    else:
        text = _fill(text)

    p.write_text(text, encoding="utf-8")
    print("  CLAUDE.md        updated")


def _materialize_web(kit_cfg, fork_cfg, with_transforms: bool) -> None:
    """Materialize the opt-in web layer (only for --with-web). wrangler.jsonc is a
    `templated` file, rendered with the SAME value-substitution sync uses (so a
    fresh web fork reports zero drift on app/wrangler.jsonc). transforms.py is
    activated ONLY when --with-transforms is also given — writing it makes the
    (always-present) SOURCE_FILES entry start contributing bytes, and the terminal
    guides deliberately do not want it (plan.md:147). Matches adopt-web.py."""
    app_dir = ROOT / "app"
    shutil.copyfile(STYLE_SCREEN_EXAMPLE, ROOT / "style-screen.css")

    if with_transforms:
        transforms = ROOT / "transforms.py"
        if not transforms.exists():
            shutil.copyfile(TRANSFORMS_EXAMPLE, transforms)

    if TEMPLATES_WEB.exists():
        shutil.copytree(TEMPLATES_WEB, app_dir, dirs_exist_ok=True)
        wrangler = app_dir / "wrangler.jsonc"
        wrangler.write_bytes(
            sync._render_templated(wrangler.read_bytes().decode("utf-8"), kit_cfg, fork_cfg).encode("utf-8")
        )
        if DEPLOY_EXAMPLE.exists():
            DEPLOY_EXAMPLE.rename(DEPLOY_EXAMPLE.with_name("deploy.yml"))
        shutil.rmtree(TEMPLATES_WEB)
        try:
            TEMPLATES_WEB.parent.rmdir()
        except OSError:
            pass
    elif not (app_dir / "wrangler.jsonc").exists():
        sys.exit(
            "bootstrap.py: web staging dir templates/web/ is missing and app/ is not "
            "materialized — cannot enable the web layer. Restore templates/web/ (or drop --with-web)."
        )
    extra = " + transforms.py" if with_transforms else " (transforms.py NOT activated)"
    print(f"  web layer        materialized (style-screen.css, app/, deploy.yml{extra})")


def _prune_kit_only(manifest) -> None:
    """Delete every KIT-ONLY path from the fork.

    A `--template` fork is a full copy of the kit, so it inherits the kit's own
    machinery: the test suite, sync.py, adopt-web.py, the manifest and its
    loader, and plans/. None of it belongs in a guide, and leaving it there is
    not merely untidy — `verify.yml`'s target branch is guarded on `tests/**`
    existing, so an inherited `tests/` makes every new fork borrow the kit's
    runner and execute the KIT's suite against the GUIDE. Those tests assert
    kit-shaped facts (bootstrap.py exists, pixi.toml has a `kit` env, every
    tracked file is classified) that are false in a fork by construction, so a
    brand-new repo lands with a permanently red default branch.

    The set is derived from the manifest rather than hardcoded: an entry that is
    `retained-in-kit` with no `projects_to` is by definition never projected into
    a target, which is exactly "kit-only". Adding such a file to the manifest
    therefore prunes it here automatically.

    bootstrap.py and .template-uninitialized are in that set too, but they are
    deleted separately at the very end — this runs before them, and pruning the
    script out from under itself mid-run would be a poor idea.
    """
    keep = {"bootstrap.py", ".template-uninitialized"}
    removed = []
    for entry in manifest.entries:
        if entry.lifecycle != "retained-in-kit" or entry.projects_to:
            continue
        rel = entry.path
        if rel in keep:
            continue
        target = ROOT / rel[:-3].rstrip("/") if rel.endswith("/**") else ROOT / rel
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(rel)
    if removed:
        print(f"  kit-only files  removed ({', '.join(sorted(removed))})")


_README_ROW_RE = re.compile(r"^\|\s*`([^`]+)`")


def _prune_readme(with_web: bool) -> None:
    """Make README.md describe THIS guide rather than the kit it came from.

    The README is filled in from the kit's, so a fresh fork inherits rows for
    files it no longer has (`bootstrap.py`, `.template-uninitialized`,
    `templates/web/`, `sync.py`, the manifest) and prose telling the reader how
    to enable a web layer that is already live. These are the public landing
    page of a new repo, so they are worth getting right.

    Row pruning is driven by what actually exists on disk rather than a
    hardcoded list, so it stays correct as the kit's file set changes.
    """
    p = ROOT / "README.md"
    if not p.is_file():
        return
    lines, kept, dropped = p.read_text(encoding="utf-8").splitlines(keepends=True), [], 0
    for line in lines:
        m = _README_ROW_RE.match(line)
        if m:
            # A row may name several paths ("`LICENSE` / `LICENSE-CONTENT`");
            # keep it if ANY of them survived, so shared rows are not lost.
            paths = re.findall(r"`([^`]+)`", line.split("|")[1])
            candidates = [c.split()[0].rstrip("/") for c in paths if c and not c.startswith("<")]
            if candidates and not any((ROOT / c).exists() for c in candidates):
                dropped += 1
                continue
        kept.append(line)
    text = "".join(kept)

    if with_web:
        text = text.replace(
            "# Opt-in web layer (only after `bootstrap.py --with-web` — see \"Website deploy\"):",
            "# Website (enabled for this guide):")
        text = text.replace(
            "The PDF is the default deliverable; the website is **opt-in**. On a PDF-only fork "
            "`make web` no-ops cleanly and `make dev`/`make deploy` exit with a \"web layer not "
            "enabled\" message — nothing under `app/` exists until you opt in.",
            "This guide has the website enabled. Note `make web` **fails** until the first "
            "reference PDF exists, because the site's download link would otherwise 404.")
        text = text.replace(
            "(The web-layer files above ship inert. A PDF-only fork has no `app/`, no "
            "`style-screen.css`, and no live `deploy.yml`.",
            "(The web layer is live in this guide: `app/`, `style-screen.css` and `deploy.yml` "
            "are all present.")

        # The "how to enable the web layer" recipe instructs running bootstrap.py,
        # which no longer exists here and would refuse anyway. Replace the whole
        # enable-it block with a statement of what this guide already has.
        text = re.sub(
            r"The website is an \*\*opt-in\*\* second output\..*?re-baseline with `make release`\.\)",
            "The website is already enabled for this guide: `style-screen.css`, the `app/` "
            "Cloudflare scaffold (with this guide's slug as the worker name) and a live "
            "`.github/workflows/deploy.yml` are all present. `transforms.py` is deliberately "
            "**not** activated — it is a `SOURCE_FILES` entry, so creating it shifts the version "
            "stamp, and this guide has no embeds to split per output.",
            text, count=1, flags=re.S)
        text = re.sub(
            r"```bash\npixi run python bootstrap\.py [^\n]*--with-web\n```\n\n", "", text, count=1)

    # Doc-only file list: drop names this guide no longer has, so the boundary
    # it describes matches the repo.
    def _prune_doconly(m: re.Match) -> str:
        kept = [seg for seg in re.findall(r"`[^`]+`", m.group(0))
                if not seg.strip("`").endswith((".py", ".toml"))
                or (ROOT / seg.strip("`")).exists()
                or seg.strip("`").startswith(("LICENSE", "pixi", "README", "CLAUDE"))]
        return ", ".join(kept)

    text = re.sub(r"(?<=This covers )`README\.md`.*?(?=, and `\.github/workflows/`)",
                  _prune_doconly, text, count=1, flags=re.S)

    # The reference PDF does not exist until the first release on the canonical
    # host, so the landing page must not link to it and 404.
    text = re.sub(
        r"^> \*\*Read the guide:\*\*.*$",
        "> **Read the guide:** the PDF is published here after the first release "
        "on the canonical host (see *Workflow: editing content*).",
        text, count=1, flags=re.MULTILINE)

    p.write_text(text, encoding="utf-8")
    print(f"  README.md        pruned ({dropped} row(s) for files this guide does not have)")


def _write_template_version(source_repo: str, kit_version: str, kit_digest: str, shape: str) -> None:
    """Record managed state so the fork starts in sync. managed_digest is the KIT's
    digest (captured from the pristine copy before any edits); rendered_checksums
    are the fork's freshly rendered managed files. state=applied (the fork IS at
    the kit's content)."""
    manifest = kitmanifest.load(ROOT)
    fork_cfg = kitconfig.load(ROOT)
    rendered: dict[str, str] = {}
    for proj in manifest.projections(shape, slug=fork_cfg.OUTPUT_SLUG):
        if proj.policy == "never":
            continue
        dest = ROOT / proj.dest
        if dest.exists():
            rendered[proj.dest] = sync._sha256(sync._checkable_bytes(proj.policy, dest.read_bytes()))
    record = {
        "schema_version": sync.SCHEMA_VERSION,
        "source_repo": source_repo,
        "kit_version": kit_version,
        "managed_digest": kit_digest,
        "state": "applied",
        "rendered_checksums": rendered,
    }
    (ROOT / sync.TEMPLATE_VERSION).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("  .template-version written")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Initialize a fork of guide-template with your own title, slug, and metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("title", help='Guide title, e.g. "A Beginner\'s Guide to Foo".')
    p.add_argument("slug", help="Kebab-case slug; drives the PDF filename and pixi project name.")
    p.add_argument("--baseline-platform", dest="baseline_platform",
                   help="Host the reference PDF is rendered on: darwin / linux / win32. "
                        "REQUIRED (no default); prompted on a TTY.")
    p.add_argument("--author", help="Author name.")
    p.add_argument("--description", help="Short guide description (guide.toml DESCRIPTION).")
    p.add_argument("--keywords", help="Comma-separated keywords (guide.toml KEYWORDS).")
    p.add_argument("--copyright-year", dest="copyright_year", type=int,
                   help="Copyright year (default: the kit's).")
    p.add_argument("--source-repo", default="rosslevinsky/guide-template",
                   help="Upstream kit repo recorded in .template-version (a third-party fork sets its own).")
    p.add_argument("--kit-version", default="unknown",
                   help="Human-readable kit version label recorded in .template-version.")
    p.add_argument("--with-web", action="store_true", help="Materialize the opt-in web layer.")
    p.add_argument("--with-transforms", action="store_true",
                   help="Also activate the transforms.py hook (only meaningful with --with-web).")
    args = p.parse_args()

    _validate(args.title, args.slug)
    # Platform guard fires BEFORE anything is written.
    platform = _resolve_platform(args.baseline_platform)

    # Capture the KIT's values + managed digest from the PRISTINE --template copy,
    # before any edit — these are what the fork records for drift comparison.
    kit_cfg = kitconfig.load(ROOT)
    try:
        kit_digest = sync.compute_managed_digest(ROOT)
    except sync.SyncError as exc:
        sys.exit(
            "bootstrap.py: cannot compute the kit's managed digest — the kit's CLAUDE.md needs "
            "<!-- kit:begin -->/<!-- kit:end --> markers (added in Phase 9). "
            f"Nothing was written. ({exc})"
        )
    kit_slug = kit_cfg.OUTPUT_SLUG
    shape = "web-enabled" if args.with_web else "pdf-only"

    print(f"Initializing fork as {args.title!r} (slug: {args.slug}, platform: {platform})...")
    _write_guide_toml(
        args.title, args.slug,
        args.author or kit_cfg.AUTHOR,
        args.description or kit_cfg.DESCRIPTION,
        args.keywords or kit_cfg.KEYWORDS,
        args.copyright_year if args.copyright_year is not None else kit_cfg.COPYRIGHT_YEAR,
        platform,
    )
    fork_cfg = kitconfig.load(ROOT)
    _render_templated_files(kit_cfg, fork_cfg, shape)
    _sub_readme(args.title, args.slug)
    _sub_claude(args.title, args.slug)

    if args.with_web:
        _materialize_web(kit_cfg, fork_cfg, args.with_transforms)

    # Delete the inherited kit reference PDF — a fresh fork has ZERO root PDFs.
    inherited_pdf = ROOT / f"{kit_slug}.pdf"
    if inherited_pdf.exists():
        inherited_pdf.unlink()
        print(f"  {kit_slug}.pdf  removed (fork has no reference PDF until its first macOS release)")

    _write_template_version(args.source_repo, args.kit_version, kit_digest, shape)

    # Load fresh: main() has no manifest in scope, and this must happen AFTER
    # _write_template_version has recorded the projections.
    _prune_kit_only(kitmanifest.load(ROOT))
    _prune_readme(args.with_web)

    SENTINEL.unlink()
    print("  .template-uninitialized  removed")
    Path(__file__).unlink()
    print("  bootstrap.py     removed")

    print()
    print("Done. Initialization commit sequence:")
    print("  1. Review the changes, then `git add -A && git commit -m \"Initialize <slug>\"`.")
    print("     (Commit FIRST — bootstrap touched files outside SOURCE_FILES, which `make release` rejects.)")
    print("  2. Write your guide in `guide.md`.")
    print(f"  3. `make release MSG=\"Initial content\"` on the {platform} host to commit source + baseline.")
    print("  4. `git push` to publish.")
    if args.with_web:
        print("  5. Web layer: `cd app && npm install`, `make dev` to preview. For deploys add")
        print("     CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID repo secrets (README \"Website deploy\").")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
