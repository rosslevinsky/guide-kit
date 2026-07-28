"""`fonts/vendor/**` and `fonts/generated/**` as SEPARATE, NON-NESTING namespaces.

Non-nesting is a correctness property, not tidiness. While `fonts/**` was the
outer namespace, a target-owned generated subset lived INSIDE a kit-managed
tree, and the only things keeping a sync from erasing it were longest-match
precedence and an explicit carve-out in the deletion guard — two mechanisms
holding back a mistake the layout can simply not permit.

The other half of the move is the closure. `font_files()` and the stamp globs
are non-recursive BY DESIGN, so relocating the faces one directory deeper is
exactly the change that could drop every face out of the version stamp while
every test still passed.
"""
import subprocess

import pytest

import kitconfig
import kitmanifest
import sync


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def test_the_namespaces_are_siblings_not_nested():
    m = kitmanifest.load(kitconfig._root(None))
    paths = {e.path for e in m.entries}
    assert "fonts/vendor/**" in paths
    assert "fonts/generated/**" in paths
    assert "fonts/**" not in paths, \
        "the outer namespace is back — generated output would sit inside a kit-managed tree"


def test_each_namespace_carries_its_own_ownership():
    m = kitmanifest.load(kitconfig._root(None))
    vendor = m.classify("fonts/vendor/SourceSans3-Regular.otf")
    generated = m.classify("fonts/generated/subset-jp.otf")
    assert vendor.policy == "identical" and vendor.lifecycle == "retained-in-kit"
    assert generated.policy == "never" and generated.lifecycle == "generated"


def test_a_generated_subset_is_not_claimed_by_the_vendor_namespace():
    """Neither prefix is a prefix of the other, so this is now decided by the
    layout rather than by precedence."""
    m = kitmanifest.load(kitconfig._root(None))
    assert m.classify("fonts/generated/subset-jp.otf").path == "fonts/generated/**"
    assert m.classify("fonts/vendor/DejaVuSans.ttf").path == "fonts/vendor/**"


def test_a_generated_subset_survives_a_sync_that_rewrites_vendor(sync_env):
    """The property the split exists for: the kit owning `fonts/vendor/` must not
    give it any claim over `fonts/generated/`."""
    env = sync_env()
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    manifest += (
        '\n[[entry]]\npath = "fonts/vendor/**"\nlifecycle = "retained-in-kit"\n'
        'projects_to = "fonts/vendor/**"\npolicy = "identical"\n'
        '\n[[entry]]\npath = "fonts/generated/**"\nlifecycle = "generated"\n'
        'projects_to = "fonts/generated/**"\npolicy = "never"\n')
    (env.kit / "kit-manifest.toml").write_text(manifest, encoding="utf-8")
    (env.kit / "fonts" / "vendor").mkdir(parents=True)
    (env.kit / "fonts" / "vendor" / "Face.otf").write_bytes(b"v1\n")
    _commit(env.kit, "kit vendor face")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    _commit(env.target, "received the face")

    # The target builds its own subset. The kit has no such directory at all.
    (env.target / "fonts" / "generated").mkdir(parents=True)
    (env.target / "fonts" / "generated" / "subset-jp.otf").write_bytes(b"built here\n")
    _commit(env.target, "target-owned subset")

    (env.kit / "fonts" / "vendor" / "Face.otf").write_bytes(b"v2\n")
    _commit(env.kit, "vendor face v2")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK

    assert (env.target / "fonts" / "vendor" / "Face.otf").read_bytes() == b"v2\n"
    assert (env.target / "fonts" / "generated" / "subset-jp.otf").read_bytes() == b"built here\n", \
        "a sync of the vendor namespace touched target-owned generated output"


# ----- the closure moved WITH the faces ---------------------------------------

def test_a_vendored_face_is_still_hashed(tmp_path):
    """`font_files()` scans one directory, non-recursively. Moving the faces a
    level deeper without moving the scan drops every one of them out of the
    version stamp — silently, because the hash still computes."""
    faces = kitconfig.font_files(kitconfig._root(None))
    assert faces, "font_files() found nothing after the move"
    assert all(p.parent.name == "vendor" for p in faces)


def test_a_vendored_face_is_still_watched():
    """The dirty guard and the closure must ask about the SAME set, or an
    uncommitted face change moves the hash while the stamp claims clean."""
    spec = kitconfig.stamp_pathspec("pdf")
    assert f":(glob,icase){kitconfig.FONT_DIR}/*.otf" in spec
    assert kitconfig.is_stamp_input("fonts/vendor/Anything.otf") is True
    assert kitconfig.is_authorable("fonts/vendor/Anything.otf") is True


@pytest.mark.parametrize("path, expected", [
    ("fonts/vendor/Alpha-Regular.otf", True),
    ("fonts/vendor/Beta-Bold.TTF", True),        # suffix match is case-insensitive
    ("fonts/vendor/README.md", False),           # not a render input
    ("fonts/vendor/OFL.txt", False),
    ("fonts/vendor/sub/Nested.otf", False),      # the scan is non-recursive
    ("fonts/Alpha-Regular.otf", False),          # the OLD flat layout is not an input
    # Target-OWNED (sync never writes it) but still a RENDER INPUT: the bytes
    # reach the page, so they are hashed and watched like any other face.
    ("fonts/generated/subset-jp.otf", True),
])
def test_font_membership_after_the_move(path, expected):
    assert kitconfig.is_stamp_input(path) is expected


def test_the_old_flat_layout_is_gone():
    """A face left behind in `fonts/` would be invisible to the closure while
    still sitting in the repository — the worst of both."""
    fonts = kitconfig._root(None) / "fonts"
    strays = [p.name for p in fonts.iterdir()
              if p.is_file() and p.suffix.lower() in (".otf", ".ttf", ".woff2")]
    assert strays == [], f"faces left flat in fonts/: {strays}"
