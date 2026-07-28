#!/usr/bin/env python3
"""`guide-kit` — the cold-start CLI, and the preflight that makes it honest.

WHAT A PREFLIGHT IS FOR. Not thoroughness. Its job is to convert a failure that
would otherwise happen twenty minutes in — on a runner, behind an opaque provider
error — into a sentence at second zero. Every check below corresponds to something
this family has actually watched go wrong, and every refusal carries a remediation
line, because a refusal that sends the reader to a search engine has moved the
problem rather than solved it.

THE PERSONA SPLIT IS THE DESIGN, not a convenience. The primary cold-start persona
is assumed to have **no Cloudflare zone**: someone trying the kit for the first
time, publishing to `<worker>.<subdomain>.workers.dev`. Requiring a zone from them
would make "live in an hour" unreachable for precisely the person that claim was
written for. So zone and route authority are checked ONLY on the custom-domain
path, and the `workers.dev` path is never even asked — a check that is "tolerated"
today becomes a hard requirement the first time someone tightens its error
handling.

NODE ≥ 22 BECAUSE WRANGLER 4.x REQUIRES IT. That is the whole reason. The kit
template once carried a causal claim that Node 20 makes
`cloudflare/wrangler-action` fall back to wrangler 3; it is false, it was synced
into seven guides, and it is not repeated here. That fallback is a *detection*
failure: with no local wrangler to find, the action installs its own default,
which is still 3.90.0 and predates assets-only Workers.

`guide-kit` is the PRODUCT and CLI name, and nothing in this file depends on the
repository's name — which is the point of having separated the two. The repo has
since been renamed to match, so the two agree today; this module would be
unaffected if they ever diverged again.
"""
from __future__ import annotations

from pathlib import Path

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

WORKERS_DEV = "workers.dev"
CUSTOM_DOMAIN = "custom-domain"
PERSONAS = (WORKERS_DEV, CUSTOM_DOMAIN)

# The worker name becomes a DNS LABEL in `<worker>.<subdomain>.workers.dev`, so
# this is DNS's constraint rather than a Cloudflare style preference: lowercase
# alphanumerics and hyphens, no leading or trailing hyphen, 63 characters max.
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

MIN_NODE = (22, 0, 0)

_TOOL_HELP = {
    "gh": "install the GitHub CLI: https://cli.github.com",
    "wrangler": "install wrangler 4.x: npm i -g wrangler@4",
    "pixi": "install pixi: https://pixi.sh",
}


class Probe:
    """Every external question this preflight asks, in one injectable place.

    Separated from the checks so the checks are testable without credentials or a
    network — which matters because the interesting cases here are the FAILURES,
    and provoking a real missing-permission error against a live account is not
    something a test suite can do repeatably.
    """

    def tool_version(self, name: str) -> str | None:
        if shutil.which(name) is None:
            return None
        got = subprocess.run([name, "--version"], capture_output=True, text=True)
        return got.stdout.strip() or "unknown"

    def node_version(self) -> tuple | None:
        if shutil.which("node") is None:
            return None
        got = subprocess.run(["node", "--version"], capture_output=True, text=True)
        match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", got.stdout)
        return tuple(int(x) for x in match.groups()) if match else None

    def _api(self, path: str):
        """One GET against Cloudflare's REST API.

        THE API, NOT GUESSED WRANGLER SUBCOMMANDS. An earlier draft of this file
        called `wrangler subdomain get` and `wrangler zones list`; neither exists
        (`wrangler zones` answers "Unknown argument: zones"). A preflight built on
        commands that do not exist reports every account as misconfigured — it
        would have refused every cold start, which is the opposite of its job. The
        REST endpoints below are documented and stable.
        """
        token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        if not token:
            return None
        req = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4{path}",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                payload = json.loads(r.read())
        except Exception:
            # None means "could not answer", which every caller reports as a
            # problem. Never silently "fine".
            return None
        return payload if payload.get("success") else None

    def account_subdomain(self, account_id: str) -> str | None:
        got = self._api(f"/accounts/{account_id}/workers/subdomain")
        return (got or {}).get("result", {}).get("subdomain") or None

    def token_permissions(self) -> set:
        # `/user/tokens/verify` confirms the token is live. It does not enumerate
        # scopes, so Workers Scripts:Edit is probed by asking a Workers endpoint
        # the account must be able to read — an answer means the scope is present.
        if self._api("/user/tokens/verify") is None:
            return set()
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if account_id and self._api(f"/accounts/{account_id}/workers/scripts") is not None:
            return {"workers_scripts:edit"}
        return set()

    def zone_for(self, domain: str) -> str | None:
        """The zone is the registrable suffix, so walk the labels rather than
        asking for an exact match: `guide.example.com` lives on zone
        `example.com`, and an exact-name query would find nothing."""
        parts = domain.split(".")
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            got = self._api(f"/zones?name={candidate}")
            if got and got.get("result"):
                return candidate
        return None


def check_tools(probe) -> list[str]:
    """`gh`, `wrangler`, `pixi`, and Node ≥ 22 — recorded defects turned into
    preconditions. Every missing tool is reported, not just the first."""
    problems = []
    for tool, help_text in _TOOL_HELP.items():
        if probe.tool_version(tool) is None:
            problems.append(f"{tool} is not installed or not on PATH — {help_text}")
    node = probe.node_version()
    if node is None:
        problems.append(
            "Node is not installed or not on PATH — wrangler 4.x requires "
            "Node >= 22; install it: https://nodejs.org")
    elif node < MIN_NODE:
        problems.append(
            f"Node {'.'.join(str(n) for n in node)} is too old — wrangler 4.x "
            f"requires Node >= {MIN_NODE[0]}; upgrade it: https://nodejs.org")
    return problems


def check_worker_name(name: str) -> list[str]:
    if not name or not _LABEL_RE.fullmatch(name):
        return [
            f"worker name {name!r} is not a valid DNS label — it becomes part of "
            f"<worker>.<subdomain>.workers.dev, so it must be 1-63 characters of "
            f"lowercase letters, digits and hyphens, and must not start or end "
            f"with a hyphen"
        ]
    return []


def check_workers_dev(probe, account_id: str) -> list[str]:
    problems = []
    if not account_id:
        # Reported and CONTINUED. Returning here suppressed every other finding,
        # which contradicts this preflight's own rule — the reader would fix the
        # account id and immediately meet the next problem alone.
        problems.append(
            "no Cloudflare account id — set CLOUDFLARE_ACCOUNT_ID, or pass "
            "--account-id; `npx wrangler whoami` prints it")
    if "workers_scripts:edit" not in probe.token_permissions():
        problems.append(
            "the API token lacks the Workers Scripts:Edit permission — create a "
            "token with it at https://dash.cloudflare.com/profile/api-tokens")
    if not probe.account_subdomain(account_id):
        problems.append(
            "this account has no workers.dev subdomain configured — the site "
            "would have nowhere to be served from. Set one in the Cloudflare "
            "dashboard under Workers & Pages > Subdomain")
    return problems


def check_custom_domain(probe, domain: str | None) -> list[str]:
    """Only for the custom-domain path. See the module docstring on why the
    primary persona is never asked these."""
    if not domain:
        return ["the custom-domain path needs a domain — pass --domain, or use "
                "the default workers.dev path which needs no zone at all"]
    if not probe.zone_for(domain):
        return [f"no Cloudflare zone found for {domain} — a custom domain must be "
                f"on a zone this account controls, or `wrangler deploy` cannot "
                f"bind the route. Add the zone, or drop --domain to publish on "
                f"workers.dev"]
    return []


def check_pdf_tools(probe) -> list[str]:
    """What building a PDF actually needs: pixi, and nothing else.

    Everything else the kit installs — pandoc, WeasyPrint, poppler, qpdf —
    arrives *through* pixi from `pixi.toml`, so asking for them separately would
    check the wrong thing. `gh`, `wrangler` and Node are website tooling.
    """
    if probe.tool_version("pixi") is None:
        return [f"pixi is not installed or not on PATH — {_TOOL_HELP['pixi']}"]
    return []


def preflight(probe, *, persona: str, account_id: str = "",
              worker_name: str = "", domain: str | None = None,
              with_web: bool = False) -> list[str]:
    """Every problem, together. A preflight that stops at the first failure turns
    a five-minute fix into five rounds of the same twenty-minute loop.

    `with_web` DECIDES WHICH PREFLIGHT THIS IS, and it defaults to False because
    the PDF is the kit's default output.

    The module docstring says the primary cold-start persona has no Cloudflare
    zone, and the code did not honour it in the way that mattered: every check
    ran unconditionally, so the README's first command — a bare `preflight`,
    documented as the way to start — demanded `gh`, `wrangler`, Node >= 22, a
    Cloudflare account id, a Workers Scripts token and a configured workers.dev
    subdomain before it would let anyone build a PDF. `--worker-name` defaults
    to `""` and was validated whatever you asked for, so it could not pass at
    all. The suite could not see it because the test helper filled in a worker
    name for every case.

    So the split is now about the OUTPUT, not only about the zone: a guide with
    no website is never asked a Cloudflare question, and a guide with one is
    asked all of them.
    """
    if persona not in PERSONAS:
        raise ValueError(
            f"unknown persona {persona!r} — expected one of {PERSONAS}. "
            f"Defaulting would silently pick one of two materially different "
            f"sets of checks.")
    if not with_web:
        return check_pdf_tools(probe)
    problems = check_tools(probe)
    problems += check_worker_name(worker_name)
    problems += check_workers_dev(probe, account_id)
    if persona == CUSTOM_DOMAIN:
        problems += check_custom_domain(probe, domain)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="guide-kit",
        description="Cold-start a guide from the kit.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("preflight", help="check the preconditions and stop")
    # `--with-web` belongs on BOTH, and it was only on `init`. Without it here,
    # `preflight` had no way to ask the question `init` answers, so it asked the
    # website's questions of everybody.
    pf.add_argument("--with-web", action="store_true",
                    help="also check the website preconditions (Cloudflare)")
    init = sub.add_parser("init", help="preflight, then bootstrap a new guide")
    # POSITIONAL, matching `bootstrap.py` — which declares `title` and `slug`
    # positionally — and matching the README. They disagreed: the docs showed
    # `init "My Guide" my-guide` while the CLI demanded `--name/--slug`, so the
    # documented invocation failed with an argparse error.
    init.add_argument("title", help="the guide's title")
    init.add_argument("slug", help="OUTPUT_SLUG (kebab-case)")
    init.add_argument("--with-web", action="store_true",
                      help="materialize the web layer (app/, deploy.yml)")
    init.add_argument("--skip-preflight", action="store_true",
                      help="initialize without checking preconditions")
    for p in (pf, init):
        p.add_argument("--persona", default=WORKERS_DEV, choices=PERSONAS,
                       help="workers.dev needs no zone; custom-domain does")
        p.add_argument("--account-id", default="")
        p.add_argument("--worker-name", default="")
        p.add_argument("--domain", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "preflight":
        problems = preflight(Probe(), persona=args.persona,
                             account_id=args.account_id,
                             worker_name=args.worker_name, domain=args.domain,
                             with_web=args.with_web)
        for p in problems:
            print(f"FAIL  {p}", file=sys.stderr)
        if problems:
            print(f"\n{len(problems)} problem(s) — fix these before initializing.",
                  file=sys.stderr)
            return 1
        if args.with_web:
            print(f"OK    preflight passed for the {args.persona} path")
        else:
            print("OK    preflight passed — you can build a PDF. "
                  "Add --with-web to check the website preconditions too.")
        return 0

    if args.cmd == "init":
        # Preflight FIRST and by default. Bootstrapping is cheap to redo, but the
        # failure it protects against is not: without it the adopter discovers a
        # missing account subdomain after committing, pushing and watching a
        # deploy fail with a provider error that names none of it.
        if not args.skip_preflight:
            problems = preflight(Probe(), persona=args.persona,
                                 account_id=args.account_id,
                                 # THE SLUG, because that is what actually becomes
                                 # the worker name — `cfadapter` derives it from
                                 # OUTPUT_SLUG. Validating a separately-supplied
                                 # --worker-name would check a string the generated
                                 # config never uses.
                                 worker_name=args.slug,
                                 domain=args.domain,
                                 # `init` already knows whether a website was
                                 # asked for. A PDF-only fork is not asked a
                                 # Cloudflare question.
                                 with_web=args.with_web)
            for p in problems:
                print(f"FAIL  {p}", file=sys.stderr)
            if problems:
                print(f"\n{len(problems)} problem(s) — fix these, or re-run with "
                      f"--skip-preflight to initialize anyway.", file=sys.stderr)
                return 1
        # POSITIONAL. `bootstrap.py` declares `title` and `slug` as positional
        # arguments, so the `--name`/`--slug` form this once used would have
        # failed on the very first real invocation with an argparse error.
        cmd = [sys.executable, "bootstrap.py", args.title, args.slug]
        if args.with_web:
            cmd.append("--with-web")
        print(f"  running {' '.join(cmd[1:])}")
        rc = subprocess.run(cmd).returncode
        if rc != 0 or not args.domain:
            return rc
        # AFTER bootstrap, not through it. `bootstrap.py` has no --domain flag on
        # purpose — the domain-less fork is the cold-start persona it was written
        # for. But a custom-domain adopter who passed preflight and then got a
        # guide with no domain configured would have had preflight check a fact
        # the generated config never received, which is worse than not checking.
        return apply_domain(args.domain)


def apply_domain(domain: str) -> int:
    """Write `[deploy] domain` into the freshly bootstrapped guide.toml and
    regenerate the wrangler config from it.

    Regenerating matters: `app/wrangler.jsonc` is target-owned and GENERATED, and
    `workers_dev` is derived from whether a domain is set. Writing the domain
    without regenerating would leave a config still publishing on workers.dev —
    the dual-publication defect that put eight sites outside their own WAF.
    """
    toml_path = Path("guide.toml")
    text = toml_path.read_text(encoding="utf-8")
    if re.search(r"^\s*domain\s*=", text, re.M):
        print(f"  [deploy] domain already set — leaving it alone")
    elif re.search(r"^\[deploy\]", text, re.M):
        text = re.sub(r"^\[deploy\]", f'[deploy]\ndomain = "{domain}"', text,
                      count=1, flags=re.M)
        toml_path.write_text(text, encoding="utf-8")
        print(f'  [deploy] domain <- "{domain}"')
    else:
        toml_path.write_text(text.rstrip("\n") + f'\n\n[deploy]\ndomain = "{domain}"\n',
                             encoding="utf-8")
        print(f'  [deploy] domain <- "{domain}" (new table)')
    try:
        import cfadapter
        import kitconfig
        out = cfadapter.write_wrangler(Path("app"), kitconfig.load())
        print(f"  WRANGLER -> {out}")
    except Exception as exc:
        print(f"guide-kit: wrote the domain but could not regenerate the wrangler "
              f"config ({exc}). Run `make wrangler` before deploying, or the site "
              f"will still publish on workers.dev.", file=sys.stderr)
        return 1
    return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
