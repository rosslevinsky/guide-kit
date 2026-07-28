"""The built site is a PLAIN STATIC DIRECTORY, and that is proven by serving it.

The kit's whole "usable by a stranger" claim rests on the output tree not being
Cloudflare-shaped. A grep for provider names cannot establish that — it shows
what the code *says*, not what a different host would actually serve. So this
starts `http.server` over the exact directory `make web` produced and makes real
requests against it.

What is deliberately NOT asserted here is forced download. `_headers` is a
Cloudflare Static Assets feature; a generic server ignores the file and serves
the PDF inline. That is a real difference between hosts, so it is documented as
**provider-optional** and covered separately in
`tests/test_wrangler_generated.py` and the adapter's own tests, rather than
being quietly claimed as universal behaviour.
"""
import functools
import http.server
import shutil
import socket
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

import cfadapter

from conftest import render  # noqa: PLC0415 — the fixture's own helper


@contextmanager
def _serving(directory):
    """A generic static server over `directory`. Nothing Cloudflare about it."""
    # `directory` MUST be passed to __init__, not set as a class attribute:
    # SimpleHTTPRequestHandler.__init__ assigns self.directory unconditionally,
    # defaulting to os.getcwd(), so a class attribute is silently overwritten and
    # the server quietly serves the repo root instead. Four of the assertions
    # below passed against a directory listing of the kit before this was fixed —
    # which is exactly the failure mode this file exists to rule out.
    quiet = type("Handler", (http.server.SimpleHTTPRequestHandler,),
                 {"log_message": lambda *a, **k: None})
    handler = functools.partial(quiet, directory=str(directory))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(base, path):
    """(status, headers, body) — 404s come back as a value, not an exception.

    Header names are lower-cased: HTTP treats them case-insensitively and
    `http.server` sends `Content-type`, so a plain `dict(r.headers)` lookup for
    `Content-Type` raises `KeyError` on a response that is perfectly correct."""
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=10) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


@pytest.fixture
def served_site(guide_repo):
    """A real built site: render the PDF, promote it as `make baseline` would
    (build_web hard-fails without a reference), then build the web layer."""
    root, _ = guide_repo
    render(root)
    shutil.copyfile(root / "build" / "probe-guide.pdf", root / "probe-guide.pdf")
    render(root, "--web")
    dist = root / "app" / "dist"
    assert dist.is_dir(), "make web produced no output directory"
    with _serving(dist) as base:
        yield base, dist


# ----- the tree serves correctly off a generic host --------------------------

def test_the_landing_page_serves_the_guides_own_content(served_site):
    base, _ = served_site
    status, headers, body = _get(base, "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"Probe Guide" in body, "the site served something that is not this guide"


def test_the_pdf_serves_with_the_right_media_type(served_site):
    base, _ = served_site
    status, headers, body = _get(base, "/probe-guide.pdf")
    assert status == 200
    assert headers["content-type"] == "application/pdf"
    assert body.startswith(b"%PDF-"), "the download link does not serve a PDF"


def test_every_asset_the_page_references_resolves(served_site):
    """The link graph has to be closed against the SERVED tree. A stylesheet or
    font that 404s is invisible to a build-time file listing and obvious to a
    reader."""
    base, _ = served_site
    _, _, body = _get(base, "/")
    html = body.decode("utf-8")
    import re
    refs = set(re.findall(r'(?:href|src)="([^"]+)"', html))
    local = [r for r in refs
             if not r.startswith(("http://", "https://", "data:", "mailto:", "#"))]
    assert local, "the page references no local assets at all — fixture is wrong"
    broken = [r for r in local if _get(base, "/" + r.lstrip("/"))[0] != 200]
    assert not broken, f"referenced but not served: {broken}"


def test_a_missing_path_is_a_plain_404(served_site):
    """No SPA rewrite, no not_found_handling: a missing path is missing. A host
    that rewrote it to index.html would make every broken link look fine."""
    base, _ = served_site
    status, _, _ = _get(base, "/no-such-page/")
    assert status == 404


# ----- the provider-specific part is isolated, and says so -------------------

def test_the_only_cloudflare_artifact_is_headers(served_site):
    """Everything else in the tree is provider-neutral.

    Asserted as EXCLUSIVITY against a list of things providers put in a static
    root, not merely as "`_headers` is present and `wrangler.jsonc` is not" —
    that pair stays green while a `_routes.json` or a `netlify.toml` quietly
    appears beside them, which is the drift this is meant to catch. A new
    provider artifact belongs in `cfadapter` and in this list, deliberately."""
    _, dist = served_site
    names = {p.name for p in dist.rglob("*") if p.is_file()}
    known_provider_artifacts = {
        "_headers", "_redirects", "_routes.json", "_worker.js",
        "wrangler.jsonc", "wrangler.toml", "netlify.toml", "vercel.json",
        ".htaccess", "staticwebapp.config.json", "firebase.json",
    }
    present = names & known_provider_artifacts
    assert present == {cfadapter.HEADERS_FILENAME}, (
        f"the built tree should carry exactly one provider-specific file "
        f"({cfadapter.HEADERS_FILENAME}); found {sorted(present)}"
    )


def test_the_site_still_serves_without_the_cloudflare_file(served_site):
    """Portability, stated as the removable thing it is: delete `_headers` and
    the site is unchanged apart from the download behaviour it existed to add."""
    base, dist = served_site
    (dist / cfadapter.HEADERS_FILENAME).unlink()
    assert _get(base, "/")[0] == 200
    status, headers, _ = _get(base, "/probe-guide.pdf")
    assert status == 200
    # And the honest part: a generic host never applied it anyway.
    assert "content-disposition" not in headers, \
        "a generic static server should not be applying _headers"
