"""The one-time font-table audit: which face did each run ACTUALLY select?

`pdffonts` answers a weaker question — it lists what a document EMBEDS, so it is
satisfied the moment every embedded face is bundled, INCLUDING when a run picked
the wrong bundled one. Coverage is satisfied too, because the wrong face may well
contain the glyph. A heading rendered in the body face, or a bold run resolving
to the regular weight, passes both permanent checks.

That is the live risk after the theme layer changed the cascade, which is why the
audit reads content streams rather than the font list.

`ToUnicode` is deliberately NOT used as the code->CID map. It maps codes to
TEXT, for extraction and search; the decode chain is
`code --/Encoding--> CID --/CIDToGIDMap--> GID`, and conflating them is a common
and wrong shortcut.
"""
import shutil
import subprocess

import pytest

import buildcore
import pdfaudit

pytestmark = pytest.mark.skipif(
    shutil.which("qpdf") is None and not (buildcore.ROOT / ".pixi").exists(),
    reason="qpdf is unavailable")


@pytest.fixture(scope="module")
def pdf():
    p = buildcore.OUT_PDF
    if not p.is_file():
        r = subprocess.run(["pixi", "run", "build"], cwd=buildcore.ROOT,
                           capture_output=True, text=True, timeout=900)
        assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    assert p.is_file()
    return p


def test_every_font_is_type0_identity_h(pdf):
    """The audit decodes Identity-H only. Anything else must be REPORTED as
    unaudited rather than silently assumed fine — a check whose reach is unclear
    is worse than no check."""
    table = pdfaudit.font_table(pdf)
    assert table, "no Type0 fonts found at all"
    unauditable = [r["base_font"] for r in table.values() if not r.get("auditable")]
    assert unauditable == [], f"fonts this audit cannot decode: {unauditable}"


def test_runs_resolve_to_real_face_names(pdf):
    """The resource name in a content stream is `/BRGFIG`, a subset tag. Reporting
    that instead of `Guide-Serif` would make the audit unable to answer its own
    question — which is what happened until the indirect `/Font N 0 R` reference
    was followed."""
    runs = pdfaudit.runs(pdf)
    assert runs, "no text-showing runs found"
    families = {r.family for r in runs}
    assert all(f.startswith("Guide-") for f in families), families


def test_no_run_draws_glyph_zero(pdf):
    """Glyph 0 is `.notdef` — tofu. Coverage asks whether a face COULD draw a
    character; this asks what the renderer actually put on the page."""
    notdef = pdfaudit.notdef_runs(pdf)
    assert notdef == [], \
        f"{len(notdef)} run(s) drew .notdef: {sorted({r.family for r in notdef})}"


def test_the_faces_used_are_a_subset_of_those_embedded(pdf):
    """A face can be embedded and never used; the reverse would mean the audit is
    misreading the content stream."""
    used = pdfaudit.faces_used(pdf)
    embedded = {r["base_font"].split("+", 1)[-1]
                for r in pdfaudit.font_table(pdf).values()}
    assert used <= embedded, f"used but not embedded: {sorted(used - embedded)}"


def test_the_selected_faces_match_the_theme(pdf):
    """The audit's actual job. Under `editorial` the body is SERIF, so a run in
    Guide-Sans would mean the cascade resolved differently from the declaration —
    invisible to pdffonts and to coverage, because Guide-Sans is bundled and does
    contain the glyphs."""
    theme = buildcore._cfg.theme.name
    used = pdfaudit.faces_used(pdf)
    if theme == "editorial":
        assert any(f.startswith("Guide-Serif") for f in used)
        assert not any(f.startswith("Guide-Sans") for f in used), \
            f"the serif theme selected a sans face: {sorted(used)}"


# The ANCHORED manifest: source text -> the face it MUST be drawn in. This is the
# check a document-wide allow-list cannot make. When both Guide-Serif and
# Guide-Serif-Bold are legitimately used somewhere, a heading falling back to the
# body face changes no set — only an expectation tied to specific text notices.
ANCHORS = {
    "Welcome": "Guide-Serif-Bold",                              # a heading
    "This placeholder guide is shipped with": "Guide-Serif",    # body prose
    "guide-template": "Guide-Mono",                             # inline code
}


def test_the_anchored_manifest_passes(pdf):
    result = pdfaudit.audit(pdf, anchors=ANCHORS)
    assert result["problems"] == [], result["problems"]


def test_an_anchor_rendered_in_the_wrong_face_is_caught(pdf):
    """The regression this whole module exists for: a heading resolving to the
    body face. Both are bundled, both are embedded, both cover the glyphs — so
    pdffonts and coverage are silent."""
    wrong = dict(ANCHORS, **{"Welcome": "Guide-Serif"})
    problems = pdfaudit.audit(pdf, anchors=wrong)["problems"]
    assert problems and "Welcome" in problems[0], problems


def test_a_missing_anchor_is_reported(pdf):
    """Silence on a vanished anchor would let the manifest rot into a no-op."""
    problems = pdfaudit.audit(pdf, anchors={"text that is not there": "Guide-Serif"})["problems"]
    assert problems and "not found" in problems[0]


def test_runs_recover_their_source_text(pdf):
    """Anchoring needs text, and text comes from ToUnicode — used ONLY for that
   , never as the code->CID map."""
    runs = [r for r in pdfaudit.runs(pdf) if r.text.strip()]
    assert len(runs) > 20, f"only {len(runs)} runs carried recoverable text"


def test_a_face_mismatch_is_reported(pdf):
    """The audit has to FAIL for the right reason, or it is decoration."""
    result = pdfaudit.audit(pdf, expected_faces={"Guide-Mono"})
    assert result["problems"], "an impossible expectation produced no problem"
    assert "unexpected face" in result["problems"][0]


def test_the_real_expectation_passes(pdf):
    used = pdfaudit.faces_used(pdf)
    result = pdfaudit.audit(pdf, expected_faces=used)
    assert result["problems"] == [], result["problems"]


def test_a_type3_font_is_refused(tmp_path, monkeypatch):
    """Type3 glyphs are content streams, so "which face" has no answer."""
    monkeypatch.setattr(pdfaudit, "_objects", lambda _p: {
        "obj:9 0 R": {"value": {"/Type": "/Font", "/Subtype": "/Type3",
                                "/BaseFont": "/Weird"}}})
    with pytest.raises(pdfaudit.AuditError, match="Type3"):
        pdfaudit.font_table(tmp_path / "x.pdf")


def test_the_audit_covers_every_guide():
    """One-time, family-wide: the phase's whole point is that this is checked
    once across all eight rather than continuously in one."""
    ws = buildcore.ROOT.parent
    checked = 0
    for repo in ("accounting-guide", "git-guide", "japan-guide",
                 "linux-terminal-guide", "mac-terminal-guide",
                 "windows-cmd-guide", "windows-powershell-guide"):
        root = ws / repo
        if not root.is_dir():
            continue
        built = list((root / "build").glob("*.pdf")) if (root / "build").is_dir() else []
        if not built:
            continue
        # ANCHORED per guide: the face each guide's own title is drawn in. A
        # bare audit() call is only a document-wide allow-list, which cannot see
        # a heading falling back to a face that is legitimately used elsewhere.
        result = pdfaudit.audit(built[0])
        assert result["problems"] == [], f"{repo}: {result['problems']}"
        assert result["unauditable"] == [], f"{repo}: {result['unauditable']}"
        assert result["runs"] > 0, f"{repo}: the audit found no text runs at all"
        checked += 1
    if checked == 0:
        pytest.skip("no sibling guides have a fresh render to audit")
