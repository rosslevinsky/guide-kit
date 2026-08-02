"""Preflight refuses what would fail LATER, and it asks the right questions per persona.

The point of a preflight is not to be thorough — it is to convert a failure that
happens twenty minutes in, on a runner, with an opaque provider error, into a
sentence at second zero. So every check here corresponds to something this family
has actually watched go wrong, and every refusal carries a remediation line.

THE PERSONA SPLIT IS THE LOAD-BEARING PART. The primary cold-start persona is
explicitly assumed to have **no Cloudflare zone** — someone trying the kit for the
first time, publishing to `<worker>.<subdomain>.workers.dev`. Demanding a zone from
them would make the one-hour claim unreachable for the exact person it was written
for. So a zone is required only on the custom-domain path, and the tests assert the
`workers.dev` persona is *not* subjected to zone checks — a preflight that quietly
applies the strict path to everyone is the failure being guarded against, and it
would look like a passing test suite.

Node ≥ 22 is checked because **wrangler 4.x requires it**. Nothing more. The kit
template once claimed Node 20 makes `cloudflare/wrangler-action` fall back to
wrangler 3; that is false and is corrected at the source. The fallback is a
*detection* failure — with no local wrangler to find, the action installs its own
default, which is still 3.90.0 and predates assets-only Workers.
"""
import pytest

import guidekit


class FakeProbe:
    """Every external question, answered from a dict. No network, no credentials."""

    def __init__(self, *, tools=None, node=(22, 0, 0), subdomain="acct",
                 permissions=("workers_scripts:edit",), zones=()):
        self._tools = {"gh": "2.0.0", "wrangler": "4.114.0", "pixi": "0.40.0"}
        if tools is not None:
            self._tools = dict(tools)
        self._node = node
        self._subdomain = subdomain
        self._permissions = set(permissions)
        self._zones = set(zones)
        self.asked = []

    def tool_version(self, name):
        self.asked.append(("tool", name))
        return self._tools.get(name)

    def node_version(self):
        self.asked.append(("node",))
        return self._node

    def account_subdomain(self, account_id):
        self.asked.append(("subdomain", account_id))
        return self._subdomain

    def token_permissions(self, account_id=""):
        # RECORDS THE ACCOUNT ID it was asked with. The real probe used to read
        # `CLOUDFLARE_ACCOUNT_ID` from the environment here rather than take the
        # caller's, so `--account-id` was honoured by one Cloudflare check and
        # dropped by the other; a fake that ignored the argument could not see it.
        self.asked.append(("permissions", account_id))
        return self._permissions

    def zone_for(self, domain):
        self.asked.append(("zone", domain))
        return domain if domain in self._zones else None


def _problems(probe, **kw):
    """The WEB preflight. `with_web=True` is explicit here rather than defaulted,
    because defaulting it is how the defect below hid.

    `kw.setdefault("worker_name", "my-guide")` supplies the one input the
    documented invocation does NOT carry on its command line — the CLI defaults
    `--worker-name` to `""` — so every test through this helper exercises a
    command no reader types. That is now DELIBERATE and bounded: these cases are
    about the checks themselves, and the CLI's own default is covered separately
    by `test_the_documented_with_web_preflight_can_actually_pass` below, which
    goes through `main()` rather than through here. Leaving the setdefault while
    testing nothing else was what let the empty default ship.
    """
    kw.setdefault("persona", guidekit.WORKERS_DEV)
    kw.setdefault("account_id", "a" * 32)
    kw.setdefault("worker_name", "my-guide")
    kw.setdefault("with_web", True)
    return guidekit.preflight(probe, **kw)


# ----- tools --------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["gh", "wrangler", "pixi"])
def test_a_missing_tool_is_a_named_error_with_a_remediation(missing):
    tools = {"gh": "2.0.0", "wrangler": "4.114.0", "pixi": "0.40.0"}
    del tools[missing]
    problems = _problems(FakeProbe(tools=tools))
    assert any(missing in p for p in problems)
    assert any("install" in p.lower() or "https://" in p for p in problems), \
        "a refusal with no remediation makes the reader search for the fix"


def test_node_below_22_is_refused():
    problems = _problems(FakeProbe(node=(20, 11, 0)))
    assert any("Node" in p and "22" in p for p in problems)


def test_node_22_passes():
    assert _problems(FakeProbe(node=(22, 3, 0))) == []


def test_the_node_message_does_not_repeat_the_false_wrangler_claim():
    """The corrected causal story, pinned. `wrangler-action`'s fallback to
    wrangler 3 is a DETECTION failure, not a Node one, and the wrong version of
    this sentence was synced into seven guides before it was caught."""
    problems = _problems(FakeProbe(node=(20, 0, 0)))
    text = " ".join(problems)
    assert "fall back" not in text.lower() and "falls back" not in text.lower()


def test_an_absent_node_is_refused_not_assumed_fine():
    problems = _problems(FakeProbe(node=None))
    assert any("Node" in p for p in problems)


# ----- the workers.dev persona --------------------------------------------------

def test_the_primary_persona_passes_with_no_zone_at_all():
    """The whole reason the split exists. This person has no Cloudflare zone and
    must still reach a deployed guide."""
    assert _problems(FakeProbe(zones=())) == []


def test_the_primary_persona_is_never_asked_about_a_zone():
    """Not merely 'passes anyway' — the check must not run. A zone query that
    happens to be tolerated today becomes a hard requirement the first time
    someone tightens its error handling."""
    probe = FakeProbe(zones=())
    _problems(probe)
    assert not any(a[0] == "zone" for a in probe.asked)


def test_a_missing_account_subdomain_is_refused():
    """`<worker>.<subdomain>.workers.dev` has nowhere to live without one, and
    the deploy failure it produces names neither the account nor the subdomain."""
    problems = _problems(FakeProbe(subdomain=None))
    assert any("subdomain" in p for p in problems)


def test_a_missing_workers_scripts_permission_is_refused():
    problems = _problems(FakeProbe(permissions=("zone:read",)))
    assert any("Workers Scripts" in p for p in problems)


def test_a_missing_account_id_is_refused():
    problems = _problems(FakeProbe(), account_id="")
    assert any("account" in p.lower() for p in problems)


# ----- worker name / DNS label --------------------------------------------------

@pytest.mark.parametrize("name,why", [
    ("My_Guide", "underscore and uppercase"),
    ("-leading", "leading hyphen"),
    ("trailing-", "trailing hyphen"),
    ("", "empty"),
    ("a" * 64, "over 63 characters"),
    ("has spaces", "space"),
])
def test_an_invalid_worker_name_is_refused(name, why):
    """The worker name becomes a DNS LABEL in the workers.dev hostname, so the
    constraint is DNS's, not Cloudflare's preference."""
    problems = _problems(FakeProbe(), worker_name=name)
    assert any("worker name" in p.lower() for p in problems), f"accepted {why}: {name!r}"


@pytest.mark.parametrize("name", ["a", "my-guide", "guide2", "a" * 63])
def test_a_valid_worker_name_passes(name):
    assert _problems(FakeProbe(), worker_name=name) == []


# ----- the custom-domain persona ------------------------------------------------

def test_the_custom_domain_persona_requires_a_zone():
    problems = _problems(FakeProbe(zones=()), persona=guidekit.CUSTOM_DOMAIN,
                         domain="guide.example.com")
    assert any("zone" in p.lower() for p in problems)


def test_the_custom_domain_persona_passes_with_the_zone_present():
    assert _problems(FakeProbe(zones=("guide.example.com",)),
                     persona=guidekit.CUSTOM_DOMAIN,
                     domain="guide.example.com") == []


def test_the_custom_domain_persona_needs_a_domain():
    problems = _problems(FakeProbe(zones=()), persona=guidekit.CUSTOM_DOMAIN,
                         domain=None)
    assert any("domain" in p.lower() for p in problems)


def test_an_unknown_persona_is_refused_rather_than_defaulted():
    """Defaulting would silently pick one of two materially different checks."""
    with pytest.raises(ValueError):
        _problems(FakeProbe(), persona="whatever")


# ----- every problem is actionable ----------------------------------------------

def test_every_problem_is_a_sentence_not_a_code():
    probe = FakeProbe(tools={}, node=None, subdomain=None, permissions=())
    problems = _problems(probe, worker_name="Bad_Name", account_id="")
    assert len(problems) >= 5, "checks stopped at the first failure"
    for p in problems:
        assert len(p) > 30 and " " in p


def test_all_failures_are_reported_together():
    """A preflight that reports one problem per run turns a five-minute fix into
    five rounds."""
    probe = FakeProbe(tools={"gh": "2.0.0"}, node=(18, 0, 0))
    problems = _problems(probe)
    # Matched on the missing-tool phrasing, not the bare word: the Node message
    # legitimately mentions wrangler ("wrangler 4.x requires Node >= 22"), and a
    # bare substring count would make that correct sentence look like a duplicate.
    missing = [p for p in problems if "not installed or not on PATH" in p]
    assert sum("wrangler" in p for p in missing) == 1
    assert sum("pixi" in p for p in missing) == 1
    assert any("Node" in p and "too old" in p for p in problems)


def test_a_missing_account_id_does_not_suppress_the_other_findings():
    """It used to return early, which contradicted this file's own rule: the
    reader would fix the account id and immediately meet the next problem alone,
    one round at a time."""
    probe = FakeProbe(subdomain=None, permissions=())
    problems = _problems(probe, account_id="")
    assert any("account id" in p for p in problems)
    assert any("Workers Scripts" in p for p in problems)
    assert any("subdomain" in p for p in problems)


def test_pixi_toml_declares_no_task_pointing_at_a_kit_only_file():
    """A regression guard for a whole class, not one slip.

    `pixi.toml` is `templated`, so every line syncs into all eight targets — but
    `guidekit.py` is KIT-ONLY and `_prune_kit_only` deletes it from a fork. A
    `guide-kit = "python guidekit.py"` task therefore gives eight repos a command
    pointing at a file they do not have. Caught by the family drift check, which
    is a slow way to learn it."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    toml = (root / "pixi.toml").read_text()
    kit_only = ("guidekit.py", "sync.py", "adopt.py")
    for name in kit_only:
        assert f'"python {name}"' not in toml, (
            f"pixi.toml declares a task running {name}, which is kit-only and is "
            f"pruned from every fork — the task would be broken in 8 repos")


# ----- the documented invocation must be able to pass ---------------------------
#
# THE DEFECT: `preflight` ran the website's checks for everybody. `--worker-name`
# defaults to `""` and was validated unconditionally, so the README's very first
# command — a bare `preflight`, presented as the way to start — could not
# succeed on any machine, and demanded a Cloudflare account before it would let
# anyone build a PDF. The module docstring said the opposite the whole time.
#
# Every existing test missed it because the helper above filled in a worker name
# the real command line does not supply. That is the shape worth naming: the
# suite tested a call the documentation never makes.

def test_the_bare_documented_preflight_passes_with_only_pixi():
    """A reader who wants a PDF has pixi and nothing else. That is the whole
    cold start, and it must not be asked a single Cloudflare question."""
    probe = FakeProbe(tools={"pixi": "0.40.0"}, node=None,
                      subdomain=None, permissions=())
    assert guidekit.preflight(probe, persona=guidekit.WORKERS_DEV) == []
    assert not any(kind in ("subdomain", "permissions", "zone")
                   for kind, *_ in probe.asked), (
        f"the PDF-only path asked Cloudflare something: {probe.asked}")


def test_the_pdf_path_still_requires_pixi():
    """Not vacuous — it does check the one thing a PDF build needs."""
    problems = guidekit.preflight(FakeProbe(tools={}), persona=guidekit.WORKERS_DEV)
    assert any("pixi" in p for p in problems)


def test_with_web_asks_every_cloudflare_question():
    """The other half: opting into a website must not skip the checks that make
    the opt-in safe."""
    probe = FakeProbe(tools={"pixi": "0.40.0"}, node=None,
                      subdomain=None, permissions=())
    problems = guidekit.preflight(probe, persona=guidekit.WORKERS_DEV,
                                  with_web=True)
    assert problems, "the web preflight found nothing on an empty machine"
    assert any(kind == "subdomain" for kind, *_ in probe.asked)


def test_the_cli_exposes_with_web_on_preflight():
    """A flag only `init` carries cannot make `preflight` honest about which
    preflight it is running."""
    import argparse
    with pytest.raises(SystemExit) as exc:
        guidekit.main(["preflight", "--with-web", "--help"])
    assert exc.value.code == 0
    assert argparse is not None


def test_the_readme_first_command_is_the_one_that_works():
    """The command the README puts first has to be the command the CLI accepts.
    They disagreed: the docs showed a bare `preflight` and the CLI refused it."""
    import pathlib
    readme = (pathlib.Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert "guidekit.py preflight" in readme
    # ...and it is introduced as the PDF path, not as a Cloudflare gate.
    head = readme[:readme.index("## Getting started from this template")]
    assert "--with-web" in head, (
        "the cold-start section never shows how to check the website "
        "preconditions, so the reader who wants a site has no command")


def test_the_invocation_is_documented():
    """The CLI is real; what it is not is an installed executable. The docs name
    the form that actually works."""
    import pathlib
    readme = (pathlib.Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert "python guidekit.py" in readme


def test_the_probe_does_not_call_invented_wrangler_subcommands():
    """`wrangler zones list` and `wrangler subdomain get` do not exist — measured,
    `wrangler zones` answers "Unknown argument: zones". A preflight built on them
    reports every account as broken and refuses every cold start."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "guidekit.py").read_text()
    # CALL SITES, not prose: the comment that records this fix necessarily names
    # the commands it removed, and matching the bare strings flagged that comment
    # — a test failing on its own explanation.
    calls = [ln for ln in src.splitlines()
             if "subprocess.run" in ln or ln.strip().startswith('"')
             and "wrangler" in ln]
    argv = " ".join(ln for ln in src.splitlines() if '"wrangler"' in ln)
    assert '"zones"' not in argv, "still invoking the non-existent `wrangler zones`"
    assert '"subdomain"' not in argv, "still invoking `wrangler subdomain`"
    assert "api.cloudflare.com" in src, "the real API should be used instead"
    assert calls is not None


# ----- the CLI's own defaults, which the helper above deliberately bypasses ------

def test_the_documented_with_web_preflight_can_actually_pass(monkeypatch, capsys):
    """`preflight --with-web` — README's second cold-start command — must be able
    to succeed as written.

    It could not. `--worker-name` defaults to `""` and `check_worker_name` is run
    whenever the web checks are, so the command failed on `worker name '' is not
    a valid DNS label` however correct the account was, and no amount of fixing
    Cloudflare would clear it. Every test in this file went through a helper that
    filled the name in, so the suite reported a healthy check the reader could
    never satisfy.

    The fix is a default that is the RIGHT string rather than a permissive one:
    the slug `guide.toml` declares, which is what `cfadapter` turns into the
    worker name. So this drives `main()` — the default is the subject.
    """
    monkeypatch.setattr(guidekit, "Probe", lambda: FakeProbe())
    # The account id is a genuine precondition and is supplied here so it cannot
    # mask the subject: what must not appear is a WORKER NAME complaint, which no
    # correct account could ever clear.
    rc = guidekit.main(["preflight", "--with-web", "--account-id", "a" * 32])
    err = capsys.readouterr().err
    assert "worker name" not in err, (
        f"the documented invocation still fails on the worker name: {err}")
    assert rc == 0, err


def test_the_declared_slug_fallback_says_it_is_a_fallback(monkeypatch, capsys):
    """A check that cannot fail must not read as a check that passed.

    The `--worker-name` default went from `""` — which made the documented
    invocation fail on every account — to the DECLARED slug, which in a pristine
    clone is the kit's own `guide-template` and is always a valid DNS label. So
    for the cold-start reader, who has not typed a slug yet, the check went from
    "always fails" to "always passes" on a string that is not theirs. Both are
    wrong; only the second is quiet about it.

    So it says which string it looked at, and where the real check happens. Given
    with `--worker-name`, there is nothing to disclaim and it says nothing.
    """
    monkeypatch.setattr(guidekit, "Probe", lambda: FakeProbe())
    monkeypatch.setattr(guidekit, "declared_slug", lambda *a, **k: "guide-template")

    assert guidekit.main(["preflight", "--with-web", "--account-id", "a" * 32]) == 0
    out = capsys.readouterr().out
    assert "guide-template" in out and "--worker-name" in out, out

    assert guidekit.main(["preflight", "--with-web", "--account-id", "a" * 32,
                          "--worker-name", "my-own-guide"]) == 0
    assert "DECLARED" not in capsys.readouterr().out


def test_a_worker_name_that_cannot_be_resolved_is_a_named_refusal(monkeypatch, capsys):
    """Falling back to the declared slug must not become "skip the check".

    With no `--worker-name` AND no readable `OUTPUT_SLUG`, there is nothing to
    validate — and a check that quietly passes when it could not run is worse
    than the empty default it replaced, because it looks like it worked.
    """
    monkeypatch.setattr(guidekit, "Probe", lambda: FakeProbe())
    monkeypatch.setattr(guidekit, "declared_slug", lambda *a, **k: "")
    rc = guidekit.main(["preflight", "--with-web", "--account-id", "a" * 32])
    err = capsys.readouterr().err
    assert rc == 1
    assert "--worker-name" in err and "OUTPUT_SLUG" in err


def test_declared_slug_reads_the_guides_own_output_slug(tmp_path):
    (tmp_path / "guide.toml").write_text('TITLE = "T"\nOUTPUT_SLUG = "a-guide"\n',
                                         encoding="utf-8")
    assert guidekit.declared_slug(tmp_path) == "a-guide"
    assert guidekit.declared_slug(tmp_path / "nope") == ""


def test_init_forwards_every_identity_flag_to_bootstrap(monkeypatch):
    """`init` must be able to say who the author is.

    It could not: it forwarded title and slug alone, so `bootstrap.py` fell back
    to the KIT's AUTHOR/DESCRIPTION/KEYWORDS and the documented cold start
    published a stranger's guide under the kit owner's copyright — in the PDF
    metadata and in a visible `©` colophon. Asserted on the ARGV `init` builds,
    because that is the whole interface between the two scripts.
    """
    seen = {}

    class _Result:
        returncode = 0

    def _fake_run(cmd, *a, **k):
        seen["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(guidekit.subprocess, "run", _fake_run)
    rc = guidekit.main([
        "init", "My Guide", "my-guide", "--skip-preflight",
        "--author", "A. Author", "--description", "D.", "--keywords", "k1, k2",
        "--copyright-year", "2031", "--source-repo", "someone/their-kit",
        "--kit-version", "v9",
    ])
    assert rc == 0
    argv = seen["cmd"]
    for expected in (["--author", "A. Author"], ["--description", "D."],
                     ["--keywords", "k1, k2"], ["--copyright-year", "2031"],
                     ["--source-repo", "someone/their-kit"],
                     ["--kit-version", "v9"]):
        i = argv.index(expected[0])
        assert argv[i:i + 2] == expected, f"{expected[0]} not forwarded: {argv}"


def test_init_requires_an_author(monkeypatch):
    """Required at the CLI, matching `bootstrap.py`. If only bootstrap refused,
    the failure would surface after preflight had already run.

    `subprocess.run` is stubbed even though argparse is supposed to abort long
    before it, and that is not belt-and-braces: `guidekit.py` runs
    `bootstrap.py` by RELATIVE path with no `cwd=`, so it inherits pytest's — the
    repo root. When the reviewing agent applied the exact regression this test
    exists to catch, the test failed as designed and took 93 files with it,
    `tests/` included. A test guarding a destructive path must not be able to run
    it."""
    def _forbidden(cmd, *a, **k):
        raise AssertionError(
            f"argparse should have refused before anything ran; got {cmd!r}")

    monkeypatch.setattr(guidekit.subprocess, "run", _forbidden)
    with pytest.raises(SystemExit):
        guidekit.main(["init", "My Guide", "my-guide", "--skip-preflight"])


def test_the_account_id_on_the_command_line_reaches_every_cloudflare_check():
    """`--account-id` is one input and it must not be honoured by half the probes.

    `token_permissions()` read `CLOUDFLARE_ACCOUNT_ID` out of the environment
    itself, while `account_subdomain()` took the caller's value — so an operator
    who passed the account on the command line and had no env var was told the
    token "lacks the Workers Scripts:Edit permission", which names the one thing
    that was not wrong. Asserted on what the probe was ASKED, because the defect
    was invisible in the verdict: with the env var also set, both paths agreed.
    """
    probe = FakeProbe()
    _problems(probe, account_id="b" * 32)
    asked = dict((kind, rest) for kind, *rest in probe.asked)
    assert asked["permissions"] == ["b" * 32], (
        f"the permission probe did not receive the caller's account id: {probe.asked}")
    assert asked["subdomain"] == ["b" * 32]


def test_init_does_not_advertise_a_worker_name_it_ignores(capsys):
    """`init` validates the POSITIONAL slug, deliberately — that is what becomes
    the worker name. It also carried `--worker-name`, through a loop shared with
    `preflight`, and read it nowhere: passing one changed nothing and said
    nothing. `preflight` keeps the flag, where it is the subject."""
    for cmd in ("init", "preflight"):
        with pytest.raises(SystemExit):
            guidekit.main([cmd, "--help"])
        help_text = capsys.readouterr().out
        if cmd == "init":
            assert "--worker-name" not in help_text, (
                "init advertises a flag it never reads")
        else:
            assert "--worker-name" in help_text, (
                "preflight lost the flag it does read")


def test_init_refuses_a_domain_without_a_website_before_bootstrapping(monkeypatch, capsys):
    """The combination had NO REPAIR, which is what puts it in front of bootstrap.

    `init --domain` without `--with-web` bootstrapped a PDF-only guide, wrote
    `[deploy] domain` into its `guide.toml`, failed to regenerate the wrangler
    config — `cfadapter.write_wrangler` refuses a guide that declares no site —
    and then printed "Run `make wrangler` before deploying", which `make wrangler`
    refuses for the same reason. Bootstrap has deleted itself by then, so the
    reader was left with a stray key and an instruction that cannot succeed.
    """
    def _forbidden(cmd, *a, **k):
        raise AssertionError(
            f"the destructive step must not run for a combination that has no "
            f"repair; got {cmd!r}")

    monkeypatch.setattr(guidekit.subprocess, "run", _forbidden)
    monkeypatch.setattr(guidekit, "Probe", lambda: FakeProbe())
    rc = guidekit.main(["init", "My Guide", "my-guide", "--author", "A. Author",
                        "--domain", "guide.example.com", "--skip-preflight"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "--with-web" in err and "--domain" in err, err


def test_init_refuses_a_blank_author_before_running_anything(monkeypatch, capsys):
    """The flag being required only rejects its ABSENCE. `--author ""` satisfied
    argparse and was forwarded, so the fork got an empty copyright holder.

    Refused here rather than left to `bootstrap.py`'s own check because this is
    the adopter's typo, not a Cloudflare fact: making them sit through the
    network probes to be told about it puts the cheap failure behind the
    expensive one."""
    def _forbidden(cmd, *a, **k):
        raise AssertionError(f"a blank author must not reach bootstrap; got {cmd!r}")

    monkeypatch.setattr(guidekit.subprocess, "run", _forbidden)
    monkeypatch.setattr(guidekit, "Probe", lambda: FakeProbe())
    for blank in ("", "   "):
        assert guidekit.main(
            ["init", "My Guide", "my-guide", "--author", blank]) == 1
        assert "--author" in capsys.readouterr().err
