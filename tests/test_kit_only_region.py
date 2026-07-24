"""Kit-only regions are STRIPPED when a templated file renders into a target.

Placement (pytest under `[feature.kit]`, not root) is asserted by
test_kit_only_test_dependency.py — but placement alone never enforced anything:
`templated` rendering copies the whole file, so the kit's test environment
reached every target's pixi.toml verbatim, and every target's pixi.lock would
gain a `kit` environment (exactly what plan.md:89, :90 forbids). These tests
cover the mechanism that actually enforces it.
"""
import tomllib

import pytest

import kitconfig
import sync

B, E = sync.KIT_ONLY_BEGIN, sync.KIT_ONLY_END


class _Cfg:
    """Minimal stand-in for a kitconfig object (only the templated fields)."""

    def __init__(self, **kw):
        for f in sync._TEMPLATED_FIELDS:
            setattr(self, f, kw.get(f, f"kit-{f}"))


def test_strips_a_region_including_its_markers():
    text = f"keep-before\n# {B}\ndropped = 1\n# {E}\nkeep-after\n"
    out = sync._strip_kit_only(text)
    assert "dropped" not in out
    assert B not in out and E not in out
    assert out == "keep-before\nkeep-after\n"


def test_strips_multiple_regions():
    text = f"a\n# {B}\nx\n# {E}\nb\n# {B}\ny\n# {E}\nc\n"
    assert sync._strip_kit_only(text) == "a\nb\nc\n"


def test_text_without_markers_is_untouched():
    text = "[workspace]\nname = 'x'\n"
    assert sync._strip_kit_only(text) == text


@pytest.mark.parametrize("bad", [
    f"# {B}\nunterminated\n",          # no end
    f"# {E}\nend without begin\n",     # no begin
    f"# {B}\na\n# {B}\nb\n# {E}\n",    # nested
])
def test_malformed_regions_are_rejected(bad):
    # A silent partial strip would leak the kit env into a target — fail loudly.
    with pytest.raises(sync.SyncError):
        sync._strip_kit_only(bad)


def test_render_templated_strips_kit_only(repo_root):
    """The real kit pixi.toml, rendered for a target, must carry no kit env."""
    kit_cfg = kitconfig.load(repo_root)
    target_cfg = _Cfg(OUTPUT_SLUG="mac-terminal-guide", TITLE="Mac Guide",
                      AUTHOR=kit_cfg.AUTHOR, DESCRIPTION="Mac desc",
                      KEYWORDS="mac", baseline_platform="darwin")
    rendered = sync._render_templated(
        (repo_root / "pixi.toml").read_text(encoding="utf-8"), kit_cfg, target_cfg
    )
    data = tomllib.loads(rendered)          # must still be valid TOML after stripping
    assert "feature" not in data, "kit-only [feature.kit.*] leaked into the target"
    assert "environments" not in data, "kit-only [environments] leaked into the target"
    assert "pytest" not in rendered and "pyyaml" not in rendered
    assert "test" not in data.get("tasks", {})
    # The parts a target genuinely needs survive.
    assert data["workspace"]["name"] == "mac-terminal-guide"
    assert "pandoc" in data["dependencies"] and "weasyprint" in data["dependencies"]
    assert "build" in data["tasks"] and "web" in data["tasks"]


def test_kit_keeps_its_own_kit_environment(repo_root):
    """Stripping is a RENDERING step — the kit's own manifest still has the env."""
    data = tomllib.loads((repo_root / "pixi.toml").read_text(encoding="utf-8"))
    assert "pytest" in data["feature"]["kit"]["dependencies"]
    assert "kit" in data["environments"]


def test_pixi_description_matches_guide_toml_so_it_substitutes(repo_root):
    """pixi.toml's description must be the kit's guide.toml DESCRIPTION verbatim.

    `templated` rendering substitutes kit guide.toml VALUES with the target's, so
    a hand-written variant cannot be matched and would propagate the kit's own
    description into every converged guide's pixi.toml.
    """
    kit_cfg = kitconfig.load(repo_root)
    data = tomllib.loads((repo_root / "pixi.toml").read_text(encoding="utf-8"))
    assert data["workspace"]["description"] == kit_cfg.DESCRIPTION

    target_cfg = _Cfg(OUTPUT_SLUG="mac-terminal-guide", TITLE="Mac Guide",
                      AUTHOR=kit_cfg.AUTHOR, DESCRIPTION="A guide to the macOS Terminal.",
                      KEYWORDS="mac", baseline_platform="darwin")
    rendered = tomllib.loads(sync._render_templated(
        (repo_root / "pixi.toml").read_text(encoding="utf-8"), kit_cfg, target_cfg
    ))
    assert rendered["workspace"]["description"] == "A guide to the macOS Terminal."
