"""buildcore.py holds no guide-specific literal; all six values resolve from guide.toml.

The rule predates the `build.py` → `buildcore.py` split and moved with the constants:
buildcore.py is where they live now, so it is the module scanned.

Two assertions: (a) each of the six guide-specific names the module exposes equals
guide.toml's value; (b) NO module-level assignment contains a string literal equal to
any guide.toml value — an AST walk, not a grep, because the module's docstring and
comments legitimately mention the template by name. Also asserts the four LICENSE_*
constants REMAIN literals: they are family-fixed, not per-guide, so moving them into
guide.toml would invite a fork to relicense by config.
"""
import ast
from pathlib import Path

import buildcore
import kitconfig

REPO_ROOT = Path(buildcore.__file__).resolve().parent
# The per-guide constants live in buildcore.py since the build.py split; that
# is the module this rule is about, so it is the one scanned.
BUILD_SRC = (REPO_ROOT / "buildcore.py").read_text(encoding="utf-8")


def test_seven_values_resolve_from_guide_toml():
    c = kitconfig.load(REPO_ROOT)
    assert buildcore.TITLE == c.TITLE
    assert buildcore.OUTPUT_SLUG == c.OUTPUT_SLUG
    assert buildcore.AUTHOR == c.AUTHOR
    assert buildcore.DESCRIPTION == c.DESCRIPTION
    assert buildcore.KEYWORDS == c.KEYWORDS
    assert buildcore.COPYRIGHT_YEAR == c.COPYRIGHT_YEAR


def _module_level_string_constants(source: str) -> list[str]:
    """Every string Constant inside a MODULE-LEVEL assignment's value. Excludes
    the module docstring, comments (absent from the AST), and anything inside a
    function/class body — only top-level Assign/AnnAssign targets' values."""
    tree = ast.parse(source)
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append(sub.value)
    return out


def test_no_module_level_literal_matches_a_guide_toml_value():
    c = kitconfig.load(REPO_ROOT)
    guide_string_values = {
        c.TITLE,
        c.OUTPUT_SLUG,
        c.AUTHOR,
        c.DESCRIPTION,
        c.KEYWORDS,
    }
    offenders = [lit for lit in _module_level_string_constants(BUILD_SRC) if lit in guide_string_values]
    assert not offenders, f"build.py hardcodes guide.toml value(s) at module level: {offenders}"


def test_six_names_assigned_from_cfg():
    # Each of the six guide-specific module-level names must be assigned from
    # `_cfg.<attr>` (kitconfig), not a literal. This catches a hardcoded-but-equal
    # regression the value-equality check above cannot — e.g. `COPYRIGHT_YEAR = 2026`
    # (an int, so it never appears in the string-literal walk) would still equal
    # guide.toml and pass, but violate "resolves from guide.toml."
    names = {
        "TITLE", "OUTPUT_SLUG", "AUTHOR", "DESCRIPTION",
        "KEYWORDS", "COPYRIGHT_YEAR",
    }
    tree = ast.parse(BUILD_SRC)
    assigns: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assigns[node.targets[0].id] = node.value
    for n in names:
        assert n in assigns, f"{n} must be a module-level assignment in build.py"
        v = assigns[n]
        assert (
            isinstance(v, ast.Attribute)
            and isinstance(v.value, ast.Name)
            and v.value.id == "_cfg"
        ), f"{n} must be assigned from _cfg.<attr>, got {ast.dump(v)}"


def test_license_constants_remain_literals_in_buildcore():
    tree = ast.parse(BUILD_SRC)
    assigned: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned[t.id] = node.value.value
    for name in ("LICENSE_CONTENT_NAME", "LICENSE_CONTENT_URL", "LICENSE_CODE_NAME", "LICENSE_CODE_URL"):
        assert name in assigned, f"{name} must remain a module-level literal in buildcore.py"
        assert isinstance(assigned[name], str) and assigned[name]
