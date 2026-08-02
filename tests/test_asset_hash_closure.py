"""Binary assets are in the artifact closures BY CONTENT HASH.

The defect this closes was already recorded in `CLAUDE.md` before it was fixed:
`render_pdf.py` passes the repo root as WeasyPrint's `base_url`, so an external file
*would* resolve in the PDF — but nothing tracked `assets/` in `SOURCE_FILES` or
the content hash, so **editing a diagram there changed the PDF while
`make verify` stayed green**. That is why every diagram in this family is inlined
SVG today, and it is what these tests stop.

The namespaces are SIBLINGS and never nest — `assets/shared`, `assets/print`,
`assets/web` — for the same reason `fonts/vendor` and `fonts/generated` are
siblings. Nested, the enclosing tree's expansion can swallow the inner one, and
here it would also put a screen-only image into the PDF's closure, which is the
one thing the split exists to prevent.
"""
import shutil

import pytest

import kitconfig

from conftest import render  # noqa: PLC0415 — the fixture's own helper

_PNG_A = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001" "0d0a2db4" "0000000049454e44ae426082")
_PNG_B = _PNG_A[:-16] + b"\x00" * 8 + _PNG_A[-8:]


def _write(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _hashes(root):
    return (kitconfig.artifact_closure_hash("pdf", root=root),
            kitconfig.artifact_closure_hash("site", root=root))


# ----- the closure moves with the BYTES ----------------------------------------

def test_a_shared_asset_is_in_both_closures(guide_repo):
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    before = _hashes(root)
    _write(root, "assets/shared/diagram.png", _PNG_A)
    after = _hashes(root)
    assert after[0] != before[0], "the PDF closure ignored a shared asset"
    assert after[1] != before[1], "the site closure ignored a shared asset"


def test_swapping_the_bytes_restales_without_a_rename(guide_repo):
    """The criterion, stated exactly: same name, different bytes, hash moves.
    A name-only closure would report this file as unchanged."""
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    _write(root, "assets/shared/diagram.png", _PNG_A)
    before = _hashes(root)
    _write(root, "assets/shared/diagram.png", _PNG_B)
    after = _hashes(root)
    assert after != before, "swapping an image's bytes did not re-stale anything"


def test_a_web_only_asset_leaves_the_pdf_closure_alone(guide_repo):
    """The whole point of the split. A screen image must not be a PDF input, or
    every web-side change re-baselines a document that did not change."""
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    pdf_before, site_before = _hashes(root)
    _write(root, "assets/web/hero.png", _PNG_A)
    pdf_after, site_after = _hashes(root)
    assert pdf_after == pdf_before, "a web-only asset entered the PDF's closure"
    assert site_after != site_before, "the site closure ignored its own asset"


def test_a_print_only_asset_leaves_the_site_closure_alone(guide_repo):
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    pdf_before, site_before = _hashes(root)
    _write(root, "assets/print/plate.png", _PNG_A)
    pdf_after, site_after = _hashes(root)
    assert pdf_after != pdf_before, "the PDF closure ignored a print asset"
    assert site_after == site_before, "a print-only asset entered the site's closure"


def test_a_nested_asset_is_still_covered(guide_repo):
    """Authors organise images in subdirectories. A non-recursive glob would
    hash the top level and silently ignore everything below it."""
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    before = _hashes(root)
    _write(root, "assets/shared/chapter-3/figure-2.png", _PNG_A)
    assert _hashes(root) != before, "a nested asset was not hashed"


def test_the_closure_hash_is_stable_across_repeat_reads(guide_repo):
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    _write(root, "assets/shared/a.png", _PNG_A)
    _write(root, "assets/shared/b/c.png", _PNG_B)
    assert _hashes(root) == _hashes(root)


def test_a_symlinked_asset_is_not_hashed(guide_repo):
    """`is_file()` follows symlinks, so a link pointing outside the repo would
    contribute bytes the artifact does not contain — the same hazard the font
    tree's expansion already guards against."""
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    outside = root.parent / "outside.png"
    outside.write_bytes(_PNG_A)
    (root / "assets" / "shared").mkdir(parents=True, exist_ok=True)
    before = _hashes(root)
    (root / "assets" / "shared" / "linked.png").symlink_to(outside)
    assert _hashes(root) == before, "a symlinked asset joined the closure"


# ----- the built site actually carries them ------------------------------------

def test_assets_are_copied_into_the_built_site(guide_repo):
    """Cloudflare serves `app/dist` and nothing else, so an asset that is not
    copied does not exist — `build_web()` had no asset-copy path at all."""
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    _write(root, "assets/shared/diagram.png", _PNG_A)
    _write(root, "assets/web/hero.png", _PNG_B)
    _write(root, "assets/shared/nested/deep.png", _PNG_A)
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    # At their own paths — `shared/` and `web/` are preserved, not flattened, so
    # the path an author writes in guide.md is the path the site serves.
    dist = root / "app" / "dist" / "assets"
    assert (dist / "shared" / "diagram.png").is_file()
    assert (dist / "web" / "hero.png").is_file()
    assert (dist / "shared" / "nested" / "deep.png").is_file(), "nested assets were not copied"


def test_print_only_assets_are_not_published_to_the_web(guide_repo):
    """They are not a site input, so shipping them would put bytes on the web
    that the site's own closure hash does not cover."""
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    _write(root, "assets/print/plate.png", _PNG_A)
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    assert not (root / "app" / "dist" / "assets" / "plate.png").exists()


def test_one_markdown_path_resolves_in_BOTH_outputs(guide_repo):
    """The whole point of the asset namespaces: one spelling in `guide.md` works
    in the PDF and on the site.

    ASSERTED ON BOTH SIDES, which is what this test used to miss. It checked only
    that the site published the file, under the name the FLATTENED copy gave it —
    the true half of a broken pair. The PDF resolves against the repo root, where
    the file is at `assets/shared/x.png`, so the flattened `dist/assets/x.png`
    meant `assets/shared/…` rendered in print and 404'd on the web while
    `assets/…` did the reverse. Neither spelling worked in both, and WeasyPrint
    does not fail a build on a missing image, so the print half was silent.
    """
    root, write_toml = guide_repo
    write_toml(outputs={"pdf": True, "site": "single", "slides": False})
    _write(root, "assets/shared/x.png", _PNG_A)
    _write(root, "assets/web/x.png", _PNG_B)
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")

    used = "assets/shared/x.png"                       # what an author writes
    assert (root / used).read_bytes() == _PNG_A, "the PDF's base_url is the repo root"
    assert (root / "app" / "dist" / used).read_bytes() == _PNG_A, (
        "the site must serve the asset at the SAME path the markdown uses, or "
        "one output resolves it and the other 404s"
    )
    # ...and the two namespaces must not collide at one destination.
    assert (root / "app" / "dist" / "assets" / "web" / "x.png").read_bytes() == _PNG_B
