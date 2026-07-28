#!/usr/bin/env python3
"""cfadapter.py — everything Cloudflare-specific about publishing a guide.

The core renderer emits a **plain static directory**: HTML, the PDF, fonts. Any
static host can serve it. This module owns the two things that are not that —
the `_headers` file and the wrangler contract — so "which provider" is one
import rather than a fact smeared through `render_site.py`.

Both are derived from `guide.toml` and nothing else. That is the point of the
module, not a tidiness preference: the two defects this family actually shipped
were both configuration that lived somewhere other than the repository. The
`workers.dev` dual-publish (recorded defect 14) was an intent written in prose
while Cloudflare's default re-asserted itself on every deploy, and the custom
domains were bound by hand in the dashboard, where nothing could review them and
a new adopter inherits nothing.

Forced download is **provider-optional**, and is stated that way rather than
promised. `_headers` is a Cloudflare Static Assets feature; a generic static
server ignores the file, so the PDF opens in the browser's viewer instead of
downloading. Everything else about the output tree behaves identically anywhere.
"""
from __future__ import annotations

import json
import re

HEADERS_FILENAME = "_headers"
WRANGLER_FILENAME = "wrangler.jsonc"

# Pinned deliberately: bumping it can change Workers runtime behaviour, so it is
# a reviewed edit rather than a value that drifts with whatever wrangler defaults
# to on the day a guide is bootstrapped.
COMPATIBILITY_DATE = "2026-04-23"

_WRANGLER_PREAMBLE = """\
{
  // Cloudflare Workers Static Assets config for the website output.
  //
  // GENERATED from guide.toml by `make wrangler` (cfadapter.py). Do not hand-edit:
  // it is `policy = "never"` in kit-manifest.toml, so sync will not overwrite your
  // edit — it will simply drift from the generator, and the kit's
  // test_each_targets_committed_wrangler_matches_the_generator goes red instead
  // of anything being silently corrected. Change guide.toml (or the generator)
  // and re-run.
  //
  // `make web` builds the site into ./dist; wrangler serves that directory. NO
  // not_found_handling (the default 404 handling is correct) and NO SPA routing.
  //
  // `workers_dev` is DERIVED, never authored: false when [deploy] domain is set,
  // true when it is not. It is not merely tidiness. Cloudflare's default is to
  // serve every worker at <name>.<account>.workers.dev, and `wrangler deploy`
  // RE-ASSERTS that default on every run unless the config says otherwise.
  // Turning it off in the dashboard therefore does not stick: the next deploy
  // silently switches it back on, and each guide ends up published at TWO public
  // URLs — its custom domain and a workers.dev one outside the zone, so outside
  // its WAF, its analytics and its redirect rules. That is exactly what happened
  // across this family: the intent was recorded in prose, never in config, and
  // eight sites were quietly dual-published for weeks.
  //
  // A guide with NO domain is the opposite case and the one the kit exists to
  // serve: a stranger with no Cloudflare zone. There `workers_dev: true` is the
  // whole publication story, and no routes block is emitted at all.
  //
  // `routes` + `custom_domain: true` bind the domain at DEPLOY time, with no
  // dashboard step — the approach the family hub already uses. A domain bound by
  // hand is invisible to review and un-inheritable by an adopter.
  //
  // `preview_urls` is a SEPARATE workers.dev surface from `workers_dev`, and is
  // authored per guide in `[deploy] preview_urls` — defaulting to FALSE.
  //
  // Turning `workers_dev` off does nothing to preview URLs: they are served at
  // `<version>-<worker>.<subdomain>.workers.dev`, EVERY version gets one (a
  // production `wrangler deploy` as much as a PR's `versions upload`), and they
  // do not expire. So a guide that has deliberately left workers.dev keeps
  // accruing public, un-WAF'd URLs serving the same content unless this is off.
  // Cloudflare made the same call: since wrangler 4.44.0 their default is
  // `preview_urls = workers_dev`.
  //
  // Set `[deploy] preview_urls = true` to get PR preview links back. That is a
  // real feature — deploy.yml comments the URL on every pull request — so it is
  // an opt-in rather than a removal.
"""


class CloudflareConfigError(ValueError):
    """A config `kitconfig` accepts that Cloudflare will not."""


# A Custom Domain pattern is a HOSTNAME. Cloudflare rejects a scheme, a path, a
# port or a wildcard, and `kitconfig` deliberately does not know that — it
# validates a guide, not a provider. So the check lives here, at the boundary
# that cares, and fails at generate time rather than at deploy time in CI.
_HOSTNAME_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"^{_HOSTNAME_LABEL}(\.{_HOSTNAME_LABEL})+$")

# workers.dev serves the Worker at <name>.<subdomain>.workers.dev, so the name
# has to be a DNS label: 63 characters, and it is the whole publication story for
# a guide with no domain.
_WORKER_NAME_RE = re.compile(rf"^{_HOSTNAME_LABEL}$")


def _validated_domain(raw: str) -> str:
    """`raw`, stripped, or "" — raising if it is set but not a hostname."""
    domain = (raw or "").strip()
    if not domain:
        return ""
    if not _HOSTNAME_RE.match(domain) or len(domain) > 253:
        raise CloudflareConfigError(
            f"[deploy] domain must be a bare hostname, not {domain!r}. Cloudflare "
            f"binds a Custom Domain by hostname: drop any scheme, port, path or "
            f"wildcard (e.g. 'guide.example.com')."
        )
    return domain


def wrangler_config(cfg) -> dict:
    """The wrangler config a guide's `guide.toml` implies.

    Separate from the rendering below so tests can assert the *decisions* —
    `workers_dev`, the presence and shape of `routes` — without parsing JSONC."""
    domain = _validated_domain(getattr(cfg, "deploy", None) and cfg.deploy.domain)
    if not domain and not _WORKER_NAME_RE.match(cfg.OUTPUT_SLUG):
        # Only when workers.dev IS the publication story. With a custom domain the
        # Worker name never appears in a hostname, so the constraint does not bind.
        raise CloudflareConfigError(
            f"OUTPUT_SLUG {cfg.OUTPUT_SLUG!r} cannot be a workers.dev subdomain "
            f"label (letters, digits and hyphens, 63 chars, no leading/trailing "
            f"hyphen). Either shorten it or set [deploy] domain."
        )
    config: dict = {
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": cfg.OUTPUT_SLUG,
        "compatibility_date": COMPATIBILITY_DATE,
        "assets": {"directory": "./dist"},
        # Derived, and asserted rather than assumed: `workers_dev` is true exactly
        # when there is no domain to serve instead.
        "workers_dev": not domain,
        # Authored per guide, defaulting OFF. A SEPARATE workers.dev surface
        # from `workers_dev` above — see kitconfig.DeployConfig.preview_urls for
        # why the default is what it is.
        "preview_urls": bool(getattr(cfg, "deploy", None)
                             and cfg.deploy.preview_urls),
    }
    if domain:
        config["routes"] = [{"pattern": domain, "custom_domain": True}]
    return config


def render_wrangler_jsonc(cfg) -> str:
    """The full `app/wrangler.jsonc` text, comments included.

    The comments are the reason this is assembled rather than `json.dumps`-ed
    whole: every one of them records a defect this family actually shipped, and a
    generated file that drops them would lose the only place that reasoning
    lives."""
    body = json.dumps(wrangler_config(cfg), indent=2)
    inner = body[1:].lstrip("\n")          # drop the opening brace; keep the rest
    return _WRANGLER_PREAMBLE + inner + "\n"


def write_wrangler(app_dir, cfg) -> "object":
    """Write `app/wrangler.jsonc`. Returns the path written."""
    app_dir.mkdir(parents=True, exist_ok=True)
    path = app_dir / WRANGLER_FILENAME
    path.write_text(render_wrangler_jsonc(cfg), encoding="utf-8")
    return path


def headers_text(pdf_name: str) -> str:
    """The `_headers` body: force the reference PDF to download.

    WHY A HEADER AND NOT JUST THE `download` ATTRIBUTE. The anchor's `download`
    attribute is enough on this guide's OWN page, where the PDF is same-origin.
    It is silently ignored cross-origin — a deliberate browser restriction — and
    an omnibus hub linking several guides serves those links from a DIFFERENT
    subdomain than the PDFs. So on such a hub the attribute does nothing and a
    button labelled "PDF" opens the browser's viewer instead of downloading. Only
    a server-side Content-Disposition works from there. (This is not
    hypothetical: it is how the hub in the family this kit came from behaves.)

    THE TRADE, stated because it is a real loss: this also makes a direct
    navigation to the PDF URL download rather than preview. That is accepted
    deliberately — the PDF is published as a downloadable deliverable, the
    readable version is the website itself, and a link labelled as a download
    doing something else is the worse failure.

    Written at build time rather than tracked as a file because `app/dist/` is
    generated and gitignored, and `app/public/` is not copied into it. A
    zone-level Transform Rule would also work, but this family has already been
    bitten by configuration that lived outside the repo — `workers.dev`, which a
    tool silently re-enabled on every deploy.
    """
    return (f"/{pdf_name}\n"
            f'  Content-Disposition: attachment; filename="{pdf_name}"\n')


def write_headers(web_dir, pdf_name: str) -> "object":
    """Write `_headers` into the built site. Returns the path written.

    PROVIDER-OPTIONAL: Cloudflare Static Assets reads this from the assets
    directory; a generic static server ignores it and serves the PDF inline.
    `tests/test_static_portability.py` asserts the tree is otherwise correct
    without it."""
    path = web_dir / HEADERS_FILENAME
    path.write_text(headers_text(pdf_name), encoding="utf-8")
    return path
