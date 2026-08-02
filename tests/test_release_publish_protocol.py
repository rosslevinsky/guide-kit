"""The edition-date predicate: one captured admission instant.

Freshness is proved by the artifact's CONTENT differing from the last released
identity — never by the date string. Two same-day releases are legal (their
hashes differ, so they are different editions); an unchanged artifact is not,
whatever the date says. "Content" means the closure NORMALISED to the last
released date, because the date key is inside the closure: compared as authored,
hand-editing the date alone moves the hash and a byte-identical artifact
masquerades as a new edition.

The date itself is validated against an instant captured ONCE when the
transaction is created and persisted with it. Every scenario below is one that a
moving clock — "date must equal today's UTC date" — gets wrong: a transaction
admitted at 23:59 and completed at 00:01 would fail its own validation, and a
next-day retry after a provider failure would dead-end.

Persistence is ONE git ref per artifact under `refs/guide-kit/release-txn/`,
compare-and-swapped on every write and deleted when the release completes. See
release.py's own note for why a ref and not a working-tree file, and why the ref
is keyed by artifact rather than by content digest.
"""
import datetime
import json
import subprocess
import sys

import pytest

import kitconfig
import release
import verify_artifacts

UTC = datetime.timezone.utc


def _git(repo, *args, capture=False):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=capture, text=capture)


def _seed(repo, date="2026-07-26", slides_file=None):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    slides_table = (
        f'[slides]\nsource = "file"\nfile = "{slides_file}"\n' if slides_file else ""
    )
    (repo / "guide.toml").write_text(
        'TITLE = "Probe Guide"\n'
        'OUTPUT_SLUG = "probe-guide"\n'
        'AUTHOR = "Tester"\n'
        'DESCRIPTION = "d"\n'
        'KEYWORDS = "k"\n'
        'COPYRIGHT_YEAR = 2026\n'
        "[outputs]\n"
        "pdf = true\n"
        'site = "none"\n'
        "slides = false\n"
        + slides_table +
        "[artifacts.pdf]\n"
        f'date = "{date}"\n',
        encoding="utf-8",
    )
    for name in ("guide.md", "style.css", "build.py", "kitconfig.py"):
        (repo / name).write_text(f"# {name}\n", encoding="utf-8")
    # The kit gitignores build/; without it here the working render would show up
    # as an untracked out-of-scope path and the preflight assertions would be
    # measuring the fixture rather than release.py.
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = _seed(tmp_path)
    monkeypatch.setattr(release, "ROOT", r)
    return r


def _at(y, mo, d, h=12, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=UTC)


def _today():
    return datetime.datetime.now(UTC).date().isoformat()


def _subjects(repo):
    out = subprocess.run(["git", "log", "--format=%s"], cwd=repo, check=True,
                         capture_output=True, text=True).stdout
    return [s for s in out.split("\n") if s]


def _stamp(date, hash_):
    """A stand-in for a parsed reference stamp."""
    return kitconfig.Stamp(date=date, hash=hash_, dirty=False)


def _run_main(repo, monkeypatch, message="release"):
    """`release.main()` with only the RENDER stubbed — the orchestration, the
    predicate and the transaction lifecycle all run for real."""
    def _stub_build():
        (repo / "build").mkdir(exist_ok=True)
        (repo / "build" / "probe-guide.pdf").write_bytes(b"%PDF-fake-render")

    monkeypatch.setattr(release, "_build", _stub_build)
    monkeypatch.setattr(verify_artifacts, "promotable_stamp",
                        lambda w, r, a="pdf": (True, "stubbed"))
    # Same reason as the line above: these tests exercise the release TRANSACTION
    # against a stub PDF, not a real render, so the document-level check has
    # nothing valid to read. Its own coverage is tests/test_promotion_smokes.py
    # (it is called, and before the copy) and tests/test_smoke_check.py (what it
    # rejects). Stubbing it here keeps this file about the protocol.
    monkeypatch.setattr(verify_artifacts, "smoke_check",
                        lambda p, r=None, artifact="pdf": 0)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", message])
    return release.main()


# ----- The admission instant is captured once and reused ---------------------

def test_the_instant_is_captured_once_and_reused(repo):
    digest = kitconfig.content_digest("pdf", root=repo)
    first = release.open_transaction("pdf", digest, None, now=_at(2026, 7, 26, 23, 59))
    # A later call with a DIFFERENT clock must still get the original instant.
    again = release.open_transaction("pdf", digest, None, now=_at(2026, 7, 27, 0, 1))
    assert again["admitted_at"] == first["admitted_at"], \
        "the instant was re-read from a moving clock"


def test_content_moving_on_opens_a_new_transaction(repo):
    """The open transaction belongs to the content it was admitted for. When the
    content changes the old one is abandoned, not kept alongside — that is what
    stops a permanent per-digest ref from resurrecting a months-old instant."""
    digest = kitconfig.content_digest("pdf", root=repo)
    mine = release.open_transaction("pdf", digest, None, now=_at(2026, 7, 26))
    other = release.open_transaction("pdf", "ffffffffffff", None, now=_at(2026, 8, 1))
    assert other["admitted_at"] != mine["admitted_at"]
    assert other["digest"] == "ffffffffffff"

    # Coming back to the original content is a NEW edition, dated now.
    again = release.open_transaction("pdf", digest, None, now=_at(2026, 9, 1))
    assert again["admitted_at"] != mine["admitted_at"]
    assert release.admission_date(again["admitted_at"]) == "2026-09-01"


def test_a_transaction_older_than_the_last_release_is_replaced(repo):
    """An abandoned transaction must not outlive the release that overtook it.

    Left in place it pins an instant that predates the published edition, and the
    backwards-date check then refuses every future release — a stale ref would
    make the repository permanently unreleasable."""
    digest = kitconfig.content_digest("pdf", root=repo)
    stale = release.open_transaction("pdf", digest, None, now=_at(2026, 7, 26))
    fresh = release.open_transaction("pdf", digest, "2026-08-15", now=_at(2026, 9, 1))
    assert fresh["admitted_at"] != stale["admitted_at"]
    assert release.admission_date(fresh["admitted_at"]) == "2026-09-01"


def test_the_transaction_lives_on_a_ref_not_in_the_working_tree(repo):
    digest = kitconfig.content_digest("pdf", root=repo)
    release.open_transaction("pdf", digest, None, now=_at(2026, 7, 26))

    # Nothing appeared in the tree — no file to special-case, nothing to clean up.
    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                               capture_output=True, text=True, check=True).stdout
    assert porcelain.strip() == "", f"the transaction dirtied the tree: {porcelain!r}"

    # ...and it is outside refs/heads and refs/tags, so it perturbs no branch or tag.
    ref = release._txn_ref("pdf")
    assert ref.startswith("refs/guide-kit/")
    payload = json.loads(subprocess.run(["git", "cat-file", "-p", ref], cwd=repo,
                                        capture_output=True, text=True, check=True).stdout)
    assert payload["digest"] == digest and payload["artifact"] == "pdf"


def test_the_admission_date_is_utc(repo):
    # 23:30 UTC is already the NEXT day in some local zones; the predicate must
    # give one answer wherever it runs.
    assert release.admission_date("2026-07-26T23:30:00+00:00") == "2026-07-26"
    assert release.admission_date("2026-07-27T01:30:00+02:00") == "2026-07-26"


# ----- Concurrency: the ref is compare-and-swapped ---------------------------

def test_writing_the_transaction_is_compare_and_swap(repo):
    ref = release._txn_ref("pdf")
    assert release._cas_txn(ref, {"a": 1}, "") is True
    # An empty old-value asserts the ref does NOT exist, so this must lose.
    assert release._cas_txn(ref, {"a": 2}, "") is False
    sha, payload = release._read_txn(ref)
    assert payload == {"a": 1}, "a blind write clobbered the existing transaction"
    assert release._cas_txn(ref, {"a": 3}, sha) is True


def test_a_lost_creation_race_adopts_the_winners_instant(repo, monkeypatch):
    """Two processes observing a missing ref must not both proceed with their own
    instant: only one is persisted, so the loser would publish a date nothing
    recorded — around midnight, one can commit July 26 while the ref says the
    27th."""
    digest = kitconfig.content_digest("pdf", root=repo)
    real_cas = release._cas_txn
    fired = []

    def racing(ref, payload, old_sha=""):
        if not fired:
            fired.append(True)
            # A concurrent release wins the ref between our read and our write.
            real_cas(ref, release._new_txn("pdf", digest, _at(2026, 7, 26, 10)), "")
        return real_cas(ref, payload, old_sha)

    monkeypatch.setattr(release, "_cas_txn", racing)
    txn = release.open_transaction("pdf", digest, None, now=_at(2026, 7, 27, 3))
    assert release.admission_date(txn["admitted_at"]) == "2026-07-26", \
        "the loser kept its own instant instead of adopting the persisted one"


def test_a_release_cannot_write_into_a_transaction_that_replaced_its_own(repo):
    """CAS proves the ref has not MOVED since it was read; it does not prove what
    is on it is still ours. Without an immutable id, a release whose transaction
    was replaced by a concurrent one writes its own source commit into the
    replacement — and then deletes it on completion."""
    digest = kitconfig.content_digest("pdf", root=repo)
    mine = release.open_transaction("pdf", digest, None, now=_at(2026, 7, 26))

    # A concurrent release moves on to different content, replacing the ref.
    theirs = release.open_transaction("pdf", "aaaaaaaaaaaa", None, now=_at(2026, 7, 27))
    assert theirs["txn_id"] != mine["txn_id"]

    with pytest.raises(SystemExit, match="was replaced while this release was running"):
        release.mark_date_written("pdf", mine["txn_id"])

    # ...and closing must not delete a transaction this release does not own.
    release.close_transaction("pdf", mine["txn_id"])
    still = release._read_txn(release._txn_ref("pdf"))
    assert still is not None and still[1]["txn_id"] == theirs["txn_id"]


@pytest.mark.parametrize("mangle,why", [
    (lambda t: {k: v for k, v in t.items() if k != "digest"}, "missing digest"),
    (lambda t: {**t, "schema_version": 99}, "unknown schema_version"),
    (lambda t: {**t, "artifact": "slides"}, "another artifact's transaction"),
    (lambda t: {**t, "digest": "nope"}, "a digest that is not a closure hash"),
    (lambda t: {**t, "admitted_at": "2026-07-26T12:00:00"}, "a timezone-less instant"),
    (lambda t: {**t, "admitted_at": "whenever"}, "an unparseable instant"),
    (lambda t: {**t, "txn_id": "not-a-uuid"}, "an id that defeats ownership checks"),
    # The sharp one: the predicate asks `is True`, so the STRING "true" answers
    # no and silently switches OFF the hand-set-date guard.
    (lambda t: {**t, "date_written": "true"}, "a non-boolean date_written"),
    (lambda t: {**t, "source_commit": "HEAD"}, "a source_commit that is not a sha"),
])
def test_an_unusable_persisted_transaction_is_refused(repo, mangle, why):
    """The payload's whole job is to be BELIEVED later, so every field a resume
    depends on is checked before it is trusted. The timezone-less case is the
    quiet one: `astimezone` reads a naive datetime as LOCAL time, so the edition
    date would shift by a day depending on where the release ran."""
    digest = kitconfig.content_digest("pdf", root=repo)
    good = release._new_txn("pdf", digest, _at(2026, 7, 26))
    release._cas_txn(release._txn_ref("pdf"), mangle(good), "")
    with pytest.raises(SystemExit, match="is not usable"):
        release.open_transaction("pdf", digest, None, now=_at(2026, 7, 27))


# ----- The predicate ---------------------------------------------------------

def test_an_unchanged_artifact_is_refused(repo, monkeypatch):
    """The date alone cannot make an identical artifact a new edition."""
    closure = kitconfig.artifact_closure_hash("pdf", root=repo)
    monkeypatch.setattr(release, "_last_released",
                        lambda a, s: _stamp("2026-07-26", closure))
    with pytest.raises(SystemExit, match="content is unchanged"):
        release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 27))


def test_a_date_only_edit_cannot_masquerade_as_a_new_edition(repo, monkeypatch):
    """The defect a full-closure comparison has: the date key is INSIDE the
    closure, so hand-editing the date moves the hash without a byte of content
    changing. Normalising the candidate to the last released date closes it."""
    released_at = "2026-07-20"
    released_hash = kitconfig.closure_hash_at_date("pdf", released_at, root=repo)
    release.set_artifact_date("pdf", "2026-07-25")          # ONLY the date moves

    # The naive comparison would now see a different hash and admit.
    assert kitconfig.artifact_closure_hash("pdf", root=repo) != released_hash

    monkeypatch.setattr(release, "_last_released",
                        lambda a, s: _stamp(released_at, released_hash))
    with pytest.raises(SystemExit, match="content is unchanged"):
        release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 25))


def test_two_same_day_releases_are_accepted_with_distinct_identities(repo, monkeypatch):
    """Requiring the date to change would make this impossible, even though the
    two artifacts have different hashes and are therefore different editions."""
    first_hash = kitconfig.closure_hash_at_date("pdf", "2026-07-26", root=repo)
    date1, _ = release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26, 9))

    # Content changes; the last release carried the FIRST identity.
    (repo / "guide.md").write_text("# changed\n", encoding="utf-8")
    monkeypatch.setattr(release, "_last_released",
                        lambda a, s: _stamp(date1, first_hash))
    date2, _ = release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26, 17))

    assert date1 == date2 == "2026-07-26", "same-day releases must both be legal"


def test_a_backwards_date_move_is_refused_and_persists_nothing(repo, monkeypatch):
    monkeypatch.setattr(release, "_last_released",
                        lambda a, s: _stamp("2026-12-01", "ffffffffffff"))
    with pytest.raises(SystemExit, match="must not move backwards"):
        release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26))
    assert release._read_txn(release._txn_ref("pdf")) is None, \
        "a refused release still opened a transaction"


def test_a_transaction_admitted_at_2359_and_completed_at_0001_is_accepted(repo):
    """The case a moving clock gets wrong: validation must use the PERSISTED
    instant, so crossing midnight mid-release is not a failure."""
    date, txn = release.release_predicate(
        "pdf", "probe-guide", now=_at(2026, 7, 26, 23, 59))
    assert date == "2026-07-26"

    release.set_artifact_date("pdf", date)
    release.mark_date_written("pdf", txn["txn_id"])

    # ...completed after midnight. The date key moved, but the transaction is
    # keyed on the date-EXCLUDED digest, so the resume finds its own instant.
    date2, txn2 = release.release_predicate(
        "pdf", "probe-guide", now=_at(2026, 7, 27, 0, 1))
    assert txn2["admitted_at"] == txn["admitted_at"], \
        "the transaction was not resumed across midnight"
    assert txn2["txn_id"] == txn["txn_id"], "a second transaction was opened"
    assert date2 == "2026-07-26", "crossing midnight moved the edition date"


def test_a_next_day_retry_resumes_the_same_transaction(repo):
    digest = kitconfig.content_digest("pdf", root=repo)
    first = release.open_transaction("pdf", digest, None, now=_at(2026, 7, 26, 22))
    # The provider succeeded but the release never completed; the operator
    # retries tomorrow. The SAME digest must resume, not open a new edition.
    retry = release.open_transaction("pdf", digest, None, now=_at(2026, 7, 27, 9))
    assert retry["admitted_at"] == first["admitted_at"]
    assert release.admission_date(retry["admitted_at"]) == "2026-07-26"


def test_a_hand_set_date_disagreeing_with_the_admission_instant_is_refused(repo):
    _, txn = release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26))
    release.mark_date_written("pdf", txn["txn_id"])

    # Someone edits the key by hand. release.py is its sole normal writer, so a
    # value that disagrees means two releases are being conflated.
    release.set_artifact_date("pdf", "2030-01-01")
    with pytest.raises(SystemExit, match="sole writer|disagrees|admitted"):
        release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26))


# ----- Failing CLOSED on a reference that cannot be read ---------------------

def test_an_unreadable_reference_stamp_refuses_rather_than_admitting(repo, monkeypatch):
    """The worst of the failure-open cases. An unreadable stamp used to read as
    "no previous release", which skipped BOTH the freshness comparison and the
    backwards-date check — a reference rendered before a stamp-grammar change
    would then have admitted anything at all."""
    (repo / "probe-guide.pdf").write_bytes(b"%PDF-unreadable")
    monkeypatch.setattr(verify_artifacts, "read_stamp_from_band", lambda p: None)
    with pytest.raises(SystemExit, match="no readable version stamp"):
        release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26))
    assert release._read_txn(release._txn_ref("pdf")) is None


def test_a_reference_that_was_released_and_deleted_refuses(repo):
    (repo / "probe-guide.pdf").write_bytes(b"%PDF-x")
    _git(repo, "add", "probe-guide.pdf")
    _git(repo, "commit", "-q", "-m", "first release")
    (repo / "probe-guide.pdf").unlink()
    with pytest.raises(SystemExit, match="released and is now missing"):
        release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26))


def test_a_shallow_clone_cannot_prove_a_reference_was_never_released(repo, monkeypatch):
    """The other way the deleted-reference check fails open. `git log -- <ref>`
    coming back empty proves "never released" only over COMPLETE history; in a
    shallow clone it equally means "I cannot see far enough back" — and a
    `--depth 1` CI checkout reaches that state first."""
    real_git = release._git

    def shallow(*args, **kw):
        if args[:2] == ("rev-parse", "--is-shallow-repository"):
            return subprocess.CompletedProcess(args, 0, "true\n", "")
        return real_git(*args, **kw)

    monkeypatch.setattr(release, "_git", shallow)
    with pytest.raises(SystemExit, match="SHALLOW"):
        release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26))


def test_an_undeclared_output_is_refused_before_anything_is_opened(tmp_path, monkeypatch):
    """A guide with `pdf = false` carries no `[artifacts.pdf]` table, so the
    authored-date lookup raised a bare KeyError — after the transaction ref had
    already been written."""
    r = _seed(tmp_path)
    monkeypatch.setattr(release, "ROOT", r)
    text = (r / "guide.toml").read_text(encoding="utf-8")
    (r / "guide.toml").write_text(
        text.replace("pdf = true", "pdf = false")
            .replace('site = "none"', 'site = "single"')
            .replace("[artifacts.pdf]", "[artifacts.site]"), encoding="utf-8")

    with pytest.raises(SystemExit, match="does not declare the pdf output"):
        release.release_predicate("pdf", "probe-guide", now=_at(2026, 7, 26))
    assert release._read_txn(release._txn_ref("pdf")) is None


def test_an_artifact_with_no_committed_reference_is_refused(repo):
    """`site` has `reference = None`, so there is no last released identity to
    compare against and every invocation would look like a first release.
    A deployed artifact is published by `deploy.yml`, not admitted here."""
    assert kitconfig.artifact_spec("site").reference is None
    with pytest.raises(SystemExit, match="no committed reference artifact"):
        release.release_predicate("site", "probe-guide", now=_at(2026, 7, 26))


# ----- _ensure_clean_state's widened contract --------------------------------

def test_any_staged_change_is_refused(repo):
    """There is no tool-owned staged path exception. release.py writes the
    WORKTREE and stages afterwards, so its own guide.toml edit is never in the
    index here — and a path-only exemption would admit an operator's unrelated
    staged guide.toml hunk, which the later `git add` folds into the release."""
    release.set_artifact_date("pdf", "2026-08-01")
    _git(repo, "add", "guide.toml")
    with pytest.raises(SystemExit, match="staged changes"):
        release._ensure_clean_state()


def test_a_clean_tree_is_not_an_error(repo):
    """"Is there anything to release?" is the PREDICATE's question. Exiting here
    dead-ended a first release from an already committed tree."""
    assert release._ensure_clean_state() == []


def test_a_site_only_edit_is_in_scope_rather_than_refused(repo):
    """`style-screen.css` is authorable. It was refused as "outside the
    stamp-input set" only while the PDF was the only artifact — which meant an
    edit to it alongside a PDF edit killed the whole release."""
    (repo / "style-screen.css").write_text("body{color:red}\n", encoding="utf-8")
    assert "style-screen.css" in release._ensure_clean_state()


def test_a_genuinely_unrelated_file_is_still_out_of_scope(repo):
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="outside the authorable set"):
        release._ensure_clean_state()


def test_scope_follows_the_configured_slide_source(tmp_path, monkeypatch):
    """With `[slides] file = "deck.md"`, deck.md is the real closure input. Scoped
    against the schema DEFAULT instead, an edit to it is refused as out of scope
    while an edit to the unused `slides.md` is admitted — exactly backwards."""
    r = _seed(tmp_path, slides_file="deck.md")
    monkeypatch.setattr(release, "ROOT", r)
    cfg = kitconfig.load(r)

    (r / "deck.md").write_text("# deck\n", encoding="utf-8")
    assert "deck.md" in release._ensure_clean_state(cfg)

    (r / "deck.md").unlink()
    (r / "slides.md").write_text("# unused\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="outside the authorable set"):
        release._ensure_clean_state(cfg)


@pytest.mark.parametrize("authored", ["./deck.md", "slides//deck.md", "deck.md"])
def test_scope_matches_the_path_spelling_git_reports(tmp_path, monkeypatch, authored):
    """git reports paths in exactly ONE spelling. `./deck.md` passes every
    validation check and is a perfectly good TOML value, but compared literally
    against git's `deck.md` it matches nothing — so the guide's real slide source
    would be refused as out of scope. The stored value is normalised."""
    want = authored.replace("./", "").replace("//", "/")
    r = _seed(tmp_path, slides_file=authored)
    monkeypatch.setattr(release, "ROOT", r)
    cfg = kitconfig.load(r)
    assert cfg.slides.file == want

    (r / want).parent.mkdir(parents=True, exist_ok=True)
    (r / want).write_text("# deck\n", encoding="utf-8")
    assert want in release._ensure_clean_state(cfg)


def test_a_globbed_slide_source_is_rejected(tmp_path):
    """`deck*.md` would be expanded as a PATTERN by the closure resolver while
    every membership predicate compared the literal string — one value, two
    meanings."""
    r = _seed(tmp_path, slides_file="deck*.md")
    with pytest.raises(kitconfig.KitConfigError, match="must name ONE file"):
        kitconfig.load(r)


# ----- The date edit itself --------------------------------------------------

def test_set_artifact_date_rewrites_a_single_quoted_value(repo):
    """`date = '2026-07-25'` is valid TOML. A rewrite that only handles double
    quotes matches the key, misses the value, and reports "unchanged" — after
    which the release publishes under a date the file never held."""
    text = (repo / "guide.toml").read_text(encoding="utf-8")
    (repo / "guide.toml").write_text(
        text.replace('date = "2026-07-26"', "date = '2026-07-25'"), encoding="utf-8")

    assert release.set_artifact_date("pdf", "2026-09-09") is True
    assert kitconfig.load(repo).artifacts["pdf"].date == "2026-09-09"


def test_set_artifact_date_rewrites_only_its_own_table(repo):
    (repo / "guide.toml").write_text(
        (repo / "guide.toml").read_text(encoding="utf-8")
        .replace('site = "none"', 'site = "single"')
        + '[artifacts.site]\ndate = "2020-01-01"\n', encoding="utf-8")

    release.set_artifact_date("pdf", "2026-09-09")
    cfg = kitconfig.load(repo)
    assert cfg.artifacts["pdf"].date == "2026-09-09"
    assert cfg.artifacts["site"].date == "2020-01-01", "the site's date was touched"


def test_set_artifact_date_preserves_comments_and_actually_writes(repo):
    original = (repo / "guide.toml").read_text(encoding="utf-8")
    (repo / "guide.toml").write_text(
        original
        .replace("[artifacts.pdf]", "# a comment that must survive\n[artifacts.pdf]")
        .replace('date = "2026-07-26"', 'date = "2026-07-26"  # trailing note'),
        encoding="utf-8")

    assert release.set_artifact_date("pdf", "2026-09-09") is True
    written = (repo / "guide.toml").read_text(encoding="utf-8")
    assert "a comment that must survive" in written
    assert "# trailing note" in written
    # The EFFECT is the point, not the comments: asserting only the comments
    # leaves this green when the setter silently does nothing.
    assert kitconfig.load(repo).artifacts["pdf"].date == "2026-09-09"


def test_set_artifact_date_reports_no_change_when_the_date_already_matches(repo):
    assert release.set_artifact_date("pdf", "2026-07-26") is False
    assert kitconfig.load(repo).artifacts["pdf"].date == "2026-07-26"


def test_set_artifact_date_refuses_syntax_it_cannot_rewrite(repo):
    text = (repo / "guide.toml").read_text(encoding="utf-8")
    (repo / "guide.toml").write_text(
        text.replace('date = "2026-07-26"', 'date = """2026-07-26"""'), encoding="utf-8")
    with pytest.raises(SystemExit, match="not a single-line quoted string"):
        release.set_artifact_date("pdf", "2026-09-09")


def test_set_artifact_date_refuses_a_missing_key(repo):
    text = (repo / "guide.toml").read_text(encoding="utf-8")
    (repo / "guide.toml").write_text(
        text.replace('date = "2026-07-26"', ""), encoding="utf-8")
    with pytest.raises(SystemExit, match="no date key found"):
        release.set_artifact_date("pdf", "2026-09-09")


def test_set_artifact_date_refuses_to_write_over_a_concurrent_edit(repo, monkeypatch):
    """The snapshot taken at the top of the write is stale by the time the file is
    replaced. Writing it back regardless silently erases whatever someone changed
    in between — a key this function never looked at and the reload never checks."""
    original = (repo / "guide.toml").read_text(encoding="utf-8")
    real_locate = release.locate_date_line

    def meddle(text, artifact, date):
        got = real_locate(text, artifact, date)
        (repo / "guide.toml").write_text(
            original.replace('KEYWORDS = "k"', 'KEYWORDS = "edited elsewhere"'),
            encoding="utf-8")
        return got

    monkeypatch.setattr(release, "locate_date_line", meddle)
    with pytest.raises(SystemExit, match="changed while the edition date was being written"):
        release.set_artifact_date("pdf", "2026-09-09")
    assert "edited elsewhere" in (repo / "guide.toml").read_text(encoding="utf-8")


def test_set_artifact_date_restores_the_file_if_the_write_broke_the_toml(repo, monkeypatch):
    """The textual rewrite and the validated config are two different things, so
    the write is proved by RELOADING guide.toml. A rewrite that leaves the file
    unparseable must put it back rather than leave the guide unbuildable."""
    original = (repo / "guide.toml").read_text(encoding="utf-8")
    monkeypatch.setattr(release, "_split_quoted_value",
                        lambda rest: (" ", '"x"', " ]["))   # trailing garbage
    with pytest.raises(SystemExit, match="unusable"):
        release.set_artifact_date("pdf", "2026-09-09")
    assert (repo / "guide.toml").read_text(encoding="utf-8") == original


def test_set_artifact_date_restores_the_file_if_the_effective_date_disagrees(repo, monkeypatch):
    """The other half of the same guard: the file parses, but the key does not
    read back as the value assigned. A date the release is about to stamp into an
    artifact must never be one guide.toml does not actually carry."""
    original = (repo / "guide.toml").read_text(encoding="utf-8")

    class _Lying:
        artifacts = {"pdf": type("A", (), {"date": "1999-01-01"})()}

    monkeypatch.setattr(kitconfig, "load", lambda root=None: _Lying())
    with pytest.raises(SystemExit, match=r"reads '1999-01-01'"):
        release.set_artifact_date("pdf", "2026-09-09")
    assert (repo / "guide.toml").read_text(encoding="utf-8") == original


# ----- main(): refuse before mutating, and the states that must not dead-end --

def test_a_refusal_leaves_the_tree_and_the_refs_untouched(repo, monkeypatch):
    """The clean-state check used to run AFTER the date was written and the
    transaction opened, so a refusal left both mutated while the code's own
    comment claimed the tree was as the operator left it."""
    (repo / "guide.md").write_text("# edited\n", encoding="utf-8")
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
    original = (repo / "guide.toml").read_text(encoding="utf-8")

    with pytest.raises(SystemExit, match="outside the authorable set"):
        _run_main(repo, monkeypatch, "should not run")

    assert (repo / "guide.toml").read_text(encoding="utf-8") == original
    assert release._read_txn(release._txn_ref("pdf")) is None
    assert _subjects(repo) == ["init"]
    assert not (repo / "probe-guide.pdf").exists()


def test_a_writer_constraint_refuses_before_the_transaction_is_opened(repo, monkeypatch):
    """`[artifacts."pdf"]` is valid TOML and loads fine, so a config that
    validates is not evidence the date key can be rewritten. Discovering that
    only after the predicate ran left an abandoned transaction ref behind."""
    (repo / "guide.md").write_text("# edited\n", encoding="utf-8")
    text = (repo / "guide.toml").read_text(encoding="utf-8")
    (repo / "guide.toml").write_text(
        text.replace("[artifacts.pdf]", '[artifacts."pdf"]'), encoding="utf-8")

    with pytest.raises(SystemExit, match="no date key found"):
        _run_main(repo, monkeypatch, "should not run")
    assert release._read_txn(release._txn_ref("pdf")) is None
    assert _subjects(repo) == ["init"]


def test_content_changing_mid_release_is_refused_by_identity_not_by_name(repo, monkeypatch):
    """A source file edited again after admission keeps its path, so comparing
    sets of names sees nothing while the bytes about to be committed are no
    longer the bytes the transaction was admitted for."""
    (repo / "guide.md").write_text("# first\n", encoding="utf-8")
    original_toml = (repo / "guide.toml").read_text(encoding="utf-8")
    real_set = release.set_artifact_date

    def meddle(artifact, date):
        got = real_set(artifact, date)
        (repo / "guide.md").write_text("# second\n", encoding="utf-8")
        return got

    monkeypatch.setattr(release, "set_artifact_date", meddle)
    with pytest.raises(SystemExit, match="content changed while the release was being prepared"):
        _run_main(repo, monkeypatch, "should not run")

    # Refused, and both durable mutations rolled back.
    assert (repo / "guide.toml").read_text(encoding="utf-8") == original_toml
    assert release._read_txn(release._txn_ref("pdf")) is None
    assert _subjects(repo) == ["init"]


def test_a_refused_write_does_not_erase_the_edit_it_refused_over(repo, monkeypatch):
    """The rollback can itself be the data loss. `set_artifact_date` refuses
    PRECISELY when it finds someone else's edit — so a handler that restores the
    preflight snapshot regardless erases the very edit that refusal protected."""
    real_set = release.set_artifact_date

    def meddle(artifact, date):
        (repo / "guide.toml").write_text(
            (repo / "guide.toml").read_text(encoding="utf-8")
            .replace('KEYWORDS = "k"', 'KEYWORDS = "edited elsewhere"'),
            encoding="utf-8")
        return real_set(artifact, date)

    # Force the date to actually MOVE, deterministically. This test used to
    # inherit the fixture's `date = "2026-07-26"`, so on that one day the write
    # took the "already current" early return and the test passed WITHOUT ever
    # reaching the rollback it is about — and on every other day it took the path
    # that does. It passed the afternoon it was written and went red the next
    # morning, which is how the underlying data loss surfaced at all.
    toml = repo / "guide.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('date = "2026-07-26"',
                                                 'date = "2000-01-01"'),
        encoding="utf-8")
    (repo / "guide.md").write_text("# changed\n", encoding="utf-8")
    monkeypatch.setattr(release, "set_artifact_date", meddle)
    with pytest.raises(SystemExit):
        _run_main(repo, monkeypatch, "should not run")

    assert "edited elsewhere" in (repo / "guide.toml").read_text(encoding="utf-8"), \
        "the rollback erased a concurrent edit"


def test_rollback_never_deletes_another_releases_transaction(repo, monkeypatch):
    """A refusal tidies up after ITSELF. If a concurrent release has already
    replaced our transaction, deleting the ref destroys that release's in-flight
    state — one process cleaning up by wrecking another's."""
    digest = kitconfig.content_digest("pdf", root=repo)
    mine = release._new_txn("pdf", digest, _at(2026, 7, 26))
    theirs = release._new_txn("pdf", "aaaaaaaaaaaa", _at(2026, 7, 27))
    release._cas_txn(release._txn_ref("pdf"), theirs, "")

    # We opened `mine`, but the ref now holds `theirs`.
    release._restore_txn("pdf", None, mine["txn_id"])
    still = release._read_txn(release._txn_ref("pdf"))
    assert still is not None and still[1]["txn_id"] == theirs["txn_id"], \
        "the rollback deleted a transaction it did not own"

    # ...and it DOES clean up its own.
    release._cas_txn(release._txn_ref("pdf"), mine, still[0])
    release._restore_txn("pdf", None, mine["txn_id"])
    assert release._read_txn(release._txn_ref("pdf")) is None


def test_a_failed_source_commit_leaves_the_index_clean(repo, monkeypatch):
    """A rejecting pre-commit hook after `git add` succeeded used to leave the
    authorable files staged, so the next invocation exited at the staged-index
    preflight instead of resuming — the documented retry refusing this run's own
    residue."""
    (repo / "guide.md").write_text("# changed\n", encoding="utf-8")
    real_git = release._git

    def failing(*args, **kw):
        if args[0] == "commit":
            raise subprocess.CalledProcessError(1, "git commit")
        return real_git(*args, **kw)

    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "release"])
    monkeypatch.setattr(release, "_git", failing)
    with pytest.raises(subprocess.CalledProcessError):
        release.main()
    monkeypatch.setattr(release, "_git", real_git)

    assert _subjects(repo) == ["init"]
    # Nothing staged — so the retry reaches the predicate rather than bouncing
    # off its own leftovers at the staged-index check.
    staged = [p for code, p in release._porcelain() if code[0] not in (" ", "?")]
    assert staged == [], f"the failed commit left the index dirty: {staged}"
    assert "guide.md" in release._ensure_clean_state()


def test_an_abandoned_promotion_is_discarded_on_the_next_run(repo, monkeypatch):
    """A process killed between the promotion and its commit leaves the reference
    in the tree. It is not authorable, so the preflight would refuse it and the
    retry would dead-end on this tool's own leftovers."""
    (repo / "guide.md").write_text("# changed\n", encoding="utf-8")
    # Stand in for the killed run: an open transaction plus a promoted reference.
    release.open_transaction("pdf", kitconfig.content_digest("pdf", root=repo),
                             None, now=_at(2026, 7, 26))
    (repo / "probe-guide.pdf").write_bytes(b"%PDF-half-written")

    assert _run_main(repo, monkeypatch, "release") == 0
    assert (repo / "probe-guide.pdf").read_bytes() == b"%PDF-fake-render", \
        "the abandoned promotion was published instead of being discarded"


def test_content_changing_between_staging_and_commit_is_refused(repo, monkeypatch):
    """The window a check placed BEFORE `git add` does not bound: at that point
    the digest was compared against a worktree git had not yet read. A source
    file changed between the add and the commit keeps its path, so the name
    comparison sees nothing and the newer bytes are what get committed."""
    (repo / "guide.md").write_text("# first\n", encoding="utf-8")
    real_git = release._git

    def meddling(*args, **kw):
        got = real_git(*args, **kw)
        if args[0] == "add":
            (repo / "guide.md").write_text("# second\n", encoding="utf-8")
        return got

    monkeypatch.setattr(release, "_git", meddling)
    with pytest.raises(SystemExit, match="changed as it was being staged"):
        _run_main(repo, monkeypatch, "should not run")
    monkeypatch.setattr(release, "_git", real_git)

    assert _subjects(repo) == ["init"], "the mismatched content was committed"
    staged = [p for code, p in release._porcelain() if code[0] not in (" ", "?")]
    assert staged == [], f"the refusal left the index dirty: {staged}"


def test_a_promotion_whose_commit_fails_leaves_no_residue(repo, monkeypatch):
    """A reference copied to the repo root but never committed is out-of-scope
    residue that the next run's preflight would refuse — turning the documented
    retry into a dead end."""
    (repo / "guide.md").write_text("# changed\n", encoding="utf-8")
    real_git = release._git

    def failing(*args, **kw):
        if args[0] == "add" and args[1] == "probe-guide.pdf":
            raise RuntimeError("index is locked")
        return real_git(*args, **kw)

    def _stub_build():
        (repo / "build").mkdir(exist_ok=True)
        (repo / "build" / "probe-guide.pdf").write_bytes(b"%PDF-fake-render")

    monkeypatch.setattr(release, "_build", _stub_build)
    monkeypatch.setattr(verify_artifacts, "promotable_stamp",
                        lambda w, r, a="pdf": (True, "stubbed"))
    # Same reason as the line above: these tests exercise the release TRANSACTION
    # against a stub PDF, not a real render, so the document-level check has
    # nothing valid to read. Its own coverage is tests/test_promotion_smokes.py
    # (it is called, and before the copy) and tests/test_smoke_check.py (what it
    # rejects). Stubbing it here keeps this file about the protocol.
    monkeypatch.setattr(verify_artifacts, "smoke_check",
                        lambda p, r=None, artifact="pdf": 0)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "release"])
    monkeypatch.setattr(release, "_git", failing)
    with pytest.raises(RuntimeError):
        release.main()
    monkeypatch.setattr(release, "_git", real_git)

    assert not (repo / "probe-guide.pdf").exists(), "the promoted reference was left behind"
    assert release._ensure_clean_state() == [], "the next preflight would refuse"


def test_a_commit_landing_mid_release_is_not_mistaken_for_our_own(repo):
    """`git rev-parse HEAD` after `git commit` is not proof the commit is ours:
    another process moving the branch in that gap hands us someone else's commit,
    which the amend step would then rewrite."""
    parent = release._head()
    (repo / "guide.md").write_text("# a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "ours")
    head, tree = release._head(), release._tree_of(release._head())

    # Parent AND tree both match — this really is our commit.
    assert release._commit_we_just_made(parent, tree) == head

    # Stacked on top of ours: the parent no longer matches.
    with pytest.raises(SystemExit, match="branch moved"):
        release._commit_we_just_made("0" * 40, tree)

    # The case the parent check alone misses — a SIBLING: the branch rewound to
    # our parent and re-committed with different content. Same parent, so only
    # the tree tells them apart.
    _git(repo, "reset", "-q", "--hard", parent)
    (repo / "guide.md").write_text("# theirs\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "theirs")
    sibling = release._head()
    assert release._parent_of(sibling) == parent, "the fixture did not build a sibling"
    with pytest.raises(SystemExit, match="branch moved"):
        release._commit_we_just_made(parent, tree)


def test_a_first_release_from_a_clean_tree_proceeds(tmp_path, monkeypatch):
    """Everything is committed and the authored date already equals the admission
    date, so nothing in the tree changes. The old flow exited with "no changes to
    commit" and a first release was therefore impossible."""
    r = _seed(tmp_path, date=_today())
    monkeypatch.setattr(release, "ROOT", r)

    assert _run_main(r, monkeypatch, "first release") == 0
    assert (r / "probe-guide.pdf").read_bytes() == b"%PDF-fake-render"
    assert _subjects(r) == ["first release", "init"]
    tracked = subprocess.run(["git", "ls-files"], cwd=r, check=True,
                             capture_output=True, text=True).stdout.split()
    assert "probe-guide.pdf" in tracked


def test_a_retry_after_a_failed_build_resumes_into_the_same_commit(repo, monkeypatch):
    """The source commit is preserved on failure, which leaves the tree clean —
    the state the old flow dead-ended in. The retry must resume the SAME
    transaction and amend into that SAME commit, not start over."""
    (repo / "guide.md").write_text("# changed\n", encoding="utf-8")

    def _boom():
        raise RuntimeError("render died")

    monkeypatch.setattr(release, "_build", _boom)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "release"])
    with pytest.raises(RuntimeError):
        release.main()

    assert _subjects(repo) == ["release", "init"], "the source commit was not preserved"
    txn = release._read_txn(release._txn_ref("pdf"))
    assert txn is not None, "the transaction did not survive the failure"
    admitted = txn[1]["admitted_at"]

    assert _run_main(repo, monkeypatch, "release") == 0
    assert _subjects(repo) == ["release", "init"], "the retry added a second commit"
    changed = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"],
                             cwd=repo, check=True, capture_output=True,
                             text=True).stdout.split()
    assert "probe-guide.pdf" in changed and "guide.md" in changed
    assert release.admission_date(admitted) == kitconfig.load(repo).artifacts["pdf"].date


def test_completing_a_release_closes_the_transaction(repo, monkeypatch):
    """An open transaction that outlives its release would resurrect its instant
    the next time the same content came round — a legitimate revert to an older
    edition would then be refused as a backwards date."""
    (repo / "guide.md").write_text("# changed\n", encoding="utf-8")
    assert _run_main(repo, monkeypatch, "release") == 0
    assert release._read_txn(release._txn_ref("pdf")) is None


def test_the_release_never_amends_a_commit_it_did_not_make(repo, monkeypatch):
    """A transaction whose recorded source commit is no longer HEAD must not
    rewrite whatever is there instead — that commit belongs to the operator."""
    (repo / "guide.md").write_text("# changed\n", encoding="utf-8")

    def _boom():
        raise RuntimeError("render died")

    monkeypatch.setattr(release, "_build", _boom)
    monkeypatch.setattr(sys, "argv", ["release.py", "-m", "release"])
    with pytest.raises(RuntimeError):
        release.main()

    # The operator commits something else on top before retrying.
    (repo / "README.md").write_text("notes\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "unrelated")

    assert _run_main(repo, monkeypatch, "release") == 0
    assert _subjects(repo) == ["release", "unrelated", "release", "init"]
    changed = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"],
                             cwd=repo, check=True, capture_output=True,
                             text=True).stdout.split()
    assert changed == ["probe-guide.pdf"], "the operator's commit was rewritten"
