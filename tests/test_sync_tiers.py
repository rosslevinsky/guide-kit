"""Writing policies: identical verbatim, templated substituted, never untouched."""
import subprocess

import pytest

import sync


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def test_identical_copied_verbatim(sync_env):
    env = sync_env()
    (env.kit / "build.py").write_text("# build.py v2 with new bytes\n", encoding="utf-8")
    _commit(env.kit, "kit v2")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "build.py").read_text() == "# build.py v2 with new bytes\n"


def test_templated_substituted_from_target_guide_toml(sync_env):
    env = sync_env(target_slug="mac-terminal-guide")
    # Change the kit's pixi.toml; the target must get it rendered with ITS slug.
    (env.kit / "pixi.toml").write_text('name = "guide-template"\n# desc for guide-template\nnew = "line"\n', encoding="utf-8")
    _commit(env.kit, "kit pixi v2")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    rendered = (env.target / "pixi.toml").read_text()
    assert 'name = "mac-terminal-guide"' in rendered   # slug substituted
    assert "guide-template" not in rendered            # kit slug fully replaced
    assert 'new = "line"' in rendered                  # new kit content present


class _Cfg:
    def __init__(self, **kw):
        for f in ("OUTPUT_SLUG", "TITLE", "AUTHOR", "DESCRIPTION", "KEYWORDS"):
            setattr(self, f, kw.get(f, f.lower()))


def test_templated_substitution_is_single_pass_no_cascade():
    # A naive sequential str.replace cascades: TITLE Alpha->Beta, then AUTHOR
    # Beta->Gamma would rewrite the just-produced "Beta" into "Gamma". Single-pass
    # must leave it as "Beta".
    kit = _Cfg(TITLE="Alpha", AUTHOR="Beta")
    target = _Cfg(TITLE="Beta", AUTHOR="Gamma")
    assert sync._render_templated("the title is Alpha.", kit, target) == "the title is Beta."


def test_templated_ambiguous_value_rejected():
    # The same kit value mapping to two different target values is ambiguous.
    kit = _Cfg(TITLE="Same", AUTHOR="Same")
    target = _Cfg(TITLE="X", AUTHOR="Y")
    with pytest.raises(sync.SyncError):
        sync._render_templated("Same", kit, target)


def test_templated_mixed_identity_and_change_is_ambiguous():
    # kit TITLE == AUTHOR == "Same"; target leaves TITLE "Same" (identity) but
    # changes AUTHOR to "Other". Skipping the identity before collision detection
    # would silently rewrite every "Same" to "Other" — it must be rejected.
    kit = _Cfg(TITLE="Same", AUTHOR="Same")
    target = _Cfg(TITLE="Same", AUTHOR="Other")
    with pytest.raises(sync.SyncError):
        sync._render_templated("Same", kit, target)


def test_never_tier_untouched(sync_env):
    env = sync_env()
    # Even if the kit's guide.md changes, the target's own guide.md is never written.
    (env.kit / "guide.md").write_text("# kit demo content CHANGED\n", encoding="utf-8")
    _commit(env.kit, "kit guide.md v2")
    target_own = (env.target / "guide.md").read_bytes()
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "guide.md").read_bytes() == target_own   # untouched
