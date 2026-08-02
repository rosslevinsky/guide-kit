"""The hub is generated from data, and `update` and `build` are separate.

The split is the point. `update` reaches the network and rewrites a committed
snapshot; `build` consumes only that snapshot. So one hub commit always renders
the same page whatever the guides happen to be serving — a hub whose output
depended on a live fetch would produce different bytes on a rebuild nobody
asked for, and a guide having a bad afternoon could silently change what the
hub says about it.

Nothing here asserts an HTTP status against a local file. That confusion is
recorded defect 12-13's other half: a structural check on a built file answers
"is the page right", and only a request to a live URL answers "is it served".
"""
import json
import socket

import pytest

import hub

_REGISTRY = """\
[[guide]]
slug = "alpha"
url = "https://alpha.example.com"
section = "First"
section_order = 1
section_lede = "The lede."
order = 10
blurb = "Alpha's blurb."

[[guide]]
slug = "beta"
url = "https://beta.example.com"
section = "First"
section_order = 1
order = 20
kind = "recommended"
badge = "Start here"
blurb = "Beta's blurb."

[[guide]]
slug = "gamma"
url = "https://gamma.example.com"
section = "Second"
section_order = 2
order = 10
link_label = "Open the site &rarr;"
blurb = "No PDF for this one."

[guide.manual]
title = "Gamma, not a kit guide"
site = "app"
"""

_TEMPLATE = """\
<!doctype html><html><head><title>{{ title }}</title></head><body>
{% for section in sections %}<h2>{{ section.name | safe }}</h2>
{%- if section.lede %}<p class="section-lede">{{ section.lede | safe }}</p>{% endif %}
{% for card in section.cards %}<div class="card{% if card.kind %} {{ card.kind }}{% endif %}">
<h3><a href="{{ card.url }}">{{ card.title }}</a>{% if card.badge %}<span class="badge">{{ card.badge }}</span>{% endif %}</h3>
<p>{{ card.blurb | safe }}</p>
<div class="links"><a href="{{ card.url }}">{{ card.link_label | safe }}</a>
{%- if card.pdf %}<a href="{{ card.url }}/{{ card.pdf }}">Download PDF</a>{% endif %}</div>
</div>{% endfor %}{% endfor %}
</body></html>
"""

_GUIDE_TOML = """\
TITLE = "Hub"
OUTPUT_SLUG = "hub-probe"
AUTHOR = "A"
DESCRIPTION = "d"
KEYWORDS = "k"
COPYRIGHT_YEAR = 2026
[outputs]
pdf = false
site = "hub"
slides = false
[artifacts.site]
date = "2026-07-27"
[hub]
registry = "registry.toml"
snapshot = "snap.json"
"""


@pytest.fixture
def hub_repo(tmp_path):
    (tmp_path / "guide.toml").write_text(_GUIDE_TOML, encoding="utf-8")
    (tmp_path / "registry.toml").write_text(_REGISTRY, encoding="utf-8")
    (tmp_path / "hub-template.html").write_text(_TEMPLATE, encoding="utf-8")
    return tmp_path


def _fetcher(**overrides):
    """A fake `/guide.json` fetcher, keyed by host."""
    base = {
        "https://alpha.example.com": {"slug": "alpha", "title": "Alpha Guide",
                                      "site": "multipage", "pdf": "alpha.pdf",
                                      "chapters": [{"slug": "x", "title": "X"}]},
        "https://beta.example.com": {"slug": "beta", "title": "Beta Guide",
                                     "site": "single", "pdf": "beta.pdf"},
    }
    base.update(overrides)

    def fetch(url):
        value = base[url.rstrip("/")]
        if isinstance(value, Exception):
            raise value
        return hub.validate_manifest(value, url)
    return fetch


# ----- the split ---------------------------------------------------------------

def test_build_renders_with_the_network_denied(hub_repo):
    """Proven by DENYING the capability, not by reading the code path. A test
    that merely observed no fetch would pass just as well on a build that
    fetched lazily."""
    hub.update(hub_repo, fetch=_fetcher())
    real = (socket.socket, socket.create_connection, socket.getaddrinfo)

    def deny(*a, **k):
        raise RuntimeError("build opened a socket")

    socket.socket, socket.create_connection, socket.getaddrinfo = deny, deny, deny
    try:
        out = hub.build(hub_repo)
    finally:
        socket.socket, socket.create_connection, socket.getaddrinfo = real
    assert out.is_file() and out.read_text(encoding="utf-8").startswith("<!doctype")


def test_build_refuses_without_a_snapshot(hub_repo):
    """`build` is offline BY DESIGN, so a missing snapshot is a refusal naming
    the command that creates one — not a silent fetch."""
    with pytest.raises(hub.HubError, match="hub update"):
        hub.build(hub_repo)


def test_the_same_snapshot_renders_the_same_bytes(hub_repo):
    hub.update(hub_repo, fetch=_fetcher())
    first = hub.build(hub_repo).read_bytes()
    second = hub.build(hub_repo).read_bytes()
    assert first == second


def test_build_refuses_when_the_registry_outruns_the_snapshot(hub_repo):
    """Otherwise a newly registered guide is silently absent from the page."""
    hub.update(hub_repo, fetch=_fetcher())
    snap = json.loads((hub_repo / "snap.json").read_text(encoding="utf-8"))
    snap["guides"] = [g for g in snap["guides"] if g["slug"] != "beta"]
    (hub_repo / "snap.json").write_text(json.dumps(snap), encoding="utf-8")
    with pytest.raises(hub.HubError, match="beta"):
        hub.build(hub_repo)


# ----- the fallback ------------------------------------------------------------

def test_an_unreachable_guide_keeps_its_previous_entry(hub_repo):
    """Dropping it would let one guide's outage delete it from the index — and
    the next build would ship that deletion as though it were a decision."""
    hub.update(hub_repo, fetch=_fetcher())
    import urllib.error
    snap = hub.update(hub_repo, fetch=_fetcher(**{
        "https://alpha.example.com": urllib.error.URLError("down")}))
    alpha = next(g for g in snap["guides"] if g["slug"] == "alpha")
    assert alpha["title"] == "Alpha Guide", "the outage dropped the guide"


def test_an_unreachable_guide_with_no_history_is_a_refusal(hub_repo):
    """The one case where falling back is impossible. Silently emitting a page
    without it would be worse than stopping."""
    import urllib.error
    with pytest.raises(hub.HubError, match="no previous snapshot"):
        hub.update(hub_repo, fetch=_fetcher(**{
            "https://alpha.example.com": urllib.error.URLError("down")}))


# ----- the no-PDF rule, enforced by DATA ---------------------------------------

def test_a_guide_without_a_pdf_gets_no_download_link(hub_repo):
    """A PDF-less hub entry in miniature. The rule used to be prose in a README;
    prose is not enforcement."""
    hub.update(hub_repo, fetch=_fetcher())
    html = hub.build(hub_repo).read_text(encoding="utf-8")
    assert "gamma.example.com/Download" not in html
    assert html.count("Download PDF") == 2, "expected exactly the two guides with PDFs"
    assert "Open the site &rarr;" in html, "its custom link label was lost"


def test_a_null_pdf_is_as_good_as_an_absent_one(hub_repo):
    hub.update(hub_repo, fetch=_fetcher(**{
        "https://beta.example.com": {"slug": "beta", "title": "Beta Guide",
                                     "site": "single", "pdf": None}}))
    html = hub.build(hub_repo).read_text(encoding="utf-8")
    assert html.count("Download PDF") == 1


# ----- validation --------------------------------------------------------------

@pytest.mark.parametrize("bad,match", [
    ({"title": "T", "site": "single"}, "slug"),
    ({"slug": "s", "site": "single"}, "title"),
    ({"slug": "s", "title": "T"}, "site"),
    ({"slug": "s", "title": 1, "site": "single"}, "title"),
    ({"slug": "s", "title": "T", "site": "single", "pdf": 7}, "pdf"),
])
def test_a_malformed_manifest_is_rejected_at_update_time(bad, match):
    """Caught on the way IN, while someone is watching, rather than at build
    time in CI."""
    with pytest.raises(hub.HubError, match=match):
        hub.validate_manifest(bad, "probe")


def test_a_manifest_that_is_not_an_object_is_rejected():
    with pytest.raises(hub.HubError, match="not a JSON object"):
        hub.validate_manifest([1, 2, 3], "probe")


def test_a_duplicate_registry_slug_is_rejected(hub_repo):
    (hub_repo / "registry.toml").write_text(
        _REGISTRY + '\n[[guide]]\nslug = "alpha"\nurl = "https://x"\nsection = "S"\n',
        encoding="utf-8")
    with pytest.raises(hub.HubError, match="duplicate"):
        hub.load_registry(hub_repo / "registry.toml")


def test_a_registry_entry_missing_a_required_key_is_rejected(hub_repo):
    (hub_repo / "registry.toml").write_text(
        '[[guide]]\nslug = "a"\nurl = "https://x"\n', encoding="utf-8")
    with pytest.raises(hub.HubError, match="section"):
        hub.load_registry(hub_repo / "registry.toml")


# ----- structure, never HTTP ---------------------------------------------------

def test_the_page_carries_the_registrys_sections_in_order(hub_repo):
    hub.update(hub_repo, fetch=_fetcher())
    html = hub.build(hub_repo).read_text(encoding="utf-8")
    assert html.index("<h2>First</h2>") < html.index("<h2>Second</h2>")
    assert '<p class="section-lede">The lede.</p>' in html


def test_editorial_data_reaches_the_page(hub_repo):
    """The hub's judgements ABOUT guides — which no guide can supply."""
    hub.update(hub_repo, fetch=_fetcher())
    html = hub.build(hub_repo).read_text(encoding="utf-8")
    assert 'class="card recommended"' in html
    assert '<span class="badge">Start here</span>' in html
    assert "Alpha's blurb." in html


def test_titles_come_from_the_guides_not_the_registry(hub_repo):
    """The one fact the hub must never retype — retyping is how the
    hand-written page drifted from the guides in the first place."""
    hub.update(hub_repo, fetch=_fetcher(**{
        "https://alpha.example.com": {"slug": "alpha", "title": "Renamed Upstream",
                                      "site": "multipage", "pdf": "alpha.pdf"}}))
    assert "Renamed Upstream" in hub.build(hub_repo).read_text(encoding="utf-8")


def test_a_template_typo_fails_rather_than_rendering_blank(hub_repo):
    """StrictUndefined. A silently blank card is the failure mode a hub page
    would ship without anyone noticing."""
    (hub_repo / "hub-template.html").write_text(
        "{% for s in sections %}{{ s.nmae }}{% endfor %}", encoding="utf-8")
    hub.update(hub_repo, fetch=_fetcher())
    import jinja2
    with pytest.raises(jinja2.UndefinedError):
        hub.build(hub_repo)


def test_the_shipped_hub_template_renders_clean(repo_root):
    """The SEED template — `templates/hub/hub-template.html` — rendered for real.

    Every other test in this file uses a synthetic template, which is exactly how
    a `<!-- STARTER TEXT … -->` maintenance note inside `<head>` came to be
    published by every hub built from this seed: an HTML comment survives
    rendering, nothing rendered the real file, and the defect was invisible to a
    suite that was otherwise thorough about hubs.

    Two properties, and both are about what reaches a READER: no maintenance
    commentary in the output, and no hardcoded upstream — the credit line is
    `{{ kit_url }}` so a third-party fork of the kit can be its own upstream.
    """
    import jinja2

    root = repo_root / "templates" / "hub"
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(root)),
        autoescape=jinja2.select_autoescape(["html"]),
        undefined=jinja2.StrictUndefined,
    )
    out = env.get_template("hub-template.html").render(
        sections=[], title="T", description="D", copyright="© 2026 A",
        kit_url="https://github.com/someone/their-kit",
    )
    for leak in ("STARTER TEXT", "policy = ", "NOTE (", "kit maintainers"):
        assert leak not in out, (
            f"the built hub publishes maintenance commentary ({leak!r}); use a "
            f"Jinja `{{# #}}` comment, which the engine removes, not an HTML one"
        )
    assert "someone/their-kit" in out, "the footer credit is not parameterized"
    assert "rosslevinsky" not in out, (
        "the seed template hardcodes this repository as the upstream, so a fork "
        "of the kit cannot credit itself"
    )
