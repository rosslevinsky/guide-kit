"""`adopt.py --output <name> --enable/--disable` as a STATE TRANSITION.

Not a fresh adoption: `sync.py --adopt` is first contact and refuses a target
that already has `.template-version`. This runs on a target that is already
`applied` and changes which output's managed files it carries.

Without it there is no way to add an output to a live guide. `sync.py` refuses an
existing managed destination absent from `rendered_checksums`, so files
materialized by hand are files sync will not touch — upstream changes to them
never arrive and drift in them is never reported. Silently, which is the worst
version of that failure, and the reason every test here checks the INVENTORY and
not just the files.

Config-first: the tool never writes guide.toml. `--enable` refuses an
undeclared output and `--disable` refuses one still declared, so the declaration
is always the user's committed edit rather than a tool's side effect.
"""
import json
import subprocess

import pytest

import adopt
import sync


def _commit(root, msg):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True, capture_output=True)


def _tv(env):
    return json.loads((env.target / ".template-version").read_text(encoding="utf-8"))


def _declare_site(env, on=True):
    """The user's own committed edit — exactly what adopt.py refuses to make."""
    p = env.target / "guide.toml"
    text = p.read_text(encoding="utf-8")
    if on:
        text = text.replace('site = "none"', 'site = "single"')
        if "[artifacts.site]" not in text:
            text += '[artifacts.site]\ndate = "2026-07-26"\n'
    else:
        text = text.replace('site = "single"', 'site = "none"')
        text = text.replace('[artifacts.site]\ndate = "2026-07-26"\n', "")
    p.write_text(text, encoding="utf-8")
    _commit(env.target, "declare the site" if on else "un-declare the site")


# ----- enable ----------------------------------------------------------------

def test_enable_refuses_an_undeclared_output(sync_env):
    """Materializing an undeclared output writes files sync will not manage."""
    env = sync_env()
    with pytest.raises(adopt.AdoptError, match="does not declare"):
        adopt.enable(env.kit, env.target, "site")
    assert not (env.target / ".github" / "workflows" / "deploy.yml").exists()


def test_enable_materializes_and_records_so_sync_does_not_refuse(sync_env):
    """The whole reason this tool exists: files present but unrecorded are files
    a later `sync --apply` REFUSES."""
    env = sync_env(shape="web-enabled")
    # Start from a target that declares the site but has not materialized it.
    (env.target / ".github" / "workflows" / "deploy.yml").unlink()
    tv = _tv(env)
    tv["rendered_checksums"].pop(".github/workflows/deploy.yml", None)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "site declared but not materialized")

    assert adopt.enable(env.kit, env.target, "site") == 0
    assert (env.target / ".github" / "workflows" / "deploy.yml").exists()
    assert ".github/workflows/deploy.yml" in _tv(env)["rendered_checksums"]

    _commit(env.target, "site enabled")
    items, _, _ = sync.build_plan(env.kit, env.target)
    assert [it.dest_rel for it in items if it.action == "refuse"] == []


def test_enable_GENERATES_wrangler_rather_than_copying_the_kits(sync_env):
    """`adopt.py` is the third path that materializes the web layer, alongside
    bootstrap.py, and it is the one that runs on a LIVE guide.

    Copying the kit's file here would enable a site whose Worker is named after
    the KIT, with no routes block — so the deploy would target the wrong Worker
    and bind nothing. The file is `policy = "never"`, which is precisely why the
    copy branch is the one it would otherwise fall into."""
    import cfadapter
    import kitconfig

    env = sync_env(shape="web-enabled")
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    manifest += ('\n[[entry]]\npath = "templates/web/wrangler.jsonc"\n'
                 'lifecycle = "bootstrap-source"\n'
                 'projects_to = "app/wrangler.jsonc"\npolicy = "never"\n')
    (env.kit / "kit-manifest.toml").write_text(manifest, encoding="utf-8")
    (env.kit / "templates" / "web").mkdir(parents=True, exist_ok=True)
    (env.kit / "templates" / "web" / "wrangler.jsonc").write_text(
        '{ "name": "THE-KITS-OWN-NAME" }\n', encoding="utf-8")
    _commit(env.kit, "the kit carries a wrangler placeholder")

    # A domained target: the case where a copied file is most obviously wrong.
    toml = (env.target / "guide.toml").read_text(encoding="utf-8")
    (env.target / "guide.toml").write_text(
        toml + '[deploy]\ndomain = "probe.example.com"\n', encoding="utf-8")
    _commit(env.target, "declare the domain")

    assert adopt.enable(env.kit, env.target, "site") == 0
    written = (env.target / "app" / "wrangler.jsonc").read_text(encoding="utf-8")
    assert "THE-KITS-OWN-NAME" not in written, \
        "adopt copied the kit's wrangler config verbatim into a live guide"
    assert written == cfadapter.render_wrangler_jsonc(kitconfig.load(env.target))
    assert '"probe.example.com"' in written, "the target's own domain was not bound"


def test_enable_is_idempotent(sync_env):
    env = sync_env(shape="web-enabled")
    assert adopt.enable(env.kit, env.target, "site") == 0
    _commit(env.target, "site enabled")      # the tool requires a clean tree
    before = _tv(env)
    assert adopt.enable(env.kit, env.target, "site") == 0
    assert _tv(env) == before


def test_enable_refuses_a_differing_pre_existing_file(sync_env):
    env = sync_env(shape="web-enabled")
    (env.target / ".github" / "workflows" / "deploy.yml").write_text(
        "someone's own workflow\n", encoding="utf-8")
    tv = _tv(env)
    tv["rendered_checksums"].pop(".github/workflows/deploy.yml", None)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "hand-written workflow")

    with pytest.raises(adopt.AdoptError, match="differs"):
        adopt.enable(env.kit, env.target, "site")
    assert (env.target / ".github" / "workflows" / "deploy.yml").read_text() \
        == "someone's own workflow\n"


def test_enable_refuses_a_target_that_was_never_adopted(sync_env):
    env = sync_env(shape="web-enabled")
    (env.target / ".template-version").unlink()
    _commit(env.target, "drop .template-version")
    with pytest.raises(adopt.AdoptError, match="state transition|--adopt"):
        adopt.enable(env.kit, env.target, "site")


def test_a_transition_refuses_a_target_that_has_not_applied(sync_env):
    """`adopted_unapplied` records the checksums of files that were ALREADY there
    at first contact — files sync has never written. Transitioning from that
    state lets --disable delete pre-existing content on the strength of an
    inventory that only ever described it."""
    env = sync_env(shape="web-enabled")
    tv = _tv(env)
    tv["state"] = "adopted_unapplied"
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "adopted but not applied")

    with pytest.raises(adopt.AdoptError, match="not 'applied'"):
        adopt.enable(env.kit, env.target, "site")
    _declare_site(env, on=False)
    with pytest.raises(adopt.AdoptError, match="not 'applied'"):
        adopt.disable(env.kit, env.target, "site")
    assert (env.target / ".github" / "workflows" / "deploy.yml").exists()


def test_a_transition_refuses_an_uncommitted_declaration(sync_env):
    """Otherwise the config edit and the file changes are separable: undeclare in
    an uncommitted guide.toml, disable, restore the edit — and the guide declares
    a site whose managed state has been deleted."""
    env = sync_env(shape="web-enabled")
    p = env.target / "guide.toml"
    p.write_text(p.read_text(encoding="utf-8").replace('site = "single"', 'site = "none"')
                 .replace('[artifacts.site]\ndate = "2026-07-26"\n', ""), encoding="utf-8")
    # Deliberately NOT committed.
    with pytest.raises(adopt.AdoptError, match="dirty"):
        adopt.disable(env.kit, env.target, "site")
    assert (env.target / ".github" / "workflows" / "deploy.yml").exists()


def test_enable_does_not_activate_the_transforms_hook_by_default(sync_env):
    """transforms.py is a SOURCE_FILES entry, so creating it shifts the PDF's
    version stamp. Enabling a SITE must not silently re-baseline the PDF."""
    env = sync_env(shape="web-enabled")
    manifest = (env.kit / "kit-manifest.toml").read_text(encoding="utf-8")
    manifest += ('\n[[entry]]\npath = "transforms.py.example"\n'
                 'lifecycle = "bootstrap-source"\nprojects_to = "transforms.py"\n'
                 'policy = "never"\n')
    (env.kit / "kit-manifest.toml").write_text(manifest, encoding="utf-8")
    (env.kit / "transforms.py.example").write_text("# hook\n", encoding="utf-8")
    _commit(env.kit, "kit gains the transforms seed")

    assert adopt.enable(env.kit, env.target, "site") == 0
    assert not (env.target / "transforms.py").exists(), \
        "enabling a site activated the transforms hook and moved the PDF's stamp"

    _commit(env.target, "site enabled")
    assert adopt.enable(env.kit, env.target, "site", with_transforms=True) == 0
    assert (env.target / "transforms.py").exists()


def test_enable_adds_the_web_gitignore_entries(sync_env):
    """Without them the first web build or npm install leaves generated output
    untracked, and every later sync refuses the target as a dirty tree."""
    env = sync_env(shape="web-enabled")
    assert adopt.enable(env.kit, env.target, "site") == 0
    ignored = (env.target / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "app/dist/" in ignored and "node_modules/" in ignored

    before = (env.target / ".gitignore").read_text(encoding="utf-8")
    _commit(env.target, "gitignore")
    assert adopt.enable(env.kit, env.target, "site") == 0
    assert (env.target / ".gitignore").read_text(encoding="utf-8") == before, \
        "the .gitignore update is not idempotent"


def test_enable_rolls_back_completely_on_failure(sync_env, monkeypatch):
    env = sync_env(shape="web-enabled")
    (env.target / ".github" / "workflows" / "deploy.yml").unlink()
    tv = _tv(env)
    tv["rendered_checksums"].pop(".github/workflows/deploy.yml", None)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "site declared but not materialized")
    before = _tv(env)

    # Fail on the LAST write — the inventory — so the test actually covers the
    # claim that a failure there rolls the FILES back too. Exploding on the first
    # write passes even if inventory rollback is removed entirely.
    reached = {"inventory": False}

    def explode(n):
        if (env.target / ".template-version").read_text(encoding="utf-8") != \
                json.dumps(before, indent=2, sort_keys=True) + "\n":
            reached["inventory"] = True
            raise RuntimeError("failure after the inventory write")

    monkeypatch.setattr(adopt, "AFTER_WRITE_HOOK", staticmethod(explode))
    with pytest.raises(RuntimeError):
        adopt.enable(env.kit, env.target, "site")
    monkeypatch.setattr(adopt, "AFTER_WRITE_HOOK", None)

    assert reached["inventory"], "the test never reached the inventory write"
    assert not (env.target / ".github" / "workflows" / "deploy.yml").exists()
    assert _tv(env) == before, "the inventory moved without the files"


# ----- disable ---------------------------------------------------------------

def test_disable_refuses_while_the_output_is_still_declared(sync_env):
    env = sync_env(shape="web-enabled")
    with pytest.raises(adopt.AdoptError, match="still declares"):
        adopt.disable(env.kit, env.target, "site")
    assert (env.target / ".github" / "workflows" / "deploy.yml").exists()


def test_disable_deletes_matching_managed_files_and_their_records(sync_env):
    """Disable DELETES rather than transferring ownership — a silent
    transfer leaves a file nobody is maintaining."""
    env = sync_env(shape="web-enabled")
    _declare_site(env, on=False)

    assert adopt.disable(env.kit, env.target, "site") == 0
    assert not (env.target / ".github" / "workflows" / "deploy.yml").exists()
    assert ".github/workflows/deploy.yml" not in _tv(env)["rendered_checksums"]
    # The target's own files are untouched.
    assert (env.target / "guide.md").exists() and (env.target / "build.py").exists()


def test_disable_refuses_the_whole_transition_on_any_local_edit(sync_env):
    """Deleting the matching files and leaving the edited one is the worst
    outcome: a half-removed output whose remnants nobody owns."""
    env = sync_env(shape="web-enabled")
    (env.target / ".github" / "workflows" / "deploy.yml").write_text(
        "locally tweaked\n", encoding="utf-8")
    _declare_site(env, on=False)

    with pytest.raises(adopt.AdoptError, match="locally modified"):
        adopt.disable(env.kit, env.target, "site")
    assert (env.target / ".github" / "workflows" / "deploy.yml").read_text() \
        == "locally tweaked\n"
    assert ".github/workflows/deploy.yml" in _tv(env)["rendered_checksums"], \
        "the inventory was edited by a refused transition"


def test_disable_leaves_unrecorded_files_alone(sync_env):
    """A path the kit never recorded is not the kit's to remove — the same
    promise sync's deletion guard makes."""
    env = sync_env(shape="web-enabled")
    tv = _tv(env)
    tv["rendered_checksums"].pop(".github/workflows/deploy.yml", None)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _declare_site(env, on=False)

    assert adopt.disable(env.kit, env.target, "site") == 0
    assert (env.target / ".github" / "workflows" / "deploy.yml").exists()


def test_disable_then_enable_round_trips(sync_env):
    env = sync_env(shape="web-enabled")
    before = _tv(env)["rendered_checksums"]

    _declare_site(env, on=False)
    assert adopt.disable(env.kit, env.target, "site") == 0
    _commit(env.target, "site disabled")

    _declare_site(env, on=True)
    assert adopt.enable(env.kit, env.target, "site") == 0
    assert _tv(env)["rendered_checksums"] == before
    assert (env.target / ".github" / "workflows" / "deploy.yml").exists()


def test_slides_has_no_managed_destinations_yet(sync_env):
    """Honest about the shape of the thing: `render_slides.py` and
    `style-slides.css` ship to every guide as ordinary `identical` files, so
    enabling slides is purely a config declaration. Saying so beats a tool that
    appears to work and materializes nothing."""
    env = sync_env()
    p = env.target / "guide.toml"
    p.write_text(p.read_text(encoding="utf-8")
                 .replace("slides = false", "slides = true")
                 + '[artifacts.slides]\ndate = "2026-07-26"\n', encoding="utf-8")
    _commit(env.target, "declare slides")

    before = _tv(env)
    assert adopt.enable(env.kit, env.target, "slides") == 0
    assert _tv(env)["rendered_checksums"] == before["rendered_checksums"]


def test_enable_writes_only_into_the_target_never_the_kit(sync_env):
    """The two-root property, carried over from the retired `adopt-web.py` suite.

    `adopt.py` takes an immutable kit_root — staging assets are READ from it,
    never written — and an explicit target. The failure it guards against is
    concrete: running the kit's own copy against another repo must not
    materialize the web layer INTO the kit. Asserted on the kit's whole tree
    being byte-identical afterwards, because "the target came out right" is
    perfectly compatible with having also written somewhere it should not.

    The fixture SHAPE is load-bearing, and getting it wrong is how this test was
    hollow once already: `pdf-only`'s synthetic kit declares no `bootstrap-source`
    entries, so `enable` materialized zero files and the kit snapshot was
    trivially unchanged whatever `adopt.py` did. So: `web-enabled`, started from a
    target that has un-materialized the projection, plus an assertion that the
    target really GAINED it — the two-root property is only tested while there is
    a write happening for it to be about.
    """
    env = sync_env(shape="web-enabled")
    dest = env.target / ".github" / "workflows" / "deploy.yml"
    dest.unlink()
    tv = _tv(env)
    tv["rendered_checksums"].pop(".github/workflows/deploy.yml", None)
    (env.target / ".template-version").write_text(
        json.dumps(tv, indent=2) + "\n", encoding="utf-8")
    _commit(env.target, "site declared but not materialized")

    def snapshot():
        return {p.relative_to(env.kit): p.read_bytes()
                for p in sorted(env.kit.rglob("*"))
                if p.is_file() and ".git/" not in p.as_posix()}

    before = snapshot()
    adopt.enable(env.kit, env.target, "site")
    assert dest.exists(), (
        "the fixture materialized nothing, so the kit-snapshot comparison below "
        "cannot fail — the test would pass on any adopt.py at all")
    assert snapshot() == before, (
        "adopt.py wrote into the KIT as well as the target; the two-root "
        "separation is what stops the kit web-enabling itself")
