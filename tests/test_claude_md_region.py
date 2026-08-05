"""The decomposition record must keep describing the file it decomposes.

`docs/claude-md-decomposition.md` states where the kit-managed region of `CLAUDE.md`
starts and ends, how many subsections it holds, how long each one is, and where each is
headed. Those numbers are what the CLAUDE.md consolidation plan apportions across resident
text, path-scoped rules, a skill, and the README — so an edit to `CLAUDE.md` that moves the
boundaries silently invalidates the plan unless something notices.

Two properties make this a check rather than a description:

**The scan is fence-aware.** A naive heading scan reads the `## ` inside the fenced
`::: slide` example as a section boundary, stops there, and reports a managed region roughly
228 lines shorter than it is, hiding seven subsections. That reading was made once and drove
a wrong apportionment.

**Per-subsection spans are pinned, not just totals.** Bounds, total length and heading count
can all stay constant while a heading moves — which changes two spans and the destination
budgets computed from them. Checking only the totals would pass straight through that, so
each row's line count is compared against the scan, and each row must carry a destination.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
DECOMPOSITION = REPO_ROOT / "docs" / "claude-md-decomposition.md"

BEGIN_RE = re.compile(r"^\s*<!--\s*kit:begin")
END_RE = re.compile(r"^\s*<!--\s*kit:end")
ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", re.M)
DESTINATIONS = ("resident", "rule", "skill", "README")


def _lines():
    return CLAUDE_MD.read_text(encoding="utf-8").splitlines()


def managed_region_bounds():
    """1-indexed (begin, end) of the kit-managed region.

    Matched against the marker *comments*. A substring search for "kit:begin" also matches
    prose that merely names the markers, which appears earlier in the file and would report
    a one-line region.
    """
    lines = _lines()
    begin = next((i for i, l in enumerate(lines, 1) if BEGIN_RE.match(l)), None)
    end = next((i for i, l in enumerate(lines, 1) if END_RE.match(l)), None)
    assert begin and end, "CLAUDE.md carries no kit:begin/kit:end marker comments"
    return begin, end


def managed_subsections():
    """[(title, span)] for every real heading in the region, fences excluded.

    The span runs from one heading to the next, and the last runs to the end marker — the
    same accounting the decomposition record uses.
    """
    begin, end = managed_region_bounds()
    found, in_fence = [], False
    for i, line in enumerate(_lines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith(("## ", "### ")) and begin < i < end:
            found.append((i, line.lstrip("# ").strip()))
    return [
        (title, (found[j + 1][0] if j + 1 < len(found) else end) - start)
        for j, (start, title) in enumerate(found)
    ]


def recorded_rows():
    """[(title, lines, destination)] parsed from the apportionment table."""
    text = DECOMPOSITION.read_text(encoding="utf-8")
    # No filtering. The header separator (`|---:|---|---|`) cannot match ROW_RE, whose first
    # cell must be digits — so a filter for dashes-and-spaces cells would be dead code whose
    # only live effect is swallowing a genuinely blank destination, leaving the emptiness
    # assertion below unable to fire on the one case it exists for.
    return [(title, int(count), dest) for count, title, dest in ROW_RE.findall(text)]


def _claimed(field):
    text = DECOMPOSITION.read_text(encoding="utf-8")
    match = re.search(rf"^- {field}:\s*(\d+)\s*$", text, re.M)
    assert match, f"docs/claude-md-decomposition.md states no '{field}'"
    return int(match.group(1))


def test_decomposition_record_exists():
    assert DECOMPOSITION.is_file(), (
        "docs/claude-md-decomposition.md is missing — the managed region has no recorded "
        "apportionment, so nothing pins the numbers the plan relies on"
    )


def test_recorded_bounds_match_the_file():
    begin, end = managed_region_bounds()
    assert _claimed("region_begin") == begin
    assert _claimed("region_end") == end
    assert _claimed("region_lines") == end - begin + 1


def test_recorded_subsection_count_matches_a_fence_aware_scan():
    assert _claimed("subsections") == len(managed_subsections())


def test_the_fenced_example_is_not_counted_as_a_subsection():
    assert "What this template gives you" not in [t for t, _ in managed_subsections()], (
        "the fenced ::: slide example was counted as a section boundary"
    )


def test_every_subsection_has_exactly_one_row_with_the_right_span():
    """Pins spans, not just totals — a heading can move without changing any total."""
    rows = {title: count for title, count, _ in recorded_rows()}
    titles = [t for t, _, _ in recorded_rows()]
    assert len(titles) == len(set(titles)), f"duplicate rows: {titles}"
    for title, span in managed_subsections():
        assert title in rows, f"subsection with no row in the record: {title!r}"
        assert rows[title] == span, (
            f"{title!r}: record says {rows[title]} lines, the file has {span}"
        )


def test_no_row_describes_a_subsection_that_is_gone():
    scanned = {t for t, _ in managed_subsections()}
    stale = [t for t, _, _ in recorded_rows() if t not in scanned]
    assert not stale, f"rows for subsections no longer in CLAUDE.md: {stale}"


def test_every_row_names_a_real_destination():
    """A blank or unrecognised destination is an unmade decision, not a passing check."""
    for title, _, dest in recorded_rows():
        assert dest.strip(), f"{title!r} has an empty destination"
        assert any(d in dest for d in DESTINATIONS), (
            f"{title!r} has destination {dest!r}, none of {DESTINATIONS}"
        )


def test_the_recorded_spans_sum_to_the_region_less_its_framing():
    """Three lines are outside every span: both markers and the blank before the first heading."""
    begin, end = managed_region_bounds()
    assert sum(c for _, c, _ in recorded_rows()) == (end - begin + 1) - 3


def test_the_framing_line_really_is_blank():
    """The count above is only meaningful if the third framing line carries nothing.

    Subtracting a fixed 3 would otherwise stay green while an instruction sat on that line,
    absent from the apportionment and from every budget derived from it.
    """
    begin, _ = managed_region_bounds()
    assert _lines()[begin] == "", (
        f"line {begin + 1} is not blank, so it is content the apportionment does not account for"
    )


def test_no_table_row_is_unparseable():
    """A malformed row is invisible to every assertion above unless something counts them.

    ROW_RE skips what it cannot read, so a stray or duplicate row with a broken cell would
    otherwise sit in the document unchecked.
    """
    text = DECOMPOSITION.read_text(encoding="utf-8")
    table = text.split("## Apportionment", 1)[1].split("## Resulting budget", 1)[0]
    pipe_rows = [l for l in table.splitlines() if l.startswith("|")]
    assert len(pipe_rows) == len(recorded_rows()) + 2, (  # + header + separator
        f"{len(pipe_rows)} rows in the table, {len(recorded_rows())} parsed"
    )
