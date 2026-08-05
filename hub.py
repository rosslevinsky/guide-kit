#!/usr/bin/env python3
"""hub.py — the omnibus index, generated from data.

    python hub.py update     # NETWORK: refresh the snapshot from live guides
    python hub.py build      # OFFLINE: render app/dist/index.html from the snapshot

TWO COMMANDS, AND THE SPLIT IS THE POINT. `update` reaches the network and
rewrites a committed snapshot; `build` consumes only that snapshot. So one hub
commit always renders the same page, whatever the guides happen to be serving
right now — a hub whose output depended on a live fetch would produce different
bytes on a rebuild nobody asked for, and a guide having a bad afternoon could
silently change what the hub says.

`build` cannot reach the network. Not "does not" — the fetching code lives in
`update` and `build` never calls it, which is what
`tests/test_hub_update_build_split.py` asserts.

THREE KINDS OF DATA, AND ONLY ONE COMES FROM A GUIDE:

  1. facts the guide knows — its title, its URL, whether it has a PDF. These
     come from `/guide.json` and are snapshotted.
  2. editorial judgements the HUB makes ABOUT guides — which section a guide
     belongs in, its order, its badge, the hub's own blurb, and the
     recommended/secondary distinctions. These live in `registry.toml`, in the
     hub's repository, because no guide can know them.
  3. how (1) and (2) become HTML — `hub-template.html`, which is
     `policy = "never"`: the kit ships the machinery, the hub owns its own
     appearance permanently.

The "this entry has no PDF" rule is (1), not prose: such an entry's manifest
carries `"pdf": null` and the template emits no download link. A rule written in
a README is a rule nothing enforces. (A listed site need not be a kit guide at
all — an ordinary web app can appear on a hub, and it has no PDF to offer.)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - floor is >=3.11
    import tomli as tomllib  # type: ignore[no-redef]

import kitconfig

ROOT = Path(__file__).parent.resolve()
FETCH_TIMEOUT = 20

# The upstream this hub credits in its footer, when its own `.template-version`
# does not say. Only a fallback: a third-party fork of the kit records its own
# `source_repo` at adoption, and the credit line is not the one place that
# should still name this repository.
DEFAULT_KIT_REPO = "rosslevinsky/guide-kit"


def _kit_url(root: Path) -> str:
    """The kit's GitHub URL, from this hub's own adoption record.

    Best-effort by design: a hub with no `.template-version` (or an unreadable
    one) falls back rather than failing a build over a footer link."""
    try:
        record = json.loads((root / ".template-version").read_text(encoding="utf-8"))
        repo = str(record.get("source_repo") or "").strip()
    except (OSError, ValueError):
        repo = ""
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo):
        repo = DEFAULT_KIT_REPO
    return f"https://github.com/{repo}"


class HubError(Exception):
    """The hub's data is missing, malformed, or inconsistent."""


# The fields a guide's manifest must carry for the hub to use it. Validated on
# the way IN, at `update` time, so a malformed manifest is caught while someone
# is watching rather than at build time in CI.
_REQUIRED_MANIFEST = {"slug": str, "title": str, "site": str}


def validate_manifest(data, source: str) -> dict:
    """Check one `/guide.json` and return it, or raise a named error."""
    if not isinstance(data, dict):
        raise HubError(f"{source}: guide.json is not a JSON object")
    for key, typ in _REQUIRED_MANIFEST.items():
        if key not in data:
            raise HubError(f"{source}: guide.json is missing {key!r}")
        if not isinstance(data[key], typ):
            raise HubError(
                f"{source}: guide.json {key!r} should be {typ.__name__}, "
                f"got {type(data[key]).__name__}"
            )
    # `pdf` may be absent or null — that IS the no-PDF rule — but if present it
    # must be a name the template can turn into a link.
    if data.get("pdf") is not None and not isinstance(data["pdf"], str):
        raise HubError(f"{source}: guide.json 'pdf' should be a string or null")
    return data


def load_registry(path: Path) -> dict:
    """The hub's editorial data: which guides, in what order, with what framing."""
    if not path.is_file():
        raise HubError(
            f"{path.name} not found. It is the hub's own data — which guides to "
            f"list, their sections and order, and the blurbs — and no guide can "
            f"supply it."
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                    # noqa: BLE001 - reported below
        raise HubError(f"{path.name} is not valid TOML: {exc}") from exc
    entries = data.get("guide", [])
    if not entries:
        raise HubError(f"{path.name} lists no [[guide]] entries")
    seen = set()
    for e in entries:
        for key in ("slug", "url", "section"):
            if key not in e:
                raise HubError(f"{path.name}: a [[guide]] entry is missing {key!r}")
        if e["slug"] in seen:
            raise HubError(f"{path.name}: duplicate [[guide]] slug {e['slug']!r}")
        seen.add(e["slug"])
    return data


# An explicit User-Agent, and NOT optional. The family's zone runs a WAF that
# rejects urllib's default `Python-urllib/3.x` with a 403 — measured: the same
# URL returns 200 to curl and 403 to an unmodified urllib request. This is
# recorded defects 12-13, and it is why the hub's live checks have always had to
# come from somewhere the WAF does not block. Identifying the client honestly is
# the fix; pretending to be a browser would be the other kind.
USER_AGENT = "guide-kit-hub/1 (+https://github.com/rosslevinsky/guide-kit)"


def fetch_manifest(url: str) -> dict:
    """GET `<url>/guide.json`. NETWORK — `update` only."""
    target = url.rstrip("/") + "/guide.json"
    req = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        return validate_manifest(json.loads(r.read().decode("utf-8")), target)


def update(root: Path, fetch=fetch_manifest) -> dict:
    """Refresh the snapshot from live guides. Returns the new snapshot.

    A guide that cannot be reached KEEPS ITS PREVIOUS ENTRY rather than being
    dropped. Dropping it would mean one guide's outage silently deletes it from
    the index — and the next `build` would ship that deletion as though it were
    a decision. `fetch` is injected so the failure path is testable without a
    network."""
    cfg = kitconfig.load(root)
    registry = load_registry(root / cfg.hub.registry)
    snap_path = root / cfg.hub.snapshot
    previous = {}
    if snap_path.is_file():
        previous = {g["slug"]: g for g in
                    json.loads(snap_path.read_text(encoding="utf-8")).get("guides", [])}

    guides, failures = [], []
    for entry in registry["guide"]:
        slug, url = entry["slug"], entry["url"]
        if "manual" in entry:
            # Not every listed site is a kit guide. Such a site has its
            # own Vite/React pipeline and publishes no `/guide.json`, so its
            # facts are stated in the registry instead of fetched. It is still
            # DATA — the absent `pdf` key is what suppresses its download link,
            # exactly as `"pdf": null` does for a guide that has a manifest.
            m = dict(entry["manual"])
            m.setdefault("slug", slug)
            validate_manifest(m, f"{slug} (registry [guide.manual])")
            guides.append({"slug": slug, "source": "registry.toml",
                           "title": m["title"], "site": m["site"],
                           "pdf": m.get("pdf"), "stamp": None, "chapters": 0})
            continue
        try:
            manifest = fetch(url)
        except (urllib.error.URLError, OSError, ValueError, HubError) as exc:
            if slug in previous:
                guides.append(previous[slug])
                failures.append(f"{slug}: {exc} — kept the previous snapshot entry")
                continue
            raise HubError(
                f"{slug}: could not fetch {url}/guide.json ({exc}), and there is no "
                f"previous snapshot entry to fall back to."
            ) from exc
        guides.append({"slug": slug, "source": url.rstrip("/") + "/guide.json",
                       "title": manifest["title"], "site": manifest["site"],
                       "pdf": manifest.get("pdf"), "stamp": manifest.get("stamp"),
                       "chapters": len(manifest.get("chapters", []))})
    snapshot = {"schema": 1, "guides": guides}
    snap_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    for f in failures:
        print(f"  hub: {f}", file=sys.stderr)
    print(f"  HUB   ->  {snap_path} ({len(guides)} guide(s))")
    return snapshot


def build(root: Path) -> Path:
    """Render `app/dist/index.html` from the snapshot. OFFLINE — no network at all.

    Every value on the page comes from either the committed snapshot (guide
    facts) or `registry.toml` (the hub's editorial data). Nothing is fetched, so
    two builds of one commit are identical."""
    import jinja2                                # deferred: only build needs it

    cfg = kitconfig.load(root)
    registry = load_registry(root / cfg.hub.registry)
    snap_path = root / cfg.hub.snapshot
    if not snap_path.is_file():
        raise HubError(
            f"{snap_path.name} not found. `hub build` is offline by design and "
            f"renders only from the committed snapshot — run `hub update` first "
            f"(that is the command that reaches the network)."
        )
    snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    facts = {g["slug"]: g for g in snapshot.get("guides", [])}

    missing = [e["slug"] for e in registry["guide"] if e["slug"] not in facts]
    if missing:
        raise HubError(
            f"registry lists {missing} but the snapshot has no entry for them. "
            f"Run `hub update` — building would silently omit them from the page."
        )

    sections: list[dict] = []
    by_name: dict[str, dict] = {}
    for entry in sorted(registry["guide"], key=lambda e: (e.get("order", 0), e["slug"])):
        name = entry["section"]
        if name not in by_name:
            by_name[name] = {"name": name, "lede": entry.get("section_lede", ""),
                             "order": entry.get("section_order", 0), "cards": []}
            sections.append(by_name[name])
        elif entry.get("section_lede") and not by_name[name]["lede"]:
            by_name[name]["lede"] = entry["section_lede"]
        f = facts[entry["slug"]]
        by_name[name]["cards"].append({
            "slug": entry["slug"],
            "url": entry["url"].rstrip("/"),
            # The guide's OWN title, from its manifest — the one fact the hub
            # should never retype, because retyping is how it drifts.
            "title": f["title"],
            "blurb": entry.get("blurb", ""),
            "kind": entry.get("kind", ""),
            "badge": entry.get("badge", ""),
            "link_label": entry.get("link_label", "Read online &rarr;"),
            # `pdf: null` means NO download link. The rule lives in the data.
            "pdf": f.get("pdf"),
        })
    sections.sort(key=lambda s: s["order"])

    tpl_path = root / "hub-template.html"
    if not tpl_path.is_file():
        raise HubError(f"{tpl_path.name} not found — the hub owns its own template.")
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(root)),
        autoescape=jinja2.select_autoescape(["html"]),
        undefined=jinja2.StrictUndefined,       # a typo'd field fails, never blanks
    )
    # `kit_url` comes from the hub's OWN `.template-version` when it has one, so
    # a third-party fork of the kit credits itself rather than this repository.
    # The template hardcoded `github.com/rosslevinsky/guide-kit` while
    # `--source-repo` was already forwardable everywhere else, which made the
    # credit line the one place a fork could not be its own upstream.
    html = env.get_template(tpl_path.name).render(
        sections=sections, title=cfg.TITLE, description=cfg.DESCRIPTION,
        copyright=f"© {cfg.COPYRIGHT_YEAR} {cfg.AUTHOR}",
        kit_url=_kit_url(root),
    )
    # `app/dist`, the SAME place a guide's site is built to, and the same place
    # `app/wrangler.jsonc` points its `assets.directory` at. The hub used to
    # render to `dist/` at the repo root with its config beside it, which made it
    # the one target whose worker lived somewhere else — and that divergence had
    # to be re-stated in every tool that went looking: the Makefile branched to
    # find the config, deploy.yml branched to pick a working directory, and
    # `render_site._check_wrangler_fresh` did not branch at all, so it looked in
    # `app/`, found nothing, and skipped the one config in the family that was
    # still hand-written. A rule written down three times is a rule that drifts.
    #
    # The hub is still genuinely different — it renders an index rather than a
    # document, from its own template, offline. Those differences remain and are
    # still branched on. WHERE ITS FILES SIT was never one of them.
    out = root / "app" / "dist" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"  HUB   ->  {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the omnibus guide index.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("update", help="NETWORK: refresh the snapshot from live guides.")
    sub.add_parser("build", help="OFFLINE: render app/dist/index.html from the snapshot.")
    args = p.parse_args(argv)
    try:
        if args.cmd == "update":
            update(ROOT)
        else:
            build(ROOT)
    except HubError as exc:
        sys.stderr.write(f"hub.py: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
