"""Every `guide.toml` example in the docs is fed to the real loader.

WHY. The README's `[outputs]` block — the one example of the kit's central
declaration — could not load. `kitconfig` requires an `[artifacts.<name>] date`
table for every declared output, the example showed none, and no example
anywhere in the repository showed one. So a reader following the documentation
got a refusal from the loader on their first build, naming a table the docs had
never mentioned.

Nothing caught it because the documentation and the schema are different files,
and the only thing connecting them was that someone had once written both.

THE GENERAL SHAPE, and the reason this file is worth its length: a fenced TOML
block in a document is *executable content that nothing executes*. It is the
same class as the guards this remediation is about — correct-looking, never
run. Extracting and loading them is what turns prose back into something with a
truth value.

Blocks are opted IN by content rather than by fence info-string alone: a doc may
legitimately show a *fragment* (`[deploy]` on its own) that is not a whole
config, so only blocks carrying the required identity keys are treated as
complete guides. A fragment that claims to be complete and is not would
otherwise have to be excluded by hand, and a hand-maintained exclusion list is
the thing that drifts.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import kitconfig

REPO_ROOT = Path(__file__).resolve().parents[1]

# The docs a reader actually follows. `docs/` is maintainer-facing and pruned
# from a fork; these two are the front door.
#
# MOVING A FENCED `toml` BLOCK OUT OF THESE FILES SILENTLY REMOVES IT FROM THIS
# CHECK. The block still looks executable and nothing executes it, which is the
# exact failure this file was written for. Two rules follow: a doc carrying a
# complete guide.toml belongs in this tuple the day it is created, and it must
# be a file a FORK still has — `bootstrap.py` deletes `docs/`, so a reference
# moved there is gone from the only reader who needs it most.
DOCS = ("README.md", "CLAUDE.md")

_FENCE = re.compile(r"^```toml\n(.*?)^```", re.M | re.S)

# A block is a COMPLETE guide.toml when it declares the identity every guide
# must have. Anything else is a fragment illustrating one table.
_REQUIRED = ("TITLE", "OUTPUT_SLUG", "AUTHOR")


def _blocks(doc: Path) -> list[tuple[int, str]]:
    text = doc.read_text(encoding="utf-8")
    out = []
    for m in _FENCE.finditer(text):
        body = m.group(1)
        line = text[:m.start()].count("\n") + 1
        out.append((line, body))
    return out


def _complete_configs() -> list[tuple[str, int, str]]:
    found = []
    for name in DOCS:
        doc = REPO_ROOT / name
        if not doc.is_file():
            continue
        for line, body in _blocks(doc):
            if all(key in body for key in _REQUIRED):
                found.append((name, line, body))
    return found


def _output_examples() -> list[tuple[str, int, str]]:
    """Blocks that declare `[outputs]`, complete or not.

    These are the ones the defect was in: a reader copies the outputs table and
    gets a refusal about a table the example never showed.
    """
    found = []
    for name in DOCS:
        doc = REPO_ROOT / name
        if not doc.is_file():
            continue
        for line, body in _blocks(doc):
            if "[outputs]" in body:
                found.append((name, line, body))
    return found


def test_there_are_toml_examples_to_check():
    """Without this the parametrized tests below pass by finding nothing — which
    is how a documentation gate quietly stops covering the documentation."""
    assert _output_examples(), (
        "no ```toml block declaring [outputs] was found in the docs; either the "
        "docs stopped showing the kit's central declaration, or the fence "
        "pattern here no longer matches how they are written")


@pytest.mark.parametrize(
    "where, body",
    [(f"{name}:{line}", body) for name, line, body in _output_examples()],
    ids=lambda v: v if isinstance(v, str) and ":" in v else "",
)
def test_a_documented_outputs_block_declares_its_artifact_dates(where, body):
    """The exact defect: `[outputs] slides = true` with no `[artifacts.slides]`.

    Checked structurally rather than by loading, because an `[outputs]` example
    may legitimately be a fragment — but a fragment that declares an output and
    omits its date teaches the reader a config the loader refuses.
    """
    declared = []
    if re.search(r"^pdf\s*=\s*true", body, re.M):
        declared.append("pdf")
    site = re.search(r'^site\s*=\s*"([^"]+)"', body, re.M)
    if site and site.group(1) != "none":
        declared.append("site")
    if re.search(r"^slides\s*=\s*true", body, re.M):
        declared.append("slides")

    missing = [a for a in declared if f"[artifacts.{a}]" not in body]
    assert not missing, (
        f"{where}: the example declares {declared} but shows no "
        f"[artifacts.{missing[0]}] date table. `kitconfig.load` refuses that "
        f"config, so a reader copying this block gets an error naming a table "
        f"the documentation never mentioned.")


@pytest.mark.parametrize(
    "where, body",
    [(f"{name}:{line}", body) for name, line, body in _complete_configs()],
    ids=lambda v: v if isinstance(v, str) and ":" in v else "",
)
def test_a_documented_complete_config_actually_loads(where, body, tmp_path):
    """The strongest form: hand it to the real loader.

    Not a schema re-implementation — `kitconfig.load` is the thing a reader's
    build calls, so it is the thing the example has to satisfy.
    """
    (tmp_path / "guide.toml").write_text(body, encoding="utf-8")
    try:
        kitconfig.load(tmp_path)
    except kitconfig.KitConfigError as exc:
        pytest.fail(
            f"{where}: this documented guide.toml does not load: {exc}\n"
            f"The documentation is teaching a configuration the kit refuses.")


def test_the_gate_would_catch_the_defect_it_was_written_for():
    """The README block as it shipped — outputs declared, no dates."""
    shipped = (
        '[outputs]\n'
        'pdf    = true\n'
        'site   = "multipage"\n'
        'slides = true\n'
    )
    with pytest.raises(AssertionError, match=r"artifacts\."):
        test_a_documented_outputs_block_declares_its_artifact_dates(
            "README.md:0", shipped)
