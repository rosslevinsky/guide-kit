"""Promotion runs the DOCUMENT check, not only the byte check.

`promotable_stamp` asks whether a render is fresh, clean and stamped.
`smoke_check` asks whether it looks like a finished guide — and it is the only
path to `footer_wrap_failures`, the single automated catcher for recorded defect
8 (a footer wrapping on every page of three shipped guides).

Before this, CI's `baseline.yml` ran `make smoke` between render and commit while
the LOCAL `make baseline` / `make release` ran neither. Two paths doing the same
job with different guarantees, and the weaker one is the one a human uses.
"""
import inspect
from pathlib import Path

import pytest

import baseline
import release
import verify_artifacts

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("module", [baseline, release])
def test_the_promotion_path_calls_smoke_check(module):
    """Asserted on the SOURCE, because reaching the real promotion in a test
    needs a full render. The pairing that matters is that `smoke_check` appears
    alongside `promotable_stamp` — the byte question and the document question,
    both, before the copy."""
    src = inspect.getsource(module)
    assert "promotable_stamp" in src, f"{module.__name__} lost its byte-level guard"
    assert "smoke_check" in src, (
        f"{module.__name__} promotes without the document-level check; "
        "footer_wrap_failures is reachable only through smoke_check"
    )


# The statement that actually publishes, per module. Matched as the CALL, not the
# definition — `release._promote_to_reference` is defined ~160 lines above the
# point where it is invoked, so searching for the bare name finds the `def` and
# concludes the smoke check runs after it.
_PUBLISH_CALL = {"baseline": "shutil.copyfile(", "release": "_promote_to_reference(slug)"}


@pytest.mark.parametrize("module", [baseline, release])
def test_smoke_is_called_BEFORE_publishing(module):
    """Order is the whole point. A check after the copy has already published."""
    src = inspect.getsource(module)
    publish = _PUBLISH_CALL[module.__name__]
    assert publish in src, f"{module.__name__}: publish call {publish!r} not found"
    assert src.index("smoke_check(") < src.index(publish), \
        f"{module.__name__} smokes AFTER publishing"


def test_footer_wrap_is_still_only_reachable_through_smoke():
    """The premise the tests above rest on, asserted rather than assumed.

    If `footer_wrap_failures` ever gains a second caller, "smoke_check is the
    only route to it" stops being true and the reasoning here should be
    re-derived rather than inherited. Comments are stripped first: a prose
    mention is not a call, and counting one as a caller would make this pass for
    the wrong reason.
    """
    src = inspect.getsource(verify_artifacts)
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    calls = [
        l for l in code.splitlines()
        if "footer_wrap_failures(" in l and not l.lstrip().startswith("def ")
    ]
    assert len(calls) == 1, f"expected exactly one call site, found: {calls}"
    assert "smoke_failures" in inspect.getsource(verify_artifacts.smoke_failures)
