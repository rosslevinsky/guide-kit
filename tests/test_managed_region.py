"""managed-region: replace only the kit:begin/end block; preserve the rest;
error clearly on missing / malformed / duplicate / reversed / nested markers."""
import subprocess
from pathlib import Path

import pytest

import sync

B, E = sync.MARK_BEGIN, sync.MARK_END
REPO_ROOT = Path(__file__).resolve().parent.parent


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def test_replaces_only_the_marked_block(sync_env):
    env = sync_env()
    (env.kit / "CLAUDE.md").write_text(f"# Kit\n{B}\nshared policy v2 UPDATED\n{E}\nkit tail\n", encoding="utf-8")
    _commit(env.kit, "kit CLAUDE v2")
    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    out = (env.target / "CLAUDE.md").read_text()
    assert "shared policy v2 UPDATED" in out                 # block updated
    assert "TARGET-OWNED section the guide maintains." in out  # outside preserved
    assert out.startswith("# probe-guide")                    # target heading preserved


def test_region_extraction():
    assert sync._region(f"a{B}X{E}b", "t") == "X"


@pytest.mark.parametrize("bad", [
    "no markers here",                          # missing
    f"{B}only begin",                           # missing end
    f"{E}only end",                             # missing begin
    f"{B}a{E}{B}b{E}",                          # duplicate
    f"{E}reversed{B}",                          # reversed
    f"{B}outer{B}inner{E}{E}",                  # nested
])
def test_marker_errors(bad):
    with pytest.raises(sync.SyncError):
        sync._region(bad, "fixture")


def test_crlf_outside_markers_preserved_verbatim(sync_env):
    # Universal-newline reads would rewrite the target's own CRLF text to LF when
    # updating the managed block. It must be preserved byte-for-byte.
    import json
    env = sync_env()
    claude = env.target / "CLAUDE.md"
    content = (f"# probe-guide\r\n{B}\nshared policy v1\n{E}\r\nTARGET CRLF tail\r\n")
    claude.write_bytes(content.encode("utf-8"))
    # keep the record consistent with the rewritten (region-only) content
    tv = json.loads((env.target / ".template-version").read_text())
    tv["rendered_checksums"]["CLAUDE.md"] = sync._sha256(
        sync._checkable_bytes("managed-region", claude.read_bytes())
    )
    (env.target / ".template-version").write_text(json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "crlf claude")
    (env.kit / "CLAUDE.md").write_text(
        f"# Kit\n{B}\nshared policy v2 UPDATED\n{E}\nkit tail\n", encoding="utf-8"
    )
    _commit(env.kit, "kit v2")

    assert sync.run_sync(env.kit, env.target, apply=True) == sync.EXIT_OK
    out = claude.read_bytes()
    assert b"shared policy v2 UPDATED" in out       # block updated
    assert b"TARGET CRLF tail\r\n" in out            # CRLF preserved verbatim
    assert b"# probe-guide\r\n" in out               # CRLF before the block too


def test_real_kit_claude_has_exactly_one_wellformed_region():
    """The shipped kit CLAUDE.md carries exactly one well-formed marker pair, and
    its managed region is real, slug-agnostic content — no leftover placeholders."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    # Exactly-one-pair is enforced by _marker_span; it raises on 0, 2+, or reversed.
    region = sync._region(text, "kit CLAUDE.md")
    assert region.strip(), "the real kit's managed region must not be empty"
    # The synced region is shared across every guide, so it must be placeholder-free
    # (a stray {{...}} or __TITLE__ would be copied verbatim into every target).
    assert "{{" not in region and "}}" not in region
    assert "__TITLE__" not in region and "__VERSION__" not in region
    # And there is real shared policy inside, not just whitespace/markers.
    assert "guide.toml" in region and "sync.py" in region


def test_real_kit_region_roundtrips_target_specific_sections_verbatim():
    """Applying the real kit's region onto a sample target replaces only the block:
    the target's guide-specific sections (before AND after the markers) survive
    byte-for-byte, and the region becomes exactly the kit's."""
    kit_text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    head = "# probe-guide\n\n## Exercise format\n\nGuide-OWNED prose the kit must never touch.\n\n"
    tail = "\n## Appendix\n\nMore guide-OWNED prose, after the block.\n"
    target = f"{head}{B}\nstale shared policy the kit will overwrite\n{E}{tail}"

    rendered = sync._render_managed(target, kit_text)

    # Guide-specific sections outside the markers are preserved verbatim.
    assert rendered.startswith(head), "text before the block was altered"
    assert rendered.endswith(tail), "text after the block was altered"
    assert "stale shared policy the kit will overwrite" not in rendered  # block replaced
    # The rendered region is byte-identical to the kit's region.
    assert sync._region(rendered, "rendered") == sync._region(kit_text, "kit CLAUDE.md")
    # Idempotent: re-applying makes no further change.
    assert sync._render_managed(rendered, kit_text) == rendered


def test_malformed_kit_source_is_reported(sync_env):
    env = sync_env()
    # kit CLAUDE.md loses its markers -> sync must error, not silently clobber.
    (env.kit / "CLAUDE.md").write_text("# Kit with no markers at all\n", encoding="utf-8")
    _commit(env.kit, "kit CLAUDE broken")
    with pytest.raises(sync.SyncError):
        sync.run_sync(env.kit, env.target, apply=True)
