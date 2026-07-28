#!/usr/bin/env python3
"""Automate the source-commit + baseline + amend dance.

Replaces the 5-step "After editing" ritual from CLAUDE.md with one command:

    pixi run python release.py -m "Your commit message"
    # or, equivalently:
    make release MSG="Your commit message"

What it does (and refuses to do):

  1. Reads OUTPUT_SLUG and the authorable source set from guide.toml via
     kitconfig (the single validated source of truth — no scraping build.py).
     That set is every artifact's inputs plus the bundled font faces.
  2. PREFLIGHT, entirely read-only: refuses if the index has staged changes
     (they would be silently folded into the release commit) or the working
     tree has modifications outside the authorable set (they would either be
     lost or unexpectedly committed). Use plain `git commit` for those first.
  3. ADMITS the release, or refuses (the edition-date predicate). The
     artifact's CONTENT must differ from the last released identity, and the
     date it will carry is the transaction's admission instant — captured once
     and persisted, never re-read from a moving clock.
  4. Writes `[artifacts.<name>] date`, then re-checks that the date edit is the
     only thing that appeared. release.py is the sole normal writer of that key
     and writes it BEFORE the source commit, so the later `--amend` cannot
     perturb it.
  5. Stages the authorable changes and creates the source commit. A tree with
     nothing to stage is still releasable — a first release from an already
     committed tree, or a retry after a failed build — and simply skips this.
  6. Re-renders the PDF — the version stamp is now clean because the source
     files are committed.
  7. Promotes build/<slug>.pdf to <slug>.pdf at the repo root (the committed
     reference that readers download from GitHub).
  8. Stages <slug>.pdf and amends it into the source commit — but ONLY into a
     commit release.py itself made for this transaction. Otherwise it lands in
     its own commit, because rewriting a commit release.py does not own is not
     something a release tool may do silently.
  9. Closes the transaction.

If any post-commit step fails, the source commit is preserved; re-running
resumes the SAME transaction (same date, same instant) and amends into that
same commit.

SCOPE: this admits an artifact that HAS a committed reference — the PDF and the
deck. The site has none by construction (it is deployed, not blessed into the
repo), so there is no last released identity to prove freshness against and
every invocation would look like a first release. `release_predicate` refuses it
by name rather than pretending every deployment is one.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import kitconfig
import verify_artifacts

ROOT = Path(__file__).parent.resolve()

# The artifact this command publishes. `--artifact` is a REAL flag again, and
# what changed is not the predicate — the predicate always worked. The flag was
# removed once, because the build, the promotable check and the promotion all
# still targeted the PDF, so selecting `slides` created the source commit and then
# validated `build/<slug>.pdf` against the wrong closure: half-wiring, which is
# worse than no wiring because it fails after mutating the tree.
#
# All four now resolve per artifact — `_build`, `_promote_to_reference` and
# `_restore_reference` take the artifact, `promotable_stamp` takes it, and
# `ArtifactSpec.reference` names the file. An artifact with NO reference (the
# site, which is deployed rather than blessed) is refused up front rather than
# silently treated as the PDF.
#
# The default stays "pdf", so every existing invocation of `make release` means
# exactly what it did before.
ARTIFACT = "pdf"


def _git(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check,
        capture_output=capture, text=capture,
        encoding="utf-8" if capture else None,
    )


def _head() -> str | None:
    """HEAD's sha, or None on an unborn branch (a repository with no commits)."""
    got = _git("rev-parse", "--verify", "--quiet", "HEAD", capture=True, check=False)
    return got.stdout.strip() or None


def _parent_of(commit: str) -> str | None:
    got = _git("rev-parse", "--verify", "--quiet", f"{commit}^", capture=True, check=False)
    return got.stdout.strip() or None


def _atomic_write(path: Path, text: str) -> None:
    """Replace `path`'s contents in one step.

    `write_text` truncates and then writes, so a crash — or a full disk — between
    the two leaves the file empty or half-written. For guide.toml that is the
    guide's entire configuration, destroyed by a release that was only trying to
    move a date by one day.

    The temporary name is UNIQUE, not derived from the target: a fixed
    `.release-tmp` is a shared name, so two writers would interleave in one
    scratch file and `os.replace` would publish whichever half won."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".release-tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _atomic_copy(src: Path, dst: Path) -> None:
    """Publish `src` at `dst` in one step — same reason as `_atomic_write`.

    `shutil.copyfile` truncates the destination and then streams into it, so a
    crash midway leaves a PARTIAL reference PDF in the tree: a deliverable that
    exists, is the wrong size, and no longer matches anything."""
    fd, tmp = tempfile.mkstemp(dir=str(dst.parent), prefix=dst.name + ".",
                               suffix=".release-tmp")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _porcelain() -> list[tuple[str, str]]:
    """Return [(status_code, path), ...] for every changed/untracked entry.
    status_code is the 2-char `git status --porcelain` prefix.

    `-z` because the default output QUOTES any path containing a space or a
    non-ASCII character — `"fonts/My Font.ttf"`, with the quotes as literal
    characters. That string then matches nothing: `_ensure_clean_state()`
    compares it against `kitconfig.is_stamp_input()`, decides a legitimate font
    change is out of scope, and refuses the release. `-z` turns quoting off and
    NUL-terminates each record instead.

    The rename skip is the part that is easy to get wrong. Under `-z` a rename
    or copy emits TWO NUL-terminated fields — the new path, then the origin —
    where the default format packs both into one line as `new -> old`. Without
    consuming that second field, the origin path is read back as an entry in its
    own right, and a rename inside SOURCE_FILES would stage a path that no
    longer exists.

    `-uall` because git otherwise COLLAPSES a wholly-untracked directory to the
    directory itself — a new `slides/deck.md` is reported as `slides/`, which is
    not a path any membership predicate can classify. It would be refused as out
    of scope naming a DIRECTORY rather than the file, so a legitimate new source
    in a new directory could never be released and the diagnostic would not say
    which file was the problem."""
    out = _git("status", "--porcelain", "-z", "-uall", capture=True).stdout
    rows: list[tuple[str, str]] = []
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        rec = fields[i]
        i += 1
        if len(rec) < 4:
            continue
        code, path = rec[:2], rec[3:]
        if code[0] in ("R", "C"):
            i += 1  # consume the origin path that follows a rename/copy
        rows.append((code, path))
    return rows


def _ensure_clean_state(cfg: "kitconfig.KitConfig | None" = None) -> list[str]:
    """Refuse to run with a dirty INDEX or with modifications outside the
    AUTHORABLE set. Returns the changed authorable paths, possibly EMPTY.

    Three changes from the original contract:

    * Scope is `kitconfig.is_authorable`, the union across artifacts, not
      `is_stamp_input`, which is the PDF's closure alone. A site-only edit
      (`style-screen.css`) is a releasable change; refusing it as "outside the
      stamp-input set" was correct only while the PDF was the only artifact.
      `cfg` is passed through so the union resolves against THIS guide's
      `[slides] file`, not the schema default.
    * It no longer exits when the tree is clean. "Is there anything to release?"
      is the PREDICATE's question, answered against the last released identity;
      a clean tree whose committed content has never been released is a
      legitimate first release, and exiting here dead-ended it.
    * The index must be entirely clean — there is no staged-path exception. An
      earlier draft admitted a staged `guide.toml` on the grounds that release.py
      writes that file itself, which was both unnecessary (it writes the WORKTREE
      and stages afterwards, so its own edit is never in the index when this
      runs) and unsafe: a path-only exemption admits an operator's unrelated
      staged `guide.toml` hunk, which the later `git add` then folds into the
      release."""
    status = _porcelain()

    staged = [p for code, p in status if code[0] not in (" ", "?")]
    if staged:
        sys.exit(
            "release.py: index has staged changes:\n  "
            + "\n  ".join(staged)
            + "\nUnstage them (`git reset HEAD <file>`) and re-run, or commit them\n"
            "with plain `git commit` first if they're unrelated to this release."
        )

    out_of_scope = [
        p for code, p in status
        if not kitconfig.is_authorable(p, cfg)
    ]
    if out_of_scope:
        sys.exit(
            "release.py: working tree has changes outside the authorable set:\n  "
            + "\n  ".join(out_of_scope)
            + "\nCommit (or revert) them with plain git first. release.py only\n"
            "stages authorable sources (every artifact's inputs, plus the fonts)."
        )

    return [p for _, p in status if kitconfig.is_authorable(p, cfg)]


# ---------------------------------------------------------------------------
# The release transaction: one captured admission instant
#
# WHERE THE INSTANT LIVES, and why. The UTC instant must be captured
# ONCE when a transaction is created and persisted with the digest, so that every
# retry, resume and rebuild validates against the SAME value rather than
# re-reading a moving clock. It needs a home that survives a failed build, an
# interrupted run and a retry the next day, without touching the working tree.
#
# CHOSEN: a git ref in the same `refs/guide-kit/` namespace, one per ARTIFACT,
# pointing at a blob holding the open transaction's JSON. A ref sits outside
# `refs/heads` and `refs/tags`, so it never changes HEAD, never dirties the
# working tree and never perturbs a tag — the same three properties required as
# its reasons for putting the journal on a ref. It survives across invocations
# and across a `make release` that fails halfway, which is exactly the retry case
# the instant exists to serve. When the journal lands, this state is already in
# its namespace and folds in as an entry.
#
# ONE REF PER ARTIFACT, NOT PER CONTENT DIGEST, and that is a lifecycle decision
# rather than a naming one. A per-digest ref is permanent and has no lifecycle:
# release content A, then B, then legitimately revert to A, and A's ORIGINAL
# admission instant is resurrected months later — the backwards-date check then
# refuses a perfectly good release. A single "currently open transaction" is
# replaced when the content moves on and DELETED when a release completes, so
# only a genuinely open transaction can ever be resumed. The digest lives INSIDE
# the payload and is what decides whether a resume is this content's.
#
# REJECTED — a committed transaction file in the working tree. It would have to
# be special-cased by `_ensure_clean_state` (which refuses staged changes and
# out-of-scope modifications), adding a second exception beside the date edit,
# and it would either be committed into the release or need deleting on every
# exit path including the failing ones.
#
# REJECTED — deriving the instant from the tag's own commit date at verification
# time, persisting nothing. Simplest, but it cannot answer the question the
# admission instant exists to answer: whether the date was chosen BEFORE the
# source commit. It also has nothing to read on the first transition, when no tag
# exists yet.

_TXN_NAMESPACE = "refs/guide-kit/release-txn"
_TXN_SCHEMA_VERSION = 1
_DIGEST_RE = re.compile(r"[0-9a-f]{12}")
_TXN_ID_RE = re.compile(r"[0-9a-f]{32}")
_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _txn_ref(artifact: str) -> str:
    """The ref holding `artifact`'s one open transaction, if any."""
    return f"{_TXN_NAMESPACE}/{artifact}"


def _read_txn(ref: str) -> tuple[str, dict] | None:
    """(blob sha, payload) for whatever is on `ref`, or None when absent.

    RAW — the payload is not validated here. `_load_txn` is the checked reader
    every decision goes through; this one exists for the writes that only need
    the sha to compare against."""
    sha = _git("rev-parse", "--verify", "--quiet", ref,
               capture=True, check=False).stdout.strip()
    if not sha:
        return None
    got = _git("cat-file", "-p", sha, capture=True, check=False)
    if got.returncode != 0 or not got.stdout.strip():
        return None
    try:
        payload = json.loads(got.stdout)
    except json.JSONDecodeError:
        sys.exit(f"release.py: transaction ref {ref} holds unreadable JSON.")
    if not isinstance(payload, dict):
        sys.exit(f"release.py: transaction ref {ref} does not hold a JSON object.")
    return sha, payload


def _load_txn(artifact: str) -> tuple[str, dict] | None:
    """The open transaction for `artifact`, VALIDATED, or None when there is none.

    Every field a resume depends on is checked before it is trusted, because the
    payload's whole job is to be believed later: a missing key crashes mid-release,
    a mismatched artifact resumes someone else's transaction, an unknown
    `schema_version` means a newer release.py wrote a shape this one is about to
    misread, and a TIMEZONE-LESS `admitted_at` is the quiet one — `astimezone`
    reads a naive datetime as LOCAL time, so the edition date would shift by a day
    depending on where the release ran, which is the exact defect UTC was chosen to
    prevent. An invalid payload is a refusal, not a silent replacement: it means
    something is wrong that an operator should look at."""
    ref = _txn_ref(artifact)
    found = _read_txn(ref)
    if found is None:
        return None
    sha, txn = found

    def bad(why: str) -> None:
        sys.exit(
            f"release.py: the release transaction on {ref} is not usable ({why}). "
            f"Inspect it with `git cat-file -p {ref}`; delete it with "
            f"`git update-ref -d {ref}` once you are satisfied nothing is in flight."
        )

    missing = [k for k in ("schema_version", "txn_id", "artifact", "digest",
                           "admitted_at") if k not in txn]
    if missing:
        bad(f"missing {', '.join(missing)}")
    if txn["schema_version"] != _TXN_SCHEMA_VERSION:
        bad(f"schema_version {txn['schema_version']!r} != {_TXN_SCHEMA_VERSION}")
    if txn["artifact"] != artifact:
        bad(f"it belongs to {txn['artifact']!r}, not {artifact!r}")
    if not isinstance(txn["digest"], str) or not _DIGEST_RE.fullmatch(txn["digest"]):
        bad(f"digest {txn['digest']!r} is not a 12-character closure hash")
    if not isinstance(txn["txn_id"], str) or not _TXN_ID_RE.fullmatch(txn["txn_id"]):
        bad(f"txn_id {txn['txn_id']!r} is not a uuid4 hex string")
    try:
        moment = datetime.datetime.fromisoformat(txn["admitted_at"])
    except (TypeError, ValueError):
        moment = None
        bad(f"admitted_at {txn['admitted_at']!r} is not an ISO-8601 instant")
    if moment is not None and moment.utcoffset() is None:
        bad(f"admitted_at {txn['admitted_at']!r} carries no timezone")
    # The OPTIONAL fields are checked too, because they are trusted later exactly
    # as the required ones are. `date_written` is the sharp one: the predicate
    # asks `is True`, so a payload carrying the STRING "true" silently answers no
    # and the hand-set-date disagreement check never fires — a crafted ref that
    # switches off a guard rather than tripping one.
    if "date_written" in txn and not isinstance(txn["date_written"], bool):
        bad(f"date_written {txn['date_written']!r} is not a boolean")
    if "source_commit" in txn and (
            not isinstance(txn["source_commit"], str)
            or not _SHA_RE.fullmatch(txn["source_commit"])):
        bad(f"source_commit {txn['source_commit']!r} is not a commit sha")
    return sha, txn


def _blob(payload: dict) -> str:
    return subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=ROOT,
        input=json.dumps(payload, indent=2, sort_keys=True),
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip()


def _cas_ref(ref: str, new_sha: str, old_sha: str = "") -> bool:
    """Compare-and-swap `ref` from `old_sha` to `new_sha`. False when we lost.

    `git update-ref <ref> <new> <old>` takes the ref lock and verifies the old
    value under it; an EMPTY <old> asserts the ref did not exist. Without the
    CAS, two concurrent releases both observe a missing ref, both pick their own
    instant, and both proceed — only the last writer's instant is persisted, so
    around midnight one process can commit July 26 while the ref records July 27
    and the resume path then disagrees with the artifact it published."""
    return _git("update-ref", ref, new_sha, old_sha,
                capture=True, check=False).returncode == 0


def _cas_txn(ref: str, payload: dict, old_sha: str = "") -> bool:
    return _cas_ref(ref, _blob(payload), old_sha)


def _delete_txn(ref: str, old_sha: str) -> bool:
    """Close the transaction. CAS again, so a concurrent replacement survives."""
    return _git("update-ref", "-d", ref, old_sha,
                capture=True, check=False).returncode == 0


def admission_date(admitted_at: str) -> str:
    """The UTC calendar date of an admission instant — the value the artifact's
    `date` key must carry. UTC, not local: the release predicate must give the
    same answer wherever it runs."""
    return datetime.datetime.fromisoformat(admitted_at).astimezone(
        datetime.timezone.utc
    ).date().isoformat()


def _new_txn(artifact: str, digest: str, now=None) -> dict:
    stamped = now or datetime.datetime.now(datetime.timezone.utc)
    if stamped.utcoffset() is None:
        sys.exit("release.py: the release clock produced a timezone-less instant.")
    return {
        "schema_version": _TXN_SCHEMA_VERSION,
        # An IMMUTABLE identity for this transaction, and the reason it exists:
        # a compare-and-swap proves only that the ref has not moved since we read
        # it, never that what is on it is still OURS. Without the id, a release
        # whose transaction was replaced by a concurrent one would happily CAS its
        # own source commit into the replacement, and then delete it on completion.
        "txn_id": uuid.uuid4().hex,
        "artifact": artifact,
        "digest": digest,
        "admitted_at": stamped.isoformat(),
    }


def _is_superseded(txn: dict, last_date: str | None) -> bool:
    """True when a persisted transaction was abandoned and overtaken.

    A transaction admitted BEFORE the last released date cannot be the one that
    produced that release, so it is left over from an attempt that never
    completed. Resuming it would date this edition earlier than one already
    published — which the backwards-date check would then refuse, turning a stale
    ref into a permanently unreleasable repository."""
    if last_date is None:
        return False
    return admission_date(txn["admitted_at"]) < last_date


def open_transaction(artifact: str, digest: str, last_date: str | None = None,
                     now=None) -> dict:
    """The open transaction for (artifact, digest), created if there is none.

    The admission instant is captured ONCE, here, and every later read returns
    that same persisted value — which is the whole point: a moving clock fails
    the two cases this exists for, a transaction admitted at 23:59 and completed
    at 00:01, and a next-day retry after a provider succeeded but the release did
    not finish.

    A persisted transaction is RESUMED only when both hold: its digest matches
    the content about to be released (a different digest means the content moved
    on, so that transaction is abandoned), and it has not been superseded by a
    later release. Otherwise a fresh one replaces it.

    `now` is injectable so tests can pin those boundary cases."""
    ref = _txn_ref(artifact)
    for _ in range(3):
        found = _load_txn(artifact)
        if found is not None:
            _, txn = found
            if txn["digest"] == digest and not _is_superseded(txn, last_date):
                return txn
        candidate = _new_txn(artifact, digest, now)
        # Refuse BEFORE writing: a candidate instant that predates the last
        # release is a clock problem, and persisting it first would leave the
        # repository holding a transaction it must then refuse to act on.
        candidate_date = admission_date(candidate["admitted_at"])
        if last_date is not None and candidate_date < last_date:
            sys.exit(
                f"release.py: refusing — the admission date {candidate_date} is BEFORE "
                f"the last released date {last_date}. An edition date must not move "
                f"backwards; check this host's clock."
            )
        if _cas_txn(ref, candidate, found[0] if found else ""):
            return candidate
        # Lost the race against a concurrent release — re-read and adopt or
        # replace the winner's payload rather than overwriting it blindly.
    sys.exit(
        f"release.py: could not open a release transaction on {ref} — another "
        f"release appears to be running against this repository."
    )


def _update_txn(artifact: str, txn_id: str, **fields) -> None:
    """Merge `fields` into OUR transaction, compare-and-swapping so a concurrent
    writer's payload is never silently clobbered — and refusing outright when the
    ref no longer holds the transaction this release opened."""
    ref = _txn_ref(artifact)
    for _ in range(3):
        found = _load_txn(artifact)
        if found is None or found[1].get("txn_id") != txn_id:
            sys.exit(
                f"release.py: the release transaction on {ref} was replaced while this "
                f"release was running — another release is operating on this repository. "
                f"Refusing to write into a transaction that is not this one's."
            )
        sha, txn = found
        if all(txn.get(k) == v for k, v in fields.items()):
            return
        if _cas_txn(ref, {**txn, **fields}, sha):
            return
    sys.exit(
        f"release.py: could not update the release transaction on {ref} — another "
        f"release appears to be running against this repository."
    )


def mark_date_written(artifact: str, txn_id: str) -> None:
    _update_txn(artifact, txn_id, date_written=True)


def close_transaction(artifact: str, txn_id: str) -> None:
    """Close OUR transaction — never one that replaced it.

    A failure to delete is reported rather than swallowed: the release itself
    succeeded, so this must not fail it, but printing `Done.` over a transaction
    that is still open would leave the next release resuming a finished one."""
    ref = _txn_ref(artifact)
    found = _read_txn(ref)
    if found is None:
        return
    sha, txn = found
    if txn.get("txn_id") != txn_id:
        sys.stderr.write(
            f"release.py: warning — {ref} now holds a different transaction; "
            f"leaving it for the release that owns it.\n"
        )
        return
    if not _delete_txn(ref, sha):
        sys.stderr.write(
            f"release.py: warning — could not close the release transaction on {ref}. "
            f"It is still open; remove it with `git update-ref -d {ref}`.\n"
        )


def _restore_txn(artifact: str, before: tuple[str, dict] | None,
                 mine_id: str | None) -> None:
    """Put the transaction ref back the way this invocation found it — but ONLY
    while the ref still holds the transaction this invocation opened.

    Used on a refusal after the transaction was opened: the phase's contract is
    that a refusal leaves the operator where they were, and a ref this release
    created and then declined to use is the abandoned state the lifecycle exists
    to avoid.

    `mine_id` is what keeps the cleanup from becoming the damage. Rolling back to
    a remembered "before" state is only safe if nothing else has written since:
    if a concurrent release has already replaced our transaction with its own,
    then deleting the ref (we found none at the start) or resetting it (we found
    a different one) destroys THAT release's in-flight state — one process
    tidying up by wrecking another's."""
    ref = _txn_ref(artifact)
    now = _read_txn(ref)
    if now is None or mine_id is None or now[1].get("txn_id") != mine_id:
        return
    if before is None:
        _delete_txn(ref, now[0])
    else:
        _cas_ref(ref, before[0], now[0])


def _last_released(artifact: str, slug: str) -> "kitconfig.Stamp | None":
    """The identity of the last released artifact, read from its committed
    reference — None ONLY when this guide demonstrably never released one.

    IT FAILS CLOSED, and that is the correction that matters most here. An
    unreadable stamp used to return None, which made the predicate skip BOTH the
    freshness comparison and the backwards-date check and admit anything: a
    reference rendered before a stamp-grammar change read as "no previous
    release" rather than as "the previous release cannot be established". A
    MISSING reference is likewise only pre-first-release if git history agrees —
    a deleted deliverable is refused, matching `verify_artifacts.staleness_check`,
    which has always drawn that distinction."""
    spec = kitconfig.artifact_spec(artifact)
    if spec.reference is None:
        sys.exit(
            f"release.py: {artifact} has no committed reference artifact, so it has no "
            f"last released identity to read. (release_predicate refuses this earlier.)"
        )
    reference = ROOT / spec.reference.replace("<slug>", slug)

    if not reference.exists():
        try:
            ever = _git("log", "-1", "--format=%H", "--", reference.name,
                        capture=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            sys.exit(
                f"release.py: refusing — cannot query git history for {reference.name} "
                f"({exc}), so a deleted deliverable cannot be told from a first release."
            )
        # An EMPTY answer only proves "never released" over COMPLETE history. In a
        # shallow clone the boundary can sit after the deletion, so the same empty
        # result means "I cannot see far enough back" — the other way for this to
        # fail open, and the one a `--depth 1` CI checkout reaches first.
        shallow = _git("rev-parse", "--is-shallow-repository",
                       capture=True, check=False).stdout.strip() == "true"
        if not ever and shallow:
            sys.exit(
                f"release.py: refusing — {reference.name} is missing and this is a SHALLOW "
                f"clone, so its absence from history cannot be told from a truncated view. "
                f"Run `git fetch --unshallow` and re-run."
            )
        if ever:
            sys.exit(
                f"release.py: refusing — {reference.name} was released and is now missing. "
                f"Restore it (`git checkout -- {reference.name}`) or re-render it first."
            )
        return None

    try:
        stamp = verify_artifacts.read_stamp_from_band(reference)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        sys.exit(f"release.py: refusing — cannot read {reference.name} ({exc}).")
    if stamp is None:
        sys.exit(
            f"release.py: refusing — {reference.name} carries no readable version stamp, "
            f"so the last released identity cannot be established and freshness cannot be "
            f"proved. (A reference rendered before a stamp-grammar change lands here, as "
            f"does one whose pages disagree.) Re-render it — `make baseline`, or let "
            f"baseline.yml do it — then re-run."
        )
    return stamp


def release_predicate(artifact: str, slug: str, now=None) -> tuple[str, dict]:
    """Decide whether this artifact may be released, and with what date.

    Returns (date_to_write, transaction). Exits with a named error when the
    release must be refused.

    Freshness is proved by the artifact's CONTENT differing from the last
    released identity, never by the date string — the date cannot prove
    freshness, and requiring it to change would make a second same-day release
    impossible even though the two have different hashes and are therefore
    different editions.

    "Content" is the closure NORMALISED to the last released date, not the
    closure as authored. The date key is inside the closure, so comparing as
    authored means hand-editing the date alone moves the hash and a
    byte-identical artifact is admitted as a new edition."""
    spec = kitconfig.artifact_spec(artifact)
    if spec.reference is None:
        sys.exit(
            f"release.py: refusing — {artifact} has no committed reference artifact, so "
            f"there is no last released identity to prove freshness against and every "
            f"invocation would look like a first release. A deployed artifact is "
            f"published by `deploy.yml`, not admitted here."
        )
    # Checked BEFORE anything is opened. A guide with `pdf = false` carries no
    # `[artifacts.pdf]` table, so the authored-date lookup below would raise a bare
    # KeyError — after the transaction ref had already been written.
    cfg = kitconfig.load(ROOT)
    if artifact not in cfg.outputs.declared:
        sys.exit(
            f"release.py: refusing — this guide does not declare the {artifact} output "
            f"([outputs] in guide.toml declares {list(cfg.outputs.declared)}), so there "
            f"is no {artifact} to release."
        )

    last = _last_released(artifact, slug)

    if last is not None:
        as_released = kitconfig.closure_hash_at_date(artifact, last.date, root=ROOT)
        if as_released == last.hash:
            sys.exit(
                f"release.py: refusing — {artifact}'s content is unchanged since the last "
                f"release (hash {last.hash}). There is nothing new to publish; the date "
                f"alone cannot make an identical artifact a new edition."
            )

    digest = kitconfig.content_digest(artifact, root=ROOT)
    txn_before = _read_txn(_txn_ref(artifact))
    txn = open_transaction(artifact, digest,
                           None if last is None else last.date, now=now)
    admitted_at = txn["admitted_at"]
    date = admission_date(admitted_at)

    authored = cfg.artifacts[artifact].date
    if authored != date and txn.get("date_written") is True:
        # The one refusal that can land AFTER the transaction was opened, so it
        # undoes its own write before exiting — the caller's rollback cannot,
        # because it never received the id that makes the undo safe.
        _restore_txn(artifact, txn_before, txn["txn_id"])
        sys.exit(
            f"release.py: refusing — [artifacts.{artifact}] date is {authored!r} but this "
            f"transaction was admitted at {admitted_at} ({date}). release.py is the sole "
            f"writer of that key; a hand-set value that disagrees with the admission "
            f"instant means two different releases are being conflated."
        )
    return date, txn


# --- Writing the date key ---------------------------------------------------

_DATE_ASSIGNMENT_RE = re.compile(r"^(?P<head>\s*date\s*=)(?P<rest>.*)$")


def _table_header(line: str) -> str | None:
    """The normalised table header a line declares, or None. `[ artifacts.pdf ]`
    and `[artifacts.pdf]` are the same table, so whitespace is collapsed."""
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return re.sub(r"\s+", "", stripped)
    return None


def _split_quoted_value(rest: str) -> tuple[str, str, str] | None:
    """Split the text after `date =` into (leading space, value, trailer).

    None when the value is not a complete single-line quoted string. That is the
    only form the schema accepts — `_check_date` requires a `str`, so a bare TOML
    local-date fails validation anyway — and the only one that can be rewritten
    without risking corruption: a `'''` opener would leave orphaned lines behind
    if its first line were replaced."""
    i = 0
    while i < len(rest) and rest[i] in " \t":
        i += 1
    if i >= len(rest) or rest[i] not in "\"'":
        return None
    quote = rest[i]
    if rest[i:i + 3] == quote * 3:
        return None
    start, i = i, i + 1
    while i < len(rest):
        if rest[i] == "\\" and quote == '"':
            i += 2                                  # basic strings take escapes
            continue
        if rest[i] == quote:
            return rest[:start], rest[start:i + 1], rest[i + 1:]
        i += 1
    return None                                     # unterminated


def locate_date_line(text: str, artifact: str, date: str) -> tuple[int, str]:
    """Find the `date` assignment under `[artifacts.<artifact>]` in `text` and
    return (line index, the line rewritten to carry `date`). Exits by name when
    the key cannot be rewritten.

    SEPARATE FROM THE WRITE so the preflight can run it before anything is
    mutated. Every constraint here is structural — a quoted table header
    (`[artifacts."pdf"]`) or a `'''` value is valid TOML that loads fine, so the
    config validating is not evidence this can rewrite it. Discovering that only
    after the transaction was opened left the ref behind on a refusal."""
    lines = text.split("\n")
    header = f"[artifacts.{artifact}]"

    hits: list[tuple[int, str]] = []
    inside = False
    for i, line in enumerate(lines):
        table = _table_header(line)
        if table is not None:
            inside = table == header
            continue
        if not inside:
            continue
        m = _DATE_ASSIGNMENT_RE.match(line)
        if m is None:
            continue
        split = _split_quoted_value(m.group("rest"))
        if split is None:
            sys.exit(
                f"release.py: cannot rewrite the date under {header} — its value is not a "
                f"single-line quoted string:\n  {line}\n"
                f'Set it to date = "{date}" by hand and re-run.'
            )
        lead, _old, trailer = split
        hits.append((i, f'{m.group("head")}{lead}"{date}"{trailer}'))

    if not hits:
        sys.exit(
            f"release.py: no date key found under {header} in guide.toml. (A quoted or "
            f'spaced header such as [artifacts."{artifact}"] is valid TOML but is not a '
            f"form release.py rewrites; write it as {header}.)"
        )
    if len(hits) > 1:
        sys.exit(
            f"release.py: {header} declares 'date' {len(hits)} times in guide.toml; "
            f"refusing to guess which one is authoritative."
        )
    return hits[0]


# The text the most recent `set_artifact_date` wrote FROM. A one-slot list rather
# than a return-value change because every caller and test reads the bool; the
# rollback is the only thing that needs this, and it needs it even when the write
# was performed by a wrapper around this function.
release_toml_source: list[str | None] = [None]


def set_artifact_date(artifact: str, date: str) -> bool:
    """Write `[artifacts.<artifact>] date` in guide.toml. True if the file changed.

    A targeted line rewrite inside the artifact's own table, not a TOML
    round-trip: the stdlib has no writer, and re-emitting the file would discard
    every comment in it — including the ones explaining why these keys exist.

    IT MUST NOT BE ABLE TO SILENTLY DO NOTHING, which is what an earlier draft
    did: it substituted a double-quoted value with a regex, so `date =
    '2026-07-25'` — valid TOML — matched the key but not the value, returned
    False, and the release carried on and published under a date the file never
    held. This one rewrites the whole VALUE span (either quoting style, any
    trailing comment preserved) and then RELOADS guide.toml to prove the
    effective date is the one assigned, restoring the file if it is not.

    The write is ATOMIC and guarded by a re-read. `write_text` truncates before
    writing, so a crash mid-write would leave the guide's whole configuration
    empty; and replacing the file from a snapshot taken moments earlier would
    silently erase an unrelated key someone edited in between."""
    path = ROOT / "guide.toml"
    original = path.read_text(encoding="utf-8")
    # Publish the exact text this write is based on, so a caller rolling back
    # restores THAT and not an older snapshot. See the rollback in main().
    release_toml_source[0] = original
    index, new_line = locate_date_line(original, artifact, date)

    lines = original.split("\n")
    if lines[index] == new_line:
        _assert_effective_date(artifact, date, original)
        return False

    lines[index] = new_line
    if path.read_text(encoding="utf-8") != original:
        sys.exit(
            "release.py: guide.toml changed while the edition date was being written; "
            "refusing to overwrite it from a stale copy. Re-run once it is settled."
        )
    _atomic_write(path, "\n".join(lines))
    _assert_effective_date(artifact, date, original)
    return True


def _assert_effective_date(artifact: str, date: str, original: str) -> None:
    """Reload guide.toml and prove the write took, restoring the file if not.

    The rewrite is textual and the config is what everything downstream reads, so
    this is the join between them: a date the release is about to stamp into an
    artifact must never be one guide.toml does not actually carry."""
    path = ROOT / "guide.toml"
    try:
        effective = kitconfig.load(ROOT).artifacts[artifact].date
    except (kitconfig.KitConfigError, KeyError) as exc:
        _atomic_write(path, original)
        sys.exit(
            f"release.py: writing the edition date left guide.toml unusable ({exc}); "
            f"the file has been restored."
        )
    if effective != date:
        _atomic_write(path, original)
        sys.exit(
            f"release.py: after writing, [artifacts.{artifact}] date reads {effective!r}, "
            f"not {date!r}; guide.toml has been restored. Set it by hand and re-run."
        )


def _index_tree() -> str:
    """The tree object for the current index — what a commit right now would carry."""
    return _git("write-tree", capture=True).stdout.strip()


def _tree_of(commit: str) -> str:
    return _git("rev-parse", "--verify", "--quiet", f"{commit}^{{tree}}",
                capture=True, check=False).stdout.strip()


def _commit_we_just_made(parent: str | None, tree: str) -> str:
    """HEAD, having PROVED it is the commit this process just created.

    Re-reading HEAD after `git commit` is not the same thing. git's index lock
    serialises the commits themselves but not the gap after one: a second process
    moving the branch in that gap hands this one someone else's commit, which the
    amend step at the end would then rewrite.

    TWO facts are checked, because either alone is defeatable. The parent catches
    a commit stacked on top of ours. It does not catch a SIBLING — a branch
    rewound to our parent and re-committed — which is why the tree is checked
    too: `git write-tree` names the exact index we were about to commit, so a
    commit carrying any other content is not ours no matter what its parent
    says. (A sibling with an identical tree AND parent is the same content by
    definition, so amending it is not a rewrite of anyone's work.)"""
    head = _head()
    if head is None or _parent_of(head) != parent or _tree_of(head) != tree:
        sys.exit(
            "release.py: the branch moved while the release commit was being made, so "
            "this release cannot tell which commit is its own. Nothing further has been "
            "changed; sort the history out and re-run."
        )
    return head


def _restore_reference(name: str) -> None:
    """Undo a promotion whose commit did not happen, so the next run's preflight
    sees the tree it saw before rather than this run's leftovers."""
    _git("reset", "-q", "HEAD", "--", name, capture=True, check=False)
    tracked = _git("ls-files", "--error-unmatch", "--", name,
                   capture=True, check=False).returncode == 0
    if tracked:
        _git("checkout", "-q", "--", name, capture=True, check=False)
    else:
        (ROOT / name).unlink(missing_ok=True)


def _discard_abandoned_promotion(slug: str) -> None:
    """Drop a reference promoted by an earlier attempt that never committed it.

    A process killed between the promotion and its commit leaves the reference in
    the tree. It is not an authorable path, so the next preflight refuses it — the
    documented retry dead-ends on this tool's own leftovers. Discarded, never
    staged: the working render is rebuilt from source further down anyway, so
    there is nothing here worth keeping.

    Guarded on an OPEN TRANSACTION, which is what makes this release.py cleaning
    up after itself rather than a tool deleting an operator's file: with no
    transaction in flight, a modified reference is someone's deliberate edit and
    the preflight refuses it as it always did."""
    spec = kitconfig.artifact_spec(ARTIFACT)
    if spec.reference is None or _read_txn(_txn_ref(ARTIFACT)) is None:
        return
    name = spec.reference.replace("<slug>", slug)
    if any(p == name for _, p in _porcelain()):
        print(f"  discarding {name}, promoted by an earlier attempt that did not commit it")
        _restore_reference(name)


def _reference_name(slug: str, artifact: str = None) -> str:
    """The committed reference filename for `artifact`. One resolver, so the
    build, the promotion and the rollback cannot disagree about which file this
    release is about — the disagreement that half-wiring produced."""
    spec = kitconfig.artifact_spec(artifact or ARTIFACT)
    return spec.reference.replace("<slug>", slug)


def _build() -> None:
    print(f"  building fresh {ARTIFACT} render...")
    # The PDF is the default build target; every other artifact has its own flag.
    cmd = (["pixi", "run", "build"] if ARTIFACT == "pdf"
           else ["pixi", "run", "python", "build.py", f"--{ARTIFACT}"])
    subprocess.run(cmd, cwd=ROOT, check=True)


def _promote_to_reference(slug: str) -> str:
    """Copy the fresh working render onto its committed reference at the repo
    root (what readers download from GitHub). Returns the reference filename for
    the caller to `git add`."""
    name = _reference_name(slug)
    working = ROOT / "build" / name
    reference = ROOT / name
    if not working.exists():
        sys.exit(f"release.py: expected fresh render at {working} but it's missing.")
    _atomic_copy(working, reference)
    print(f"  {ARTIFACT} reference <- {working.relative_to(ROOT)}")
    return reference.name


def main() -> int:
    p = argparse.ArgumentParser(
        description="Stage source + refresh reference PDF + amend, in one commit.",
    )
    p.add_argument("-m", "--message", required=True, help="Commit message")
    p.add_argument("--artifact", default="pdf", choices=kitconfig.ARTIFACT_NAMES,
                   help="which artifact to release (default: pdf)")
    args = p.parse_args()

    # Rebind the module-level name the helpers read. A global rather than a
    # threaded parameter because the transaction helpers below are also called
    # from the resume path, where there is no argv to thread from.
    global ARTIFACT
    ARTIFACT = args.artifact
    spec = kitconfig.artifact_spec(ARTIFACT)
    if spec.reference is None:
        sys.exit(
            f"release.py: {ARTIFACT} has no committed reference artifact — "
            f"{spec.no_reference_reason}. There is nothing for `release` to "
            f"promote. This artifact ships by being pushed: deploy.yml rebuilds "
            f"and publishes it on a push to the default branch."
        )

    # No platform guard. release.py used to refuse off a recorded canonical host,
    # on the theory that a Linux VM must not promote a Linux-typography PDF into
    # a family of macOS-rendered ones. Bundled faces and `fontconfig/fonts.conf`
    # removed the premise — the render no longer reads the host's font stack —
    # so the guard recorded an intention nothing could violate. Host agreement is
    # now MEASURED by the drift canary (driftcanary.py) rather than declared.
    cfg = kitconfig.load(ROOT)
    slug = cfg.OUTPUT_SLUG
    toml_path = ROOT / "guide.toml"

    # 1. PREFLIGHT — read-only, and FIRST. Every refusal that can be decided
    #    without touching anything is decided here, because an earlier draft
    #    wrote the edition date and opened the transaction and only then rejected
    #    an unrelated staged file: the refusal left both the operator's tree and
    #    this repository's refs mutated while its own comment claimed nothing had
    #    moved. The date key is LOCATED here too — whether it can be rewritten is
    #    a structural question about guide.toml's text, and one a valid config
    #    can still answer no to.
    _discard_abandoned_promotion(slug)
    before = _ensure_clean_state(cfg)
    toml_before = toml_path.read_text(encoding="utf-8")
    locate_date_line(toml_before, ARTIFACT, "0000-00-00")
    txn_before = _read_txn(_txn_ref(ARTIFACT))
    txn: dict | None = None
    toml_written: str | None = None

    # 2-4 mutate two things that outlive a failed process: guide.toml and the
    #     transaction ref. Any refusal in here puts BOTH back, so "a refusal
    #     leaves the operator's tree as they left it" holds for the whole region
    #     and not just its first step. Past the source commit it no longer
    #     applies, and must not: that commit is what a retry resumes into.
    try:
        # 2. ADMIT, or refuse (the edition-date predicate).
        date, txn = release_predicate(ARTIFACT, slug)

        # 3. MUTATE. The date is written BEFORE the source commit for the reason
        #    required: the later `--amend` must not be able to perturb it.
        # `set_artifact_date` hands back the EXACT text it wrote from, and the
        # rollback restores that rather than the preflight snapshot. The
        # difference is a real data loss: the preflight copy predates anything
        # that landed in guide.toml between preflight and the write, so restoring
        # it discards a concurrent edit — the very loss the rollback's own comment
        # says it exists to avoid. That comment was only ever true of the case
        # where this function REFUSES; when it SUCCEEDS on top of someone else's
        # edit, only the text it actually read is "the tree as they left it".
        if set_artifact_date(ARTIFACT, date):
            toml_before = release_toml_source[0] or toml_before
            toml_written = toml_path.read_text(encoding="utf-8")
            print(f"  [artifacts.{ARTIFACT}] date <- {date} "
                  f"(admitted {txn['admitted_at']})")
        mark_date_written(ARTIFACT, txn["txn_id"])

        # 4. RE-CHECK the exact expected state, by CONTENT and not by path name.
        #    The transaction was admitted for one specific closure; a source file
        #    edited again since then keeps the same path, so a set-of-names
        #    comparison sees nothing while the bytes about to be committed are no
        #    longer the bytes that were admitted. The digest excludes the date, so
        #    this run's own write cannot move it.
        if kitconfig.content_digest(ARTIFACT, root=ROOT) != txn["digest"]:
            sys.exit(
                "release.py: the artifact's content changed while the release was being "
                "prepared, so it is no longer the content that was admitted. Re-run once "
                "the tree is settled."
            )
        to_stage = _ensure_clean_state(cfg)
        unexpected = sorted(set(to_stage) - set(before) - {"guide.toml"})
        if unexpected:
            sys.exit(
                "release.py: the working tree changed while the release was being "
                "prepared:\n  " + "\n  ".join(unexpected) + "\nRe-run once it is settled."
            )
    except SystemExit:
        # Restore only what THIS invocation wrote, and only while it is still
        # what is there. Rolling back to the preflight snapshot unconditionally
        # is itself a way to lose data: `set_artifact_date` refuses precisely
        # when it finds someone else's edit, and blindly restoring would erase
        # the edit that refusal existed to protect.
        if (toml_written is not None
                and toml_path.read_text(encoding="utf-8") == toml_written):
            _atomic_write(toml_path, toml_before)
        _restore_txn(ARTIFACT, txn_before, txn["txn_id"] if txn else None)
        raise

    # 5. The source commit — skipped when there is nothing to stage. That is a
    #    real state, not a no-op: a first release from an already committed tree,
    #    and a retry after a build failure that preserved the source commit, both
    #    arrive here clean, and exiting instead dead-ended both.
    if to_stage:
        print(f"  staging: {', '.join(to_stage)}")
        parent = _head()
        _git("add", "--", *to_stage)
        try:
            # Re-checked AFTER staging, because the check before it bounds nothing:
            # the digest was compared against a worktree that `git add` had not yet
            # read. A source file changed in between keeps its path, so the name
            # comparison sees nothing and the newer bytes are what get committed —
            # published under an admission instant that belongs to the older ones.
            if kitconfig.content_digest(ARTIFACT, root=ROOT) != txn["digest"]:
                sys.exit(
                    "release.py: the artifact's content changed as it was being staged, "
                    "so what is in the index is not what was admitted. Nothing was "
                    "committed; re-run once the tree is settled."
                )
            tree = _index_tree()
            _git("commit", "-m", args.message)
            source_commit = _commit_we_just_made(parent, tree)
        except BaseException:
            # A refusal here — or a rejecting pre-commit hook — must not leave the
            # index dirty: the next invocation would exit at the staged-index
            # preflight instead of resuming, which is the documented retry path
            # refusing this run's own residue. The date edit and the transaction
            # stay: unstaged, they are exactly what a resume expects to find.
            _git("reset", "-q", "HEAD", "--", *to_stage, capture=True, check=False)
            raise
        _update_txn(ARTIFACT, txn["txn_id"], source_commit=source_commit)
        print(f"  committed source: {args.message!r}")
    else:
        print("  no source changes to stage — releasing the committed tree.")

    _build()

    # The last point at which a mid-flight content change is still catchable: the
    # build renders whatever is on disk NOW, so a source edit during it would
    # produce an artifact whose stamp is internally consistent and whose edition
    # date belongs to different content.
    if kitconfig.content_digest(ARTIFACT, root=ROOT) != txn["digest"]:
        sys.exit(
            "release.py: the artifact's content changed after it was committed, so the "
            "render is not the content that was admitted. The source commit is preserved; "
            "re-run once the tree is settled."
        )

    # Don't bless a render that isn't demonstrably fresh and clean — same guard
    # `make baseline` uses, so `make release` can't promote a stale/dirty/unstamped
    # file. The source commit above is preserved for the operator to investigate.
    working = ROOT / "build" / _reference_name(slug)
    ok, msg = verify_artifacts.promotable_stamp(working, ROOT, ARTIFACT)
    if not ok:
        sys.exit(
            f"release.py: not promoting — {msg}. The source commit is preserved; "
            "re-run once fixed and this same transaction resumes into it."
        )

    # The document-level guard, not just the byte-level one. `promotable_stamp`
    # asks whether the render is fresh, clean and stamped; `smoke_check` asks
    # whether it looks like a finished guide — and it is the ONLY path to
    # `footer_wrap_failures`, the single automated catcher for recorded defect 8.
    # A release is the most consequential promotion there is (it commits, tags
    # and redeploys), so it must not be the one path that skips the check CI runs.
    # PDF only, and this is not an exemption being smuggled in. `smoke_check`
    # asks "does this look like a finished GUIDE" — page count, a title, no
    # placeholders, an unwrapped footer. A slide deck answers that wrongly by
    # construction: two slides is a legitimate deck and a broken guide. Applying
    # it to the deck would make every deck unreleasable, which is not a stricter
    # check, just a wrong one.
    if ARTIFACT == "pdf" and verify_artifacts.smoke_check(working, ROOT) != 0:
        sys.exit(
            "release.py: not promoting — the fresh render does not pass `make smoke` "
            "(see above). The source commit is preserved; re-run once fixed and this "
            "same transaction resumes into it."
        )

    reference_name = _promote_to_reference(slug)
    try:
        _git("add", reference_name)

        # Amend ONLY into a source commit release.py made for THIS transaction —
        # this run's, or a previous attempt's that failed after committing. Anything
        # else at HEAD belongs to the operator, and rewriting it is not something a
        # release tool may do silently, so the reference lands in its own commit.
        found = _read_txn(_txn_ref(ARTIFACT))
        owned = found is not None and found[1].get("txn_id") == txn["txn_id"]
        source_commit = found[1].get("source_commit") if owned else None
        if source_commit is not None and source_commit == _head():
            _git("commit", "--amend", "--no-edit")
            verb = "amended into"
        else:
            _git("commit", "-m", args.message)
            verb = "committed as"
    except BaseException:
        # The promoted reference is this run's residue. Left behind it is an
        # out-of-scope modification (or a staged one), and the next invocation —
        # the documented retry — would refuse it instead of resuming.
        _restore_reference(reference_name)
        raise
    short = _git("rev-parse", "--short", "HEAD", capture=True).stdout.strip()
    print(f"  {verb} {short}.")

    # The transaction is complete. Closing it is what stops a later, legitimate
    # revert to this same content from resurrecting today's admission instant.
    close_transaction(ARTIFACT, txn["txn_id"])
    print("Done. `make verify` to confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
