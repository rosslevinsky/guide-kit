"""`app/wrangler.jsonc` is generated from `guide.toml`, and every deploy fact in
it is derived rather than authored or clicked.

Two defects this family actually shipped are the reason:

  * `workers_dev` was turned off in the Cloudflare dashboard, so `wrangler deploy`
    silently re-asserted Cloudflare's default on every run and eight sites were
    dual-published for weeks — at their custom domain AND at a workers.dev URL
    outside the zone, hence outside its WAF, analytics and redirect rules.
  * custom domains were bound by hand in the dashboard, where nothing reviews
    them and an adopter inherits nothing.

Both are now config, and config is generated from the one file a guide owns.
"""
import json
import re
import shutil
import subprocess

import pytest

import cfadapter
import kitconfig
import buildcore

TARGETS = ["accounting-guide", "git-guide", "japan-guide", "linux-terminal-guide",
           "mac-terminal-guide", "windows-cmd-guide", "windows-powershell-guide"]


def _strip_jsonc(text: str) -> str:
    """Drop `//` comment lines so the result parses as JSON."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))


def _cfg_with_domain(tmp_path, domain, slug="probe-guide"):
    """A minimal valid guide.toml carrying (or omitting) a [deploy] domain."""
    text = (
        f'TITLE = "Probe"\nOUTPUT_SLUG = "{slug}"\nAUTHOR = "A"\n'
        'DESCRIPTION = "d"\nKEYWORDS = "k"\nCOPYRIGHT_YEAR = 2026\n'
        '[outputs]\npdf = true\nsite = "single"\nslides = false\n'
        '[artifacts.pdf]\ndate = "2026-07-26"\n'
        '[artifacts.site]\ndate = "2026-07-26"\n'
    )
    if domain is not None:
        text += f'[deploy]\ndomain = "{domain}"\n'
    (tmp_path / "guide.toml").write_text(text, encoding="utf-8")
    return kitconfig.load(tmp_path)


# ----- the derived decisions -------------------------------------------------

def test_no_domain_means_workers_dev_and_no_routes(tmp_path):
    """The cold-start persona: a stranger with no Cloudflare zone. workers.dev IS
    the publication story there, so the routes block must be absent entirely —
    an empty `pattern` is rejected by wrangler."""
    c = cfadapter.wrangler_config(_cfg_with_domain(tmp_path, None))
    assert c["workers_dev"] is True
    assert "routes" not in c


def test_a_domain_means_routes_and_no_workers_dev(tmp_path):
    c = cfadapter.wrangler_config(_cfg_with_domain(tmp_path, "probe.example.com"))
    assert c["workers_dev"] is False
    assert c["routes"] == [{"pattern": "probe.example.com", "custom_domain": True}]


def test_a_blank_domain_is_treated_as_no_domain(tmp_path):
    """`domain = ""` must not produce `pattern: ""`, which wrangler rejects — and
    must not leave `workers_dev` false, which would publish the guide nowhere."""
    c = cfadapter.wrangler_config(_cfg_with_domain(tmp_path, "   "))
    assert c["workers_dev"] is True
    assert "routes" not in c


def test_workers_dev_cannot_be_authored(tmp_path):
    """It is DERIVED. An authored key would be the dashboard problem again, in a
    new location: two sources for one fact, and no way to tell which won."""
    (tmp_path / "guide.toml").write_text(
        'TITLE = "P"\nOUTPUT_SLUG = "p"\nAUTHOR = "A"\nDESCRIPTION = "d"\n'
        'KEYWORDS = "k"\nCOPYRIGHT_YEAR = 2026\n'
        '[outputs]\npdf = true\nsite = "single"\nslides = false\n'
        '[artifacts.pdf]\ndate = "2026-07-26"\n[artifacts.site]\ndate = "2026-07-26"\n'
        '[deploy]\ndomain = "p.example.com"\nworkers_dev = false\n', encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(tmp_path)


def test_preview_urls_default_off_and_are_authorable(tmp_path):
    """The SECOND workers.dev surface, and the one `workers_dev` does not cover.

    Every version gets a preview URL — a production `wrangler deploy` as much as
    a PR's `versions upload` — and they do not expire, so a guide that has
    deliberately left workers.dev would otherwise accrue public, un-WAF'd URLs
    serving the same content forever. Default off; opt in per guide."""
    assert cfadapter.wrangler_config(
        _cfg_with_domain(tmp_path, "probe.example.com"))["preview_urls"] is False
    assert cfadapter.wrangler_config(
        _cfg_with_domain(tmp_path, None))["preview_urls"] is False

    # Re-establish a [deploy] table: the domain-less call above rewrote
    # guide.toml without one, so opting in has to have something to opt into.
    _cfg_with_domain(tmp_path, "probe.example.com")
    p = tmp_path / "guide.toml"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "[deploy]\n", "[deploy]\npreview_urls = true\n"), encoding="utf-8")
    assert cfadapter.wrangler_config(kitconfig.load(tmp_path))["preview_urls"] is True


def test_a_non_boolean_preview_urls_is_rejected(tmp_path):
    _cfg_with_domain(tmp_path, "probe.example.com")
    p = tmp_path / "guide.toml"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "[deploy]\n", '[deploy]\npreview_urls = "yes"\n'), encoding="utf-8")
    with pytest.raises(kitconfig.KitConfigError):
        kitconfig.load(tmp_path)


def test_a_domain_that_is_not_a_hostname_is_refused(tmp_path):
    """`kitconfig` validates a guide, not a provider — it happily accepts any
    string. Cloudflare binds a Custom Domain by HOSTNAME, so a URL here would be
    emitted verbatim as a `pattern` and fail at deploy time, in CI, after the
    change had already been propagated to seven repositories."""
    for bad in ("https://guide.example.com", "guide.example.com/docs",
                "*.example.com", "guide.example.com:8080", "localhost"):
        cfg = _cfg_with_domain(tmp_path, bad)
        with pytest.raises(cfadapter.CloudflareConfigError):
            cfadapter.wrangler_config(cfg)


def test_a_slug_that_cannot_be_a_dns_label_is_refused_only_without_a_domain(tmp_path):
    """workers.dev serves the Worker at `<name>.<subdomain>.workers.dev`, so with
    no custom domain the slug has to be a DNS label. With one, the name never
    appears in a hostname and the constraint does not bind — so refusing it there
    would reject a guide that deploys perfectly well."""
    long_slug = "g" * 64
    with pytest.raises(cfadapter.CloudflareConfigError):
        cfadapter.wrangler_config(_cfg_with_domain(tmp_path, None, slug=long_slug))
    c = cfadapter.wrangler_config(_cfg_with_domain(tmp_path, "ok.example.com",
                                                   slug=long_slug))
    assert c["name"] == long_slug


# ----- the rendered file ------------------------------------------------------

def test_the_rendered_file_is_valid_jsonc_and_keeps_its_reasoning(tmp_path):
    text = cfadapter.render_wrangler_jsonc(_cfg_with_domain(tmp_path, "probe.example.com"))
    parsed = json.loads(_strip_jsonc(text))
    assert parsed["routes"][0]["pattern"] == "probe.example.com"
    assert parsed["name"] == "probe-guide"
    # The comments are the only place these two defects are explained. A generated
    # file that dropped them would lose that, silently.
    assert "dual-published" in text, "the workers.dev rationale was lost"
    assert "dashboard" in text, "the custom-domain rationale was lost"
    assert "GENERATED from guide.toml" in text, "nothing warns against hand-editing"


def test_round_tripping_the_generator_is_stable(tmp_path):
    cfg = _cfg_with_domain(tmp_path, "probe.example.com")
    assert cfadapter.render_wrangler_jsonc(cfg) == cfadapter.render_wrangler_jsonc(cfg)


# ----- the drift check, which is what replaces sync writing the file ----------

@pytest.mark.parametrize("target", TARGETS)
def test_each_targets_committed_wrangler_matches_the_generator(target):
    """`app/wrangler.jsonc` is `policy = "never"` — target-owned — so sync will
    never overwrite a hand-edit. This is what keeps the kit in control anyway:
    propagation becomes a RED CHECK rather than a silent correction.

    Skips when the sibling is not checked out, exactly as the other cross-repo
    checks do: `verify.yml` clones this repo alone."""
    root = buildcore.ROOT.parent / target
    if not root.is_dir():
        pytest.skip(f"{target} is not checked out beside the kit")
    if not (root / "app" / "wrangler.jsonc").is_file():
        pytest.skip(f"{target} has no web layer")
    # HEAD, not the working tree. What deploys is what is COMMITTED — reading the
    # file on disk would let an uncommitted `make wrangler` satisfy a check whose
    # whole subject is the committed config, and the uncommitted version is
    # precisely the one CI will not have.
    shown = subprocess.run(
        ["git", "-C", str(root), "show", "HEAD:app/wrangler.jsonc"],
        capture_output=True, text=True)
    assert shown.returncode == 0, f"{target}: app/wrangler.jsonc is not committed"
    expected = cfadapter.render_wrangler_jsonc(kitconfig.load(root))
    assert shown.stdout == expected, (
        f"{target}: the COMMITTED app/wrangler.jsonc has drifted from the generator "
        f"— run `make wrangler` there and commit the result"
    )


def test_building_the_site_refuses_a_stale_wrangler(guide_repo):
    """The kit's drift check above SKIPS in a target's own CI — `verify.yml`
    clones the kit alone. This is the one that runs everywhere: `make web` is in
    every guide's verify.yml and runs immediately before `wrangler deploy` in its
    deploy.yml, so a stale routes block cannot reach a deploy through it.

    Without this, editing `[deploy] domain` and pushing would deploy the OLD
    binding silently — every other check still passes, because nothing else reads
    that file."""
    import subprocess
    import sys
    root, write_toml = guide_repo
    write_toml(deploy={"domain": "probe.example.com"})
    subprocess.run([sys.executable, "build.py"], cwd=root, check=True,
                   capture_output=True, text=True)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    app = root / "app"
    app.mkdir(parents=True, exist_ok=True)
    # A config from before the domain was set: exactly what a forgotten
    # `make wrangler` leaves behind. Rendered from a SCRATCH config dir so the
    # guide's own guide.toml — the thing being disagreed with — is untouched.
    scratch = root / "_scratch"
    scratch.mkdir()
    (app / "wrangler.jsonc").write_text(
        cfadapter.render_wrangler_jsonc(_cfg_with_domain(scratch, None)),
        encoding="utf-8")

    proc = subprocess.run([sys.executable, "build.py", "--web"], cwd=root,
                          capture_output=True, text=True)
    assert proc.returncode != 0, "a stale deploy config built a site anyway"
    assert "wrangler.jsonc" in (proc.stdout + proc.stderr)

    # And the fix the message prescribes actually clears it.
    cfadapter.write_wrangler(app, kitconfig.load(root))
    ok = subprocess.run([sys.executable, "build.py", "--web"], cwd=root,
                        capture_output=True, text=True)
    assert ok.returncode == 0, f"regenerating did not clear the refusal:\n{ok.stderr}"


# ----- the identifier gate ----------------------------------------------------

_SECRET_SHAPES = [
    # A Cloudflare account ID is 32 lowercase hex characters.
    (re.compile(r"\b[0-9a-f]{32}\b"), "a Cloudflare-account-ID-shaped token"),
    (re.compile(r"speedytuna\.com"), "this family's own zone"),
]

# Prose may cite the real zone as an EXAMPLE; code and templates may not. The
# distinction is the whole point — a stranger cloning the kit must not inherit
# one of our hostnames as a default, but the docs are allowed to show a real URL.
_PROSE = {"README.md", "CLAUDE.md", "CHANGELOG.md"}


def test_no_account_ids_or_personal_hostnames_in_kit_code_or_templates():
    tracked = subprocess.run(["git", "-C", str(buildcore.ROOT), "ls-files"],
                             capture_output=True, text=True, check=True).stdout.split()
    offenders = []
    for rel in tracked:
        # `tests/` is NOT exempt: a real account ID committed in a fixture is
        # exactly as published as one in a module, and blanket-skipping the
        # directory made this gate silent about the largest tree in the repo.
        # Only this file is, because it has to name the shapes it looks for.
        if rel.startswith(("docs/", "plans/")) or rel in _PROSE:
            continue
        if rel == "tests/test_wrangler_generated.py":
            continue
        if rel.endswith((".pdf", ".ttf", ".otf", ".woff2", ".lock")):
            continue
        path = buildcore.ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern, what in _SECRET_SHAPES:
            for m in pattern.finditer(text):
                line = text[:m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line} contains {what} ({m.group(0)})")
    assert not offenders, (
        "kit code/templates must carry no account ID, zone or personal hostname:\n  "
        + "\n  ".join(offenders))
