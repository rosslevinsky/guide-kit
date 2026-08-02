"""The second thing sync is allowed to delete: a destination whose LITERAL
manifest entry the kit has removed.

Tree deletion (`tests/test_sync_tree_projection.py`) answered "a file vanished
from a tree the kit owns". It deliberately did not answer "the kit removed the
entry itself", and that gap orphaned `verify_pdf.py` in all seven targets when
it was renamed to `verify_artifacts.py`: sync stopped projecting the old path
and had no way to say so, so every guide kept a dead script forever.

The two events are now the same kind of event, under the SAME guard clauses —
recorded, checksum-matching, refuse-if-modified, journaled, never inferred for an
unrecorded path. What is NOT the same, and is the line this file exists to hold:

  * a destination the kit still declares but this target's SHAPE no longer wants
    is `adopt.py --disable`'s transition (config-first, never writes
    guide.toml, refuses a dirty tree). Sync must not perform it silently.
  * an inventory key is input, not fact. With the tree gate gone, key
    normalisation is the ONLY thing standing between a corrupt `.template-version`
    and an arbitrary deletion in the target.
"""
import json
import subprocess

import pytest

import sync

_BUILD_ENTRY = ('[[entry]]\npath = "build.py"\nlifecycle = "retained-in-kit"\n'
                'projects_to = "build.py"\npolicy = "identical"\n')


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def _drop_build_entry(env, msg="unclassify build.py"):
    """Remove build.py's LITERAL manifest entry from the fixture kit.

    Nothing else changes: the kit still HAS build.py on disk, the target still
    has it, and the target still has it recorded. Only the classification is
    gone — which is exactly what happened to `verify_pdf.py`."""
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    assert _BUILD_ENTRY in manifest, "fixture manifest changed shape"
    (env.kit / "kit-manifest.toml").write_text(
        manifest.replace(_BUILD_ENTRY, ""), encoding="utf-8")
    _commit(env.kit, msg)
    return env


def _recorded(env):
    return json.loads(
        (env.target / ".template-version").read_text(encoding="utf-8")
    )["rendered_checksums"]


# ----- the happy path --------------------------------------------------------

def test_a_removed_literal_entry_is_deleted_in_the_target(sync_env):
    env = _drop_build_entry(sync_env())

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert not (env.target / "build.py").exists(), "the orphan survived"
    # The record goes too, or the next run keeps re-deciding a file that is gone.
    assert "build.py" not in _recorded(env)
    # Nothing else was touched.
    assert (env.target / "pixi.toml").exists()
    assert (env.target / "CLAUDE.md").exists()
    assert (env.target / "guide.md").exists()


def test_the_deletion_needs_no_managed_tree_to_exist(sync_env):
    """The tree path returned early when the manifest declared no tree at all.
    The fixture kit declares none, so this whole file would be dead code if that
    early return survived."""
    import kitmanifest
    env = _drop_build_entry(sync_env())
    m = kitmanifest.load(env.kit)
    assert not [p for p in m.projections("pdf-only", slug="probe-guide")
                if p.dest.endswith("/**")], "fixture gained a tree"

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert not (env.target / "build.py").exists()


# ----- the guard, clause by clause -------------------------------------------

def test_a_locally_modified_file_whose_entry_was_removed_is_refused(sync_env):
    """Ownership is not transferred silently and work is not destroyed: the
    WHOLE transition refuses, so a second unrelated update does not land either."""
    env = sync_env()
    (env.target / "build.py").write_text("# the guide edited this\n", encoding="utf-8")
    _commit(env.target, "local edit")
    (env.kit / "pixi.toml").write_text(
        'name = "guide-template"\n# desc for guide-template\n# v2\n', encoding="utf-8")
    _drop_build_entry(env, "unclassify build.py, and bump pixi.toml")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    assert (env.target / "build.py").read_text() == "# the guide edited this\n"
    assert "build.py" in _recorded(env), "the record was dropped by a refused transition"
    assert "# v2" not in (env.target / "pixi.toml").read_text(), \
        "a refusal let the rest of the transition apply"


def test_a_record_for_a_removed_entry_already_gone_is_forgotten(sync_env):
    """A stale record is not harmless: a later guide-authored file at that path
    is falsely refused, or — if its bytes happen to match — deleted."""
    env = sync_env()
    (env.target / "build.py").unlink()
    _commit(env.target, "the guide removed it by hand")
    _drop_build_entry(env)

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert "build.py" not in _recorded(env), "a stale inventory record survived"


def test_a_removed_entry_replaced_by_a_symlink_is_refused(sync_env):
    """`exists()` is False for a BROKEN link, which would read as "already gone"
    and quietly forget the record while the link stayed."""
    env = sync_env()
    (env.target / "build.py").unlink()
    (env.target / "build.py").symlink_to(env.target / "nowhere.py")
    _commit(env.target, "a broken symlink where the script was")
    _drop_build_entry(env)

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    assert (env.target / "build.py").is_symlink(), "the symlink was silently removed"
    assert "build.py" in _recorded(env), "the record was forgotten behind a symlink"


def _reclassify_build_to_never(env):
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    (env.kit / "kit-manifest.toml").write_text(
        manifest.replace(_BUILD_ENTRY,
                         _BUILD_ENTRY.replace('policy = "identical"', 'policy = "never"')),
        encoding="utf-8")
    _commit(env.kit, "build.py becomes target-owned")
    return env


def test_a_destination_reclassified_to_never_is_not_deleted(sync_env):
    """Reclassifying to `never` HANDS the file to the guide. Reading that as an
    upstream deletion would take back the file the reclassification gave away."""
    env = _reclassify_build_to_never(sync_env())

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "build.py").exists(), \
        "a file handed to the guide was deleted as an upstream removal"


def test_reclassifying_to_never_forgets_the_record(sync_env):
    """Surviving the reclassification is not enough: the RECORD has to go too.

    A `never` destination is one sync never writes and never reports drift on, so
    its checksum record is dead weight — except that the record is precisely what
    authorises a deletion. Keep it and the handover is only half done: remove the
    `never` entry later and sync deletes a file the guide has owned since the
    reclassification, on the strength of a record from before it."""
    env = _reclassify_build_to_never(sync_env())
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert "build.py" not in _recorded(env), \
        "the record outlived the ownership handover"
    _commit(env.target, "ownership handed over")

    # The second half of the chain: the kit drops the `never` entry entirely.
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    (env.kit / "kit-manifest.toml").write_text(
        manifest.replace(_BUILD_ENTRY.replace('policy = "identical"',
                                              'policy = "never"'), ""),
        encoding="utf-8")
    _commit(env.kit, "drop the target-owned entry too")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "build.py").exists(), \
        "a file the guide has owned since reclassification was deleted"


def test_a_shared_ownership_file_is_forgotten_not_deleted(sync_env):
    """A managed-region file is SHARED: the kit owns the marked block, the guide
    owns everything around it. The kit dropping its entry means the block stops
    being maintained — it does not mean the guide's own prose should vanish.

    This is also the one case where the delete path's "tree projections are
    byte-for-byte by construction" assumption stops holding: the record covers
    only the marked region, so hashing the whole file can never match it, and
    treating that as a local modification would wedge sync in a refusal no edit
    can clear."""
    env = sync_env()
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    entry = ('[[entry]]\npath = "CLAUDE.md"\nlifecycle = "retained-in-kit"\n'
             'projects_to = "CLAUDE.md"\npolicy = "managed-region"\n')
    assert entry in manifest
    (env.kit / "kit-manifest.toml").write_text(manifest.replace(entry, ""), encoding="utf-8")
    _commit(env.kit, "unclassify CLAUDE.md")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK, \
        "sync wedged on a record it can never match"
    body = (env.target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "TARGET-OWNED section the guide maintains." in body, \
        "the guide's own prose was deleted with the kit's block"
    assert "CLAUDE.md" not in _recorded(env), "the unmatchable record survived"


def test_a_symlinked_directory_cannot_alias_a_protected_file(sync_env):
    """`_safe_inventory_key` is a check on the STRING. `alias/guide.md` is
    perfectly canonical — no `..`, no leading slash — yet with `alias -> .`
    committed in the target it names the guide's own `guide.md`, which is
    `policy = "never"`. The string guards all compare `alias/guide.md` against
    declaration sets that contain `guide.md`, so every one of them passes it
    through; only comparing what the path actually RESOLVES to catches it."""
    env = sync_env()
    (env.target / "alias").symlink_to(env.target)
    guide_md = (env.target / "guide.md").read_bytes()

    tv = json.loads((env.target / ".template-version").read_text(encoding="utf-8"))
    tv["rendered_checksums"]["alias/guide.md"] = sync._sha256(guide_md)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "an aliasing inventory key")

    assert sync.run_sync(env.kit, env.target, apply=True) in (sync.EXIT_OK, sync.EXIT_DRIFT)
    assert (env.target / "guide.md").read_bytes() == guide_md, \
        "a symlinked directory aliased past the target-owned guard"


def _plan_action(env, dest_rel):
    items, _, _ = sync.build_plan(env.kit, env.target)
    by_dest = {it.dest_rel: it.action for it in items}
    assert dest_rel in by_dest, f"{dest_rel} produced no plan item at all"
    return by_dest[dest_rel]


def test_a_hard_link_cannot_alias_a_protected_file(sync_env):
    """The symlink case above is caught by the lexical `dest_abs != target/dest_rel`
    test on its own, so it does not anchor the inode set — a hard link is what
    does. `alias.md` is a perfectly canonical key that resolves to exactly itself
    and IS the guide's `guide.md`.

    Asserted on the PLAN, not on `guide.md` surviving: unlinking one of two hard
    links leaves the other, so a survival assertion here would pass with the
    identity check deleted and prove nothing."""
    env = sync_env()
    guide_md = (env.target / "guide.md").read_bytes()
    (env.target / "alias.md").hardlink_to(env.target / "guide.md")

    tv = json.loads((env.target / ".template-version").read_text(encoding="utf-8"))
    tv["rendered_checksums"]["alias.md"] = sync._sha256(guide_md)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "a hard-linked inventory key")

    assert _plan_action(env, "alias.md") == "refuse", \
        "a hard link onto a target-owned file was planned for deletion"


def test_alias_protection_covers_a_destination_declared_only_in_ANOTHER_shape(sync_env):
    """Deletion eligibility is unioned over every shape (`dests_under_any_shape`),
    so the alias protection has to be unioned too. Seeded from the ACTIVE shape's
    projections alone it has a hole exactly the width of the difference between
    the shapes: on a pdf-only target the web-only `deploy.yml` is protected by
    NAME through `kit_declares`, and not protected at all by identity.

    On a case-folding filesystem that gap is reachable for real — a stale record
    spelled `DEPLOY.yml` names the same directory entry — which cannot be
    fixtured on ext4. The hard link stands in for it: same identity, different
    key, and it exercises the same seeding."""
    env = sync_env(shape="web-enabled")
    dest = env.target / ".github" / "workflows" / "deploy.yml"
    body = dest.read_bytes()

    from conftest import _guide_toml  # noqa: PLC0415 — the fixture's own helper
    (env.target / "guide.toml").write_text(_guide_toml("probe-guide", site="none"),
                                           encoding="utf-8")
    (env.target / "alias.yml").hardlink_to(dest)
    tv = json.loads((env.target / ".template-version").read_text(encoding="utf-8"))
    tv["rendered_checksums"]["alias.yml"] = sync._sha256(body)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "pdf-only now, with an alias onto the web-only workflow")

    assert _plan_action(env, "alias.yml") == "refuse", \
        "an alias onto a web-only destination was planned for deletion on a pdf-only target"


def test_a_destination_absent_only_because_the_shape_changed_is_not_deleted(sync_env):
    """THE LINE. `.github/workflows/deploy.yml` is web-only: un-declaring the site
    makes it vanish from this target's projections while the kit's entry is
    untouched. That is `adopt.py --disable`'s transition — config-first, refusing
    a dirty tree, journalled by that tool — and sync doing it as a side effect of
    an ordinary `--apply` would bypass every one of those guards."""
    env = sync_env(shape="web-enabled")
    dest = env.target / ".github" / "workflows" / "deploy.yml"
    assert dest.exists() and ".github/workflows/deploy.yml" in _recorded(env)

    from conftest import _guide_toml  # noqa: PLC0415 — the fixture's own helper
    (env.target / "guide.toml").write_text(_guide_toml("probe-guide", site="none"),
                                           encoding="utf-8")
    _commit(env.target, "un-declare the site")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert dest.exists(), "sync performed adopt.py --disable's transition silently"
    assert ".github/workflows/deploy.yml" in _recorded(env)


def test_a_traversing_inventory_key_is_not_deleted(sync_env):
    """With the managed-tree gate gone, key normalisation is the ONLY thing
    between a corrupt `.template-version` and an arbitrary deletion: every
    recorded key the kit does not declare is now a deletion candidate."""
    env = sync_env()
    (env.target / "EXTRA.txt").write_text("the guide's own file\n", encoding="utf-8")
    outside = env.target.parent / "outside.txt"
    outside.write_text("not the target's\n", encoding="utf-8")

    tv = json.loads((env.target / ".template-version").read_text(encoding="utf-8"))
    for key, body in [("sub/../EXTRA.txt", b"the guide's own file\n"),
                      ("./EXTRA.txt", b"the guide's own file\n"),
                      ("../outside.txt", b"not the target's\n")]:
        tv["rendered_checksums"][key] = sync._sha256(body)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "traversing inventory keys")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "EXTRA.txt").exists(), "a traversing key deleted a target file"
    assert outside.exists(), "a traversing key deleted a file outside the target"


# ----- transaction properties -------------------------------------------------

def test_the_deletion_rolls_back_with_the_rest_of_the_transaction(sync_env):
    """Literal deletions ride the same journal as tree deletions and writes: if
    anything fails, the removed bytes AND the inventory come back."""
    env = sync_env()
    (env.kit / "pixi.toml").write_text(
        'name = "guide-template"\n# desc for guide-template\n# v2\n', encoding="utf-8")
    _drop_build_entry(env, "unclassify build.py, and bump pixi.toml")

    seen = {"deleted": False}

    def explode(n):
        # Fail AFTER the unlink, not on the first write: aborting earlier would
        # let this pass with deletion journaling removed entirely.
        if not (env.target / "build.py").exists():
            seen["deleted"] = True
            raise RuntimeError("failure after the deletion")

    sync.AFTER_WRITE_HOOK = staticmethod(explode)
    try:
        with pytest.raises(RuntimeError):
            sync.run_sync(env.kit, env.target, apply=True)
    finally:
        sync.AFTER_WRITE_HOOK = None

    assert seen["deleted"], "the test never reached the deletion it claims to cover"
    assert (env.target / "build.py").read_text() == "# build.py v1\n", \
        "the deletion was not rolled back"
    assert "build.py" in _recorded(env), "the inventory was not rolled back"


def test_a_dry_run_reports_the_deletion_and_writes_nothing(sync_env, capsys):
    """A removed literal entry deletes a file in seven repositories, so it must
    be visible in the report BEFORE anyone types --apply."""
    env = _drop_build_entry(sync_env())

    assert sync.run_sync(env.kit, env.target, apply=False) == sync.EXIT_DRIFT
    out = capsys.readouterr().out
    assert "would delete" in out and "build.py" in out, out
    assert (env.target / "build.py").exists(), "a dry run deleted a file"


def test_apply_refuses_a_dirty_target_before_deleting_anything(sync_env):
    env = _drop_build_entry(sync_env())
    (env.target / "uncommitted.txt").write_text("work in progress\n", encoding="utf-8")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    assert (env.target / "build.py").exists(), "a dirty target was swept anyway"


def test_re_running_after_the_deletion_is_a_no_op(sync_env):
    env = _drop_build_entry(sync_env())
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    _commit(env.target, "the orphan is gone")

    assert sync.run_sync(env.kit, env.target, apply=False) == sync.EXIT_OK, \
        "the second run still saw something to do"
