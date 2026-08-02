"""The platform guard is RETIRED, and this is the test that keeps it retired.

This file replaces `test_baseline_platform_guard.py`, which asserted the
opposite: that `make baseline` / `make release` refuse when `sys.platform`
differs from `guide.toml`'s `baseline_platform`, with `--allow-platform-mismatch`
as the escape hatch.

WHY IT WENT. The guard was written for a family that shipped system-font stacks,
where the host genuinely chose the typeface and a Linux VM really could bless a
Linux-typography PDF into a family of macOS-rendered ones. Bundled faces plus
`fontconfig/fonts.conf` — both in every artifact's closure — removed that
premise: the render no longer consults the host's fonts, and macOS/Linux
byte-identity was measured across the family at the time the faces were bundled.
What was left was a config key recording an intention nothing could violate, and
a CLI flag to override a check that could not fail for a real reason.

WHY A TEST INSTEAD OF A DELETION. Deleting the old file would leave the retirement
asserted by nothing, and the shape of it is easy to reintroduce by accident — a
future `guide.toml` key, a resurrected `--allow-platform-mismatch`, a
`sys.platform` comparison somewhere in the promotion path. Each assertion below
names one way back in.

The replacement control is not a config key at all: it is `driftcanary.py`, which
MEASURES whether a fresh render still matches the committed reference instead of
declaring which host is allowed to produce one. See `test_drift_canary.py`.
"""
import subprocess
import sys
from pathlib import Path

import pytest

import baseline
import kitconfig
import release

REPO_ROOT = Path(__file__).resolve().parent.parent
SLUG = "probe-guide"


def _toml() -> str:
    return (
        'TITLE = "Probe"\n'
        f'OUTPUT_SLUG = "{SLUG}"\n'
        'AUTHOR = "T"\n'
        'DESCRIPTION = "d"\n'
        'KEYWORDS = "k"\n'
        'COPYRIGHT_YEAR = 2026\n'
        '[outputs]\n'
        'pdf = true\n'
        'site = "none"\n'
        'slides = false\n'
        '[artifacts.pdf]\n'
        'date = "2026-07-26"\n'
    )


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _mkrepo(tmp_path, *, dirty=False):
    (tmp_path / "guide.toml").write_text(_toml(), encoding="utf-8")
    for name in kitconfig.SOURCE_FILES:
        if name not in ("guide.toml", "transforms.py"):
            # SOURCE_FILES contains NESTED paths (fontconfig/fonts.conf), so a
            # flat write is not enough.
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text(f"seed-{name}\n", encoding="utf-8")
    (tmp_path / f"{SLUG}.pdf").write_bytes(b"%PDF-reference")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "clean")
    if dirty:
        (tmp_path / "guide.md").write_text("seed-guide.md\ndirtied\n", encoding="utf-8")
    return tmp_path


# ----- the key is gone from the config language -----

def test_guide_toml_has_no_platform_key(tmp_path):
    """A guide.toml with no platform key loads. It was REQUIRED before."""
    repo = _mkrepo(tmp_path)
    cfg = kitconfig.load(repo)
    assert not hasattr(cfg, "baseline_platform")


def test_a_leftover_platform_key_is_REJECTED(tmp_path):
    """A fork carrying the retired key must fail loudly, not be quietly ignored.

    Same treatment `[release]` got when it was removed: a retired key that
    silently does nothing is worse than one that errors, because the author
    goes on believing it is in force.
    """
    repo = _mkrepo(tmp_path)
    toml = repo / "guide.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace(
            "COPYRIGHT_YEAR = 2026\n",
            'COPYRIGHT_YEAR = 2026\nbaseline_platform = "linux"\n',
        ),
        encoding="utf-8",
    )
    with pytest.raises(kitconfig.KitConfigError) as exc:
        kitconfig.load(repo)
    assert "baseline_platform" in str(exc.value)


def test_the_matcher_function_is_gone():
    """`kitconfig.baseline_platform_matches` was the guard's whole mechanism."""
    assert not hasattr(kitconfig, "baseline_platform_matches")


# ----- the promotion path no longer refuses on host -----

def test_baseline_does_not_refuse_on_this_host(tmp_path, monkeypatch):
    """`make baseline` reaches the dirty guard — i.e. gets PAST any host check.

    Proven by the failure it DOES produce: the dirty-tree refusal. Under the old
    guard on a mismatched host it exited earlier, with a platform message.
    """
    repo = _mkrepo(tmp_path, dirty=True)
    monkeypatch.setattr(baseline, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["baseline.py"])
    with pytest.raises(SystemExit) as exc:
        baseline.main()
    msg = str(exc.value)
    assert "dirty" in msg
    assert "platform" not in msg.lower()


def test_baseline_rejects_the_retired_override_flag(tmp_path, monkeypatch):
    """`--allow-platform-mismatch` must be an ERROR, not silently accepted.

    argparse ignores nothing — an unknown flag exits 2 — but a future
    `parse_known_args()` would swallow it, so assert the refusal directly.
    """
    repo = _mkrepo(tmp_path)
    monkeypatch.setattr(baseline, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["baseline.py", "--allow-platform-mismatch"])
    with pytest.raises(SystemExit) as exc:
        baseline.main()
    assert exc.value.code == 2


def test_release_rejects_the_retired_override_flag(tmp_path, monkeypatch):
    repo = _mkrepo(tmp_path)
    monkeypatch.setattr(release, "ROOT", repo)
    monkeypatch.setattr(
        sys, "argv", ["release.py", "-m", "msg", "--allow-platform-mismatch"]
    )
    with pytest.raises(SystemExit) as exc:
        release.main()
    assert exc.value.code == 2


# ----- no sys.platform comparison survives in the promotion path -----

# Every spelling of "which host am I on?" that Python offers. Asserting only
# `sys.platform` was too narrow: a guard rebuilt on `platform.system()` or
# `os.name` would restore exactly the behaviour this file exists to prevent while
# every other test here still passed — and on Linux it would pass even a guard
# that rejects Windows, because these tests run on one host and can only observe
# the branch that host takes. Naming the API surface is what makes the assertion
# host-independent.
_HOST_PROBES = (
    "sys.platform",
    "platform.system",
    "platform.machine",
    "platform.uname",
    "os.uname",
    "os.name",
    "sys.getwindowsversion",
)


@pytest.mark.parametrize("module", ["baseline.py", "release.py", "kitconfig.py"])
@pytest.mark.parametrize("probe", _HOST_PROBES)
def test_the_promotion_path_does_not_ASK_what_host_it_is_on(module, probe):
    """The guard's shape, not just its name, and not just one spelling of it.

    A promotion path that never asks the question cannot branch on the answer —
    which is a stronger statement than "it does not refuse on THIS host", and it
    is the only version of the claim a single-host test run can actually make.
    """
    text = (REPO_ROOT / module).read_text(encoding="utf-8")
    assert probe not in text, (
        f"{module} consults {probe} — the promotion path must not depend on "
        "which host it runs on"
    )


# ----- wiring (inherited from the file this replaces) -----

def test_makefile_wires_baseline_to_baseline_py():
    out = subprocess.run(
        ["make", "-n", "baseline"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout
    assert "baseline.py" in out
