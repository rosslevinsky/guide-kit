"""The kit's README is a PUBLIC landing page, and it has to read like one.

THE DEFECT. This repository's README was written as a fork's README with
`{{GUIDE_NAME}}` / `{{GUIDE_SLUG}}` placeholders throughout, and nothing
substituted them here — `bootstrap.py` fills them in a FORK. So the public page
opened with a literal `# {{GUIDE_NAME}}` heading, and its first link, "Read the
guide", pointed at `{{GUIDE_SLUG}}.pdf`, which 404s for every visitor.

THE DISTINCTION THAT MAKES THE FIX RIGHT, rather than a blanket de-placeholdering:
a placeholder inside a command a reader adapts (`build/{{GUIDE_SLUG}}.pdf`) is
doing its job — it says "your slug here". A placeholder in a **link target** is
not: a link either resolves or it is broken. And an unsubstituted **H1** is the
page's title.

So the front matter is a block `bootstrap.py` replaces wholesale, and the rest
of the file keeps its placeholders. These tests pin both halves — including that
a fork still gets its own front page, because "make the kit's README correct" has
an obvious wrong fix that breaks every guide.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"

_PLACEHOLDER = re.compile(r"\{\{GUIDE_(?:NAME|SLUG)\}\}")
# [text](target) — the target is what has to resolve.
_LINK = re.compile(r"\[(?:[^\]]*)\]\(([^)]+)\)")
# Fenced code blocks: a placeholder inside one is instructional, not broken.
_FENCE = re.compile(r"^```.*?^```", re.M | re.S)
# HTML comments render as nothing, so their contents are not prose a visitor
# reads. This is a real exclusion rather than a convenience: the front-matter
# block's own comment EXPLAINS the placeholder defect and necessarily quotes
# `{{GUIDE_NAME}}` to do it — the same trap `test_workflow_expressions.py`
# records, where a note about a delimiter, written inside the thing that reads
# that delimiter, becomes the thing it was warning about.
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _prose(text: str) -> str:
    """The README as a reader sees it: no code fences, no HTML comments."""
    return _COMMENT.sub("", _FENCE.sub("", text))


def test_the_published_title_is_not_a_placeholder():
    first = README.read_text(encoding="utf-8").lstrip()
    heading = next(line for line in first.splitlines()
                   if line.startswith("# "))
    assert not _PLACEHOLDER.search(heading), (
        f"the public README's H1 is {heading!r} — GitHub renders that literally "
        f"as the repository's landing-page title")


def test_no_link_target_is_a_placeholder():
    """A link either resolves or it is broken; there is no instructional
    reading of a 404."""
    text = README.read_text(encoding="utf-8")
    bad = [t for t in _LINK.findall(_prose(text)) if _PLACEHOLDER.search(t)]
    assert not bad, (
        f"these README links point at unsubstituted placeholders and 404 for "
        f"every visitor: {bad}")


def test_relative_links_in_the_front_door_resolve_on_disk():
    """The front matter links this repo's own files. If one is renamed the link
    dies silently — GitHub renders a 404 without complaint."""
    text = README.read_text(encoding="utf-8")
    head = text[:text.index("## Getting started from this template")]
    for target in _LINK.findall(_prose(head)):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        assert (REPO_ROOT / target.split("#")[0]).exists(), (
            f"README front matter links {target!r}, which does not exist")


def test_the_front_matter_block_is_marked_for_bootstrap():
    """The markers are the mechanism. Without them a fork inherits the KIT's
    front page — headed `guide-kit`, linking the kit's own PDF."""
    import bootstrap

    text = README.read_text(encoding="utf-8")
    assert text.count(bootstrap.README_FRONT_BEGIN) == 1, (
        "the README front-matter begin marker is missing or duplicated")
    assert text.count(bootstrap.README_FRONT_END) == 1, (
        "the README front-matter end marker is missing or duplicated")
    assert text.index(bootstrap.README_FRONT_BEGIN) < text.index(
        bootstrap.README_FRONT_END), "the front-matter markers are inverted"


def test_a_fork_gets_its_own_front_page():
    """The other half. `# guide-kit` is right for this repo and wrong for every
    guide built from it."""
    import bootstrap

    front = bootstrap._guide_front_matter("My Guide", "my-guide")
    assert front.startswith("# My Guide")
    assert "my-guide.pdf" in front
    assert not _PLACEHOLDER.search(front)
    assert "guide-kit" not in front, (
        "a guide's front page describes the guide, not the toolkit")


def test_the_placeholders_that_remain_are_instructional():
    """Deleting them all is the obvious wrong fix: 21 of them survive into a
    fork's README and are what make it describe that guide. What must hold is
    that the surviving ones are inside code, not in prose a visitor reads as a
    broken sentence."""
    text = README.read_text(encoding="utf-8")
    head = text[:text.index("## Getting started from this template")]
    leftover = _PLACEHOLDER.findall(_prose(head))
    assert not leftover, (
        f"the front section still has {len(leftover)} placeholder(s) in prose; "
        f"a visitor reads those before anything else")


def test_bootstrap_substitutes_the_whole_block(tmp_path, monkeypatch):
    """End to end through the real function, because the failure mode is that it
    silently does nothing — a `find` returning -1 and a block left in place."""
    import bootstrap

    fork = tmp_path / "fork"
    fork.mkdir()
    (fork / "README.md").write_text(README.read_text(encoding="utf-8"),
                                    encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ROOT", fork)
    bootstrap._sub_readme("My Guide", "my-guide")

    out = (fork / "README.md").read_text(encoding="utf-8")
    assert out.lstrip().startswith("# My Guide"), out[:120]
    assert bootstrap.README_FRONT_BEGIN not in out, "the marker survived into a fork"
    assert bootstrap.README_FRONT_END not in out
    assert not _PLACEHOLDER.search(out), "a fork's README kept a placeholder"
    assert "## Getting started from this template" not in out


def test_the_gate_would_catch_the_shipped_defect(tmp_path, monkeypatch):
    """The README as it was: an H1 of `# {{GUIDE_NAME}}` and a link to
    `{{GUIDE_SLUG}}.pdf`.

    THIS TEST INVOKES THE REAL GATES rather than re-deriving them. Written the
    obvious way it asserted only that its own hard-coded string matched its own
    hard-coded regexes — so it stayed green no matter how weak the actual gates
    became, which is a test of nothing at all wearing the name of a regression
    test.
    """
    global README
    shipped = tmp_path / "README.md"
    shipped.write_text(
        "# {{GUIDE_NAME}}\n\n"
        "> **Read the guide:** [x]({{GUIDE_SLUG}}.pdf)\n\n"
        "## Getting started from this template\n",
        encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "README", shipped)

    with pytest.raises(AssertionError, match="H1"):
        test_the_published_title_is_not_a_placeholder()
    with pytest.raises(AssertionError, match="404"):
        test_no_link_target_is_a_placeholder()


@pytest.mark.parametrize("anchor", ["#cold-start-guide-kit", "#the-guide-family",
                                    "#quick-start"])
def test_the_front_door_anchors_exist(anchor):
    """A heading rename breaks these silently — GitHub scrolls nowhere and says
    nothing."""
    text = README.read_text(encoding="utf-8")
    slugs = set()
    for line in text.splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            slug = re.sub(r"[^a-z0-9\s-]", "", title.lower())
            slugs.add("#" + re.sub(r"\s+", "-", slug).strip("-"))
    assert anchor in slugs, f"{anchor} matches no heading; found {sorted(slugs)}"


def test_the_download_bullet_is_replaced_whole(tmp_path, monkeypatch):
    """A fork has no reference PDF yet, so the "Read the guide" link is rewritten.

    THE DEFECT this pins: that bullet is wrapped across two lines, and the
    rewrite matched `^…$` under MULTILINE — so it replaced the first line and
    left the second stranded. Every fork's landing page opened with a dangling
    `> this repo).` under the replacement sentence, in the first thing a visitor
    reads. Found by running a real fork end to end, not by a test, because every
    assertion here was about the line that WAS replaced.
    """
    import bootstrap

    fork = tmp_path / "fork"
    fork.mkdir()
    (fork / "README.md").write_text(README.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ROOT", fork)
    bootstrap._sub_readme("My Guide", "my-guide")
    bootstrap._prune_readme(with_web=False)

    out = (fork / "README.md").read_text(encoding="utf-8")
    assert "> this repo)." not in out, "the bullet's continuation line was orphaned"
    assert "published here after the first release" in out
    # The bullets AFTER it must survive — the match must not run past its own.
    assert "**Build it yourself:**" in out
    assert "**Edit / contribute:**" in out


def test_the_front_matter_is_separated_from_the_body(tmp_path, monkeypatch):
    """A missing blank line is legal Markdown and renders as one merged
    paragraph — the front matter's last line running into the body's first."""
    import bootstrap

    fork = tmp_path / "fork"
    fork.mkdir()
    (fork / "README.md").write_text(README.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ROOT", fork)
    bootstrap._sub_readme("My Guide", "my-guide")

    out = (fork / "README.md").read_text(encoding="utf-8")
    tail = bootstrap._guide_front_matter("My Guide", "my-guide").rstrip("\n").splitlines()[-1]
    idx = out.index(tail) + len(tail)
    assert out[idx:idx + 2] == "\n\n", (
        f"front matter runs straight into the body: {out[idx:idx + 60]!r}")
