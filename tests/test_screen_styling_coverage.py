"""A guide's own classes must be styled for the WEB, not only for print.

WHY THIS FILE EXISTS. `style-screen.css` is materialised from the kit's seed, and
the seed cannot know a guide's own class names. A guide that authors its own
markup therefore styles those classes in `style.css`, where it is looking at the
PDF, and gets nothing on the web. Both outputs build. Every test passes. The
website renders that markup as plain body text and nobody finds out until someone
looks at it.

Measured when this was written, across the seven guides in the family:

    guide                      authored   print-only (unstyled on the web)
    accounting-guide                  3   —
    git-guide                        11   165 uses: ai(87) exlabel(33) diff(29)
                                            cover(8) part-divider(8)
    japan-guide                       8   —
    linux-terminal-guide              7   —
    mac-terminal-guide                6   —
    windows-cmd-guide                 7   —
    windows-powershell-guide          8   —

One guide, 165 elements — its whole cover collapsed into left-aligned paragraphs,
eight part dividers indistinguishable from prose, and every exercise label run
together with the sentence beside it. It was the most customised of the seven,
which is exactly the guide the seed serves least well.

THE GUARD IS IN THE BUILD, NOT ONLY HERE. `render_site.check_screen_styling` runs
inside `build_web()`, so it fires during `make web` in every guide's own CI —
which is the only place that can see a guide's files, since `tests/**` is
`retained-in-kit` and never syncs. These tests prove that guard is wired and that
it fails on the real shape of the defect.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import render_site

REPO_ROOT = Path(__file__).resolve().parents[1]


def _missing(markdown: str, screen: str, print_css: str) -> list[str]:
    """The check's own rule, restated independently of its implementation."""
    authored: set[str] = set()
    for m in re.finditer(r'class="([^"]+)"', markdown):
        authored.update(m.group(1).split())
    return sorted(
        c for c in authored
        if re.search(rf"\.{re.escape(c)}\b", print_css)
        and not re.search(rf"\.{re.escape(c)}\b", screen)
    )


def test_the_guard_is_called_from_the_web_build():
    """Structural, and it earns its place: the behavioural trigger needs a
    materialised guide with a bespoke class, and a guard that is correct but
    never called is the failure mode this repo keeps designing against."""
    import ast
    src = (REPO_ROOT / "render_site.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "build_web")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "check_screen_styling" in called, (
        "build_web() no longer calls check_screen_styling, so a guide can ship "
        "print-only styling to the web again"
    )


def test_a_print_only_class_is_detected():
    """The real shape of the defect: styled in style.css, absent from screen."""
    md = '<div class="part-divider">Part I</div>'
    assert _missing(md, ".callout { color: red }", ".part-divider { color: red }") \
        == ["part-divider"]


def test_a_class_styled_on_both_is_fine():
    md = '<div class="part-divider">Part I</div>'
    assert _missing(md, ".part-divider { color: blue }", ".part-divider { color: red }") == []


def test_a_class_the_kit_merely_mentions_does_not_count():
    """THE FALSE NEGATIVE THIS RULE WAS TIGHTENED FOR.

    Checking against the served sheet (kit chrome + the guide's own) found four
    of git-guide's five print-only classes and passed `.cover`, because
    WEB_CHROME_CSS names `.cover h1` — as a scroll-timeline hook for the running
    title, not as anything that gives it an appearance. A mention is not a
    dressing, and the guide's own sheet is where an authored class belongs."""
    assert ".cover h1" in render_site.WEB_CHROME_CSS, (
        "the timeline hook this test is about has moved; re-point the test"
    )
    md = '<div class="cover"><h1>T</h1></div>'
    # The kit mentions it; the guide's own sheet does not style it -> still a miss.
    assert _missing(md, ".something-else { color: red }", ".cover { color: red }") \
        == ["cover"]


def test_a_class_in_neither_sheet_is_not_reported():
    """Only PRINT-STYLED classes are the defect. A class styled nowhere is a
    guide's own business — it may be a hook for JavaScript or a semantic marker,
    and flagging it would make this gate noisy enough to switch off."""
    md = '<div class="js-hook">x</div>'
    assert _missing(md, "", "") == []


@pytest.mark.parametrize("cls,decoy", [
    ("diff", ".different { color: red }"),
    ("ai", ".aiming { color: red }"),
])
def test_matching_is_word_bounded(cls, decoy):
    """A substring test reported git-guide clean: `.ai` matched `.aiming`, and
    `.diff` matched `.different`. The bug hid behind an unrelated rule."""
    md = f'<span class="{cls}">x</span>'
    assert _missing(md, decoy, f".{cls} {{ color: red }}") == [cls]


def test_the_whole_family_passes_today():
    """The check applied to every sibling guide present in this workspace.

    Skipped rather than failed when the siblings are absent — the kit is cloned
    on its own in CI, and a test that fails for being alone is a test that gets
    deleted."""
    workspace = REPO_ROOT.parent
    guides = [d for d in sorted(workspace.iterdir())
              if (d / "guide.toml").exists()
              and (d / "style-screen.css").exists()
              and d.name != REPO_ROOT.name]
    if not guides:
        pytest.skip("no sibling guides in this workspace")
    offenders = {}
    for g in guides:
        miss = _missing((g / "guide.md").read_text(encoding="utf-8"),
                        (g / "style-screen.css").read_text(encoding="utf-8"),
                        (g / "style.css").read_text(encoding="utf-8"))
        if miss:
            offenders[g.name] = miss
    assert not offenders, (
        f"guides shipping print-only styling to the web: {offenders}"
    )
