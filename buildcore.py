#!/usr/bin/env python3
"""Artifact-neutral build orchestration: everything the renderers share.

Split out of `build.py` so that per-artifact renderers can live in their own
modules. That split is the mechanism behind a specific promise: `build.py` was a
PDF-closure input while it also held the website's chrome, its navigation script
and its post-processing, so **every web change re-staled all eight reference
PDFs**. Web behaviour now lives in `render_site.py`, which no artifact but the
site depends on.

What belongs here: config and paths, the version stamp and determinism helpers,
the transforms hook, the glyph-coverage gate, pandoc invocation, the shared HTML
wrapper, and template hygiene. What does not: anything that knows how one
artifact in particular is rendered.

**Renderers must reach shared state as `buildcore.NAME`, never
`from buildcore import NAME`.** The second form binds a copy at import time, so a
test that monkeypatches `buildcore.REFERENCE_PDF` would not be seen by the
renderer — and several tests rely on exactly that.
"""
from __future__ import annotations


import base64
import hashlib
from html.parser import HTMLParser
import html
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import datetime as _datetime
from pathlib import Path

import cascadecheck
import kitconfig

# ----- Repo root + per-guide constants -----
# ROOT is established first so kitconfig's strict loader reads THIS repo's
# guide.toml. The six guide-specific values now live in guide.toml and are
# read through kitconfig — build.py holds no guide-specific literal (that
# property is asserted by tests/test_guide_toml_complete.py). The four LICENSE_*
# values below are family-fixed, identical-tier constants and deliberately stay
# here.
ROOT = Path(__file__).parent.resolve()
_cfg = kitconfig.load(ROOT)
TITLE = _cfg.TITLE
OUTPUT_SLUG = _cfg.OUTPUT_SLUG
AUTHOR = _cfg.AUTHOR
DESCRIPTION = _cfg.DESCRIPTION
KEYWORDS = _cfg.KEYWORDS
COPYRIGHT_YEAR = _cfg.COPYRIGHT_YEAR

# ----- Licensing shown in the rendered output -----
# The guide CONTENT is CC BY 4.0; the build tooling (code, CSS, config) is
# Apache 2.0. The PDF colophon (last page) surfaces this so a reader of the
# PDF sees the terms, not just someone browsing the repo. COPYRIGHT is DERIVED
# from guide.toml's year + author — the year is a stored constant (never a clock
# read) so renders stay deterministic and `make verify` is stable.
COPYRIGHT = f"© {COPYRIGHT_YEAR} {AUTHOR}"
LICENSE_CONTENT_NAME = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
LICENSE_CONTENT_URL = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_CODE_NAME = "Apache License 2.0"
LICENSE_CODE_URL = "https://www.apache.org/licenses/LICENSE-2.0"

# ----- Paths -----
SRC = ROOT / "guide.md"
STYLE = ROOT / "style.css"
# The build/ directory holds the WORKING render (gitignored). `make` writes
# here; `make verify` compares this to the committed reference at the repo
# root. `make baseline` (and `make release`) copies build/<slug>.pdf onto
# the root <slug>.pdf, which is the file readers download from GitHub.
BUILD_DIR = ROOT / "build"
OUT_PDF = BUILD_DIR / f"{OUTPUT_SLUG}.pdf"
OUT_HTML = BUILD_DIR / f"{OUTPUT_SLUG}.html"
# The committed reference PDF at the repo root. Named for the guide so it
# downloads cleanly from GitHub (no anonymous "baseline.pdf"). Override
# REFERENCE_PDF if you want the old `baseline.pdf` convention.
REFERENCE_PDF = ROOT / f"{OUTPUT_SLUG}.pdf"

# Files whose changes invalidate the version stamp and the deterministic-render
# timestamp. transforms.py is included unconditionally — git silently ignores
# nonexistent paths in `log` / `status` queries, and `_content_hash` guards
# with `p.exists()`, so the same list works whether or not the hook is
# activated. (Activating the hook does still bump the footer hash, because
# the new file's bytes become part of the content. That gotcha is intrinsic
# to a content-derived stamp and is called out in CLAUDE.md.)
SOURCE_FILES = kitconfig.SOURCE_FILES  # canonical list (adds guide.toml, kitconfig.py) lives in kitconfig


# ---------------------------------------------------------------------------
# Version stamp + determinism helpers
# ---------------------------------------------------------------------------

def _is_dirty(artifact: str = "pdf") -> bool:
    """Return True if `git status --porcelain` reports any modified or
    untracked stamp input. The `--` scope is load-bearing: it constrains the
    dirty check to the version-stamp input list so transient build artifacts
    (notably the just-rendered PDF) don't trigger a false dirty.

    That scope is `stamp_pathspec(artifact)` — the artifact's own file deps
    plus guide.toml — because those feed its closure hash. Scoped to the PDF's
    inputs alone, an uncommitted style-screen.css edit moved the site's hash
    while its stamp still claimed clean, which is precisely the unreproducible
    reference the marker exists to prevent.

    guide.toml is included whole here even though the config dependency is
    key-level, because git cannot scope to a key. That is deliberately
    conservative in the safe direction: it can report dirty when only an
    out-of-closure table moved, which never blesses an unreproducible
    reference. Removing git from the render path entirely settles it."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--"]
            + kitconfig.stamp_pathspec(artifact, _cfg),
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# The footer stamp's field separator, re-exported from its single definition in
# kitconfig. Named here because it is a rendered literal that lives in code
# rather than guide.md, so check_glyph_coverage() has to scan it explicitly — an
# editor who swaps it for a glyph the bundled faces lack would otherwise put an
# uncovered character on every page. Aliased rather than re-spelled: two
# spellings of one separator is exactly the drift a single definition removes.
_STAMP_SEP = kitconfig.STAMP_SEP

# A character reference, numeric or named. Used by the glyph gate to see the
# codepoint an author WROTE AS ASCII but that pandoc puts on the page.
_CHAR_REF_RE = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);")


def _decode_char_refs(text: str) -> str:
    """Replace HTML character references with the characters pandoc renders.

    NOT `html.unescape()`, which is wrong here in two specific ways. It applies
    the HTML5 parser's invalid-codepoint rules and returns '' for a
    noncharacter — `&#xFDD0;` decodes to nothing, while pandoc renders U+FDD0 —
    so the gate would go quiet about exactly the kind of exotic codepoint least
    likely to be covered. And `&#10;` decodes to a real newline, shifting every
    later line number in the diagnostic. This decodes by codepoint and folds a
    decoded newline to a space, so the reported `file:line` stays true.

    Unrecognised or out-of-range references are left as written: the literal
    ASCII is then what gets scanned, which is what renders.
    """
    def one(m: "re.Match[str]") -> str:
        ref = m.group(1)
        if ref.startswith("#"):
            try:
                cp = int(ref[2:], 16) if ref[1] in "xX" else int(ref[1:])
            except ValueError:
                return m.group(0)
            # Surrogates are not characters; out of range is not decodable.
            if not 0 <= cp <= 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
                return m.group(0)
            decoded = chr(cp)
        else:
            decoded = html.entities.html5.get(ref + ";")
            if decoded is None:
                return m.group(0)
        return "".join(" " if c in "\r\n" else c for c in decoded)

    return _CHAR_REF_RE.sub(one, text)


def artifact_date(artifact: str = "pdf") -> str:
    """The artifact's authored EDITION date, from `[artifacts.<name>] date`.

    Replaces a `git log` over a pathspec. Git could not tell a `[deploy]` edit
    from a `[theme]` edit inside one guide.toml, so the displayed date — and
    therefore the rendered bytes — moved for either. An authored key cannot."""
    cfg = kitconfig.load(ROOT)
    entry = cfg.artifacts.get(artifact)
    if entry is None:
        raise SystemExit(
            f"build: artifact {artifact!r} has no [artifacts.{artifact}] table in "
            f"guide.toml, so it has no edition date to stamp with."
        )
    return entry.date


def _version_stamp(artifact: str = "pdf") -> str:
    """Compose this artifact's stamp: its authored date, its own closure hash,
    and ` · dirty` when the working tree has uncommitted changes to its inputs.

    Per-artifact throughout. Sharing one stamp is what made a screen-only edit
    move the PDF, and would make a slides stylesheet re-stale a document that
    did not change."""
    return kitconfig.format_stamp(
        artifact_date(artifact),
        kitconfig.artifact_closure_hash(artifact, root=ROOT),
        dirty=_is_dirty(artifact),
    )


def _source_date_epoch(artifact: str = "pdf") -> int:
    """`SOURCE_DATE_EPOCH` for the reproducible-builds standard: midnight UTC of
    the artifact's authored date.

    Midnight UTC, not local: a local-midnight interpretation would make the
    embedded PDF timestamp depend on the renderer's timezone, which is exactly
    the host-dependence the determinism regime exists to remove."""
    date = _datetime.datetime.strptime(artifact_date(artifact), "%Y-%m-%d")
    return int(date.replace(tzinfo=_datetime.timezone.utc).timestamp())


def _qpdf_canonicalize(pdf_path: Path) -> None:
    """Rewrite `pdf_path` in place via `qpdf --deterministic-id
    --normalize-content=y --object-streams=preserve`. Strips per-run document
    IDs and normalizes content streams so two builds of identical source
    produce content-identical PDFs."""
    with tempfile.NamedTemporaryFile(
        suffix=".pdf", delete=False, dir=pdf_path.parent
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            [
                "qpdf",
                "--deterministic-id",
                "--normalize-content=y",
                "--object-streams=preserve",
                str(pdf_path),
                str(tmp_path),
            ],
            check=True,
        )
        os.replace(tmp_path, pdf_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _load_transforms():
    """Import `transforms.py` if it exists next to build.py, else return None."""
    hook_path = ROOT / "transforms.py"
    if not hook_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("transforms", hook_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_transforms(html_body: str, target: str) -> str:
    """Pipe `html_body` through the transforms hook for the given target
    ("pdf" or "web"). Prefers the per-output entry point
    (`post_pandoc_html_for_<target>`); falls back to the single-entry
    `post_pandoc_html` for forks that don't differentiate; returns the body
    unchanged when no hook is present."""
    module = _load_transforms()
    if module is None:
        return html_body
    per_output = getattr(module, f"post_pandoc_html_for_{target}", None)
    if callable(per_output):
        return per_output(html_body)
    single = getattr(module, "post_pandoc_html", None)
    if callable(single):
        return single(html_body)
    return html_body


# ---------------------------------------------------------------------------
# Glyph coverage gate
# ---------------------------------------------------------------------------

# Codepoints that never reach a glyph: ASCII control characters plus the
# whitespace the layout engine consumes rather than draws. Checking them would
# produce false failures on every document.
_NON_RENDERING = set(range(0x00, 0x20)) | {0x7F, 0x20, 0xA0, 0x200B, 0xFEFF}


def _bundled_font_files() -> list[Path]:
    """The faces the gate checks. Read from disk via kitconfig rather than by
    parsing style.css's @font-face rules: the parse would be the more precise
    question ("is every DECLARED face present?") but it is also a second,
    drifting implementation of the cascade. Checking the directory means a face
    that exists but was never wired up counts as coverage it does not actually
    provide — a deliberate false-negative, preferred over a CSS parser whose
    disagreements with WeasyPrint would surface as phantom failures."""
    return kitconfig.font_files(ROOT)


UPSTREAM_HASHES = "UPSTREAM-HASHES.json"

# The hermetic Fontconfig template and where its resolved copy is written.
FONTCONFIG_TEMPLATE = ROOT / "fontconfig" / "fonts.conf"
FONTCONFIG_DIR = BUILD_DIR / "fontconfig"


def fontconfig_env(resolved: Path) -> dict[str, str]:
    """The environment variables that select `resolved`.

    Separated from the mutation so a CALLER can pass them to one subprocess
    instead of changing the whole process. `hermetic_fontconfig()` still sets
    them globally, because the in-process renderer needs them — but a test or a
    tool that only wants to ASK a question should not have to accept a permanent
    change to os.environ to do it."""
    return {"FONTCONFIG_FILE": str(resolved),
            "FONTCONFIG_PATH": str(resolved.parent)}


def hermetic_fontconfig(set_env: bool = True) -> Path | None:
    """Resolve the Fontconfig template to absolute paths, write it under build/,
    and point this process at it. Returns the resolved path (None if no template).

    WHY THE INDIRECTION. Fontconfig has no portable spelling for "relative to the
    repository root", so a checked-in config would need an absolute path that is
    wrong on every other machine. The template is the reviewable, synced artifact;
    the resolved copy is generated and gitignored.

    WHY IT MATTERS AT ALL. Bundling faces and writing a careful cascade does not
    make a render host-independent on its own: WeasyPrint delegates matching and
    fallback to Pango/Fontconfig, which answers from the HOST's fonts. Measured
    before this existed, `fc-match 'Source Serif 4'` on an ordinary Linux box
    returned a host DejaVu — a system font standing in for a family this
    repository ships."""
    if not FONTCONFIG_TEMPLATE.is_file():
        # FAIL CLOSED when there are faces to protect. A fork that never adopted
        # bundled fonts has nothing to be hermetic ABOUT and passes; a tree that
        # HAS the faces but lost the template would otherwise render against the
        # host's font configuration, silently, under an unchanged stamp — the
        # precise failure the template exists to prevent.
        if kitconfig.font_files(ROOT):
            raise SystemExit(
                f"build: {FONTCONFIG_TEMPLATE.relative_to(ROOT)} is missing, but this "
                f"guide bundles fonts. Rendering would fall back to the host's font "
                f"configuration. Restore it (`sync.py <guide> --apply`) and re-run."
            )
        return None
    font_dir = ROOT / kitconfig.FONT_DIR
    cache_dir = FONTCONFIG_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    resolved = FONTCONFIG_DIR / "fonts.conf"
    resolved.write_text(
        FONTCONFIG_TEMPLATE.read_text(encoding="utf-8")
        .replace("__FONT_DIR__", str(font_dir))
        .replace("__GENERATED_DIR__", str(ROOT / kitconfig.GENERATED_FONT_DIR))
        .replace("__CACHE_DIR__", str(cache_dir)),
        encoding="utf-8",
    )
    # FONTCONFIG_FILE replaces the config entirely; FONTCONFIG_PATH is set too so
    # a library that looks for a directory rather than a file finds the same one.
    # `set_env=False` is for callers that only want the resolved path: leaving a
    # stale FONTCONFIG_FILE behind pointed a later in-process render at a config
    # whose directory had been deleted, and Pango segfaulted rather than
    # complaining.
    if set_env:
        os.environ.update(fontconfig_env(resolved))
    return resolved


def assert_hermetic_fontconfig(set_env: bool = True) -> None:
    """Prove the environment is actually hermetic, by asking it.

    A config file that exists is not evidence; `fc-match` resolving INSIDE
    fonts/vendor is. Skipped where fc-match is unavailable — the assertion is a
    guard, not a dependency."""
    resolved = hermetic_fontconfig(set_env=set_env)
    if resolved is None or shutil.which("fc-match") is None:
        return
    allowed = tuple(str((ROOT / d).resolve())
                    for d in (kitconfig.FONT_DIR, kitconfig.GENERATED_FONT_DIR))
    env = {**os.environ, **fontconfig_env(resolved)}

    # THE WHOLE REACHABLE SET, not a sample of winning matches. Probing a handful
    # of families only ever proves those families resolved well: a config that
    # scanned fonts/vendor AND a host directory would answer all of them from
    # vendor and still leave every other host face available to the renderer for
    # fallback. `fc-list` enumerates what Fontconfig can see at all, which is the
    # property being claimed.
    listed = subprocess.run(
        ["fc-list", "--format=%{file}\n"], capture_output=True, text=True,
        encoding="utf-8", env=env,
    ).stdout.splitlines()
    outsiders = sorted({f for f in (x.strip() for x in listed)
                        if f and not f.startswith(allowed)})
    if outsiders:
        raise SystemExit(
            "build: Fontconfig is NOT hermetic — it can see fonts outside the "
            f"bundled directories:\n  " + "\n  ".join(outsiders[:10])
            + (f"\n  ...and {len(outsiders) - 10} more" if len(outsiders) > 10 else "")
            + "\nAny of these is reachable as a fallback, so this render is not "
              "reproducible on another machine."
        )
    if not listed or not any(x.strip() for x in listed):
        raise SystemExit(
            "build: Fontconfig can see NO fonts at all — the bundled directory is "
            "not being scanned, so every glyph would fall back to nothing."
        )

    # ...and the matches still have to LAND somewhere bundled, including the
    # generics and a family that does not exist, which is the fallback path.
    leaked = []
    for family in ("Source Serif 4", "Source Sans 3", "DejaVu Sans Mono",
                   "serif", "sans-serif", "monospace", "NoSuchFamilyAnywhere"):
        got = subprocess.run(
            ["fc-match", "-f", "%{file}", family],
            capture_output=True, text=True, encoding="utf-8", env=env,
        ).stdout.strip()
        if not got.startswith(allowed):
            leaked.append(f"{family} -> {got or '(no match)'}")
    if leaked:
        raise SystemExit(
            "build: Fontconfig is NOT hermetic — these resolved outside the "
            f"bundled directories:\n  " + "\n  ".join(leaked)
        )


def check_font_provenance() -> None:
    """Assert every bundled face still hashes to its recorded upstream value.

    Runs BEFORE rendering, which is the whole point. A face is a render input
    with no other tripwire: swap one for a silently different upstream build —
    a re-release under the same version, a corrupted download, a well-meant
    "update the fonts" commit — and every guide's typography changes. The stamp
    would move (the faces are in the closure), but nothing would say WHY, and a
    re-baseline would simply bless the new bytes. This names the file instead.

    A face present on disk but absent from the record is refused too: unrecorded
    provenance is the state the record exists to prevent, and admitting it would
    let the check be bypassed by adding a face without registering it."""
    import json

    record_path = _root_font_dir() / UPSTREAM_HASHES
    if not record_path.is_file():
        return  # a fork that has not adopted bundled fonts has nothing to assert

    recorded = json.loads(record_path.read_text(encoding="utf-8")).get("faces", {})
    problems: list[str] = []
    for path in _bundled_font_files():
        want = recorded.get(path.name)
        if want is None:
            problems.append(f"{path.name}: present on disk but not in {UPSTREAM_HASHES}")
            continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != want:
            problems.append(
                f"{path.name}: sha256 {got[:16]}… != recorded {want[:16]}…"
            )
    missing = sorted(set(recorded) - {p.name for p in _bundled_font_files()})
    problems += [f"{name}: recorded but missing from disk" for name in missing]

    if problems:
        raise SystemExit(
            "build: bundled font provenance check FAILED —\n  "
            + "\n  ".join(problems)
            + f"\nThe faces are render inputs. Restore the recorded binaries, or — if "
            f"this change is intended — update {kitconfig.FONT_DIR}/{UPSTREAM_HASHES} "
            f"in the same commit so the new provenance is reviewed, not assumed."
        )


def _root_font_dir() -> Path:
    return ROOT / kitconfig.FONT_DIR


def embedded_faces(pdf: Path) -> list[str]:
    """The font names a rendered PDF actually EMBEDS, via `pdffonts`.

    The output side of the no-synthesized-weights requirement. Asserting the real
    bold and italic binaries exist on disk checks the INPUT; it does not check
    that the renderer reached for them. WeasyPrint will fake a missing weight
    from the regular face, and the result renders, looks roughly right, and is
    not the typeface anyone chose — so the only conclusive evidence is what came
    out."""
    out = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    faces = []
    for line in out.splitlines()[2:]:          # skip the header + rule
        if not line.strip():
            continue
        name = line.split()[0]
        # pdffonts prefixes a subsetted face with a 6-letter tag + '+'.
        faces.append(name.split("+", 1)[1] if "+" in name else name)
    return sorted(faces)


THEMES_DIR = ROOT / "themes"


# One family name per CJK locale. The families are supplied by subset faces in
# `fonts/generated/` (tools/subset-cjk.py); the kit bundles no CJK binary itself.
_CJK_FAMILY = {"jp": "Guide CJK JP", "sc": "Guide CJK SC",
               "tc": "Guide CJK TC", "kr": "Guide CJK KR"}
_CJK_LANG = {"jp": "ja", "sc": "zh-Hans", "tc": "zh-Hant", "kr": "ko"}


def cjk_css() -> str:
    """`:lang()`-keyed font selection for every declared CJK locale.

    AN ORDERED CONFIG LIST IS NOT SUFFICIENT, which is the whole reason this
    exists. Han unification gives Japanese, Simplified Chinese, Traditional
    Chinese and Korean the SAME codepoints for many characters, with different
    regional glyph shapes: U+76F4 is one codepoint and four correct drawings. A
    priority list can only pick one face for that codepoint, so a guide declaring
    two locales would render one of them wrong — and wrong in a way that looks
    like a font choice rather than an error.

    The selector is `:lang()`, so the ANNOTATION carries the answer. That makes
    the `lang` attribute a hard requirement rather than a nicety: text with no
    annotation falls through to the first declared locale, which is a guess.
    `check_cjk_annotations()` refuses a build that relies on that guess."""
    locales = _cfg.fonts.cjk
    if not locales:
        return ""
    rules = ["/* ---- CJK: per-locale faces, selected by :lang() ---- */"]
    for loc in locales:
        family, tag = _CJK_FAMILY[loc], _CJK_LANG[loc]
        rules.append(
            f':lang({tag}) {{ font-family: "{family}", var(--body-font); }}')
    return "\n".join(rules) + "\n"


class _LangScanner(HTMLParser):
    """Find CJK text that no ancestor element annotates with `lang`.

    A PARSER, not a regex. The regex this replaces was wrong in both directions,
    and each way is its own kind of bad: `<img lang="ja"/><p>直</p>` was ACCEPTED
    because the non-greedy match ran past the void element and swallowed the
    following paragraph, while `<div lang="ja"><p>直</p><p>文</p></div>` was
    REJECTED because the match stopped at the first closing tag and the second
    paragraph looked unannotated. Nesting and inheritance are the whole question
    here, so the answer has to model them: `lang` is inherited, and a text node is
    annotated if ANY open ancestor carries it."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "source", "track", "wbr"}
    CJK = re.compile(
        "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[bool] = []       # has this open element (or an ancestor) a lang?
        self.unannotated: str | None = None

    def _has_lang(self, attrs) -> bool:
        return any(k.lower() == "lang" and v for k, v in attrs)

    def handle_starttag(self, tag, attrs):
        inherited = self.stack[-1] if self.stack else False
        if tag.lower() in self.VOID:
            return                        # void: annotates itself only, and it has no text
        self.stack.append(inherited or self._has_lang(attrs))

    def handle_startendtag(self, tag, attrs):
        return                            # self-closing: no content to annotate

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.unannotated is not None:
            return
        if self.stack and self.stack[-1]:
            return                        # annotated by this element or an ancestor
        m = self.CJK.search(data)
        if m:
            self.unannotated = m.group(0)


def check_cjk_annotations(html_body: str) -> None:
    """Refuse a multi-locale guide whose CJK text is not annotated.

    Only fires when more than ONE locale is declared: with a single locale there
    is nothing to disambiguate and the document language settles it. With two,
    unannotated Han text is a coin flip between two correct-looking renders."""
    locales = _cfg.fonts.cjk
    if len(locales) < 2:
        return
    scanner = _LangScanner()
    scanner.feed(html_body)
    scanner.close()
    found = scanner.unannotated
    if found:
        raise SystemExit(
            f"build: this guide declares {len(locales)} CJK locales "
            f"({', '.join(locales)}) but has CJK text outside any lang-annotated "
            f"element (first: {found!r} U+{ord(found):04X}).\n"
            f"  Han unification means the same codepoint needs a DIFFERENT face per "
            f"locale, so `:lang()` — not an ordered list — is what selects it. "
            f"Wrap the text in an element carrying `lang`."
        )


def theme_css(output: str, override: str) -> str:
    """The resolved cascade for one output, as a single stylesheet.

    THREE LAYERS, IN THIS ORDER — theme tokens, then the guide's `[theme.tokens]`,
    then the guide's own override file:

        themes/<name>/<output>.css   the selected theme's token set
        [theme.tokens] in guide.toml one guide retinting a value or two
        style{,-screen,-slides}.css  the guide's own sheet — structure, and the
                                     last word on anything it chooses to set

    CONCATENATION ORDER, not `@layer`. `@layer` inverts the intuition an author
    brings — a later layer loses to an earlier one unless it is also layered — and
    WeasyPrint's support for it is not something a family of eight repositories
    should be betting its typography on. Plain source order means "later wins",
    which is what every contributor already expects from CSS.

    The SCREEN and SLIDES sheets are layered over `print.css` rather than
    repeating it: only what genuinely differs on screen belongs in screen.css, so
    a palette change is made once.

    A missing theme is a hard failure, not a silent fallback: the render would
    otherwise proceed with every `var()` unresolved, which does not look like an
    error — it looks like a slightly wrong design."""
    name = _cfg.theme.name
    layers: list[str] = []
    # The @font-face declarations come FIRST and are KIT-OWNED: a theme names
    # these families in its tokens, so they must already exist, and no override
    # is allowed to declare one (see cascadecheck.check_override).
    faces = ROOT / "fontfaces.css"
    if faces.is_file():
        layers.append(f"/* ---- kit: fontfaces.css ---- */\n"
                      + faces.read_text(encoding="utf-8"))
    sheets = ["print.css"] if output == "print" else ["print.css", f"{output}.css"]
    for sheet in sheets:
        path = THEMES_DIR / name / sheet
        if not path.is_file():
            raise SystemExit(
                f"build: theme {name!r} has no {sheet} ({path.relative_to(ROOT)} is "
                f"missing). Every `var()` would resolve to nothing, which renders as a "
                f"subtly wrong design rather than as an error."
            )
        layers.append(f"/* ---- theme: {name}/{sheet} ---- */\n"
                      + path.read_text(encoding="utf-8"))
    token_css = _cfg.theme.token_css
    if token_css:
        layers.append(token_css)
    cjk = cjk_css()
    if cjk:
        layers.append(cjk)
    layers.append(f"/* ---- guide override ---- */\n{override}")
    return "\n".join(layers)


def bundled_font_families() -> list[str]:
    """The distinct typographic families among the bundled faces.

    Read from each font's OWN name table, not inferred from filenames: the
    colophon is a licence attribution, so the family it names has to be the
    family the binary declares itself to be. Deriving it also means adding a face
    updates the credit — a hardcoded list is the kind of paired edit that gets
    forgotten exactly when a new family is introduced."""
    from fontTools.ttLib import TTFont

    names: set[str] = set()
    for path in _bundled_font_files():
        with TTFont(str(path), lazy=True, fontNumber=0) as font:
            # nameID 16 (typographic family) where present, else 1 (family):
            # for a 4-face family the two differ, and 16 is the one that groups
            # "Bold" and "Italic" under one name instead of splitting them.
            fam = font["name"].getDebugName(16) or font["name"].getDebugName(1)
            if fam:
                names.add(fam.strip())
    return sorted(names)


def _covered_codepoints() -> set[int]:
    """Union of the cmap tables of every bundled face."""
    from fontTools.ttLib import TTFont

    covered: set[int] = set()
    for path in _bundled_font_files():
        with TTFont(str(path), lazy=True, fontNumber=0) as font:
            covered |= set(font.getBestCmap().keys())
    return covered


def check_overrides(cascade_css: str) -> None:
    """Refuse any override that can reach a family the kit does not bundle.

    Runs on the SHIPPING files, not on a fixture: the print and screen overrides
    and — the vector a CSS-only guard misses entirely — the `font-family`
    presentation attributes on the inline SVG diagrams in `guide.md`. A diagram
    can set a family with no stylesheet involved at all."""
    allowed = cascadecheck.bundled_families(cascade_css)
    if not allowed:
        raise SystemExit(
            "build: the cascade declares no @font-face families, so the override "
            "guard has nothing to check against. fontfaces.css is missing or empty."
        )
    try:
        for sheet in ("style.css", "style-screen.css", "style-slides.css"):
            cascadecheck.check_override(ROOT / sheet, allowed)
        cascadecheck.check_svg_attributes(SRC, allowed)
    except cascadecheck.CascadeError as exc:
        raise SystemExit(f"build: {exc}") from exc


def _family_cmaps(cascade_css: str) -> dict[str, set[int]]:
    """CSS family name (folded) -> the codepoints its faces provide."""
    from fontTools.ttLib import TTFont

    faces = (ROOT / "fontfaces.css")
    faces_css = faces.read_text(encoding="utf-8") if faces.is_file() else cascade_css
    out: dict[str, set[int]] = {}
    for path in _bundled_font_files():
        with TTFont(str(path), lazy=True, fontNumber=0) as font:
            cmap = set(font.getBestCmap().keys())
            fam = (font["name"].getDebugName(16) or font["name"].getDebugName(1) or "")
        names = cascadecheck.families_for_source(faces_css, path.name) or {fam}
        for name in names:
            out.setdefault(name.strip().lower(), set()).update(cmap)
    return out


def check_rendered_coverage(document, cascade_css: str) -> None:
    """Every codepoint on the page is drawn by a face THAT BOX's family reaches.

    This is the corpus check the phase asks for, and it is a different question
    from the pre-render scan in two ways that matter.

    The CORPUS is the final box tree — after Pandoc, after `transforms.py`, after
    the injected colophon and stamp, including CSS generated content. The source
    scan cannot see any of those.

    And COVERAGE is per box, computed from the family the cascade actually
    resolved for it, rather than from every family mentioned anywhere in the
    stylesheets. A syntactic reachable-set counts a family named in a selector
    that matches nothing: adding `.never-matches { font-family: "Guide Sans" }`
    would otherwise contribute Guide Sans's 42 exclusive codepoints to coverage
    while no rendered box can use them, and a character only that face provides
    would pass the gate and render as tofu."""
    cmaps = _family_cmaps(cascade_css)
    missing: dict[int, str] = {}

    def families_of(box) -> list[str]:
        style = getattr(box, "style", None)
        if style is None:
            return []
        try:
            return [str(f).strip().lower() for f in style["font_family"]]
        except (KeyError, TypeError):
            return []

    def walk(box):
        text = getattr(box, "text", None)
        if text:
            covered: set[int] = set()
            for fam in families_of(box):
                covered |= cmaps.get(fam, set())
            for ch in text:
                cp = ord(ch)
                if cp not in covered and cp not in missing and not ch.isspace():
                    missing[cp] = ", ".join(families_of(box)) or "(no family)"
        for child in getattr(box, "children", ()) or ():
            walk(child)

    for page in document.pages:
        walk(page._page_box)

    if missing:
        detail = "\n  ".join(
            f"U+{cp:04X} {chr(cp)!r} — the box's cascade resolved to: {fams}"
            for cp, fams in sorted(missing.items())[:20])
        raise SystemExit(
            f"build: {len(missing)} codepoint(s) on the rendered page have no glyph "
            f"in the faces their own cascade reaches:\n  {detail}\n"
            f"  These render as tofu. Either the character does not belong in the "
            f"guide, or the cascade for that element needs a family that covers it."
        )


def check_rendered_families(document, cascade_css: str) -> None:
    """Every text box in the RENDERED box tree resolves to a bundled family.

    The output-side counterpart to the override guard. The guard reads the CSS
    the repository contains; this reads what WeasyPrint actually computed, after
    the cascade, inheritance and the `var()` substitutions have all happened — so
    a family reached by a route nobody anticipated still shows up here.

    STATED LIMIT: this proves a FAMILY, not a FACE. Which binary Fontconfig then
    hands the renderer for that family is a different question, answered by the
    hermetic environment and by reading the embedded faces back out of the PDF."""
    allowed = {f.lower() for f in cascadecheck.bundled_families(cascade_css)}
    seen: set[str] = set()

    def walk(box):
        style = getattr(box, "style", None)
        if style is not None:
            try:
                seen.update(str(f) for f in style["font_family"])
            except (KeyError, TypeError):
                pass
        for child in getattr(box, "children", ()) or ():
            walk(child)

    for page in document.pages:
        walk(page._page_box)

    # HOST_GENERICS are checked BEFORE the generic allowance: `system-ui` is a
    # generic keyword and resolves to whatever the host calls its UI font, so
    # letting the generic rule wave it through would make this backstop weaker
    # than the static guard it exists to back up.
    strangers = sorted(
        f for f in seen
        if f.lower() in cascadecheck.HOST_GENERICS
        or (f.lower() not in allowed and f.lower() not in cascadecheck.GENERIC)
    )
    if strangers:
        raise SystemExit(
            "build: the rendered box tree resolves families the kit does not "
            f"bundle: {', '.join(strangers)}.\n"
            "  These reached the page through the resolved cascade, so no override "
            "file names them directly — inheritance or a custom property did."
        )


def cascade_covered_codepoints(cascade_css: str) -> set[int]:
    """Codepoints covered by faces the RESOLVED CASCADE actually reaches.

    The predecessor unioned the cmap of every file in `fonts/`, whether or not
    any CSS referred to it, and its own docstring called that a deliberate
    false-negative. It is worse than conservative: a face that is bundled but
    unreachable covers nothing that can appear on the page, so coverage computed
    that way passes for characters the render will draw as tofu.

    Reachability is per THEME, so this genuinely differs between guides: under
    `editorial` nothing names "Guide Sans", so its cmap is not coverage."""
    from fontTools.ttLib import TTFont

    wanted = {f.lower() for f in cascadecheck.reachable_families(cascade_css)}
    covered: set[int] = set()
    for path in _bundled_font_files():
        with TTFont(str(path), lazy=True, fontNumber=0) as font:
            fam = (font["name"].getDebugName(16) or font["name"].getDebugName(1) or "")
            names = {n.lower() for n in _css_family_for(path, fam)}
            if not (names & wanted):
                continue
            covered |= set(font.getBestCmap().keys())
    return covered


def _css_family_for(path: Path, upstream_family: str) -> set[str]:
    """The CSS family a bundled binary is exposed as.

    The kit RENAMES the upstream families in its `@font-face` rules — Source
    Serif 4 becomes "Guide Serif" — so the binary's own name table cannot be
    compared against the cascade directly. The mapping is read from
    fontfaces.css, which is the file that performs the rename."""
    faces = ROOT / "fontfaces.css"
    if not faces.is_file():
        return upstream_family
    families = cascadecheck.families_for_source(faces.read_text(encoding="utf-8"), path.name)
    return families or {upstream_family}


def check_glyph_coverage(cascade_css: str | None = None) -> None:
    """Hard-fail if any codepoint in the rendered source lacks a glyph in the
    bundled fonts.

    WHY THIS EXISTS. Bundling fonts buys one property: the PDF renders
    identically regardless of what the host has installed. An uncovered
    codepoint silently voids it — the cascade falls through to whatever the
    machine happens to provide, so the character renders on the author's box
    and as tofu on someone else's, while `make verify` stays green because the
    SOURCE genuinely did not change. The staleness check answers "is the stamp
    fresh", not "can these fonts draw this text"; this answers the second
    question, and without it the determinism claim is unenforced.

    Scans guide.md plus the strings build.py injects (TITLE via the running
    footer, its `·` separator, and the colophon's author/copyright line).
    Markdown and inline-HTML syntax characters are all ASCII, so the raw file
    is *almost* a superset of the rendered text — with one exception that has
    to be handled rather than waved at: an HTML character reference is pure
    ASCII in source and a non-ASCII codepoint on the page. `&#x1F9D1;` scans as
    covered ASCII and renders as U+1F9D1. `_decode_char_refs()` closes that.

    TWO KNOWN LIMITS, stated rather than hidden.

    It scans source, not the post-pandoc, post-transforms DOM, so a
    transforms.py hook that *injects* a character absent from guide.md goes
    unseen. Scanning rendered HTML would close that, but it moves the gate
    after pandoc and the transform hook — a much later failure point, for a
    case no guide in the family exercises. Revisit if a transform ever emits
    non-ASCII.

    It decodes references without knowing Markdown context, so a reference
    written INSIDE a code span — where pandoc renders it as literal ASCII — is
    scanned as the character it names. That direction is a false POSITIVE: the
    build fails loudly and names the codepoint, rather than shipping tofu
    quietly. For a gate whose entire value is recall, failing loud is the right
    way round to be wrong."""
    covered = cascade_covered_codepoints(cascade_css) if cascade_css else _covered_codepoints()
    if not covered:
        raise SystemExit(
            "build.py: the resolved cascade reaches NO bundled face — the "
            "glyph-coverage gate cannot run, and the render would silently depend "
            "on host fonts."
        )

    # (codepoint, char) -> first "file:line" it appears at
    missing: dict[int, str] = {}

    def scan(text: str, label: str) -> None:
        for lineno, line in enumerate(text.splitlines(), 1):
            for ch in line:
                cp = ord(ch)
                if cp in _NON_RENDERING or cp in covered or cp in missing:
                    continue
                missing[cp] = f"{label}:{lineno}"

    # Decoded, so a character reference is scanned as the codepoint it renders
    # as rather than as the covered ASCII an author typed.
    scan(_decode_char_refs(SRC.read_text(encoding="utf-8")), SRC.name)
    # Strings build.py injects into the page itself; they are not in guide.md
    # but they are just as rendered, and an author's name is exactly where a
    # non-Latin character shows up first.
    scan(f"{TITLE}\n{AUTHOR}\n{COPYRIGHT}", "guide.toml")
    # Literals build.py itself puts on the page: the running footer's stamp
    # separator and the colophon's license names. All ASCII today — scanned so
    # they stay that way, since nothing else would catch an edit here.
    scan(
        f"{_STAMP_SEP}\n{LICENSE_CONTENT_NAME}\n{LICENSE_CODE_NAME}",
        "build.py",
    )

    if not missing:
        return

    faces = ", ".join(p.name for p in _bundled_font_files())
    lines = [
        f"build.py: {len(missing)} codepoint(s) in the source have no glyph in "
        f"the bundled fonts.",
        "",
    ]
    for cp in sorted(missing):
        lines.append(f"  U+{cp:04X} {chr(cp)!r}  first seen at {missing[cp]}")
    lines += [
        "",
        f"Bundled faces: {faces}",
        "",
        "Rendering would fall through to a host font for these, which is exactly",
        "the host-dependence bundled fonts exist to remove. Either add a face that",
        "covers them (see fonts/README.md) or remove the characters from the source.",
    ]
    raise SystemExit("\n".join(lines))


def _pandoc_body() -> str:
    """Run pandoc on guide.md and return the raw HTML body (pre-transform)."""
    pandoc = subprocess.run(
        ["pandoc", str(SRC), "-f", "markdown+raw_html-smart", "-t", "html5"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return pandoc.stdout


def _favicon_data_uri() -> str:
    """A `data:` URI favicon, built from up to two initials of OUTPUT_SLUG.

    A data URI rather than a file because the markup and the resource are then
    the same thing. `<link rel="icon" href="favicon.svg">` satisfies a grep for
    `rel="icon"` whether or not anything ever writes that file, so the check and
    the claim would be about different things; this resource cannot 404 — it IS
    the markup. (When this was written the site build had no asset-copy path at
    all, which made the gap unavoidable rather than merely easy to miss.)

    Derived from OUTPUT_SLUG so each guide's tab is distinguishable, and from
    nothing else, so it is deterministic: no clock, no randomness, no per-build
    id. OUTPUT_SLUG is already a stamp input, so the icon moves only when the
    guide's identity does.
    """
    # Initials of the slug's words, minus a trailing "guide", capped at two.
    # The first letter alone is NOT distinguishable: windows-cmd-guide and
    # windows-powershell-guide both start with "w" and would ship the same icon,
    # which defeats the only reason the icon is derived from the guide at all.
    words = [w for w in OUTPUT_SLUG.split("-") if w and w != "guide"] or ["g"]
    letter = html.escape("".join(w[0] for w in words[:2]).upper())
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="12" fill="#1f2933"/>'
        '<text x="32" y="45" font-family="Helvetica,Arial,sans-serif" '
        f'font-size="34" font-weight="bold" fill="#ffffff" text-anchor="middle">{letter}</text>'
        "</svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)(?!['"]?(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|/|\#))""")


def _prefix_css_urls(css: str, prefix: str) -> str:
    """Prepend `prefix` to every RELATIVE `url()` in a stylesheet.

    Left alone, because none of them resolve against the page's directory:
    absolute (`/x`), protocol-relative (`//host/x`), any scheme (`https:`,
    `data:`), and fragments (`#id`). The scheme test is the general one rather
    than a `data:`/`http:` list — `blob:` and `about:` exist too, and a rewriter
    that only knew the common two would corrupt the rest."""
    if not prefix:
        return css
    return _CSS_URL_RE.sub(lambda m: f"url({m.group(1)}{prefix}", css)


def _wrap_html(body: str, css: str, *, title: str | None = None,
               head_extra: str = "", asset_prefix: str = "") -> str:
    """Wrap a transformed HTML body in the document shell with inlined CSS.

    `title` overrides the document title for a chapter page, which should not
    claim to be the whole guide in a browser tab or a search result.

    `head_extra` carries the indexing directives — `rel="canonical"` or
    `noindex`, decided by `site.canonical`.

    `asset_prefix` is prepended to every relative `url()` in the CSS. A chapter
    is served from `/<slug>/`, one level down, so `fonts/vendor/…` would resolve
    to `/<slug>/fonts/vendor/…` and 404. Passing `../` keeps one CSS string
    correct at both depths without the stylesheet knowing where it is.

    Rewritten GENERICALLY rather than by substituting the one prefix the kit
    happens to emit today. No guide's `style-screen.css` currently contains a
    `url()` at all — checked across all seven — so a `fonts/vendor/`-only
    substitution would be correct by luck, and would silently 404 the first time
    a guide referenced an image. `assets/` arrives in a later phase.

    Absolute, protocol-relative, `data:` and fragment URLs are left alone: they
    do not resolve against the page's directory, so prefixing them would break
    what currently works."""
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{html.escape(title or TITLE)}</title>'
        f'<meta name="author" content="{AUTHOR}">'
        f'<meta name="description" content="{DESCRIPTION}">'
        f'<meta name="keywords" content="{KEYWORDS}">'
        f'<link rel="icon" href="{_favicon_data_uri()}">'
        f'{head_extra}'
        f'<style>{_prefix_css_urls(css, asset_prefix)}</style>'
        '</head><body>'
        f'{body}'
        '</body></html>'
    )


# ---------------------------------------------------------------------------
# Template hygiene
# ---------------------------------------------------------------------------

# Sentinel file shipped with the template repo. bootstrap.py deletes it after
# it substitutes placeholders for the fork's own values. Its presence means
# "the user is building the unrenamed template" and suppresses the hygiene
# check below.
TEMPLATE_SENTINEL = ROOT / ".template-uninitialized"

# Placeholders the template ships with in its docs (README.md, CLAUDE.md).
# If a forked guide still contains any of these, the fork forgot to
# initialize. The hygiene check refuses to build until they're gone.
PLACEHOLDERS = ("{{GUIDE_NAME}}", "{{GUIDE_SLUG}}", "<DESCRIBE YOUR GUIDE>")


def _check_template_hygiene() -> None:
    if TEMPLATE_SENTINEL.exists():
        return
    issues = []
    for name in ("README.md", "CLAUDE.md"):
        p = ROOT / name
        if not p.exists():
            continue
        body = p.read_text(encoding="utf-8")
        for ph in PLACEHOLDERS:
            if ph in body:
                issues.append(f"{name}: still contains '{ph}'")
    # The uninitialized-template signal is the sentinel (handled above) plus the
    # doc placeholders. The former TITLE/OUTPUT_SLUG == default comparisons were
    # dropped: they required a module-level literal equal to guide.toml's values,
    # which this phase forbids (the constants now live only in guide.toml). The
    # slug/title-default backstop is intentionally not reconstructed here:
    # `bootstrap.py` writes the fork's guide.toml itself, so an initialized
    # fork no longer carries the template defaults to compare against.
    if not issues:
        return
    bullet = "\n  ".join(issues)
    raise SystemExit(
        "build.py: template not initialized. Run\n"
        "  pixi run python bootstrap.py \"My Guide Title\" my-guide-slug\n"
        "to substitute placeholders, or delete `.template-uninitialized` to silence\n"
        "this check after handling them manually.\n\n"
        f"Issues:\n  {bullet}"
    )
