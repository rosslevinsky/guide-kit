"""Directory-tree projection, and the one place sync is allowed to delete.

A manifest entry may project a TREE (`fonts/**` -> `fonts/**`) instead of a
single file. Before this existed, `projects_to` was resolved as a literal path,
so a glob destination made sync try to read a file named `fonts/**` and the copy
failed — which is why the bundled faces were enumerated one manifest entry each,
the paired edit the glob was meant to remove.

A tree is the only construct that can express "the kit owns whatever is in
here", and that is what makes upstream DELETION meaningful: a face removed from
the kit's tree should leave the guides. Every clause of the deletion guard is
tested here, because "sync deletes things now" is exactly the sentence that has
to be false in every case but one.
"""
import json
import subprocess

import pytest

import kitmanifest
import sync

_TREE_ENTRY = """
[[entry]]
path = "fonts/**"
lifecycle = "retained-in-kit"
projects_to = "fonts/**"
policy = "identical"
"""

_NESTED_ENTRY = """
[[entry]]
path = "fonts/generated/**"
lifecycle = "generated"
projects_to = "fonts/generated/**"
policy = "never"
"""


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def _with_tree(env, *, nested=False, faces=("A.ttf", "B.ttf")):
    """Give the fixture kit a managed font tree and sync it into the target."""
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    manifest += _TREE_ENTRY + (_NESTED_ENTRY if nested else "")
    (env.kit / "kit-manifest.toml").write_text(manifest, encoding="utf-8")
    (env.kit / "fonts").mkdir(exist_ok=True)
    for f in faces:
        (env.kit / "fonts" / f).write_bytes(f"face {f} v1\n".encode())
    _commit(env.kit, "kit gains a font tree")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    _commit(env.target, "target receives the tree")
    return env


def _recorded(env):
    return json.loads(
        (env.target / ".template-version").read_text(encoding="utf-8")
    )["rendered_checksums"]


# ----- projection ------------------------------------------------------------

def test_a_tree_entry_projects_every_file_in_it(sync_env):
    env = _with_tree(sync_env())
    assert (env.target / "fonts" / "A.ttf").read_bytes() == b"face A.ttf v1\n"
    assert (env.target / "fonts" / "B.ttf").read_bytes() == b"face B.ttf v1\n"
    # ...and each expanded destination is recorded individually, which is what
    # makes a later deletion decidable.
    rec = _recorded(env)
    assert "fonts/A.ttf" in rec and "fonts/B.ttf" in rec


def test_a_file_added_to_the_kit_tree_arrives_without_a_manifest_edit(sync_env):
    """The whole point of the tree: adding a face is a file, not a paired edit."""
    env = _with_tree(sync_env())
    (env.kit / "fonts" / "C.ttf").write_bytes(b"face C.ttf v1\n")
    _commit(env.kit, "new face")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "fonts" / "C.ttf").read_bytes() == b"face C.ttf v1\n"
    assert "fonts/C.ttf" in _recorded(env)


def test_a_modified_file_in_the_tree_updates(sync_env):
    env = _with_tree(sync_env())
    (env.kit / "fonts" / "A.ttf").write_bytes(b"face A.ttf v2\n")
    _commit(env.kit, "face v2")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "fonts" / "A.ttf").read_bytes() == b"face A.ttf v2\n"


def test_nested_namespaces_resolve_by_longest_match(sync_env):
    """`fonts/generated/**` is target-owned INSIDE the kit-owned `fonts/**`. Only
    longest-match makes the inner namespace mean anything; first-match would make
    the answer depend on the order the entries happen to appear in."""
    env = _with_tree(sync_env(), nested=True)
    m = kitmanifest.load(env.kit)
    assert m.classify("fonts/A.ttf").path == "fonts/**"
    assert m.classify("fonts/generated/subset.otf").path == "fonts/generated/**"
    assert m.classify("fonts/generated/subset.otf").policy == "never"

    # The file is claimed by the INNER namespace, not the outer one — so it
    # carries `never` (target-owned) rather than `identical` (kit-owned), and
    # sync therefore leaves it alone.
    (env.kit / "fonts" / "generated").mkdir()
    (env.kit / "fonts" / "generated" / "subset.otf").write_bytes(b"kit build output\n")
    _commit(env.kit, "kit generated face")
    by_dest = {p.dest: p for p in m.expanded_projections(env.kit, "pdf-only")}
    claimed = by_dest["fonts/generated/subset.otf"]
    assert claimed.policy == "never", "the kit-owned outer tree claimed a generated face"
    assert claimed.source.startswith("fonts/generated/")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert not (env.target / "fonts" / "generated" / "subset.otf").exists(), \
        "a never-tier destination was written into the target"


def test_a_tree_source_must_project_to_a_tree(tmp_path):
    """`fonts/**` -> `fonts/faces.ttf` would have every face in the tree claim one
    destination, and the last one copied would win silently."""
    (tmp_path / "kit-manifest.toml").write_text(
        '[[entry]]\npath = "fonts/**"\nlifecycle = "retained-in-kit"\n'
        'projects_to = "fonts/one.ttf"\npolicy = "identical"\n', encoding="utf-8")
    with pytest.raises(kitmanifest.ManifestError, match="directory tree"):
        kitmanifest.load(tmp_path)


# ----- deletion: the guard, clause by clause ---------------------------------

def test_a_file_deleted_upstream_is_deleted_in_the_target(sync_env):
    env = _with_tree(sync_env())
    (env.kit / "fonts" / "B.ttf").unlink()
    _commit(env.kit, "drop a face")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert not (env.target / "fonts" / "B.ttf").exists()
    assert (env.target / "fonts" / "A.ttf").exists(), "the wrong file was deleted"
    # The inventory is tidied too, or the next run would keep re-deciding it.
    assert "fonts/B.ttf" not in _recorded(env)


def test_a_locally_modified_file_deleted_upstream_is_refused_not_deleted(sync_env):
    """The point of recording checksums is to know the difference between a file
    sync wrote and one someone edited. Deleting the second is destroying work."""
    env = _with_tree(sync_env())
    (env.target / "fonts" / "B.ttf").write_bytes(b"the guide edited this\n")
    _commit(env.target, "local edit")
    (env.kit / "fonts" / "B.ttf").unlink()
    _commit(env.kit, "drop a face")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    assert (env.target / "fonts" / "B.ttf").read_bytes() == b"the guide edited this\n"


def test_an_unrecorded_file_in_a_managed_tree_is_never_deleted(sync_env):
    """A path sync never wrote is a path a guide put there. Sync does not delete
    what it did not create — the standing promise the tree does not revoke."""
    env = _with_tree(sync_env())
    (env.target / "fonts" / "guide-only.ttf").write_bytes(b"the guide's own face\n")
    _commit(env.target, "target-owned face inside a managed tree")

    (env.kit / "fonts" / "A.ttf").write_bytes(b"face A.ttf v2\n")
    _commit(env.kit, "unrelated update to drive an apply")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "fonts" / "guide-only.ttf").exists()


def test_removing_a_literal_manifest_entry_also_deletes(sync_env):
    """Deletion used to be scoped to managed TREES, on the reasoning that a
    literal entry disappearing was "someone editing the manifest" rather than an
    upstream deletion. That distinction orphaned `verify_pdf.py` in all seven
    targets when it became `verify_artifacts.py`, so the two are now one event
    under one set of guards. The guards themselves live in
    `tests/test_sync_literal_deletion.py`; this asserts only that a tree in the
    manifest does not change the answer for a literal entry alongside it."""
    env = _with_tree(sync_env())
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    manifest = manifest.replace(
        '[[entry]]\npath = "build.py"\nlifecycle = "retained-in-kit"\n'
        'projects_to = "build.py"\npolicy = "identical"\n', "")
    (env.kit / "kit-manifest.toml").write_text(manifest, encoding="utf-8")
    _commit(env.kit, "unclassify build.py")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert not (env.target / "build.py").exists(), "the removed entry's file survived"
    assert "build.py" not in _recorded(env)
    assert (env.target / "fonts" / "A.ttf").exists(), "the tree was collateral damage"


def test_a_deletion_rolls_back_with_the_rest_of_the_transaction(sync_env, monkeypatch):
    """Deletions ride the same journal as writes: if anything fails, the removed
    bytes come back with everything else."""
    env = _with_tree(sync_env())
    (env.kit / "fonts" / "B.ttf").unlink()
    (env.kit / "fonts" / "A.ttf").write_bytes(b"face A.ttf v2\n")
    _commit(env.kit, "drop one face, update another")

    # Fail AFTER the deletion has happened, not on the first write: aborting
    # before B.ttf is unlinked would let this pass with deletion journaling
    # removed entirely.
    seen = {"deleted": False}

    def explode(n):
        if not (env.target / "fonts" / "B.ttf").exists():
            seen["deleted"] = True
            raise RuntimeError("failure after the deletion")

    monkeypatch.setattr(sync, "AFTER_WRITE_HOOK", staticmethod(explode))
    with pytest.raises(RuntimeError):
        sync.run_sync(env.kit, env.target, apply=True)
    monkeypatch.setattr(sync, "AFTER_WRITE_HOOK", None)

    assert seen["deleted"], "the test never reached the deletion it claims to cover"
    assert (env.target / "fonts" / "B.ttf").read_bytes() == b"face B.ttf v1\n", \
        "the deletion was not rolled back"
    assert (env.target / "fonts" / "A.ttf").read_bytes() == b"face A.ttf v1\n"
    assert "fonts/B.ttf" in _recorded(env), "the inventory was not rolled back"


def test_an_inventory_key_cannot_escape_the_managed_tree(sync_env):
    """The inventory is JSON living in the TARGET repo, so its keys are input,
    not fact — and this is the one place a key decides that a file is deleted.
    `fonts/../guide.md` passes a raw prefix test and resolves to the guide's own
    file; a normalising check is what makes the prefix mean what it reads as."""
    env = _with_tree(sync_env())
    guide_md = (env.target / "guide.md").read_bytes()

    tv = json.loads((env.target / ".template-version").read_text(encoding="utf-8"))
    tv["rendered_checksums"]["fonts/../guide.md"] = sync._sha256(guide_md)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "a traversing inventory key")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "guide.md").read_bytes() == guide_md, \
        "a traversing inventory key deleted a target-owned file"


def test_a_destination_reclassified_as_target_owned_is_not_deleted(sync_env):
    """Reclassifying a file to `never` hands it to the guide. The ENCLOSING tree
    must not then read its absence from the projected set as an upstream
    deletion and remove the file the reclassification just gave away."""
    env = _with_tree(sync_env(), nested=True)
    (env.kit / "fonts" / "generated").mkdir(exist_ok=True)
    (env.target / "fonts" / "generated").mkdir(exist_ok=True)
    (env.target / "fonts" / "generated" / "subset.otf").write_bytes(b"built here\n")

    tv = json.loads((env.target / ".template-version").read_text(encoding="utf-8"))
    tv["rendered_checksums"]["fonts/generated/subset.otf"] = sync._sha256(b"built here\n")
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    (env.kit / "fonts" / "generated" / "subset.otf").write_bytes(b"built here\n")
    _commit(env.kit, "kit side")
    _commit(env.target, "previously managed, now target-owned")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "fonts" / "generated" / "subset.otf").exists(), \
        "the outer tree deleted a file the inner namespace made target-owned"


def test_a_record_for_a_file_gone_from_both_sides_is_forgotten(sync_env):
    """A stale record is not harmless: a later guide-authored file at that path
    is falsely refused, or — if its bytes happen to match — deleted."""
    env = _with_tree(sync_env())
    (env.kit / "fonts" / "B.ttf").unlink()
    (env.target / "fonts" / "B.ttf").unlink()
    _commit(env.kit, "drop a face")
    _commit(env.target, "drop it locally too")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert "fonts/B.ttf" not in _recorded(env), "a stale inventory record survived"


def test_a_symlinked_source_is_not_projected(sync_env):
    """`is_file()` follows symlinks, so a tracked link would have the expansion
    read bytes from outside the repository and copy them into every target."""
    env = _with_tree(sync_env())
    secret = env.kit.parent / "outside-the-kit.txt"
    secret.write_bytes(b"not the kit's to distribute\n")
    (env.kit / "fonts" / "linked.ttf").symlink_to(secret)
    _commit(env.kit, "a symlinked face")

    m = kitmanifest.load(env.kit)
    dests = {p.dest for p in m.expanded_projections(env.kit, "pdf-only")}
    assert "fonts/linked.ttf" not in dests
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert not (env.target / "fonts" / "linked.ttf").exists()


def test_a_target_owned_namespace_survives_the_kit_removing_its_file(sync_env):
    """The namespace, not the file listing, is what makes a path target-owned. A
    `never` file the kit has since deleted is absent from the expanded set, and
    the enclosing kit-owned tree would otherwise read that absence as an upstream
    deletion and remove the file the classification handed to the guide."""
    env = _with_tree(sync_env(), nested=True)
    (env.target / "fonts" / "generated").mkdir(exist_ok=True)
    (env.target / "fonts" / "generated" / "subset.otf").write_bytes(b"built here\n")
    tv = json.loads((env.target / ".template-version").read_text(encoding="utf-8"))
    tv["rendered_checksums"]["fonts/generated/subset.otf"] = sync._sha256(b"built here\n")
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "target-owned generated face")
    # The kit has NO fonts/generated/ at all — only the namespace declaration.
    assert not (env.kit / "fonts" / "generated").exists()

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    assert (env.target / "fonts" / "generated" / "subset.otf").exists(), \
        "a target-owned namespace was deleted through the enclosing tree"


def test_a_symlinked_tree_base_projects_nothing(sync_env, tmp_path):
    """Validating each file against `base.resolve()` is circular when the BASE is
    the link: it anchors the whole comparison outside the repository, so every
    external file passes."""
    env = _with_tree(sync_env(), faces=("A.ttf",))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "smuggled.ttf").write_bytes(b"not the kit's to distribute\n")

    import shutil
    shutil.rmtree(env.kit / "fonts")
    (env.kit / "fonts").symlink_to(outside)
    m = kitmanifest.load(env.kit)
    dests = {p.dest for p in m.expanded_projections(env.kit, "pdf-only")}
    assert "fonts/smuggled.ttf" not in dests


def test_untracked_droppings_in_a_tree_are_not_projected(sync_env):
    """`rglob` happily returns `.DS_Store` and `node_modules/` — gitignored, so
    they never dirty the kit, yet they would be copied into every target."""
    env = _with_tree(sync_env())
    (env.kit / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")
    _commit(env.kit, "ignore droppings")
    (env.kit / "fonts" / ".DS_Store").write_bytes(b"junk\n")

    m = kitmanifest.load(env.kit)
    dests = {p.dest for p in m.expanded_projections(env.kit, "pdf-only")}
    assert "fonts/.DS_Store" not in dests
    assert "fonts/A.ttf" in dests, "tracked faces stopped projecting"


def test_a_destination_replaced_by_a_symlink_is_refused(sync_env):
    """`exists()` is False for a BROKEN link, which would read as "already gone"
    and quietly forget the record while the link stayed."""
    env = _with_tree(sync_env())
    (env.target / "fonts" / "B.ttf").unlink()
    (env.target / "fonts" / "B.ttf").symlink_to(env.target / "nowhere.ttf")
    _commit(env.target, "a broken symlink where a face was")
    (env.kit / "fonts" / "B.ttf").unlink()
    _commit(env.kit, "drop the face upstream")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    assert (env.target / "fonts" / "B.ttf").is_symlink(), "the symlink was silently removed"
    assert "fonts/B.ttf" in _recorded(env), "the record was forgotten behind a symlink"


def test_a_managed_tree_whose_base_vanished_refuses_instead_of_mass_deleting(sync_env):
    """Expansion reads the KIT FILESYSTEM, so "the tree is empty" and "the tree
    could not be read" produce the same answer: no destinations. The manifest
    still declares `fonts/**`, and the git index still tracks the faces — but a
    sparse checkout, an interrupted clone or a mount that did not come up all
    present as an upstream deletion of every face at once.

    Deleting a whole managed tree across seven repositories on the strength of a
    directory that failed to appear is the wrong default. Fail closed instead:
    the entry is declared, the base is gone, so refuse and say so."""
    env = _with_tree(sync_env())
    import shutil
    shutil.rmtree(env.kit / "fonts")
    _commit(env.kit, "the tree's base is gone, its manifest entry is not")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    assert (env.target / "fonts" / "A.ttf").exists(), "a vanished base mass-deleted the tree"
    assert (env.target / "fonts" / "B.ttf").exists()
    assert "fonts/A.ttf" in _recorded(env)


def test_a_PARTIALLY_materialized_tree_refuses_too(sync_env):
    """A sparse checkout does not have to lose the whole directory. `fonts/` can
    be present with `fonts/B.ttf` absent while git still tracks it — and checking
    only the base then reports the tree readable, expansion silently omits B, and
    B is deleted in every target as an upstream removal.

    The precise question is not "does the directory exist" but "is every path git
    still TRACKS actually here". A face genuinely removed upstream is untracked by
    the commit that removed it, so this does not block real deletions."""
    env = _with_tree(sync_env())
    (env.kit / "fonts" / "B.ttf").unlink()          # gone from disk, still tracked

    items, _, _ = sync.build_plan(env.kit, env.target)
    by_dest = {it.dest_rel: it for it in items}
    assert "fonts/B.ttf" in by_dest, "the recorded face produced no plan item at all"
    assert by_dest["fonts/B.ttf"].action == "refuse", \
        f"a partially materialized tree yielded {by_dest['fonts/B.ttf'].action!r}"
    assert (env.target / "fonts" / "B.ttf").exists()


def test_an_unreadable_WEB_ONLY_tree_protects_a_pdf_only_target(sync_env):
    """`unreadable_tree_dests` has to be unioned over shapes for the same reason
    `dests_under_any_shape` is. Computed for the active shape alone, a pdf-only
    target skips a web-only tree entirely — so an unreadable web-only tree is
    invisible to the guard while its recorded destinations are still eligible for
    deletion, which is the worst of both answers."""
    env = sync_env(shape="web-enabled")
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    # web-only is DERIVED from `lifecycle = "bootstrap-source"`, not a manifest
    # key — declaring `web_only = true` would be silently ignored and the tree
    # would project into a pdf-only target, making this test vacuous.
    manifest += ('\n[[entry]]\npath = "webfonts/**"\nlifecycle = "bootstrap-source"\n'
                 'projects_to = "webfonts/**"\npolicy = "identical"\n')
    (env.kit / "kit-manifest.toml").write_text(manifest, encoding="utf-8")
    (env.kit / "webfonts").mkdir()
    (env.kit / "webfonts" / "W.woff2").write_bytes(b"web face v1\n")
    _commit(env.kit, "a web-only font tree")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    _commit(env.target, "target receives the web tree")
    assert "webfonts/W.woff2" in _recorded(env)

    # The kit's web tree becomes unreadable, and the target drops to pdf-only.
    import shutil
    shutil.rmtree(env.kit / "webfonts")
    _commit(env.kit, "the web tree's base is gone, its entry is not")
    from conftest import _guide_toml  # noqa: PLC0415
    (env.target / "guide.toml").write_text(_guide_toml("probe-guide", site="none"),
                                           encoding="utf-8")
    _commit(env.target, "drop to pdf-only")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_DRIFT
    assert (env.target / "webfonts" / "W.woff2").exists(), \
        "an unreadable web-only tree was mass-deleted on a pdf-only target"


def test_a_dry_run_reports_the_deletion_and_writes_nothing(sync_env):
    env = _with_tree(sync_env())
    (env.kit / "fonts" / "B.ttf").unlink()
    _commit(env.kit, "drop a face")

    assert sync.run_sync(env.kit, env.target, apply=False) == sync.EXIT_DRIFT
    assert (env.target / "fonts" / "B.ttf").exists(), "a dry run deleted a file"
