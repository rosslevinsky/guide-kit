"""The strict guide.toml loader (kitconfig.load) validates rather than trusts.

Covers plan.md:56 — required keys present, correct types, kebab-case OUTPUT_SLUG,
baseline_platform in an enum, integer COPYRIGHT_YEAR, and slug values that would
escape the repo root. Runs on stdlib only (no pandoc/WeasyPrint).
"""
import pytest

import kitconfig

VALID = {
    "TITLE": "Guide Template",
    "OUTPUT_SLUG": "guide-template",
    "AUTHOR": "Ross Levinsky",
    "DESCRIPTION": "A description with a colon: and a url https://example.com/",
    "KEYWORDS": "guide, template, pandoc",
    "COPYRIGHT_YEAR": 2026,
    "baseline_platform": "darwin",
}


def _dump(d: dict) -> str:
    lines = []
    for k, v in d.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, int):
            lines.append(f"{k} = {v}")
        else:
            s = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{s}"')
    return "\n".join(lines) + "\n"


def _write(tmp_path, d: dict):
    (tmp_path / "guide.toml").write_text(_dump(d), encoding="utf-8")
    return tmp_path


def test_valid_config_loads(tmp_path):
    c = kitconfig.load(root=_write(tmp_path, VALID))
    assert c.TITLE == "Guide Template"
    assert c.OUTPUT_SLUG == "guide-template"
    assert c.AUTHOR == "Ross Levinsky"
    assert c.KEYWORDS == "guide, template, pandoc"
    assert c.COPYRIGHT_YEAR == 2026
    assert c.baseline_platform == "darwin"


def test_missing_guide_toml_rejected(tmp_path):
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=tmp_path)


@pytest.mark.parametrize("missing", list(VALID))
def test_missing_key_rejected(tmp_path, missing):
    d = dict(VALID)
    d.pop(missing)
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


def test_year_must_be_integer(tmp_path):
    d = dict(VALID)
    d["COPYRIGHT_YEAR"] = "2026"  # string, not int
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


def test_year_bool_rejected(tmp_path):
    d = dict(VALID)
    d["COPYRIGHT_YEAR"] = True  # bool is an int subclass — must be rejected
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


def test_title_must_be_string(tmp_path):
    d = dict(VALID)
    d["TITLE"] = 5
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


@pytest.mark.parametrize("bad", ["Guide_Template", "-guide", "guide-", "UPPER", "has space", "under_score"])
def test_non_kebab_slug_rejected(tmp_path, bad):
    d = dict(VALID)
    d["OUTPUT_SLUG"] = bad
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


@pytest.mark.parametrize("ok", ["a1", "guide-template", "g2g", "windows-cmd-guide"])
def test_valid_slugs_accepted(tmp_path, ok):
    d = dict(VALID)
    d["OUTPUT_SLUG"] = ok
    assert kitconfig.load(root=_write(tmp_path, d)).OUTPUT_SLUG == ok


@pytest.mark.parametrize("bad", ["macos", "solaris", "osx", "Darwin"])
def test_platform_out_of_enum_rejected(tmp_path, bad):
    d = dict(VALID)
    d["baseline_platform"] = bad
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


@pytest.mark.parametrize("ok", ["darwin", "linux", "win32"])
def test_platform_enum_accepted(tmp_path, ok):
    d = dict(VALID)
    d["baseline_platform"] = ok
    assert kitconfig.load(root=_write(tmp_path, d)).baseline_platform == ok


@pytest.mark.parametrize("evil", ["../../x", "../escape", "a/../../b"])
def test_slug_escaping_repo_root_rejected(tmp_path, evil):
    d = dict(VALID)
    d["OUTPUT_SLUG"] = evil
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=_write(tmp_path, d))


def test_slug_with_trailing_newline_rejected(tmp_path):
    # A TOML escaped `\n` decodes to a real newline; regex `$` (with .match())
    # matches just before a trailing newline, so this must be rejected by the
    # .fullmatch() anchor — else OUTPUT_SLUG yields a filename with an embedded
    # newline. Write the raw TOML so tomllib decodes the escape (the _dump helper
    # would instead emit an invalid multi-line basic string).
    rest = _dump({k: v for k, v in VALID.items() if k != "OUTPUT_SLUG"})
    text = 'OUTPUT_SLUG = "guide-template\\n"\n' + rest
    (tmp_path / "guide.toml").write_text(text, encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(root=tmp_path)


def test_source_files_exact_contract():
    # Pin the exact list, not just membership: the original four in order, then
    # guide.toml and kitconfig.py (plan.md:59, :61). A reorder or duplicate is a
    # real change to the hash input and must fail this.
    assert kitconfig.SOURCE_FILES == [
        "guide.md",
        "style.css",
        "build.py",
        "transforms.py",
        "guide.toml",
        "kitconfig.py",
    ]


def test_content_hash_covers_every_source_file(tmp_path):
    # Every SOURCE_FILES entry must feed the hash — especially guide.toml and
    # kitconfig.py, the two this phase adds. If content_hash iterated only the
    # first four, mutating either new file would leave the hash unchanged and
    # this fails by name.
    for name in kitconfig.SOURCE_FILES:
        (tmp_path / name).write_text(f"init-{name}", encoding="utf-8")
    baseline = kitconfig.content_hash(root=tmp_path)
    assert len(baseline) == 12
    assert kitconfig.content_hash(root=tmp_path) == baseline  # deterministic

    for name in kitconfig.SOURCE_FILES:
        p = tmp_path / name
        original = p.read_text(encoding="utf-8")
        p.write_text(original + "X", encoding="utf-8")
        assert kitconfig.content_hash(root=tmp_path) != baseline, f"{name} not covered by hash"
        p.write_text(original, encoding="utf-8")  # restore
        assert kitconfig.content_hash(root=tmp_path) == baseline
