"""The shared topic-coverage module must actually catch what it claims.

Four required behaviours (phase-16): it detects a missing subject, detects a
declared command with no authored example, detects an example with no recorded
expected output, and — the load-bearing one — PASSES on re-framed headings that
teach the right subject under different words. Without that last property the
module would force Unix framings onto the Windows guides, contradicting the
re-framing requirement (plan.md:159).
"""
import pytest

import topic_coverage as tc

# A minimal but genuinely complete guide, written in Unix vocabulary.
UNIX_GUIDE = """
# A Guide

## What is the Terminal, and why bother?
It is a way to talk to your computer with words.

## Opening and closing it
Use Spotlight to open it; type exit to close.

## Folders and directories are the same thing
Your files live in a tree of directories.

## Home, the Tilde, and the Two Dots
Your home directory is written ~. The current directory is . and .. is up.
A relative path starts from where you are.

## The essential commands
Here is an example of each.

```
$ pwd
/Users/you
```

```
$ ls
notes.txt  photos
```

## Careful: deleting is permanent
`rm` does not go to the Trash. It cannot be undone.

## Quick Reference Card

| Command | Does |
|---|---|
| pwd | print working directory |

## Exercises

**Exercise 1** do a thing
**Exercise 2** do a thing
**Exercise 3** do a thing
**Exercise 4** do a thing
**Exercise 5** do a thing

## Where to go from here
Read more.
"""

UNIX_COMMANDS = ["pwd", "ls"]


def test_a_complete_guide_passes():
    rep = tc.analyze(UNIX_GUIDE, UNIX_COMMANDS)
    assert rep.ok, rep.failure_text("unix")


def test_detects_a_missing_subject():
    # Drop the Quick Reference Card section entirely.
    broken = UNIX_GUIDE.replace("## Quick Reference Card", "## Some Other Table")
    broken = broken.replace("| Command | Does |", "| Thing | Does |")
    rep = tc.analyze(broken, UNIX_COMMANDS)
    assert not rep.ok
    assert "quick-reference" in rep.missing_subjects
    assert "quick-reference" in rep.failure_text("g")


def test_detects_declared_command_with_no_example():
    # `mkdir` is promised but never demonstrated.
    rep = tc.analyze(UNIX_GUIDE, UNIX_COMMANDS + ["mkdir"])
    assert not rep.ok
    assert rep.commands_without_example == ["mkdir"]
    assert "never demonstrated" in rep.failure_text("g")


def test_detects_example_with_no_recorded_output():
    # `ls` is shown but the block records nothing the reader should see.
    no_output = UNIX_GUIDE.replace("$ ls\nnotes.txt  photos", "$ ls")
    rep = tc.analyze(no_output, UNIX_COMMANDS)
    assert not rep.ok
    assert rep.commands_without_output == ["ls"]
    assert "records no output" in rep.failure_text("g")


def test_passes_on_reframed_headings():
    """The cmd guide's own vocabulary must satisfy the same subjects.

    Shares essentially NO heading text with the Unix guide — no "terminal",
    no tilde, no "folders and directories", no Unix commands — and must still
    pass. This is the property that lets the cmd guide re-frame rather than
    translate.
    """
    cmd_guide = """
# Command Prompt

## What is the Command Prompt?
A window where you type instructions.

## Opening and closing Command Prompt
Find it in the Start Menu. Type exit to close it.

## Drive letters and folders
Everything lives under a drive letter such as C:\\.

## Your User Folder and Moving Around
%USERPROFILE% is your user folder. Use .. to go up one directory.

## The commands you will actually use
Each one has an example.

```
C:\\> cd
C:\\Users\\you
```

```
C:\\> dir
 Volume in drive C has no label.
 notes.txt
```

## Deleting is permanent
`del` removes a file for good — it cannot be undone and does not go to the Recycle Bin.

## Quick Reference

| Command | Does |
|---|---|
| dir | list files |

## Exercises
**Exercise 1** a
**Exercise 2** a
**Exercise 3** a
**Exercise 4** a
**Exercise 5** a

## Next steps
Keep going.
"""
    rep = tc.analyze(cmd_guide, ["cd", "dir"])
    assert rep.ok, rep.failure_text("cmd")
    # And prove it really is re-framed, not quietly sharing Unix wording.
    for unix_ism in ("~", "Tilde", "Folders and directories are the same"):
        assert unix_ism not in cmd_guide


def test_too_few_exercises_fails():
    few = UNIX_GUIDE
    for n in (3, 4, 5):
        few = few.replace(f"**Exercise {n}** do a thing\n", "")
    rep = tc.analyze(few, UNIX_COMMANDS)
    assert not rep.ok
    assert rep.exercise_count == 2
    assert "at least 5" in rep.failure_text("g")


def test_word_boundary_prevents_false_command_match():
    """`cd` must not be satisfied by an unrelated token containing it."""
    guide = UNIX_GUIDE.replace("$ pwd\n/Users/you", "$ cdrom-mount\nmounted")
    rep = tc.analyze(guide, ["cd"])
    assert rep.commands_without_example == ["cd"]


def test_prompt_only_block_is_not_output():
    """Consecutive command lines are not 'output' for the earlier command."""
    guide = UNIX_GUIDE.replace("$ ls\nnotes.txt  photos", "$ ls\n$ pwd")
    rep = tc.analyze(guide, ["ls"])
    assert rep.commands_without_output == ["ls"]


def test_assert_full_coverage_raises_with_path(tmp_path):
    p = tmp_path / "guide.md"
    p.write_text(UNIX_GUIDE.replace("## Where to go from here\nRead more.", ""), encoding="utf-8")
    with pytest.raises(AssertionError) as e:
        tc.assert_full_coverage(p, UNIX_COMMANDS)
    assert "guide.md" in str(e.value) and "where-next" in str(e.value)


def test_all_nine_subjects_are_declared():
    assert len(tc.SUBJECTS) == 9
    assert len({s.key for s in tc.SUBJECTS}) == 9
