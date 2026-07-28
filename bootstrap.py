#!/usr/bin/env python3
"""One-shot initialize-your-fork script.

After `gh repo create my-new-guide --template rosslevinsky/guide-kit`,
run this from the new repo's root:

    pixi run python bootstrap.py "My Guide Title" my-guide-slug
    # full form:
    pixi run python bootstrap.py "My Guide Title" my-guide-slug \\
        --author "Author Name" \\
        --description "Short description for PDF metadata" \\
        --keywords "kw1, kw2, kw3" \\
        --source-repo rosslevinsky/guide-kit \\
        --kit-version 2026-07 \\
        --with-web                            # opt into the website output
        # --with-transforms                   # opt into the transforms.py hook

What it does:
  * guide.toml:        WRITES the six per-guide values (TITLE, OUTPUT_SLUG,
                       AUTHOR, DESCRIPTION, KEYWORDS, COPYRIGHT_YEAR).
                       build.py reads these via kitconfig — no build.py
                       literals are substituted anymore.
  * templated files:   re-renders every `templated` destination (pixi.toml,
                       verify.yml, kit-drift.yml) with the FORK's identity via the
                       same path sync uses, so the fork does not silently inherit
                       the kit's slug / paths filter.
  * README / CLAUDE.md: fills {{GUIDE_NAME}} / {{GUIDE_SLUG}} (and drops the
                       "getting started from this template" section / the
                       <DESCRIBE YOUR GUIDE> placeholder).
  * inherited PDF:     DELETES the kit's reference PDF — a fresh fork has ZERO
                       root PDFs until its own first release.
  * .template-version: WRITES the managed-state record {schema_version,
                       source_repo, kit_version, managed_digest, state,
                       rendered_checksums} so the fork starts in sync.
  * --with-web:        materializes the opt-in web layer. transforms.py is NOT
                       activated unless --with-transforms is also given.
  * Deletes `.template-uninitialized` and itself.

There is no platform to record. Rendering is hermetic — bundled faces plus
`fontconfig/fonts.conf` — so a fork baselines from whatever host it has, and CI's
drift canary measures agreement instead of a config key asserting it.

Initialization commit sequence (the closing message repeats it): make an ordinary
`git commit` of the bootstrap changes FIRST (they touch files outside SOURCE_FILES,
which `make release` would reject), then run `make release` for the content baseline.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import json
import re
import shutil
import sys
from pathlib import Path

import cfadapter
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


def _toml_str(s: str) -> str:
    out = (s.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return '"' + out + '"'


def _write_guide_toml(title, slug, author, description, keywords, copyright_year,
                      *, with_web: bool = False, today: str | None = None) -> None:
    """Compose the fork's guide.toml, including its declared shape and a SEEDED
    edition date per declared artifact.

    Seeding the dates matters: `[artifacts.<name>] date` is required, so without
    this a freshly created guide would fail its own loader and the adopter would
    have to invent a value before anything could build. The date is the one
    place a clock read is legitimate — it is an authoring-time default written
    into the file, never a value the renderer reads at build time."""
    date = today or _datetime.date.today().isoformat()
    site = "single" if with_web else "none"
    text = (
        "# Per-guide constants — written by bootstrap.py. kitconfig.py validates these.\n"
        f"TITLE = {_toml_str(title)}\n"
        f"OUTPUT_SLUG = {_toml_str(slug)}\n"
        f"AUTHOR = {_toml_str(author)}\n"
        f"DESCRIPTION = {_toml_str(description)}\n"
        f"KEYWORDS = {_toml_str(keywords)}\n"
        f"COPYRIGHT_YEAR = {int(copyright_year)}\n"
        "\n# What this guide builds — declared, never inferred from file presence.\n"
        "[outputs]\n"
        "pdf = true\n"
        f"site = {_toml_str(site)}\n"
        "slides = false\n"
        "\n# The token set this guide renders with. EXPLICIT, never left to the kit's\n"
        "# default: a guide that omits this would silently change appearance the day\n"
        "# the default moves, which is the one thing naming an appearance prevents.\n"
        "[theme]\n"
        f"name = {_toml_str(kitconfig.DEFAULT_THEME)}\n"
        "\n# Per-artifact EDITION dates. One table per declared output; the date moves\n"
        "# at release, not on an ordinary refresh.\n"
        "[artifacts.pdf]\n"
        f"date = {_toml_str(date)}\n"
    )
    if site != "none":
        text += f"\n[artifacts.site]\ndate = {_toml_str(date)}\n"
    (ROOT / "guide.toml").write_text(text, encoding="utf-8")
    print("  guide.toml       written")


def _render_templated_files(kit_cfg, fork_cfg, shape: str) -> None:
    """Re-render every `templated` destination with the FORK's identity, exactly
    as sync would — so the fork does not inherit the kit's slug / paths filter,
    and a fresh fork reports zero drift against sync."""
    manifest = kitmanifest.load(ROOT)
    for proj in manifest.expanded_projections(ROOT, shape, slug=fork_cfg.OUTPUT_SLUG):
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


README_FRONT_BEGIN = "<!-- front-matter:begin"
README_FRONT_END = "<!-- front-matter:end -->"


def _guide_front_matter(title: str, slug: str) -> str:
    """The opening of a GUIDE's README — a book's front page, not the kit's.

    Substituted as a whole block rather than filled in, because the two
    documents say different things: the kit's front page describes a toolkit and
    links its own worked example, and a guide's describes the guide and links
    the PDF a reader came for. Writing one in placeholders produced a public
    landing page headed `# {{GUIDE_NAME}}` with a "Read the guide" link to
    `{{GUIDE_SLUG}}.pdf` — a 404 for every visitor.
    """
    return (
        f"# {title}\n"
        f"\n"
        f"A single-document beginner guide, authored in Markdown and rendered to PDF\n"
        f"via pandoc + WeasyPrint. The reference PDF — `{slug}.pdf` — lives at the repo\n"
        f"root, so anyone can download it directly from GitHub without cloning,\n"
        f"installing, or building.\n"
        f"\n"
        f"> **Read the guide:** [`{slug}.pdf`]({slug}.pdf) (downloadable directly from\n"
        f"> this repo).\n"
        f">\n"
        f"> **Build it yourself:** [Quick start](#quick-start) below — `pixi install && make`.\n"
        f">\n"
        f"> **Edit / contribute:** [Workflow](#workflow-editing-content) — "
        f"`make release MSG=\"...\"` does source-commit + reference-refresh + amend in one shot.\n"
    )


def _sub_readme(title: str, slug: str) -> None:
    p = ROOT / "README.md"
    text = p.read_text(encoding="utf-8")
    # The front matter is REPLACED, not filled. A missing marker pair is not
    # fatal — the placeholder pass below still runs — but it is worth saying,
    # because the result is a guide wearing the kit's front page.
    start = text.find(README_FRONT_BEGIN)
    end = text.find(README_FRONT_END)
    if start != -1 and end > start:
        # The "\n" is the blank line between the block and the body. `lstrip`
        # removes every newline the marker left behind, which without this ran
        # the front matter's last line straight into the body's first — legal
        # Markdown, and it renders as one merged paragraph.
        text = (text[:start] + _guide_front_matter(title, slug) + "\n"
                + text[end + len(README_FRONT_END):].lstrip("\n"))
    else:
        print("  README.md        WARNING: no front-matter markers; kept the kit's opening")
    text = text.replace("{{GUIDE_NAME}}", title).replace("{{GUIDE_SLUG}}", slug)
    text = re.sub(r"\n## Getting started from this template\n.*?(?=\n## )", "\n", text, count=1, flags=re.S)
    p.write_text(text, encoding="utf-8")
    print("  README.md        updated")


CLAUDE_FRONT_BEGIN = "<!-- claude-front:begin"
CLAUDE_FRONT_END = "<!-- claude-front:end -->"


def _guide_claude_front(title: str, slug: str) -> str:
    """The opening of a GUIDE's CLAUDE.md — notes about a book, not the toolkit.

    Swapped as a whole block for the same reason README.md's front matter is: the
    two documents say different things, and writing one of them in placeholders
    means the OTHER one ships unfilled. The kit's copy read
    "## What this is / <DESCRIBE YOUR GUIDE>" on a public repository, which is the
    same class of defect as the README's `# {{GUIDE_NAME}}` heading.

    Emits NO `<DESCRIBE YOUR GUIDE>` token. That string is in `PLACEHOLDERS`, so
    `buildcore._check_template_hygiene` refuses to build while it is present and
    `--smoke` rejects a PDF containing it — and the sentinel that suppresses the
    check is deleted at the end of this same run. A fork that kept the token would
    therefore fail its very first `make`. The invitation to describe the guide is
    made in prose instead, where it costs nothing.
    """
    return (
        f"# Project notes for Claude\n"
        f"\n"
        f"This file documents the conventions of this project so you can make good edits.\n"
        f"\n"
        f"## What this is\n"
        f"\n"
        f"A single-document Markdown → PDF project for **{title}**. Source lives in\n"
        f"`guide.md`; styling in `style.css` over a theme; the per-guide values in\n"
        f"`guide.toml`; the build pipeline in `buildcore.py` plus one `render_*.py` per\n"
        f"output, dispatched by `build.py`. The committed reference PDF `{slug}.pdf` at\n"
        f"the repo root is the deliverable readers download.\n"
        f"\n"
        f"Replace this paragraph with what **{title}** actually covers, who it is for,\n"
        f"and any convention a contributor would otherwise have to infer.\n"
    )


def _sub_claude(title: str, slug: str) -> None:
    p = ROOT / "CLAUDE.md"
    text = p.read_text(encoding="utf-8")

    # The front matter is REPLACED, not filled — see _guide_claude_front. This runs
    # BEFORE the managed-region split below, and cannot disturb it: the block ends
    # above `<!-- kit:begin -->`, and a missing marker pair leaves the text alone.
    fs = text.find(CLAUDE_FRONT_BEGIN)
    fe = text.find(CLAUDE_FRONT_END)
    if fs != -1 and fe > fs:
        # Trailing "\n" for the blank line the body needs — see _sub_readme.
        text = (text[:fs] + _guide_claude_front(title, slug) + "\n"
                + text[fe + len(CLAUDE_FRONT_END):].lstrip("\n"))
    else:
        print("  CLAUDE.md        WARNING: no front-matter markers; kept the kit's opening")

    def _fill(s: str) -> str:
        return (s.replace("{{GUIDE_NAME}}", title)
                 .replace("{{GUIDE_SLUG}}", slug)
                 .replace("<DESCRIBE YOUR GUIDE>\n\n", ""))

    # Fill placeholders ONLY outside the managed region, so bootstrap never alters
    # the shared block — it must stay byte-identical to the kit's, or the fork's
    # managed-region checksum diverges and it drifts immediately. If markers are
    # absent (a pre-marker CLAUDE.md) fall back to whole-file substitution.
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
    """Materialize the opt-in web layer (only for --with-web). wrangler.jsonc is
    GENERATED from the fork's guide.toml by cfadapter, not substituted from the
    template: its `routes` block is conditional structure (present only when
    [deploy] domain is set), which value substitution cannot express, and the
    domain-less fork is the cold-start persona the kit exists for. transforms.py is
    activated ONLY when --with-transforms is also given — writing it makes the
    (always-present) SOURCE_FILES entry start contributing bytes, and the terminal
    guides deliberately do not want it. Matches adopt-web.py."""
    app_dir = ROOT / "app"
    shutil.copyfile(STYLE_SCREEN_EXAMPLE, ROOT / "style-screen.css")

    if with_transforms:
        transforms = ROOT / "transforms.py"
        if not transforms.exists():
            shutil.copyfile(TRANSFORMS_EXAMPLE, transforms)

    if TEMPLATES_WEB.exists():
        shutil.copytree(TEMPLATES_WEB, app_dir, dirs_exist_ok=True)
        cfadapter.write_wrangler(app_dir, fork_cfg)
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
    print(f"  web layer        materialized (style-screen.css, app/, "
          f"deploy.yml{extra})")


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

    def kit_only(rel: str) -> bool:
        """Ask the MANIFEST, per path, rather than trusting the entry we are on.

        `classify()` resolves exact-entry-before-glob (pinned by
        `test_exact_entry_wins_over_a_covering_glob`), so a file that sits under
        a kit-only glob but carries its own projected entry answers False here.
        Deleting the glob's directory wholesale — which this used to do — ignored
        that rule, so the two halves of one manifest disagreed about the same
        file and only the pruner's answer was destructive.
        """
        e = manifest.classify(rel)
        return e is not None and e.lifecycle == "retained-in-kit" and not e.projects_to

    for entry in manifest.entries:
        if entry.lifecycle != "retained-in-kit" or entry.projects_to:
            continue
        rel = entry.path
        if rel in keep:
            continue
        if rel.endswith("/**"):
            root = ROOT / rel[:-3].rstrip("/")
            if not root.exists():
                continue
            # FILE BY FILE, so a projected exception inside the tree survives.
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    r = p.relative_to(ROOT).as_posix()
                    if r not in keep and kit_only(r):
                        p.unlink()
            # Then the directories, deepest first, and only when empty — an
            # exception left behind must keep the path it lives at.
            for p in sorted((d for d in root.rglob("*") if d.is_dir()),
                            key=lambda d: len(d.parts), reverse=True):
                if not any(p.iterdir()):
                    p.rmdir()
            if root.exists() and not any(root.iterdir()):
                root.rmdir()
            removed.append(rel)
            continue
        target = ROOT / rel
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

    # The reference PDF does not exist until the first release, so the landing
    # page must not link to it and 404.
    #
    # THE CONTINUATION LINES ARE PART OF THE MATCH, and leaving them out is not a
    # cosmetic miss. The bullet this replaces is wrapped across two lines, so an
    # `^…$` match under MULTILINE consumed only the first and left the second
    # stranded — every fork's landing page opened with
    #     > **Read the guide:** the PDF is published here after the first release
    #     > (see *Workflow: editing content*).
    #     > this repo).
    # a dangling half-sentence, in the first thing a visitor reads. The trailing
    # group takes any following `> ` line that does not begin a new bold bullet,
    # so the `>` separator and the bullets after it survive untouched.
    text = re.sub(
        r"^> \*\*Read the guide:\*\*.*(?:\n> (?!\*\*)\S.*)*",
        "> **Read the guide:** the PDF is published here after the first release "
        "(see *Workflow: editing content*).",
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
    for proj in manifest.expanded_projections(ROOT, shape, slug=fork_cfg.OUTPUT_SLUG):
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
        description="Initialize a fork of guide-kit with your own title, slug, and metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("title", help='Guide title, e.g. "A Beginner\'s Guide to Foo".')
    p.add_argument("slug", help="Kebab-case slug; drives the PDF filename and pixi project name.")
    p.add_argument("--author", help="Author name.")
    p.add_argument("--description", help="Short guide description (guide.toml DESCRIPTION).")
    p.add_argument("--keywords", help="Comma-separated keywords (guide.toml KEYWORDS).")
    p.add_argument("--copyright-year", dest="copyright_year", type=int,
                   help="Copyright year (default: the kit's).")
    p.add_argument("--source-repo", default="rosslevinsky/guide-kit",
                   help="Upstream kit repo recorded in .template-version (a third-party fork sets its own).")
    p.add_argument("--kit-version", default="unknown",
                   help="Human-readable kit version label recorded in .template-version.")
    p.add_argument("--with-web", action="store_true", help="Materialize the opt-in web layer.")
    p.add_argument("--with-transforms", action="store_true",
                   help="Also activate the transforms.py hook (only meaningful with --with-web).")
    args = p.parse_args()

    _validate(args.title, args.slug)

    # Capture the KIT's values + managed digest from the PRISTINE --template copy,
    # before any edit — these are what the fork records for drift comparison.
    kit_cfg = kitconfig.load(ROOT)
    try:
        kit_digest = sync.compute_managed_digest(ROOT)
    except sync.SyncError as exc:
        sys.exit(
            "bootstrap.py: cannot compute the kit's managed digest — the kit's CLAUDE.md needs "
            "<!-- kit:begin -->/<!-- kit:end --> markers. "
            f"Nothing was written. ({exc})"
        )
    kit_slug = kit_cfg.OUTPUT_SLUG
    shape = "web-enabled" if args.with_web else "pdf-only"

    print(f"Initializing fork as {args.title!r} (slug: {args.slug})...")
    _write_guide_toml(
        args.title, args.slug,
        args.author or kit_cfg.AUTHOR,
        args.description or kit_cfg.DESCRIPTION,
        args.keywords or kit_cfg.KEYWORDS,
        args.copyright_year if args.copyright_year is not None else kit_cfg.COPYRIGHT_YEAR,
        with_web=args.with_web,
    )
    fork_cfg = kitconfig.load(ROOT)
    _render_templated_files(kit_cfg, fork_cfg, shape)
    _sub_readme(args.title, args.slug)
    _sub_claude(args.title, args.slug)

    if args.with_web:
        _materialize_web(kit_cfg, fork_cfg, args.with_transforms)

    # Delete every inherited kit reference artifact — a fresh fork has ZERO root
    # PDFs. Both the guide and the DECK: a fork that kept `guide-template-slides.pdf`
    # would ship the kit's placeholder deck under its own name, and the drift
    # check would report a file the fork never rendered.
    for inherited in (ROOT / f"{kit_slug}.pdf", ROOT / f"{kit_slug}-slides.pdf"):
        if inherited.exists():
            inherited.unlink()
            print(f"  {inherited.name}  removed (a fork has no reference artifact "
                  f"until its first release)")

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
    print("  3. `make release MSG=\"Initial content\"` to commit source + baseline.")
    print("  4. `git push` to publish.")
    if args.with_web:
        print("  5. Web layer: `cd app && npm install`, `make dev` to preview. For deploys add")
        print("     CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID repo secrets (README \"Website deploy\").")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
