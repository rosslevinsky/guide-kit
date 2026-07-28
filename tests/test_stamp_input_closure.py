"""The stamp-input closure: every file `content_hash()` reads is also a file the
dirty/release/staleness guards watch.

WHY THIS EXISTS. Bundling fonts widened the version stamp's input set —
`kitconfig.content_hash()` hashes the bundled faces as well as SOURCE_FILES,
because swapping a face changes the PDF's typography exactly as editing
style.css does. But the guards that decide "is the tree clean enough to bless a
reference PDF" were all scoped to SOURCE_FILES alone, so the two sets diverged.

The reachable failure that gap allows: edit a bundled face without committing
it. `content_hash()` moves, so the freshly rendered PDF carries a NEW stamp —
but `_is_dirty()` looks only at SOURCE_FILES, sees a clean tree, and omits the
` · dirty` marker. `make baseline` (guard 2, same scope) does not refuse. A
reference PDF is promoted from uncommitted font bytes wearing a stamp that
claims to be reproducible, and no committed state will ever reproduce it.

So the invariant these tests pin is a closure property, not a feature: the set
of paths feeding the hash and the set of paths watched by the guards must be the
same set. `stamp_pathspec()` scopes git to it and `is_stamp_input()` decides
membership; the tests assert each consumer actually uses them.

DELETION is the case worth naming, because the obvious implementation gets it
wrong. A list built by walking `fonts/` can only name faces that still exist —
so deleting a tracked face drops it from the very pathspec meant to notice the
deletion, and the falsely-clean tree comes back by the other door. Hence a
pattern pathspec (git matches it against the index too) and a name predicate
rather than a disk lookup.
"""
import subprocess

import pytest

import kitconfig


GUIDE_TOML = (
    'TITLE = "Probe"\n'
    'OUTPUT_SLUG = "probe-guide"\n'
    'AUTHOR = "T"\n'
    'DESCRIPTION = "d"\n'
    'KEYWORDS = "k"\n'
    'COPYRIGHT_YEAR = 2026\n'
    '[outputs]\n'
    'pdf = true\n'
    'site = "none"\n'
    'slides = false\n'
    '[artifacts.pdf]\n'
    'date = "2026-07-26"\n'
)


def _mkrepo(tmp_path, with_fonts=True):
    (tmp_path / "guide.toml").write_text(GUIDE_TOML, encoding="utf-8")
    for name in kitconfig.SOURCE_FILES:
        if name != "guide.toml":
            # SOURCE_FILES now contains a NESTED path (fontconfig/fonts.conf),
            # so a flat write is no longer enough.
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text(f"seed-{name}\n", encoding="utf-8")
    if with_fonts:
        d = tmp_path / kitconfig.FONT_DIR
        d.mkdir(parents=True, exist_ok=True)
        # Content, not real font tables: nothing here parses a font, these
        # tests are about which PATHS are watched.
        (d / "Alpha-Regular.otf").write_bytes(b"alpha-bytes")
        (d / "Beta-Bold.ttf").write_bytes(b"beta-bytes")
        (d / "README.md").write_text("not a face\n", encoding="utf-8")
    return tmp_path


def test_pathspec_is_source_files_then_face_patterns():
    got = kitconfig.stamp_pathspec()

    assert got[: len(kitconfig.SOURCE_FILES)] == [
        f":(literal){n}" for n in kitconfig.SOURCE_FILES
    ]
    # Patterns, not a walked file list — see the deletion note in the module
    # docstring. `:(glob)` keeps `*` from crossing `/`, matching font_files()'s
    # non-recursive scan.
    # Derived from FONT_DIR, not hardcoded: the faces moved from flat `fonts/`
    # into the `fonts/vendor/` ownership namespace, and a test that spells the
    # directory out is a test that has to be swept every time the layout moves.
    faces = [
        f":(glob,icase){d}/*{suffix}"
        for d in (kitconfig.FONT_DIR, kitconfig.GENERATED_FONT_DIR)
        for suffix in (".otf", ".ttf", ".woff2")
    ]
    # Then the asset trees. RECURSIVE `**`, unlike the faces: an author organises
    # images into subdirectories, and a non-recursive pattern would leave the
    # dirty check blind to everything below the top level — the stamp would claim
    # clean over an edited figure.
    assets = [f":(glob,icase){d}/**"
              for d in (kitconfig.ASSET_SHARED_DIR, kitconfig.ASSET_PRINT_DIR)]
    assert got[len(kitconfig.SOURCE_FILES):] == faces + assets
    assert kitconfig.FONT_DIR == "fonts/vendor", "the namespace moved without this test noticing"
    # `assets/web` is absent ON PURPOSE: it is not a PDF input, so an uncommitted
    # screen image must not make the PDF's stamp read `· dirty`.
    assert not any(kitconfig.ASSET_WEB_DIR in g for g in got)


@pytest.mark.parametrize(
    "path, expected",
    [
        ("guide.md", True),
        ("style.css", True),
        ("fonts/vendor/Alpha-Regular.otf", True),
        ("fonts/vendor/Beta-Bold.TTF", True),          # suffix match is case-insensitive
        ("fonts/vendor/README.md", False),             # not a render input
        ("fonts/vendor/LICENSE-DejaVu.txt", False),
        ("fonts/vendor/sub/Nested.otf", False),        # font_files() is non-recursive
        ("style-screen.css", False),            # screen-only, never in the stamp
        ("app/dist/index.html", False),
        # THE GLOB DEPS, which the predicate could not see at all. `file_deps`
        # holds patterns, and membership was tested with `in` — string equality
        # — so every glob answered False for every real path under it.
        ("assets/shared/diagram.pdf", True),    # a declared PDF input
        ("assets/print/figure.svg", True),
        ("assets/shared/nested/deep.png", True),   # `**` spans separators
        ("assets/web/og.png", False),           # site-only: not a PDF input
        ("assets/shared2/x.pdf", False),        # the separator is load-bearing
    ],
)
def test_is_stamp_input_membership(path, expected):
    assert kitconfig.is_stamp_input(path) is expected


@pytest.mark.parametrize(
    "path, expected",
    [
        ("assets/shared/diagram.pdf", True),
        ("assets/print/figure.svg", True),
        ("assets/web/og.png", True),            # site input — authorable, not stamped
        ("fonts/vendor/Alpha-Regular.otf", True),
        ("fonts/vendor/sub/Nested.otf", False),
        ("style-screen.css", True),
        ("README.md", False),
    ],
)
def test_is_authorable_membership(path, expected):
    """THE DEFECT: editing a tracked asset made `make release` refuse.

    `release.py:_ensure_clean_state` rejects any changed path outside the
    authorable set. `assets/shared/**` is a declared input of the PDF being
    released, and `is_authorable` answered False for every file under it — so
    the one command that exists to publish a change refused the change.
    """
    assert kitconfig.is_authorable(path) is expected


def test_the_authorable_globs_are_derived_from_the_specs():
    """Listed by hand, this set was the font globs alone and silently omitted
    `assets/**`. Derived, a spec that gains a glob cannot leave it behind."""
    declared = {f for spec in kitconfig._ARTIFACT_SPECS.values()
                for f in spec.file_deps if "*" in f}
    resolved = {kitconfig._with_defaults(f) for f in declared}
    missing = sorted(resolved - set(kitconfig.AUTHORABLE_GLOBS))
    assert not missing, f"glob deps missing from AUTHORABLE_GLOBS: {missing}"


def test_a_release_admits_an_asset_edit(tmp_path):
    """End-to-end through the predicate release.py actually calls, with a real
    config — the static-defaults form is a different code path."""
    repo = _mkrepo(tmp_path)
    cfg = kitconfig.load(repo)
    assert kitconfig.is_authorable("assets/shared/diagram.pdf", cfg)
    assert kitconfig.is_authorable("assets/web/og.png", cfg)


def test_is_stamp_input_answers_for_paths_not_on_disk(tmp_path):
    """The deletion case, at the predicate level: a face that no longer exists
    is still a stamp input, because its removal changes the hash. A disk-based
    check would answer False for exactly the path that most needs staging."""
    assert kitconfig.is_stamp_input("fonts/vendor/Deleted-Face.otf") is True


def test_pathspec_covers_every_path_content_hash_reads(tmp_path):
    """The closure property itself: mutating any path the pathspec matches moves
    the hash, and no unmatched path does. This is what keeps the two sets from
    drifting apart the next time a render input is added."""
    repo = _mkrepo(tmp_path)
    baseline = kitconfig.content_hash(repo)

    watched = [
        *(n for n in kitconfig.SOURCE_FILES if (repo / n).exists() and n != "guide.toml"),
        "fonts/vendor/Alpha-Regular.otf",
        "fonts/vendor/Beta-Bold.ttf",
    ]
    for rel in watched:
        p = repo / rel
        original = p.read_bytes()
        p.write_bytes(original + b"x")
        assert kitconfig.content_hash(repo) != baseline, (
            f"{rel} is a watched stamp input but editing it does not move the hash"
        )
        p.write_bytes(original)
    assert kitconfig.content_hash(repo) == baseline

    # guide.toml is watched too, but it reaches the hash KEY-LEVEL: it is parsed,
    # not hashed as bytes. So the meaningful mutation is a value change, not
    # appended bytes (which would simply be invalid TOML).
    toml = repo / "guide.toml"
    original = toml.read_text(encoding="utf-8")
    toml.write_text(original.replace('TITLE = "Probe"', 'TITLE = "Moved"'), encoding="utf-8")
    assert kitconfig.content_hash(repo) != baseline, (
        "guide.toml is a watched stamp input but changing an in-closure key does "
        "not move the hash"
    )
    toml.write_text(original, encoding="utf-8")
    assert kitconfig.content_hash(repo) == baseline

    # The other direction: a file under fonts/ that is NOT a face must not move
    # the hash, or an unrelated README edit would stale every reference.
    readme = repo / "fonts" / "vendor" / "README.md"
    readme.write_text("edited\n", encoding="utf-8")
    assert kitconfig.content_hash(repo) == baseline
    assert not kitconfig.is_stamp_input("fonts/vendor/README.md")


def test_deleting_a_face_moves_the_hash(tmp_path):
    """The premise the deletion guard rests on: removal is a render change."""
    repo = _mkrepo(tmp_path)
    baseline = kitconfig.content_hash(repo)
    (repo / "fonts" / "vendor" / "Alpha-Regular.otf").unlink()
    assert kitconfig.content_hash(repo) != baseline


@pytest.mark.parametrize(
    "module_name, func_name",
    [("buildcore", "_is_dirty"), ("baseline", "_dirty_source_files")],
)
def test_dirty_guards_watch_font_files(tmp_path, monkeypatch, module_name, func_name):
    """An uncommitted font edit must read as dirty. Before the closure fix both
    guards scoped `git status` to SOURCE_FILES and returned clean."""
    repo = _mkrepo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "seed"],
        cwd=repo, check=True,
    )

    mod = pytest.importorskip(module_name)
    monkeypatch.setattr(mod, "ROOT", repo)

    assert not _dirty_result(mod, func_name), "clean tree should not read dirty"

    face = repo / "fonts" / "vendor" / "Alpha-Regular.otf"
    original = face.read_bytes()

    face.write_bytes(b"swapped-face")
    assert _dirty_result(mod, func_name), (
        "an uncommitted bundled-font edit must read as dirty — otherwise "
        "`make baseline` blesses a reference no committed state reproduces"
    )
    face.write_bytes(original)
    assert not _dirty_result(mod, func_name)

    # DELETION, the case a walked file list cannot see: the path is gone, so a
    # list built from disk would not name it and git would be asked about
    # nothing at all.
    face.unlink()
    assert _dirty_result(mod, func_name), (
        "deleting a tracked face must read as dirty — its removal changes "
        "content_hash() just as an edit does"
    )
    face.write_bytes(original)

    # A non-face file under fonts/ must NOT read as dirty: it is not a render
    # input, and staling every reference on a README edit would be wrong.
    (repo / "fonts" / "vendor" / "README.md").write_text("edited\n", encoding="utf-8")
    assert not _dirty_result(mod, func_name)


def _dirty_result(mod, func_name):
    """Call the module's dirty check, passing a config when it takes one.

    `baseline._dirty_source_files` REQUIRES a config: without one,
    `stamp_pathspec()` resolves `themes/<theme>/print.css` against the schema
    default, and a guide on a non-default theme had its real theme file invisible
    to the guard. Calling it config-less here would re-test the bug.
    """
    import inspect

    import kitconfig

    fn = getattr(mod, func_name)
    if "cfg" in inspect.signature(fn).parameters:
        return bool(fn(kitconfig.load(mod.ROOT)))
    return bool(fn())
