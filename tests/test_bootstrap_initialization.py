"""bootstrap.py initializes a fork into a correct, honest, ZERO-DRIFT state.

Two checkpoints: immediately after bootstrap there are ZERO root
reference PDFs; after a (simulated) release there is exactly one. Also: the fork
emits guide.toml + .template-version with NO platform key (that config surface is
retired — see test_no_platform_guard.py); transforms.py is absent without
--with-transforms; and the freshly bootstrapped fork reports zero drift against a
pristine kit (its templated files carry the fork's identity, not the kit's).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import kitconfig
import sync

REPO_ROOT = Path(__file__).resolve().parent.parent
_IGNORE = shutil.ignore_patterns(".git", ".pixi", "build", "__pycache__", "node_modules", "app")


def _mkcopy(dst: Path) -> Path:
    """A --template-style copy of the kit. The kit's real CLAUDE.md already carries
    the kit:begin/end markers, which compute_managed_digest needs — so the
    copy is faithful with no synthetic marker injection."""
    shutil.copytree(REPO_ROOT, dst, ignore=_IGNORE)
    # Guard: the fixture is only valid while the kit ships exactly one marker pair.
    claude = (dst / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.count(sync.MARK_BEGIN) == 1 and claude.count(sync.MARK_END) == 1, \
        "kit CLAUDE.md must carry exactly one managed-region marker pair"
    return dst


def _run_bootstrap(fork: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(fork / "bootstrap.py"), "Fork Guide", "fork-guide", *extra],
        cwd=fork, capture_output=True, text=True,
    )


def test_bootstrap_needs_no_platform_argument(tmp_path):
    """Title and slug are the whole required surface now.

    This inverts the assertion it replaces: `--baseline-platform` used to be
    REQUIRED non-interactively and bootstrap refused without it. The flag is gone
    with the guard, so a bare invocation must SUCCEED — and passing the retired
    flag must fail rather than be silently ignored.
    """
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork)
    assert r.returncode == 0, r.stderr
    cfg = kitconfig.load(fork)
    assert cfg.OUTPUT_SLUG == "fork-guide"
    assert not hasattr(cfg, "baseline_platform")
    assert 'baseline_platform' not in (fork / "guide.toml").read_text(encoding="utf-8")


def test_bootstrap_rejects_the_retired_platform_flag(tmp_path):
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork, "--baseline-platform", "darwin")
    assert r.returncode != 0
    # refused before writing: guide.toml is still the kit's, sentinel still present
    assert kitconfig.load(fork).OUTPUT_SLUG == "guide-template"
    assert (fork / ".template-uninitialized").exists()


def test_bootstrap_full_initialization_zero_drift(tmp_path):
    pristine = _mkcopy(tmp_path / "kit")        # stands in for source_repo at check time
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork, "--source-repo", "rosslevinsky/guide-kit",
                       "--kit-version", "test")
    assert r.returncode == 0, r.stderr

    # guide.toml written with the fork's identity.
    cfg = kitconfig.load(fork)
    assert cfg.OUTPUT_SLUG == "fork-guide"
    assert cfg.TITLE == "Fork Guide"

    # CHECKPOINT 1: zero root reference PDFs (inherited guide-template.pdf deleted).
    assert list(fork.glob("*.pdf")) == []

    # transforms.py NOT activated (no --with-transforms), and no web layer.
    assert not (fork / "transforms.py").exists()
    assert not (fork / "style-screen.css").exists()

    # templated files carry the FORK's identity (pixi project name), not the kit's.
    assert 'name = "fork-guide"' in (fork / "pixi.toml").read_text()

    # .template-version: full record, state applied.
    tv = json.loads((fork / ".template-version").read_text())
    for k in ("schema_version", "source_repo", "kit_version", "managed_digest", "state", "rendered_checksums"):
        assert k in tv
    assert tv["state"] == "applied"
    assert tv["source_repo"] == "rosslevinsky/guide-kit"

    # bootstrap self-deleted and removed the sentinel.
    assert not (fork / "bootstrap.py").exists()
    assert not (fork / ".template-uninitialized").exists()

    # ZERO DRIFT against the pristine kit — the fork is genuinely in sync.
    drifted, msgs = sync.drift_report(pristine, fork)
    assert not drifted, msgs
    # The genuine cross-check: the real planner `sync.py <fork>` uses. This proves
    # bootstrap rendered every file BYTE-IDENTICALLY to what sync would produce
    # (drift_report's local loop is self-referential against bootstrap's own record).
    items, _, _ = sync.build_plan(pristine, fork)
    assert all(it.action == "in-sync" for it in items), [(i.dest_rel, i.action) for i in items if i.action != "in-sync"]

    # CHECKPOINT 2 (simulated release): after the first baseline there is
    # exactly one root reference PDF.
    (fork / "fork-guide.pdf").write_bytes(b"%PDF-fork-baseline")
    assert [p.name for p in fork.glob("*.pdf")] == ["fork-guide.pdf"]


def test_bootstrap_with_web_but_no_transforms(tmp_path):
    pristine = _mkcopy(tmp_path / "kit")
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork, "--with-web")
    assert r.returncode == 0, r.stderr
    # web layer materialized, but transforms.py stays absent (the terminal-guide case).
    assert (fork / "style-screen.css").exists()
    assert (fork / "app" / "wrangler.jsonc").exists()
    assert (fork / ".github" / "workflows" / "deploy.yml").exists()
    assert not (fork / "transforms.py").exists()
    # the worker name is the fork's slug, rendered by value-substitution (matches sync).
    assert '"name": "fork-guide"' in (fork / "app" / "wrangler.jsonc").read_text()
    assert "{{GUIDE_SLUG}}" not in (fork / "app" / "wrangler.jsonc").read_text()
    # a fresh web fork also reports ZERO drift (incl. app/wrangler.jsonc).
    drifted, msgs = sync.drift_report(pristine, fork)
    assert not drifted, msgs
    items, _, _ = sync.build_plan(pristine, fork)
    assert all(it.action == "in-sync" for it in items), [(i.dest_rel, i.action) for i in items if i.action != "in-sync"]


def test_bootstrap_prunes_every_kit_only_path(tmp_path):
    """A fork must inherit none of the kit's own machinery.

    `--template` copies the whole kit, so without pruning a fork ships the kit's
    test suite, sync.py, adopt-web.py, the manifest and its loader, and plans/.
    That is not cosmetic: verify.yml's target branch is guarded on `tests/**`
    existing, so an inherited tests/ makes the fork borrow the kit's runner and
    run the KIT's suite against the GUIDE — asserting kit-shaped facts that are
    false in a fork by construction (bootstrap.py present, a `kit` pixi env,
    every tracked file classified). The result is a brand-new repo with a
    permanently red default branch.
    """
    import kitmanifest
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork,
                       "--source-repo", "rosslevinsky/guide-kit", "--kit-version", "test")
    assert r.returncode == 0, r.stderr

    manifest = kitmanifest.load(REPO_ROOT)
    kit_only = [e.path for e in manifest.entries
                if e.lifecycle == "retained-in-kit" and not e.projects_to]
    assert kit_only, "manifest declares no kit-only entries — the guard would be vacuous"

    leaked = []
    for rel in kit_only:
        p = fork / (rel[:-3].rstrip("/") if rel.endswith("/**") else rel)
        if p.exists():
            leaked.append(rel)
    assert not leaked, f"kit-only paths leaked into the fork: {leaked}"

    # The guide's own machinery must survive the pruning.
    for kept in ("guide.md", "style.css", "build.py", "kitconfig.py", "verify_artifacts.py",
                 "Makefile", "pixi.toml", "guide.toml", ".template-version"):
        assert (fork / kept).exists(), f"pruning removed a file the guide needs: {kept}"


def _relative_links(markdown: str) -> list[str]:
    """Relative link targets in a markdown document.

    Inline code spans are stripped FIRST. The README teaches asset syntax with a
    literal `![](assets/x.png)` inside backticks; that is an example of markup,
    not a link, and a checker that cannot tell the difference reports a false
    positive on the one document this test exists to police — which is how a
    checker gets ignored.
    """
    import re
    prose = re.sub(r"`[^`]*`", "", markdown)
    return [t for t in re.findall(r"\]\(([^)][^)]*)\)", prose)
            if not t.startswith(("http://", "https://", "mailto:", "#"))]


def test_a_forks_own_documentation_does_not_point_at_pruned_files(tmp_path):
    """THE FORK'S README MUST NOT LINK TO ANYTHING BOOTSTRAP JUST DELETED.

    This exists because it happened. Two long README sections were moved into
    `docs/` to shorten the front page — a change that looks documentation-only
    and cannot break a build. But `docs/**` is kit-only, so `_prune_kit_only`
    removes it from a fork, while the links to it live *after* the front-matter
    marker and therefore survive. Every test passed. The kit's own README was
    fine. Only a fork was broken, and nothing here forks the kit and reads what
    is left.

    Worse, the two sections were the `guide.toml` key reference and the deploy
    how-to: precisely what a new guide author opens first. The reader with the
    least context got the broken document.

    Asserted against a REAL fork rather than by reasoning about the manifest,
    because the manifest is what was already consistent — `docs/**` is correctly
    kit-only. What no rule captured is that a surviving document must still make
    sense once the pruned ones are gone.
    """
    fork = _mkcopy(tmp_path / "fork")
    r = _run_bootstrap(fork)
    assert r.returncode == 0, r.stderr

    checked = 0
    dangling = []
    for doc in ("README.md", "CLAUDE.md"):
        p = fork / doc
        if not p.exists():
            continue
        for target in _relative_links(p.read_text(encoding="utf-8")):
            checked += 1
            if not (fork / target.split("#")[0]).exists():
                dangling.append(f"{doc} -> {target}")
    assert checked, (
        "no relative links were examined at all; the check has gone blind and "
        "would pass on a README that linked nowhere"
    )
    assert not dangling, (
        f"a fork's documentation links to files bootstrap pruned: {dangling}. "
        f"Either the target belongs in the fork (give it a `projects_to` in "
        f"kit-manifest.toml) or the content belongs inline in the README."
    )


def test_a_projected_exception_survives_inside_a_kit_only_tree(tmp_path):
    """The pruner resolves the manifest PER PATH, like `classify()` does.

    `kit-manifest.toml` already says an exact entry beats a covering glob —
    `test_exact_entry_wins_over_a_covering_glob` pins it for the classifier. The
    pruner used to ignore that and `rmtree` the glob's whole directory, so the
    two halves of one manifest disagreed about the same file and only the
    destructive half's answer took effect.

    Nothing depended on it, which is why it went unnoticed: every file under
    `docs/**` is genuinely kit-only today. It matters the moment one is not — a
    guide-facing reference living beside the maintainer's decision record — and
    the failure mode would have been a fork silently missing a file the manifest
    said it should have.
    """
    fork = _mkcopy(tmp_path / "fork")
    (fork / "docs").mkdir(exist_ok=True)
    (fork / "docs" / "for-the-guide.md").write_text("# Kept\n", encoding="utf-8")
    (fork / "docs" / "for-the-kit.md").write_text("# Pruned\n", encoding="utf-8")
    # An exact, PROJECTED entry beneath the kit-only `docs/**` glob.
    with (fork / "kit-manifest.toml").open("a", encoding="utf-8") as fh:
        fh.write('\n[[entry]]\npath = "docs/for-the-guide.md"\n'
                 'lifecycle = "retained-in-kit"\n'
                 'projects_to = "docs/for-the-guide.md"\npolicy = "identical"\n')

    r = _run_bootstrap(fork)
    assert r.returncode == 0, r.stderr

    assert (fork / "docs" / "for-the-guide.md").exists(), (
        "the pruner deleted a file the manifest projects into a target, because "
        "it removed the covering glob's directory instead of resolving per path"
    )
    assert not (fork / "docs" / "for-the-kit.md").exists(), (
        "the exception stopped the rest of the kit-only tree being pruned"
    )
    assert not (fork / "docs" / "family-as-built.md").exists(), (
        "the maintainer's decision record leaked into a fork"
    )
