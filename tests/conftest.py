"""Shared pytest fixtures for the kit test suite.

The suite is run by the kit-only pixi environment (`pixi run -e kit test`);
targets never run it (they have neither pytest nor a `test` task). This file
also puts the repo root on sys.path so `import kitconfig` (and the other
root-level kit modules) resolves when tests live under tests/.
"""
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Prepend the repo root so root-level modules (kitconfig, build, ...) import
# from tests/ without an installed package.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def repo_root() -> Path:
    """Absolute path to the guide-kit repo root."""
    return REPO_ROOT


# ---------------------------------------------------------------------------
# sync.py test harness: an isolated temp kit + temp target, starting in-sync.
# ---------------------------------------------------------------------------

def _guide_toml(slug: str, *, title="Probe", author="A", desc="d", keywords="k",
                year=2026, site="none") -> str:
    """A valid guide.toml, including the declared shape and the per-artifact
    edition dates the loader now requires. `site` carries the declared shape so
    a fixture's manifest resolution matches what it materializes on disk."""
    text = (
        f'TITLE = "{title}"\n'
        f'OUTPUT_SLUG = "{slug}"\n'
        f'AUTHOR = "{author}"\n'
        f'DESCRIPTION = "{desc}"\n'
        f'KEYWORDS = "{keywords}"\n'
        f'COPYRIGHT_YEAR = {year}\n'
        '[outputs]\n'
        'pdf = true\n'
        f'site = "{site}"\n'
        'slides = false\n'
        '[artifacts.pdf]\n'
        'date = "2026-07-26"\n'
    )
    if site != "none":
        text += '[artifacts.site]\ndate = "2026-07-26"\n'
    return text


_MINIMAL_MANIFEST_PDF = """\
[[entry]]
path = "build.py"
lifecycle = "retained-in-kit"
projects_to = "build.py"
policy = "identical"

[[entry]]
path = "pixi.toml"
lifecycle = "retained-in-kit"
projects_to = "pixi.toml"
policy = "templated"

[[entry]]
path = "CLAUDE.md"
lifecycle = "retained-in-kit"
projects_to = "CLAUDE.md"
policy = "managed-region"

[[entry]]
path = "guide.md"
lifecycle = "retained-in-kit"
projects_to = "guide.md"
policy = "never"
"""

# A `never` web projection as well as an `identical` one, and the pair is the
# point. With only the `identical` entry, every adoption test ran against a
# fixture with no TARGET-OWNED web file in it — so `enable()` comparing such a
# file against the kit's seed and refusing on any difference passed the whole
# suite while breaking the only documented way to add a website to an existing
# guide. A fixture that cannot express the real manifest's shape cannot test it.
_MANIFEST_WEB_EXTRA = """\
[[entry]]
path = ".github/workflows/deploy.yml.example"
lifecycle = "bootstrap-source"
projects_to = ".github/workflows/deploy.yml"
policy = "identical"

[[entry]]
path = "style-screen.css.example"
lifecycle = "bootstrap-source"
projects_to = "style-screen.css"
policy = "never"
"""


@dataclass
class SyncEnv:
    kit: Path
    target: Path


@pytest.fixture
def sync_env(tmp_path):
    """Factory: build an isolated temp kit + temp target that start fully in-sync.

    Tests then mutate one thing to create the drift/refusal/etc. under test.
    Both are real git repos (for the clean-tree checks); rendered_checksums are
    computed with sync's own helpers so the baseline is genuinely in-sync.
    """
    import json
    import sync

    def _git(root, *args):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)

    def _init_commit(root):
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "T")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "state")

    def _make(*, shape="pdf-only", target_slug="probe-guide"):
        kit = tmp_path / "kit"
        target = tmp_path / target_slug
        kit.mkdir()
        target.mkdir()

        # --- kit source ---
        (kit / "guide.toml").write_text(_guide_toml("guide-template"), encoding="utf-8")
        (kit / "build.py").write_text("# build.py v1\n", encoding="utf-8")
        (kit / "pixi.toml").write_text('name = "guide-template"\n# desc for guide-template\n', encoding="utf-8")
        (kit / "CLAUDE.md").write_text(
            f"# Kit\n{sync.MARK_BEGIN}\nshared policy v1\n{sync.MARK_END}\nkit-only tail\n", encoding="utf-8"
        )
        (kit / "guide.md").write_text("# kit demo content\n", encoding="utf-8")
        manifest = _MINIMAL_MANIFEST_PDF
        if shape == "web-enabled":
            (kit / ".github" / "workflows").mkdir(parents=True)
            (kit / ".github" / "workflows" / "deploy.yml.example").write_text("deploy workflow v1\n", encoding="utf-8")
            # The kit's SEED, deliberately different from what the target owns
            # below — that difference is the state `enable()` used to refuse.
            (kit / "style-screen.css.example").write_text("body{color:seed}\n", encoding="utf-8")
            manifest = manifest + "\n" + _MANIFEST_WEB_EXTRA
        (kit / "kit-manifest.toml").write_text(manifest, encoding="utf-8")

        # --- target: projected files, as if previously synced (in-sync) ---
        # The target DECLARES its shape; sync resolves from that declaration, so
        # a web-enabled fixture must say so rather than rely on which files the
        # fixture happens to create.
        (target / "guide.toml").write_text(
            _guide_toml(target_slug, site="single" if shape == "web-enabled" else "none"),
            encoding="utf-8",
        )
        # identical: verbatim copy of the kit file
        (target / "build.py").write_text("# build.py v1\n", encoding="utf-8")
        # templated: the kit file rendered with the target's slug
        kit_cfg = kitconfig_load(kit)
        tgt_cfg = kitconfig_load(target)
        rendered_pixi = sync._render_templated(
            (kit / "pixi.toml").read_text(encoding="utf-8"), kit_cfg, tgt_cfg
        )
        (target / "pixi.toml").write_text(rendered_pixi, encoding="utf-8")
        # managed-region: same shared block, but the target owns its own tail
        (target / "CLAUDE.md").write_text(
            f"# {target_slug}\n{sync.MARK_BEGIN}\nshared policy v1\n{sync.MARK_END}\n"
            "TARGET-OWNED section the guide maintains.\n", encoding="utf-8"
        )
        # never: target-owned content
        (target / "guide.md").write_text("# the target's own guide content\n", encoding="utf-8")
        if shape == "web-enabled":
            (target / "style-screen.css").write_text("body{color:black}\n", encoding="utf-8")
            (target / ".github" / "workflows").mkdir(parents=True)
            (target / ".github" / "workflows" / "deploy.yml").write_text("deploy workflow v1\n", encoding="utf-8")

        # rendered_checksums computed via sync's own helpers (so baseline = in-sync)
        rc = {}
        for dest, policy in [("build.py", "identical"), ("pixi.toml", "templated"),
                             ("CLAUDE.md", "managed-region")]:
            b = (target / dest).read_bytes()
            rc[dest] = sync._sha256(sync._checkable_bytes(policy, b))
        if shape == "web-enabled":
            d = ".github/workflows/deploy.yml"
            rc[d] = sync._sha256(sync._checkable_bytes("identical", (target / d).read_bytes()))
        record = {
            "schema_version": 1, "source_repo": "rosslevinsky/guide-kit",
            "kit_version": "test", "managed_digest": "test", "state": "applied",
            "rendered_checksums": rc,
        }
        (target / ".template-version").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

        _init_commit(kit)
        _init_commit(target)
        return SyncEnv(kit, target)

    return _make


def kitconfig_load(root: Path):
    import kitconfig
    return kitconfig.load(root)


# ---------------------------------------------------------------------------
# A minimal RENDERABLE guide repo, for tests that must assert on real output
# bytes rather than on a closure hash. The plan is explicit that a closure hash
# alone is under-specified: it would pass while the stamp moved.
# ---------------------------------------------------------------------------

_FIXTURE_GUIDE_MD = """\
# Probe Guide

A probe document.

## First section

Some prose.

## Second section

More prose.
"""


def _toml_scalar(v) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_scalar(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def materialize_guide(root: Path):
    """Materialize a self-contained guide repo at `root`; return its `write_toml`.

    Split out of the `guide_repo` fixture below so a MODULE-SCOPED caller can
    build one tree and share it. `tests/test_nav_dom.py` drives a dozen
    assertions off a single rendered site, and a function-scoped fixture would
    re-render it for each one — about a minute of suite time buying no coverage
    at all, since every case reads the same bytes."""
    root.mkdir(parents=True, exist_ok=True)
    for name in ("build.py", "buildcore.py", "render_pdf.py", "render_site.py",
                 "render_slides.py", "kitconfig.py", "cascadecheck.py",
                 "cfadapter.py", "chapters.py", "style.css"):
        shutil.copy2(REPO_ROOT / name, root / name)
    shutil.copy2(REPO_ROOT / "style-screen.css.example", root / "style-screen.css")
    # The @font-face declarations: kit-owned, first in the cascade, and a render
    # input — without them every family in the fixture resolves to nothing.
    shutil.copy2(REPO_ROOT / "fontfaces.css", root / "fontfaces.css")
    shutil.copytree(REPO_ROOT / "fonts", root / "fonts")
    # The hermetic Fontconfig template travels with the fonts. It is a render
    # input (it decides what each family resolves to) and the build FAILS CLOSED
    # without it when faces are present — correctly, since rendering would
    # otherwise fall back to the host's font configuration.
    shutil.copytree(REPO_ROOT / "fontconfig", root / "fontconfig")
    # The theme layer: the selected theme supplies every token the
    # stylesheet reads through var(), so a fixture without it renders with
    # every value unresolved.
    shutil.copytree(REPO_ROOT / "themes", root / "themes")
    (root / "guide.md").write_text(_FIXTURE_GUIDE_MD, encoding="utf-8")

    def write_toml(**overrides):
        """Write guide.toml. `overrides` are merged over the defaults; nested
        tables are merged one level deep so a caller can bump a single date."""
        base = {
            "TITLE": "Probe Guide",
            "OUTPUT_SLUG": "probe-guide",
            "AUTHOR": "A. Author",
            "DESCRIPTION": "A probe.",
            "KEYWORDS": "probe",
            "COPYRIGHT_YEAR": 2026,
            "outputs": {"pdf": True, "site": "single", "slides": False},
            "artifacts": {"pdf": {"date": "2026-07-26"}, "site": {"date": "2026-07-26"}},
        }
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                merged = dict(base[k])
                for kk, vv in v.items():
                    if isinstance(vv, dict) and isinstance(merged.get(kk), dict):
                        merged[kk] = {**merged[kk], **vv}
                    else:
                        merged[kk] = vv
                base[k] = merged
            else:
                base[k] = v

        lines = [f"{k} = {_toml_scalar(v)}" for k, v in base.items() if not isinstance(v, dict)]
        for k, v in base.items():
            if not isinstance(v, dict):
                continue
            scalars = {kk: vv for kk, vv in v.items() if not isinstance(vv, dict)}
            subs = {kk: vv for kk, vv in v.items() if isinstance(vv, dict)}
            if scalars or not subs:
                lines.append(f"[{k}]")
                lines += [f"{kk} = {_toml_scalar(vv)}" for kk, vv in scalars.items()]
            for kk, vv in subs.items():
                lines.append(f"[{k}.{kk}]")
                lines += [f"{k2} = {_toml_scalar(v2)}" for k2, v2 in vv.items()]
        (root / "guide.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    write_toml()
    return write_toml


@pytest.fixture
def guide_repo(tmp_path):
    """Materialize a self-contained guide repo that `build.py` can actually
    render, and return (root, write_toml).

    Deliberately NOT a git repo: the stamp's date half is still git-derived at
    this stage, and outside a repo it resolves to the empty string, so the
    rendered bytes depend only on what the test varies. Fonts are copied because
    they are render inputs and the glyph-coverage gate reads their cmaps."""
    root = tmp_path / "guide"
    return root, materialize_guide(root)


def render(root: Path, *args: str) -> None:
    """Run build.py inside `root`. Uses the running interpreter, which is
    already the pixi environment the suite runs under."""
    result = subprocess.run(
        [sys.executable, "build.py", *args],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"build.py {' '.join(args)} failed ({result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
