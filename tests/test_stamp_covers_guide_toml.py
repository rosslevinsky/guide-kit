"""Mutating guide.toml changes build.py's version stamp — proving guide.toml is
in SOURCE_FILES (plan.md:61). If guide.toml were dropped from the hash inputs,
editing a guide's title/author/copyright would not bump the footer stamp.
"""
import build
import kitconfig


def test_version_stamp_changes_when_guide_toml_changes(tmp_path, monkeypatch):
    # Seed every SOURCE_FILES entry so the hash has real content. In a non-git
    # tmp dir the date/dirty parts of the stamp are empty, so the stamp is the
    # content hash alone — exactly what we want to observe moving.
    for name in kitconfig.SOURCE_FILES:
        (tmp_path / name).write_text(f"seed-{name}", encoding="utf-8")

    monkeypatch.setattr(build, "ROOT", tmp_path)
    first = build._version_stamp()

    (tmp_path / "guide.toml").write_text("seed-guide.toml-CHANGED", encoding="utf-8")
    second = build._version_stamp()

    assert first != second


def test_guide_toml_and_kitconfig_are_in_source_files():
    assert "guide.toml" in build.SOURCE_FILES
    assert "kitconfig.py" in build.SOURCE_FILES
