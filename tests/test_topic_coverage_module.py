"""The shared topic-coverage module must catch what it claims — and only that.

This check can fail in two fatal directions, and an earlier version failed both:

  TOO LOOSE — a whole-document substring scan passed a "guide" that was one line
  of keyword soup plus a single command.
  TOO TIGHT — the same version failed a well-written PowerShell guide on six of
  nine subjects because its markers encoded Mac/Unix vocabulary. That is exactly
  the outcome the design exists to prevent: the Windows guides must RE-FRAME
  rather than translate (plan.md:159).

So the suite pins BOTH edges, and the marker sets are validated against three
independently-written drafts — bash, PowerShell and cmd — instead of one sample
written against the marker list. The PowerShell draft below is deliberately
adversarial: verb-noun cmdlets, Recycle Bin, "Further reading", and no Unix
wording anywhere.
"""
import pytest

import topic_coverage as tc

# ---------------------------------------------------------------------------
# Three drafts, each in its own shell's native vocabulary.
# ---------------------------------------------------------------------------

BASH_GUIDE = """
# A Beginner's Guide to the Linux Terminal

## What is the terminal, and why bother?
The terminal is a window where you type instructions instead of clicking them.
Every desktop action has a text equivalent, and the text one can be repeated,
scripted, and explained to someone else exactly.

## Opening and closing it
Press Ctrl+Alt+T on most desktops, or find Terminal in your applications menu.
Type `exit` and press Enter to close it again. Closing the window does the same
thing, but `exit` is the habit worth building.

## Folders, directories, and the tree
Your files live in a single tree that starts at `/`. What a file manager calls a
folder, the terminal calls a directory — they are the same thing seen through
two different windows onto the same disk.

## Home, the tilde, and the two dots
Your home directory is where you start, written `~`. A single dot means the
current directory and two dots means the one above it, so `cd ..` walks upward.
A relative path is read from wherever you happen to be standing.

## The essential commands
Each of these gets a worked example, and each example shows what you should see.

```
$ pwd
/home/you
```

```
$ ls
notes.txt  photos
```

Deleting is **permanent**: `rm` does not go to the Trash, and there is no undo.

## Quick Reference Card

| Command | What it does |
|---|---|
| pwd | print the working directory |
| ls | list files |

## Exercises

<div class="exercise">**Exercise 1** Look around.</div>
<div class="exercise">**Exercise 2** Make a folder.</div>
<div class="exercise">**Exercise 3** Copy a file.</div>
<div class="exercise">**Exercise 4** Rename it.</div>
<div class="exercise">**Exercise 5** Delete it.</div>

## Where to go from here
Pick a small real task and do it in the terminal for a week.
"""
BASH_COMMANDS = ["pwd", "ls"]


# The reviewer's counter-example, kept verbatim in spirit: native PowerShell
# vocabulary throughout, sharing no headings with the bash draft.
POWERSHELL_GUIDE = """
# A Beginner's Guide to Windows PowerShell

# Why PowerShell is worth your time
PowerShell is a shell built around objects rather than plain text, which means
the things you list, filter and sort keep their structure instead of becoming
lines you have to re-parse. Learning it pays off the first time you automate
something you used to click through.

# Launching and quitting PowerShell
Press the Start button and type PowerShell, then press Enter. To leave, type
`exit`, or close the window. Both do the same thing; `exit` is the habit that
carries over to remote sessions where there is no window to close.

# Drives, folders and where your files live
Everything lives beneath a drive such as `C:\\`. PowerShell also exposes other
providers as drives, so the same navigation verbs work in more places than a
plain file browser would suggest.

# Your profile folder and moving around
`$HOME` and `%USERPROFILE%` both point at your profile folder. `..` refers to
the folder above the current one, so you can move upward without typing a full
path from the drive letter down.

# The cmdlets you will actually use
PowerShell names things Verb-Noun, so the list is short and guessable. Each one
below has an example with the output you should expect.

```
PS C:\\Users\\you> Get-Location

Path
----
C:\\Users\\you
```

```
PS C:\\Users\\you> Get-ChildItem

    Directory: C:\\Users\\you

Name
----
notes.txt
```

# Removing files is forever
`Remove-Item` bypasses the Recycle Bin. Once it returns, the file is gone and
there is no way back, so read the path twice before you press Enter.

# Cmdlet reference

| Cmdlet | What it does |
|---|---|
| Get-Location | show the current folder |
| Get-ChildItem | list items |

# Practice

<div class="exercise">**Exercise 1** Look around.</div>
<div class="exercise">**Exercise 2** Make a folder.</div>
<div class="exercise">**Exercise 3** Copy an item.</div>
<div class="exercise">**Exercise 4** Rename it.</div>
<div class="exercise">**Exercise 5** Remove it.</div>

# Further reading
The built-in help is genuinely good: start with `Get-Help about_Providers`.
"""
POWERSHELL_COMMANDS = ["Get-Location", "Get-ChildItem"]


CMD_GUIDE = """
# A Beginner's Guide to the Windows Command Prompt

## What is the Command Prompt?
It is a window where you type instructions for Windows to carry out. Anything
you can do by clicking, you can usually describe in a line of text instead, and
a line of text can be saved and repeated exactly.

## Opening and closing Command Prompt
Open the Start Menu, type `cmd`, and press Enter. To finish, type `exit` and
press Enter. The window closes; nothing is left running behind it.

## Drive letters and folders
Everything sits under a drive letter such as `C:\\`. A folder inside a folder is
written with backslashes between the names, and each drive has its own separate
tree rather than all of them hanging off one root.

## Your user folder and moving around
`%USERPROFILE%` is your own folder, usually `C:\\Users\\yourname`. Two dots mean
the folder above, so `cd..` steps up one level. To change drive as well as
folder you need `cd /d`.

## The commands you will actually use
Each one has an example showing what appears on screen.

```
C:\\Users\\you> cd
C:\\Users\\you
```

```
C:\\Users\\you> dir
 Volume in drive C has no label.
 notes.txt
```

## Deleting is permanent
`del` removes a file for good. It does not go to the Recycle Bin and there is no
way back, so check the name before pressing Enter.

## Quick reference

| Command | What it does |
|---|---|
| cd | show or change the current folder |
| dir | list files |

## Exercises

<div class="exercise">**Exercise 1** Look around.</div>
<div class="exercise">**Exercise 2** Make a folder.</div>
<div class="exercise">**Exercise 3** Copy a file.</div>
<div class="exercise">**Exercise 4** Rename it.</div>
<div class="exercise">**Exercise 5** Delete it.</div>

## Next steps
Try doing one real task a day without the mouse.
"""
CMD_COMMANDS = ["cd", "dir"]


ALL_DRAFTS = [
    pytest.param(BASH_GUIDE, BASH_COMMANDS, id="bash"),
    pytest.param(POWERSHELL_GUIDE, POWERSHELL_COMMANDS, id="powershell"),
    pytest.param(CMD_GUIDE, CMD_COMMANDS, id="cmd"),
]


# ---------------------------------------------------------------------------
# The module must PASS all three — this is the re-framing property
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("guide,commands", ALL_DRAFTS)
def test_each_shell_dialect_passes_on_its_own_vocabulary(guide, commands):
    rep = tc.analyze(guide, commands)
    assert rep.ok, rep.failure_text("draft")


def test_windows_drafts_share_no_unix_framing():
    """Proves the drafts above really are re-framed, not translated.

    If they leaked Unix wording the pass would be meaningless — it would show
    only that Unix-shaped Windows guides pass, which is the bug.
    """
    for draft in (POWERSHELL_GUIDE, CMD_GUIDE):
        for unix_ism in ("the terminal", "tilde", "~", "/home/", "Trash"):
            assert unix_ism.lower() not in draft.lower(), unix_ism
    # And their TEACHING headings are re-framed, not shared. Structural headings
    # like "Exercises" are expected to coincide across the family and are not
    # what "re-framed" is about — the subject-bearing ones are.
    bash_teaching = {s.heading for s in tc.sections(BASH_GUIDE)} - {"Exercises"}
    for draft in (POWERSHELL_GUIDE, CMD_GUIDE):
        shared = bash_teaching & {s.heading for s in tc.sections(draft)}
        assert not shared, f"teaching headings were translated, not re-framed: {shared}"


# ---------------------------------------------------------------------------
# TOO LOOSE — garbage must fail
# ---------------------------------------------------------------------------

def test_keyword_soup_is_rejected():
    """One line of every marker word plus one command must NOT pass.

    This is the regression for the substring-scan version, which accepted it.
    """
    soup = """
what is the terminal why bother opening closing folder directory current
relative path the commands example permanent quick reference where to go from
here **Exercise 1** **Exercise 2** **Exercise 3** **Exercise 4** **Exercise 5**

```
$ ls
z
```
"""
    rep = tc.analyze(soup, ["ls"])
    assert not rep.ok
    # It has no headings at all, so every heading-scoped subject is missing.
    assert {"what-and-why", "open-and-close", "filesystem-model",
            "home-and-relative", "essential-commands", "where-next"} <= set(rep.missing_subjects)


def test_bare_headings_with_no_body_are_rejected():
    """Headings alone are labels, not teaching."""
    stub = "\n".join(f"## {h}\n" for h in (
        "What is the terminal", "Opening and closing", "Folders and directories",
        "Home and moving around", "The commands", "Quick reference", "Where to go from here"))
    rep = tc.analyze(stub, ["ls"])
    assert not rep.ok
    assert "what-and-why" in rep.missing_subjects


def test_empty_inventory_is_rejected():
    """An empty COMMANDS list would silently disable the half of this check with teeth."""
    rep = tc.analyze(BASH_GUIDE, [])
    assert not rep.ok and rep.empty_inventory
    assert "COMMANDS is empty" in rep.failure_text("g")


# ---------------------------------------------------------------------------
# Command inventory — the four ways a command can look demonstrated but isn't
# ---------------------------------------------------------------------------

def test_command_only_in_a_comment_does_not_count():
    md = "```\n$ pwd\n# you will meet rm later\n/home/you\n```\n"
    no_ex, _ = tc.check_commands(md, ["rm"])
    assert no_ex == ["rm"]


def test_command_as_an_argument_does_not_count():
    md = "```\n$ man rm\nRM(1) User Commands\n```\n"
    no_ex, _ = tc.check_commands(md, ["rm"])
    assert no_ex == ["rm"]


def test_command_quoted_in_a_warning_string_does_not_count():
    md = '```\n$ echo "never run rm -rf /"\nnever run rm -rf /\n```\n'
    no_ex, _ = tc.check_commands(md, ["rm"])
    assert no_ex == ["rm"]


def test_silent_command_documented_by_its_effect_passes():
    """A silent command shown with a following check DOES demonstrate a result.

    An earlier version ended the output window at the next command line, so a
    silent command could never satisfy the check — and half a terminal guide's
    inventory (cd, mkdir, cp, mv, rm) is silent on success. That made the rule
    unsatisfiable for exactly the commands these guides teach. The honest rule
    is "the example demonstrates a result", not "the command printed something".
    """
    md = "```\n$ rm notes.txt\n$ ls\nphotos\n```\n"
    no_ex, no_out = tc.check_commands(md, ["rm"])
    assert no_ex == [] and no_out == []


def test_a_block_of_commands_with_no_output_at_all_fails():
    """What the rule actually rejects: an example that shows nothing verifiable."""
    md = "```\n$ rm a.txt\n$ rm b.txt\n```\n"
    no_ex, no_out = tc.check_commands(md, ["rm"])
    assert no_ex == [] and no_out == ["rm"]


def test_command_name_inside_the_prompt_path_does_not_count():
    md = "```\nC:\\Users\\you\\dir> echo hi\nhi\n```\n"
    no_ex, _ = tc.check_commands(md, ["dir"])
    assert no_ex == ["dir"]


def test_cmd_punctuated_invocations_do_count():
    """`cd..` and `cd\\` are genuine cmd syntax, not near-misses."""
    for line in ("C:\\Users\\you> cd..", "C:\\Users\\you> cd\\"):
        md = f"```\n{line}\nC:\\Users\n```\n"
        no_ex, no_out = tc.check_commands(md, ["cd"])
        assert no_ex == [] and no_out == [], line


def test_word_boundary_prevents_false_command_match():
    md = "```\n$ cdrom-mount\nmounted\n```\n"
    no_ex, _ = tc.check_commands(md, ["cd"])
    assert no_ex == ["cd"]


def test_detects_declared_command_with_no_example():
    rep = tc.analyze(BASH_GUIDE, BASH_COMMANDS + ["mkdir"])
    assert rep.commands_without_example == ["mkdir"]
    assert "never INVOKED" in rep.failure_text("g")


def test_detects_example_with_no_recorded_output():
    stripped = BASH_GUIDE.replace("$ ls\nnotes.txt  photos", "$ ls")
    rep = tc.analyze(stripped, BASH_COMMANDS)
    assert rep.commands_without_output == ["ls"]
    assert "demonstrates no result" in rep.failure_text("g")


# ---------------------------------------------------------------------------
# Prompt classification — one row per alternative, both directions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line,is_cmd", [
    ("$ ls", True), ("    $ ls", True), ("$", False),
    ("PS C:\\Users\\you> Get-ChildItem", True), ("PS> Get-Item", True),
    ("C:\\Users\\you> dir", True), ("D:\\> cd", True),
    ("C:\\Users\\you", False),          # printed cmd path, NOT a prompt
    ("/home/you", False),               # printed unix path
    ("Directory: C:\\Users\\you", False),
    ("# this is a comment", False),     # comments are not prompts
    ("> notes.txt", False),             # redirection / quoted output
    ("notes.txt", False), ("", False),
])
def test_prompt_classification(line, is_cmd):
    assert (tc._invocation(line) is not None) is is_cmd, line


# ---------------------------------------------------------------------------
# Exercises
# ---------------------------------------------------------------------------

def test_island_and_bold_form_are_not_double_counted():
    """The documented idiom nests **Exercise N** inside a div — counting both
    scores every exercise twice and turns MIN_EXERCISES=5 into 3."""
    md = "\n".join(f'<div class="exercise">\n\n**Exercise {i}** do a thing\n\n</div>'
                   for i in range(1, 6))
    assert tc.count_exercises(md) == 5


def test_prose_cross_references_do_not_inflate_the_count():
    md = ("As we saw in **Exercise 1**, and again in **Exercise 2**, and **Exercise 3**, "
          "**Exercise 4** and **Exercise 5** — all cross-references.\n")
    assert tc.count_exercises(md) == 0


def test_styled_elements_table_row_does_not_count():
    md = '| `<div class="exercise">` | Green exercise box |\n'
    assert tc.count_exercises(md) == 0


def test_unnumbered_and_worded_exercises_count():
    md = "### Exercise: Look around\n\n### Exercise: Make a folder\n"
    assert tc.count_exercises(md) == 2


def test_too_few_exercises_fails():
    few = BASH_GUIDE
    for n in (3, 4, 5):
        few = few.replace(f'<div class="exercise">**Exercise {n}** ', "<p>")
    rep = tc.analyze(few, BASH_COMMANDS)
    assert not rep.ok and rep.exercise_count == 2
    assert "at least 5" in rep.failure_text("g")


# ---------------------------------------------------------------------------
# Structure parsing
# ---------------------------------------------------------------------------

def test_headings_inside_code_blocks_do_not_create_sections():
    md = "## Real\n\nbody\n\n```\n# Not A Heading\n$ ls\nx\n```\n"
    assert [s.heading for s in tc.sections(md)] == ["Real"]


def test_nested_fences_do_not_desynchronize():
    md = "````\n$ cat readme.md\n```\ninner\n```\n````\n"
    blocks = tc.code_blocks(md)
    assert len(blocks) == 1 and "$ cat readme.md" in blocks[0]


def test_prose_outside_fences_is_never_a_code_block():
    md = "Just prose, no fences at all.\n"
    assert tc.code_blocks(md) == []


def test_detects_a_missing_subject():
    broken = BASH_GUIDE.replace("## Quick Reference Card", "## Assorted Notes")
    rep = tc.analyze(broken, BASH_COMMANDS)
    assert "quick-reference" in rep.missing_subjects
    assert "quick-reference" in rep.failure_text("g")


def test_reference_heading_without_a_table_does_not_count():
    """A 'Quick Reference' section must contain an actual table."""
    no_table = BASH_GUIDE.replace(
        "| Command | What it does |\n|---|---|\n| pwd | print the working directory |\n| ls | list files |",
        "pwd prints the working directory and ls lists files.")
    rep = tc.analyze(no_table, BASH_COMMANDS)
    assert "quick-reference" in rep.missing_subjects


def test_assert_full_coverage_raises_with_path(tmp_path):
    p = tmp_path / "guide.md"
    p.write_text(BASH_GUIDE.replace("## Where to go from here", "## Assorted"), encoding="utf-8")
    with pytest.raises(AssertionError) as e:
        tc.assert_full_coverage(p, BASH_COMMANDS)
    assert "guide.md" in str(e.value) and "where-next" in str(e.value)


def test_all_nine_subjects_are_declared():
    assert len(tc.SUBJECTS) == 9
    assert len({s.key for s in tc.SUBJECTS}) == 9


def test_pipeline_downstream_commands_count_as_invoked():
    """A cmdlet used downstream in a pipeline IS being run.

    PowerShell's model is the pipeline, so requiring first-position on the line
    would report Where-Object and Select-Object — its two most characteristic
    cmdlets — as never invoked in a guide that teaches them properly.
    """
    md = ("```\nPS C:\\> Get-ChildItem | Where-Object Length -gt 10 | Select-Object Name\n"
          "Name\n----\nlist.txt\n```\n")
    for cmd in ("Get-ChildItem", "Where-Object", "Select-Object"):
        no_ex, no_out = tc.check_commands(md, [cmd])
        assert no_ex == [] and no_out == [], cmd


def test_pipeline_split_does_not_excuse_a_mere_mention():
    """Splitting on `|` must not weaken the mention checks."""
    md = '```\n$ echo "never run rm -rf /"\nnever run rm -rf /\n```\n'
    assert tc.check_commands(md, ["rm"])[0] == ["rm"]
    md2 = "```\n$ man rm\nRM(1)\n```\n"
    assert tc.check_commands(md2, ["rm"])[0] == ["rm"]
