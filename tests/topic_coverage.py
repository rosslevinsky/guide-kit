"""Shared topic-coverage assertions for the terminal-guide family.

Imported by a thin `tests/test_topic_coverage.py` in each terminal guide, which
points it at that guide's own `guide.md` and command inventory. The logic lives
here so it is not copy-pasted three times; *invocation and blame* stay in each
guide, so a content edit in `windows-cmd-guide` turns that repo's CI red rather
than the kit's.

This file is `retained-in-kit` with no destination policy, so `sync.py` never
projects it into a target, and `bootstrap.py` prunes it from a `--template`
fork. A guide reaches it through the borrowed test runner (CI checks the kit
out to `_kit/`), so a guide's test file locates it like this:

    import sys, pathlib
    _t = pathlib.Path(__file__).resolve().parent
    for _c in (_t.parent / "_kit" / "tests",                 # CI: borrowed runner
               _t.parent.parent / "guide-template" / "tests"):  # local workspace
        if (_c / "topic_coverage.py").exists():
            sys.path.insert(0, str(_c)); break
    from topic_coverage import assert_full_coverage

TWO FAILURE MODES, BOTH FATAL
-----------------------------
This check has to thread a needle, and an earlier version missed on both sides:

*Too loose* — a whole-document substring scan passed a guide consisting of one
line of keyword soup and a single command. Subjects are therefore matched
against HEADINGS that own real body text, not against the document blob.

*Too tight* — the same version failed a well-written PowerShell guide on six of
nine subjects, because its markers encoded Mac/Unix vocabulary ("terminal",
"delete", "command") and PowerShell says cmdlet / Remove-Item / Recycle Bin.
That is the exact failure the design exists to prevent: the Windows guides are
required to RE-FRAME rather than translate (plan.md:159), so a check that only
recognizes Unix wording silently forces Unix framings onto Windows.

The marker sets below are therefore validated in the test suite against three
independently-written drafts — bash, PowerShell and cmd — rather than against a
single sample tuned to the list.

THE COMMAND-INVENTORY DECLARATION FORMAT
----------------------------------------
Markers alone prove only that nine labels exist. Each guide also declares the
commands it promises to teach, as a module-level `COMMANDS` list in its own
`tests/test_topic_coverage.py`. Deliberately not in `guide.toml`: that file has
a strict seven-key schema enforced by `kitconfig.py`, and an eighth key would
fail validation in every consumer.

Every declared command must be INVOKED in a fenced example (as the command
itself — not merely mentioned in a comment, quoted in a warning string, or
passed as an argument to something else) and that example must DEMONSTRATE A
RESULT, because these guides show the reader what to expect.

"Demonstrates a result" deliberately does NOT mean "the command printed
something". Half the inventory of a terminal guide is silent on success — `cd`,
`mkdir`, `cp`, `mv`, `rm` — and the correct way to document a silent command is
to run it and then show the effect:

    $ mkdir photos
    $ ls
    list.txt   notes   photos

Requiring direct output would make those commands unsatisfiable and turn this
check into a false-positive machine for precisely the commands these guides
exist to teach. So the rule is: somewhere after the invocation, the block must
contain at least one OUTPUT line. A block that is nothing but a stack of
commands with no output anywhere teaches the reader nothing verifiable, and
that is what this rejects.

Copy this into a new terminal guide as `tests/test_topic_coverage.py`:

    import pathlib, sys
    _t = pathlib.Path(__file__).resolve().parent
    for _c in (_t.parent / "_kit" / "tests",
               _t.parent.parent / "guide-template" / "tests"):
        if (_c / "topic_coverage.py").exists():
            sys.path.insert(0, str(_c)); break
    from topic_coverage import assert_full_coverage

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

MIN_EXERCISES = 5
# A heading must own at least this much prose to count as teaching its subject.
# Tuned low enough that a terse but real section passes, high enough that a bare
# heading or a one-line stub does not.
MIN_SECTION_CHARS = 120


# --------------------------------------------------------------------------
# Subjects
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Subject:
    key: str
    description: str
    groups: tuple[tuple[str, ...], ...]
    scope: str = "heading"      # "heading" | "body" | "table"
    # Minimum body length for a heading-scoped subject. Per-subject because a
    # "where to go from here" close is legitimately two sentences, while a
    # section claiming to teach the filesystem model is not.
    min_body: int = MIN_SECTION_CHARS

    def group_matches(self, text: str) -> bool:
        return any(all(term in text for term in group) for group in self.groups)


SUBJECTS: tuple[Subject, ...] = (
    Subject("what-and-why", "what a terminal/shell is and why it's worth learning", (
        ("what is",), ("what the",), ("why",), ("meet ",), ("introducing",),
        ("worth",), ("about the",),
    )),
    Subject("open-and-close", "how to open and close it", (
        ("open",), ("opening",), ("launch",), ("launching",), ("start",),
        ("starting",), ("quit",), ("quitting",), ("close",), ("closing",),
        ("getting in",), ("running it",),
    )),
    Subject("filesystem-model", "the filesystem / folder model", (
        ("folder",), ("director",), ("file system",), ("filesystem",),
        ("drive",), ("where files",), ("tree",), ("path",),
    )),
    Subject("home-and-relative", "home directory and relative-path notation", (
        ("home",), ("user folder",), ("userprofile",), ("profile folder",),
        ("moving around",), ("where you are",), ("current",), ("navigat",),
        ("getting around",), ("relative",),
    )),
    Subject("essential-commands", "an essential-command section with a worked example per command", (
        ("command",), ("cmdlet",), ("verbs",), ("the basics",),
        ("you will use",), ("you'll use",), ("essential",), ("toolkit",),
    )),
    # Body-scoped: the destructive warning is normally a callout inside another
    # section, not a heading of its own. Requiring a heading here would force an
    # artificial section break on every guide.
    Subject("destructive-warning", "a destructive-command warning", (
        ("permanent",), ("cannot be undone",), ("can't be undone",),
        ("no undo",), ("no way back",), ("forever",), ("irreversible",),
        ("does not go to",), ("doesn't go to",), ("bypass", "recycle"),
        ("skips the recycle",), ("not go to the trash",), ("gone for good",),
    ), scope="body"),
    Subject("quick-reference", "a Quick Reference Card table", (
        ("quick reference",), ("reference card",), ("cheat sheet",),
        ("reference",), ("at a glance",), ("summary of",),
    ), scope="table"),
    Subject("exercises", "at least 5 exercises", (
        ("exercise",), ("practice",), ("try it",),
    ), scope="body"),
    Subject("where-next", "a 'where to go from here' close", (
        ("where to go",), ("next steps",), ("what next",), ("from here",),
        ("going further",), ("further reading",), ("keep learning",),
        ("keep going",), ("learn more",), ("beyond",), ("next",),
    ), min_body=40),
)

# --------------------------------------------------------------------------
# Markdown structure
# --------------------------------------------------------------------------

_ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_OPEN_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def _strip_fences(lines: list[str]) -> list[str]:
    """Lines outside fenced code blocks. Tracks the opening fence's char and
    length so a nested shorter fence cannot desynchronize the toggle."""
    out, closer = [], None
    for line in lines:
        m = _FENCE_OPEN_RE.match(line)
        if closer is None:
            if m:
                closer = (m.group(2)[0], len(m.group(2)))
                continue
            out.append(line)
        else:
            if m and m.group(2)[0] == closer[0] and len(m.group(2)) >= closer[1] \
                    and not m.group(3).strip():
                closer = None
            # inside a fence: dropped either way
    return out


@dataclass
class Section:
    heading: str
    body: str


def sections(markdown: str) -> list[Section]:
    """(heading, body) pairs. Headings inside fenced blocks are ignored, so a
    code sample containing `# comment` cannot invent a section."""
    lines = _strip_fences(markdown.splitlines())
    out: list[Section] = []
    cur_head, cur_body = None, []
    for line in lines:
        m = _ATX_RE.match(line)
        if m:
            if cur_head is not None:
                out.append(Section(cur_head, "\n".join(cur_body)))
            cur_head, cur_body = m.group(2), []
        elif cur_head is not None:
            cur_body.append(line)
    if cur_head is not None:
        out.append(Section(cur_head, "\n".join(cur_body)))
    return out


def code_blocks(markdown: str) -> list[list[str]]:
    """Every fenced code block's lines, fences excluded."""
    blocks, cur, closer = [], [], None
    for line in markdown.splitlines():
        m = _FENCE_OPEN_RE.match(line)
        if closer is None:
            if m:
                closer, cur = (m.group(2)[0], len(m.group(2))), []
            continue
        if m and m.group(2)[0] == closer[0] and len(m.group(2)) >= closer[1] \
                and not m.group(3).strip():
            blocks.append(cur)
            closer, cur = None, []
            continue
        cur.append(line)
    if closer is not None and cur:
        blocks.append(cur)
    return blocks


# --------------------------------------------------------------------------
# Command examples
# --------------------------------------------------------------------------
# A COMMAND line is a prompt followed by an invocation. Windows cases must
# require the trailing '>': a cmd prompt is `C:\\Users\\you>` but a printed PATH
# is `C:\\Users\\you`, and matching the `C:\\` prefix alone would classify cmd's
# own output as another command — every cmd example would look output-less.
#
# `#` is NOT a prompt. It is overwhelmingly a shell comment inside these guides,
# and treating it as a prompt let a command that appears only in a comment count
# as demonstrated.
_PROMPT_RE = re.compile(
    r"""^[ \t]*(?:
          (?P<bash>\$)(?:[ \t]+|$)          # bash/zsh:    $ ls
        | (?P<ps>PS\b[^>]*>)                # PowerShell:  PS C:\Users\you> Get-ChildItem
        | (?P<cmd>[A-Za-z]:\\[^>]*>)        # cmd:         C:\Users\you> dir
    )""",
    re.VERBOSE,
)


def _invocation(line: str) -> str | None:
    """The command text after the prompt, or None if this is not a command line."""
    m = _PROMPT_RE.match(line)
    if not m:
        return None
    rest = line[m.end():].strip()
    return rest or None          # a bare prompt invokes nothing


def _first_token_is(invocation: str, command: str) -> bool:
    """True when `command` is the thing being RUN, not merely mentioned.

    Checks the first token of EVERY pipeline segment, not just the first token
    of the line. In a pipeline shell the downstream commands are genuinely being
    run — PowerShell's entire model is `Get-ChildItem | Where-Object ... |
    Select-Object ...`, and requiring first-position would report its two most
    characteristic cmdlets as never invoked. Splitting on `|` keeps the property
    that matters: `man rm`, `echo "never run rm"` and `rm` as an argument still
    do not count, because in each the command is not first in any segment.

    Trailing punctuation is allowed because `cd..` and `cd\\` are genuine cmd
    invocations. (A literal `|` inside a quoted string would over-split; that
    errs toward permissive and has not arisen in these guides.)
    """
    if not invocation:
        return False
    for segment in invocation.split("|"):
        parts = segment.split()
        if not parts:
            continue
        token = parts[0]
        if token == command:
            return True
        if token.startswith(command) and token[len(command):len(command) + 1] in (".", "\\", "/"):
            return True
    return False


@dataclass
class CoverageReport:
    missing_subjects: list[str] = field(default_factory=list)
    exercise_count: int = 0
    commands_without_example: list[str] = field(default_factory=list)
    commands_without_output: list[str] = field(default_factory=list)
    empty_inventory: bool = False

    @property
    def ok(self) -> bool:
        return not (
            self.missing_subjects
            or self.commands_without_example
            or self.commands_without_output
            or self.empty_inventory
            or self.exercise_count < MIN_EXERCISES
        )

    def failure_text(self, guide: str) -> str:
        lines = [f"topic coverage failed for {guide}:"]
        if self.empty_inventory:
            lines.append(
                "  - COMMANDS is empty: the inventory is the part of this check with teeth, "
                "so an empty list would disable it while still reporting success"
            )
        for k in self.missing_subjects:
            s = next(s for s in SUBJECTS if s.key == k)
            where = {"heading": "no section heading covers it (with real body text)",
                     "body": "not found anywhere in the prose",
                     "table": "no reference section with an actual table"}[s.scope]
            lines.append(f"  - subject not taught: {k} — {s.description} ({where})")
        if self.exercise_count < MIN_EXERCISES:
            lines.append(
                f"  - only {self.exercise_count} exercise(s); at least {MIN_EXERCISES} required"
            )
        for c in self.commands_without_example:
            lines.append(
                f"  - declared command never INVOKED in a fenced example: {c!r} "
                "(mentioning it in a comment, a warning string, or as an argument does not count)"
            )
        for c in self.commands_without_output:
            lines.append(
                f"  - command {c!r} is invoked but its example demonstrates no result — the block "
                "shows only commands and no output. For a silent command, run it and then show "
                "the effect (e.g. `mkdir photos` followed by `ls`)"
            )
        return "\n".join(lines)


def check_commands(markdown: str, commands: list[str]) -> tuple[list[str], list[str]]:
    """Returns (never_invoked, invoked_without_a_demonstrated_result).

    A result is demonstrated when, somewhere after the invocation in the same
    block, there is an output line. That covers both a command that prints
    directly and a silent one whose effect is shown by a following check — see
    the module docstring for why requiring direct output would be wrong.
    """
    no_example, no_output = [], []
    blocks = code_blocks(markdown)
    for cmd in commands:
        invoked = with_output = False
        for block in blocks:
            for i, line in enumerate(block):
                inv = _invocation(line)
                if inv is None or not _first_token_is(inv, cmd):
                    continue
                invoked = True
                if any(line_.strip() and _invocation(line_) is None
                       for line_ in block[i + 1:]):
                    with_output = True
                    break
            if with_output:
                break
        if not invoked:
            no_example.append(cmd)
        elif not with_output:
            no_output.append(cmd)
    return no_example, no_output


def count_exercises(markdown: str) -> int:
    """Count exercises without double-counting the family's own island idiom.

    The documented pattern wraps a `**Exercise N**` line inside
    `<div class="exercise">`, so counting both forms scores every exercise twice
    and makes MIN_EXERCISES=5 mean 3. Islands win when present; the bold/heading
    form is the fallback for guides that do not use them. Table rows are skipped
    so a styled-elements table documenting the island cannot inflate the count.
    """
    lines = [l for l in _strip_fences(markdown.splitlines()) if not l.lstrip().startswith("|")]
    text = "\n".join(lines)
    islands = len(re.findall(r'<div[^>]*class="[^"]*\bexercise\b', text, re.IGNORECASE))
    if islands:
        return islands
    return len(re.findall(
        r'^\s*(?:#{1,6}\s*)?(?:\*\*)?exercise\b', text, re.IGNORECASE | re.MULTILINE))


def analyze(markdown: str, commands: list[str]) -> CoverageReport:
    rep = CoverageReport()
    secs = sections(markdown)
    body_all = "\n".join(s.body for s in secs).lower() or markdown.lower()

    for subj in SUBJECTS:
        if subj.key == "exercises":
            continue                                    # counted separately
        if subj.scope == "body":
            covered = subj.group_matches(body_all)
        elif subj.scope == "table":
            covered = any(
                subj.group_matches(s.heading.lower()) and _TABLE_ROW_RE.search(s.body)
                for s in secs
            )
        else:                                           # heading
            covered = any(
                subj.group_matches(s.heading.lower()) and len(s.body.strip()) >= subj.min_body
                for s in secs
            )
        if not covered:
            rep.missing_subjects.append(subj.key)

    rep.exercise_count = count_exercises(markdown)
    rep.empty_inventory = not commands
    rep.commands_without_example, rep.commands_without_output = check_commands(markdown, commands)
    return rep


def assert_full_coverage(guide_md: Path | str, commands: list[str]) -> None:
    """Raise AssertionError with an actionable report if coverage is incomplete."""
    p = Path(guide_md)
    rep = analyze(p.read_text(encoding="utf-8"), commands)
    assert rep.ok, rep.failure_text(p.name)
