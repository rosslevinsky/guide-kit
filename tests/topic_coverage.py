"""Shared topic-coverage assertions for the terminal-guide family.

Imported by a thin `tests/test_topic_coverage.py` in each terminal guide, which
points it at that guide's own `guide.md` and command inventory. The logic lives
here so it is not copy-pasted three times; *invocation and blame* stay in each
guide, so a content edit in `windows-cmd-guide` turns that repo's CI red rather
than the kit's.

This file is `retained-in-kit` with no destination policy — it is never
projected into a target. A guide reaches it through the borrowed test runner
(CI checks the kit out to `_kit/`), so a guide's test file locates it like this:

    import sys, pathlib
    _t = pathlib.Path(__file__).resolve().parent
    for _c in (_t.parent / "_kit" / "tests",                 # CI: borrowed runner
               _t.parent.parent / "guide-template" / "tests"):  # local workspace
        if (_c / "topic_coverage.py").exists():
            sys.path.insert(0, str(_c)); break
    from topic_coverage import assert_full_coverage

WHY MARKERS AND NOT HEADINGS
----------------------------
The nine items (plan.md:151) are *subjects that must be taught*, not headings
that must match. The cmd guide is required to re-frame rather than translate:
the Mac guide's "Home, the Tilde, and the Two Dots" becomes something like
"Your User Folder and Moving Around", which teaches subject 4 correctly while
sharing no heading text. A test keyed on identical headings would force Unix
framings onto Windows and contradict that requirement outright.

So each subject carries several alternative marker groups. A subject is covered
when ANY group matches, and a group matches when ALL of its terms appear. That
lets a shell-specific vocabulary satisfy a subject on its own terms.

WHY THE COMMAND INVENTORY EXISTS
--------------------------------
Markers alone prove only that nine labels exist, which is theatre. Each guide
also declares the commands it promises to teach, and every declared command
must have an authored example that RECORDS ITS OUTPUT — because these guides
show expected output, so an unexecuted or stale example is a reader-facing
defect, not a typo.

THE COMMAND-INVENTORY DECLARATION FORMAT
----------------------------------------
The inventory is declared **in the guide's own repo**, as a module-level
`COMMANDS` list in `tests/test_topic_coverage.py`. Deliberately not in
`guide.toml`: that file has a strict seven-key schema enforced by
`kitconfig.py`, and an eighth key would fail validation in every consumer.
Keeping it beside the assertion also means the declaration and the thing it
gates are read together.

The declaration is a promise to the reader, so it is written FIRST — before the
prose — and the test then fails until the guide makes good on it. Copy this
file into a new terminal guide as `tests/test_topic_coverage.py`:

    \"\"\"This guide teaches every subject in the family contract, and every
    command it promises.\"\"\"
    import pathlib, sys

    _t = pathlib.Path(__file__).resolve().parent
    for _c in (_t.parent / "_kit" / "tests",                    # CI: borrowed runner
               _t.parent.parent / "guide-template" / "tests"):  # local workspace
        if (_c / "topic_coverage.py").exists():
            sys.path.insert(0, str(_c))
            break
    from topic_coverage import assert_full_coverage

    # The commands this guide promises to teach. Every one must appear in a
    # fenced example with its output recorded.
    COMMANDS = ["pwd", "ls", "cd", "mkdir", "cp", "mv", "more", "rm"]

    def test_topic_coverage():
        assert_full_coverage(_t.parent / "guide.md", COMMANDS)

Reference inventories (plan.md:151) — the content lanes own the final lists:

  mac-terminal-guide      pwd ls cd mkdir cp mv more open rm
  linux-terminal-guide    mirrors mac, with xdg-open in place of open
  windows-powershell-guide / windows-cmd-guide
                          declare their own; the Windows guides RE-FRAME rather
                          than translate, so neither the commands nor the
                          section framings should mirror the Unix ones.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# The nine required subjects (plan.md:151)
# --------------------------------------------------------------------------
# Each entry: (key, human description, [group, group, ...]) where a group is a
# tuple of terms that must ALL appear (case-insensitive) for that group to
# match. Groups are alternatives — deliberately generous about vocabulary and
# strict about the concept.


@dataclass(frozen=True)
class Subject:
    key: str
    description: str
    groups: tuple[tuple[str, ...], ...]

    def matched_by(self, text: str) -> bool:
        return any(all(term in text for term in group) for group in self.groups)


SUBJECTS: tuple[Subject, ...] = (
    Subject("what-and-why", "what a terminal is and why it's worth learning", (
        ("what is", "terminal"), ("what the terminal", ), ("why", "terminal"),
        ("what is", "command prompt"), ("what is", "powershell"),
        ("why bother", ), ("why learn", ),
    )),
    Subject("open-and-close", "how to open and close it", (
        ("open", "close"), ("opening", "closing"),
        ("start menu", ), ("spotlight", ), ("launch", "terminal"),
        ("open", "powershell"), ("open", "command prompt"),
    )),
    Subject("filesystem-model", "the filesystem / folder model", (
        ("folder", "directory"), ("file system", ), ("filesystem", ),
        ("tree", "director"), ("drive letter", ), ("path", "folder"),
    )),
    Subject("home-and-relative", "home directory and relative-path notation", (
        ("home", "director"), ("home folder", ), ("user folder", ),
        ("%userprofile%", ), ("~", "home"), ("current director", ),
        ("relative path", ), ("..", "director"),
    )),
    Subject("essential-commands", "essential-command section with a worked example per command", (
        ("essential command", ), ("the commands", ), ("core command", ),
        ("basic command", ), ("command", "example"),
    )),
    Subject("destructive-warning", "a destructive-command warning callout", (
        ("permanent", ), ("cannot be undone", ), ("can't be undone", ),
        ("no undo", ), ("does not go to the", ), ("doesn't go to the", ),
        ("gone forever", ), ("careful", "delet"),
    )),
    Subject("quick-reference", "a Quick Reference Card table", (
        ("quick reference", ), ("reference card", ), ("cheat sheet", ),
        ("command reference", ),
    )),
    Subject("exercises", "at least 5 exercises", (
        ("exercise", ),
    )),
    Subject("where-next", "a 'where to go from here' close", (
        ("where to go", ), ("next steps", ), ("going further", ),
        ("what next", ), ("from here", ), ("keep learning", ),
    )),
)

MIN_EXERCISES = 5

# What counts as a COMMAND line across the three shells. Everything else inside
# a fenced block is recorded OUTPUT.
#
# The Windows cases must require the trailing '>'. A cmd prompt is `C:\Users\you>`
# but a printed PATH is `C:\Users\you` — matching on the `C:\` prefix alone would
# classify cmd's own output as another command, and every cmd example would then
# look like it records no output. Same for PowerShell's `PS C:\...>`.
_PROMPT_RE = re.compile(
    r"""^[ \t]*(?:
          \$(?:\s|$)                 # bash/zsh:      $ ls
        | \#(?:\s|$)                 # root shell:    # apt install
        | PS\b[^>]*>                 # PowerShell:    PS C:\Users\you> Get-ChildItem
        | [A-Za-z]:\\[^>]*>          # cmd:           C:\Users\you> dir
        | >(?:\s|$)                  # bare chevron prompt
    )""",
    re.VERBOSE,
)

_FENCE_RE = re.compile(r"^[ \t]*(?:```|~~~)(.*)$")


@dataclass
class CoverageReport:
    missing_subjects: list[str] = field(default_factory=list)
    exercise_count: int = 0
    commands_without_example: list[str] = field(default_factory=list)
    commands_without_output: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.missing_subjects
            or self.commands_without_example
            or self.commands_without_output
            or self.exercise_count < MIN_EXERCISES
        )

    def failure_text(self, guide: str) -> str:
        lines = [f"topic coverage failed for {guide}:"]
        for k in self.missing_subjects:
            s = next(s for s in SUBJECTS if s.key == k)
            lines.append(f"  - subject not taught: {k} ({s.description})")
        if self.exercise_count < MIN_EXERCISES:
            lines.append(
                f"  - only {self.exercise_count} exercise(s); at least {MIN_EXERCISES} required"
            )
        for c in self.commands_without_example:
            lines.append(f"  - declared command never demonstrated in a fenced example: {c!r}")
        for c in self.commands_without_output:
            lines.append(
                f"  - command {c!r} is shown but its example records no output — these guides "
                "show what the reader should see, so an example with no output is unverifiable"
            )
        return "\n".join(lines)


def code_blocks(markdown: str) -> list[list[str]]:
    """Every fenced code block's lines, fences excluded."""
    blocks, cur, in_block = [], [], False
    for line in markdown.splitlines():
        if _FENCE_RE.match(line):
            if in_block:
                blocks.append(cur); cur = []
            in_block = not in_block
            continue
        if in_block:
            cur.append(line)
    if in_block and cur:          # unterminated fence — take what we have
        blocks.append(cur)
    return blocks


def _is_command_line(line: str) -> bool:
    return bool(line.strip()) and _PROMPT_RE.match(line) is not None


def _mentions_command(line: str, command: str) -> bool:
    """The command appears as a whole word (so `cd` does not match `cdrom`)."""
    return re.search(rf"(?<![\w-]){re.escape(command)}(?![\w-])", line) is not None


def check_commands(markdown: str, commands: list[str]) -> tuple[list[str], list[str]]:
    """Returns (no_example, no_output).

    A command has an EXAMPLE when some fenced block contains a prompt-prefixed
    line invoking it. It RECORDS OUTPUT when that same block also carries at
    least one non-prompt, non-blank line after the invocation — i.e. the guide
    shows the reader what to expect rather than only what to type.
    """
    no_example, no_output = [], []
    blocks = code_blocks(markdown)
    for cmd in commands:
        demonstrated = False
        with_output = False
        for block in blocks:
            for i, line in enumerate(block):
                if not (_is_command_line(line) and _mentions_command(line, cmd)):
                    continue
                demonstrated = True
                tail = block[i + 1:]
                if any(t.strip() and not _is_command_line(t) for t in tail):
                    with_output = True
                    break
            if with_output:
                break
        if not demonstrated:
            no_example.append(cmd)
        elif not with_output:
            no_output.append(cmd)
    return no_example, no_output


def analyze(markdown: str, commands: list[str]) -> CoverageReport:
    lower = markdown.lower()
    rep = CoverageReport()
    rep.missing_subjects = [s.key for s in SUBJECTS if not s.matched_by(lower)]
    # Count exercise headings/boxes rather than the bare word, so prose
    # mentioning "exercise" cannot inflate the count.
    rep.exercise_count = len(
        re.findall(r'(?:class="exercise"|\*\*exercise\s*\d|^#{1,6}\s*exercise\s*\d)',
                   markdown, re.IGNORECASE | re.MULTILINE)
    )
    rep.commands_without_example, rep.commands_without_output = check_commands(markdown, commands)
    return rep


def assert_full_coverage(guide_md: Path | str, commands: list[str]) -> None:
    """Raise AssertionError with an actionable report if coverage is incomplete."""
    p = Path(guide_md)
    text = p.read_text(encoding="utf-8")
    rep = analyze(text, commands)
    assert rep.ok, rep.failure_text(p.name)
