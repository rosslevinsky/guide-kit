"""Every `${{ ... }}` in a workflow VALUE must be a valid expression.

WHY THIS EXISTS. GitHub evaluates expression syntax anywhere in a workflow
*value*, and does not care that a given position is a shell comment inside a
`run:` block. A note reading "passed via env rather than <delimiters>
interpolation", written with the real delimiters inside a `run:` body, is
therefore not a comment: it is an EMPTY EXPRESSION, and it invalidates the entire
workflow file. GitHub reports that as a run named after the file path, with no
jobs and no annotations — a long way from pointing at the line.

It shipped exactly that way to eight repos, so this is a regression test.

THE DISTINCTION THAT MAKES THIS TEST CORRECT. A `#` comment at YAML level is
stripped by the YAML parser before GitHub ever sees it, so the same prose is
perfectly safe there — `deploy.yml.example` and `baseline.yml` both carry it and
have always run fine. Only text that survives into a parsed VALUE is
interpolated. So this walks the parsed document rather than the raw file: a
raw-text scan flags the harmless YAML comments and would have to be suppressed,
and a suppressed check is worth nothing.

`yaml.safe_load` succeeding proves nothing on its own here — the offending text
is a perfectly valid YAML string.

The same trap in a different costume has now bitten this repo three times: prose
containing a literal managed-region marker unbalanced the sync parser twice, and
this. The rule generalises — never write a live delimiter in prose that lives
inside the thing that parses it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WF_DIR = REPO_ROOT / ".github/workflows"
WORKFLOWS = sorted(WF_DIR.glob("*.yml")) + sorted(WF_DIR.glob("*.yml.example"))

_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)

# Contexts and expression functions GitHub actually provides.
_KNOWN = frozenset({
    "github", "env", "vars", "job", "jobs", "steps", "runner", "secrets",
    "strategy", "matrix", "needs", "inputs",
    "always", "success", "failure", "cancelled", "contains", "startsWith",
    "endsWith", "format", "join", "toJSON", "toJson", "fromJSON", "fromJson",
    "hashFiles",
})


def _strings(node, path="") -> list[tuple[str, str]]:
    """Every string VALUE in the parsed document, with a path for the message.

    Keys are walked as well as values: a mapping key is also a value GitHub
    interpolates (e.g. an `env:` name built from an expression)."""
    out: list[tuple[str, str]] = []
    if isinstance(node, str):
        out.append((path or "<root>", node))
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str):
                out.append((f"{path}.<key>", k))
            out += _strings(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _strings(v, f"{path}[{i}]")
    return out


def _load(wf: Path):
    return yaml.safe_load(wf.read_text(encoding="utf-8"))


def test_there_are_workflows_to_check():
    """Guard against the glob matching nothing, which would make every
    assertion below vacuously true."""
    assert WORKFLOWS, f"no workflow files found under {WF_DIR}"
    # The two that carry the auto-baseline wiring must be among them.
    names = {w.name for w in WORKFLOWS}
    assert {"verify.yml", "baseline.yml"} <= names, names


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_no_empty_expressions_in_values(wf: Path):
    empties = [
        (path, value.strip()[:90])
        for path, value in _strings(_load(wf))
        for body in _EXPR.findall(value)
        if not body.strip()
    ]
    assert not empties, (
        f"{wf.name} has an EMPTY expression inside a VALUE, which invalidates the "
        f"whole workflow file. GitHub interpolates expression syntax even inside a "
        f"shell comment in a run: block — move the note to a YAML comment, or "
        f"reword it. Offenders: {empties}"
    )


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_expression_delimiters_balanced_in_values(wf: Path):
    bad = [
        (path, value.strip()[:90])
        for path, value in _strings(_load(wf))
        if value.count("${{") != value.count("}}")
    ]
    assert not bad, (
        f"{wf.name} has an unterminated expression in a value, which invalidates "
        f"the workflow file: {bad}"
    )


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_expressions_reference_a_known_context(wf: Path):
    """A typo'd context (`secret.FOO`, `step.x.outputs.y`) resolves to empty at
    runtime instead of failing — a silent wrong value, which is the failure mode
    this family keeps rediscovering."""
    bad = []
    for path, value in _strings(_load(wf)):
        for body in _EXPR.findall(value):
            body = body.strip()
            if not body:
                continue  # covered above
            head = re.match(r"[A-Za-z_][A-Za-z0-9_]*", body)
            if head and head.group(0) not in _KNOWN:
                bad.append((path, body[:90]))
    assert not bad, f"{wf.name} references unknown context(s): {bad}"
