"""The staleness check (make verify) — platform-independent, no renderer.

Covers: fresh (embedded stamp == content hash) passes; editing a SOURCE_FILES
entry without re-releasing fails and NAMES the stale file; the absent-PDF cases
(pre-first-release passes with a notice; deleted-after-release fails). Runs with
no pandoc and no WeasyPrint — the PDF's stamp is injected via monkeypatch, so no
real render is needed (plan.md:94, :157).
"""
import subprocess

import pytest

import kitconfig
import verify_pdf

SLUG = "probe-guide"
GUIDE_TOML = (
    'TITLE = "Probe"\n'
    f'OUTPUT_SLUG = "{SLUG}"\n'
    'AUTHOR = "T"\n'
    'DESCRIPTION = "d"\n'
    'KEYWORDS = "k"\n'
    'COPYRIGHT_YEAR = 2026\n'
    'baseline_platform = "darwin"\n'
)


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _mkrepo(tmp_path, with_pdf=True):
    (tmp_path / "guide.toml").write_text(GUIDE_TOML, encoding="utf-8")
    # Seed every SOURCE_FILES entry except transforms.py (left absent so the
    # untracked-naming case has a real source file to create).
    for name in kitconfig.SOURCE_FILES:
        if name not in ("guide.toml", "transforms.py"):
            (tmp_path / name).write_text(f"seed-{name}\n", encoding="utf-8")
    if with_pdf:
        (tmp_path / f"{SLUG}.pdf").write_bytes(b"%PDF-fake")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "release")
    return tmp_path


def test_fresh_passes(tmp_path, monkeypatch):
    repo = _mkrepo(tmp_path)
    fresh = kitconfig.content_hash(repo)
    monkeypatch.setattr(verify_pdf, "extract_stamp_hash", lambda pdf: fresh)
    assert verify_pdf.staleness_check(repo) == 0


def test_edited_source_fails_and_names_file(tmp_path, monkeypatch, capsys):
    repo = _mkrepo(tmp_path)
    baseline_hash = kitconfig.content_hash(repo)
    monkeypatch.setattr(verify_pdf, "extract_stamp_hash", lambda pdf: baseline_hash)
    # Edit a source file after "release" — the content hash now moves.
    (repo / "guide.md").write_text("seed-guide.md\n\nan added paragraph\n", encoding="utf-8")
    assert kitconfig.content_hash(repo) != baseline_hash

    assert verify_pdf.staleness_check(repo) == 1
    err = capsys.readouterr().err
    assert "STALE" in err
    assert "guide.md" in err  # names the stale file


def test_absent_pre_first_release_passes(tmp_path, capsys):
    repo = _mkrepo(tmp_path, with_pdf=False)  # never had a reference PDF
    assert verify_pdf.staleness_check(repo) == 0
    assert "pre-first-release" in capsys.readouterr().out


def test_deleted_after_release_fails(tmp_path, capsys):
    repo = _mkrepo(tmp_path, with_pdf=True)  # PDF committed...
    (repo / f"{SLUG}.pdf").unlink()          # ...then removed
    assert verify_pdf.staleness_check(repo) == 1
    assert "now missing" in capsys.readouterr().err


def test_no_readable_stamp_fails(tmp_path, monkeypatch, capsys):
    repo = _mkrepo(tmp_path)
    monkeypatch.setattr(verify_pdf, "extract_stamp_hash", lambda pdf: None)
    assert verify_pdf.staleness_check(repo) == 1
    assert "no readable version stamp" in capsys.readouterr().err


def test_names_untracked_source_file(tmp_path, monkeypatch, capsys):
    # A newly created (untracked) source file changes the hash and must be NAMED
    # too — `git diff` alone omits untracked files (regression guard for the
    # early-return that only reported tracked changes).
    repo = _mkrepo(tmp_path)  # transforms.py absent
    baseline_hash = kitconfig.content_hash(repo)
    monkeypatch.setattr(verify_pdf, "extract_stamp_hash", lambda pdf: baseline_hash)
    (repo / "transforms.py").write_text("# newly added source\n", encoding="utf-8")
    assert kitconfig.content_hash(repo) != baseline_hash
    assert verify_pdf.staleness_check(repo) == 1
    assert "transforms.py" in capsys.readouterr().err


def test_parse_stamp_hash_requires_date_prefix():
    # A dated footer stamp parses (with or without a dirty segment)...
    assert verify_pdf.parse_stamp_hash("2026-01-02 03:04:05 · abcdef123456") == "abcdef123456"
    assert verify_pdf.parse_stamp_hash("2026-01-02 03:04:05 · abcdef123456 · dirty") == "abcdef123456"
    assert verify_pdf.parse_stamp_hash("no stamp here") is None
    # ...but a `· <12hex>` fragment WITHOUT a date (e.g. a body example) is not
    # mistaken for the stamp, and a real dated stamp after it still wins.
    assert verify_pdf.parse_stamp_hash("see example · deadbeefcafe here") is None
    assert verify_pdf.parse_stamp_hash(
        "example · deadbeefcafe\n2026-01-02 03:04:05 · abcdef123456"
    ) == "abcdef123456"
