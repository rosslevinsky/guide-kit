"""Shared pytest fixtures for the kit test suite.

The suite is run by the kit-only pixi environment (`pixi run -e kit test`);
targets never run it (they have neither pytest nor a `test` task). This file
also puts the repo root on sys.path so `import kitconfig` (and the other
root-level kit modules) resolves when tests live under tests/.
"""
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
    """Absolute path to the guide-template repo root."""
    return REPO_ROOT


# ---------------------------------------------------------------------------
# sync.py test harness: an isolated temp kit + temp target, starting in-sync.
# ---------------------------------------------------------------------------

def _guide_toml(slug: str, *, title="Probe", author="A", desc="d", keywords="k",
                year=2026, platform="darwin") -> str:
    return (
        f'TITLE = "{title}"\n'
        f'OUTPUT_SLUG = "{slug}"\n'
        f'AUTHOR = "{author}"\n'
        f'DESCRIPTION = "{desc}"\n'
        f'KEYWORDS = "{keywords}"\n'
        f'COPYRIGHT_YEAR = {year}\n'
        f'baseline_platform = "{platform}"\n'
    )


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

_MANIFEST_WEB_EXTRA = """\
[[entry]]
path = ".github/workflows/deploy.yml.example"
lifecycle = "bootstrap-source"
projects_to = ".github/workflows/deploy.yml"
policy = "identical"
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
            manifest = manifest + "\n" + _MANIFEST_WEB_EXTRA
        (kit / "kit-manifest.toml").write_text(manifest, encoding="utf-8")

        # --- target: projected files, as if previously synced (in-sync) ---
        (target / "guide.toml").write_text(_guide_toml(target_slug), encoding="utf-8")
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
            "schema_version": 1, "source_repo": "rosslevinsky/guide-template",
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
