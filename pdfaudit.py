#!/usr/bin/env python3
"""The one-time PDF font-table audit: which face did each ANCHORED run select?

`pdffonts` answers a weaker question. It lists the faces a document EMBEDS, so it
is satisfied the moment every embedded face is bundled — INCLUDING when a run
picked the wrong bundled one. Coverage is satisfied too, because the wrong face
usually contains the glyph. A heading rendered in the body face, or a bold run
resolving to the regular weight, passes both permanent checks and looks merely
"a bit off".

So the audit reads content streams and answers, per run: which face, and drawing
which glyphs. It is ANCHORED — an expectation is attached to specific source text
— because a document-wide allow-list cannot catch the regression that matters:
when both faces are legitimately used somewhere, swapping one for the other
changes no set.

THE DECODE CHAIN, and one thing it is not.
    character code --/Encoding CMap--> CID --/CIDToGIDMap--> GID
`ToUnicode` is NOT that map. It maps codes to TEXT, for extraction and search.
It is used here ONLY to recover the source text a run represents, so an anchor
can be matched — which is precisely what it is for.

WHAT IS AUDITED, AND WHAT IS REPORTED AS NOT. A check whose reach is unclear is
worse than none, so anything outside the decodable case is listed in
`unauditable` rather than passing silently:
  * Only `Identity-H` Type0 fonts are decoded. Simple fonts (Type1/TrueType with
    a byte encoding) and any other CMap are REPORTED.
  * A non-Identity `/CIDToGIDMap` is REPORTED: the CID->GID step then needs the
    stream, and assuming identity would be assuming the answer.
  * CIDFontType0 (CFF) maps CID->GID through the CFF charset, which this does not
    parse. WeasyPrint emits identity there; it is REPORTED as an assumption.
  * Type3 fonts are refused outright — their glyphs are content streams, so
    "which face" has no answer.
"""
from __future__ import annotations

import json
import re
import subprocess
import zlib
from dataclasses import dataclass, field
from pathlib import Path


class AuditError(Exception):
    """The PDF cannot be audited, or an anchored run selected the wrong face."""


@dataclass
class Run:
    """One text-showing operation: the face it selected and what it drew."""

    base_font: str
    cids: list[int] = field(default_factory=list)
    text: str = ""
    page: int = 0

    @property
    def family(self) -> str:
        """The face name with the PDF subset tag stripped."""
        return self.base_font.split("+", 1)[1] if "+" in self.base_font else self.base_font


# ---------------------------------------------------------------------------
# qpdf access
# ---------------------------------------------------------------------------

def _objects(pdf: Path) -> dict:
    out = subprocess.run(["qpdf", "--json=latest", "--json-stream-data=inline", str(pdf)],
                         capture_output=True, check=False)
    if out.returncode not in (0, 3) or not out.stdout:
        raise AuditError(f"qpdf --json failed for {pdf.name}: "
                         f"{out.stderr.decode('utf-8', 'replace')[:200]}")
    return json.loads(out.stdout).get("qpdf", [{}, {}])[1]


def _key(ref) -> str:
    """qpdf keys objects as `obj:N 0 R`; references inside objects are `N 0 R`."""
    s = str(ref)
    return s if s.startswith("obj:") else f"obj:{s}"


def _val(objs: dict, ref) -> object:
    """Resolve a value that may be an indirect reference."""
    if isinstance(ref, str) and ref.endswith(" R"):
        entry = objs.get(_key(ref))
        return entry.get("value") if isinstance(entry, dict) else None
    return ref


def _stream_bytes(objs: dict, ref) -> bytes:
    """A stream's decoded bytes. qpdf inlines stream data as base64."""
    import base64

    entry = objs.get(_key(ref))
    if not isinstance(entry, dict):
        return b""
    data = entry.get("stream", {}).get("data")
    if data is None:
        return b""
    raw = base64.b64decode(data)
    filt = str(entry.get("stream", {}).get("dict", {}).get("/Filter", ""))
    if "FlateDecode" in filt:
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
    return raw


# ---------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------

def font_table(pdf: Path) -> dict[str, dict]:
    """Every font object, keyed by its object id, with what can be audited."""
    objs = _objects(pdf)
    table: dict[str, dict] = {}
    for name, entry in objs.items():
        value = entry.get("value") if isinstance(entry, dict) else None
        if not isinstance(value, dict) or value.get("/Type") != "/Font":
            continue
        subtype = str(value.get("/Subtype", ""))
        base = str(value.get("/BaseFont", "")).lstrip("/")
        if subtype in ("/CIDFontType0", "/CIDFontType2"):
            # A DESCENDANT, reached through a Type0's /DescendantFonts. It carries
            # /Type /Font but is never selected by Tf, so treating it as a
            # top-level font reported every real face as an unauditable
            # "simple font" and left the audit with nothing to audit.
            continue
        if subtype == "/Type3":
            raise AuditError(
                f"{pdf.name}: {base or name} is a Type3 font — its glyphs are content "
                f"streams, so 'which face' has no answer, and nothing here should emit one."
            )
        record = {"base_font": base, "subtype": subtype,
                  "encoding": str(value.get("/Encoding", "")),
                  "tounicode": value.get("/ToUnicode"), "reason": ""}
        if subtype != "/Type0":
            # Simple fonts use a BYTE encoding, so their shown strings are not
            # 2-byte CIDs. Reported, never skipped: silently omitting one would
            # let its text escape the audit entirely.
            record["auditable"] = False
            record["reason"] = f"simple font ({subtype or 'unknown subtype'})"
        elif record["encoding"] != "/Identity-H":
            record["auditable"] = False
            record["reason"] = f"encoding {record['encoding']} is not Identity-H"
        else:
            desc = _val(objs, (_val(objs, value.get("/DescendantFonts")) or [None])[0])
            cid2gid = str(desc.get("/CIDToGIDMap", "/Identity")) if isinstance(desc, dict) else "/Identity"
            record["descendant"] = str(desc.get("/Subtype", "")) if isinstance(desc, dict) else ""
            if cid2gid not in ("/Identity", ""):
                # A CIDToGIDMap STREAM means CID != GID; assuming identity would
                # be assuming the very thing the audit is meant to establish.
                record["auditable"] = False
                record["reason"] = "non-identity /CIDToGIDMap"
            else:
                record["auditable"] = True
                record["cid_is_gid"] = True
        table[name] = record
    return table


def _tounicode(objs: dict, ref) -> dict[int, str]:
    """code -> text, parsed from a ToUnicode CMap. TEXT ONLY."""
    if not ref:
        return {}
    data = _stream_bytes(objs, ref if isinstance(ref, str) else "")
    if not data:
        return {}
    text = data.decode("latin-1", "replace")
    out: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            out[int(src, 16)] = _utf16be(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            start = int(dst, 16)
            for i, code in enumerate(range(int(lo, 16), int(hi, 16) + 1)):
                out[code] = chr(start + i)
    return out


def _utf16be(hexstr: str) -> str:
    try:
        return bytes.fromhex(hexstr).decode("utf-16-be", "replace")
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# content streams
# ---------------------------------------------------------------------------

_TOKEN = re.compile(rb"""
      /(?P<name>[A-Za-z0-9#+.\-_]+)
    | (?P<hex><[0-9A-Fa-f\s]*>)
    | (?P<num>-?[\d.]+)
    | (?P<op>Tf|TJ|Tj|'|"|q|Q|Do|BT|ET)
""", re.X)


def _literal_strings(chunk: bytes) -> list[bytes]:
    """`(…)` strings, with escapes and nesting handled.

    A hex-only scan misses these entirely, and WeasyPrint is free to emit them —
    so a run of visible text would simply not appear in the audit."""
    out, i = [], 0
    while i < len(chunk):
        if chunk[i:i + 1] != b"(":
            i += 1
            continue
        depth, j, buf = 1, i + 1, bytearray()
        while j < len(chunk) and depth:
            c = chunk[j:j + 1]
            if c == b"\\":
                buf += chunk[j:j + 2]
                j += 2
                continue
            if c == b"(":
                depth += 1
            elif c == b")":
                depth -= 1
                if not depth:
                    break
            buf += c
            j += 1
        out.append(bytes(buf))
        i = j + 1
    return out


def _page_contents(objs: dict) -> list[tuple[int, bytes, dict]]:
    """(page number, content bytes, resource->font-object map) per page.

    SCOPED, deliberately. Scanning every stream in the file reads font programs,
    ToUnicode CMaps and images as if they were page content, where matching bytes
    can fabricate a run or a false tofu report. And resources are PER PAGE: `/F1`
    on page 1 and `/F1` on page 2 can be different fonts, so one global map
    mis-attributes runs to the wrong face."""
    pages: list[tuple[int, bytes, dict]] = []
    n = 0
    for name, entry in objs.items():
        value = entry.get("value") if isinstance(entry, dict) else None
        if not isinstance(value, dict) or value.get("/Type") != "/Page":
            continue
        n += 1
        contents = value.get("/Contents")
        refs = contents if isinstance(contents, list) else [contents]
        data = b"".join(_stream_bytes(objs, r) for r in refs if isinstance(r, str))
        resources = _val(objs, value.get("/Resources")) or {}
        fonts = _val(objs, resources.get("/Font")) if isinstance(resources, dict) else {}
        fmap = {k.lstrip("/"): v for k, v in (fonts or {}).items()} if isinstance(fonts, dict) else {}
        # Form XObjects carry their OWN /Resources; their content is drawn by Do.
        xobjs = _val(objs, resources.get("/XObject")) if isinstance(resources, dict) else {}
        for xref in (xobjs or {}).values() if isinstance(xobjs, dict) else []:
            xval = _val(objs, xref)
            if not isinstance(xval, dict) or str(xval.get("/Subtype")) != "/Form":
                continue
            xres = _val(objs, xval.get("/Resources")) or {}
            xfonts = _val(objs, xres.get("/Font")) if isinstance(xres, dict) else {}
            data += b"\n" + _stream_bytes(objs, xref if isinstance(xref, str) else "")
            fmap.update({k.lstrip("/"): v
                         for k, v in (xfonts or {}).items()} if isinstance(xfonts, dict) else {})
        pages.append((n, data, fmap))
    return pages


def runs(pdf: Path) -> list[Run]:
    """Every text-showing run, with the face it selected and the CIDs it drew."""
    objs = _objects(pdf)
    table = font_table(pdf)
    unicode_maps = {k: _tounicode(objs, rec.get("tounicode"))
                    for k, rec in table.items()}
    out: list[Run] = []

    for page_no, data, fmap in _page_contents(objs):
        current: str | None = None
        stack: list[str | None] = []
        pending: list[bytes] = []
        pos = 0
        while True:
            m = _TOKEN.search(data, pos)
            if not m:
                break
            pos = m.end()
            if m.group("name"):
                pending.append(m.group("name"))
                continue
            if m.group("hex") is not None:
                pending.append(m.group("hex"))
                continue
            raw_op = m.group("op")
            if raw_op is None:
                continue
            # DECODED. The pattern is bytes, so `m.group("op")` is bytes and every
            # comparison against a str operator silently evaluated False — the
            # tokenizer ran correctly and the dispatch below never fired once.
            op = raw_op.decode("latin-1")
            if op == "q":
                stack.append(current)
            elif op == "Q":
                # Graphics-state RESTORE also restores the font. Without this a
                # `q /F2 Tf … Q` block left every later run attributed to F2.
                current = stack.pop() if stack else current
            elif op == "Tf":
                names = [p for p in pending if isinstance(p, bytes) and not p.startswith(b"<")]
                if names:
                    current = names[-1].decode("latin-1")
            elif op in ("Tj", "TJ", "'", '"'):
                ref = fmap.get(current or "")
                key = _key(ref) if isinstance(ref, str) else None
                rec = table.get(key or "", {})
                base = rec.get("base_font", current or "?")
                codes: list[int] = []
                for token in pending:
                    if isinstance(token, bytes) and token.startswith(b"<"):
                        digits = re.sub(rb"[^0-9A-Fa-f]", b"", token)
                        codes += [int(digits[i:i + 4], 16)
                                  for i in range(0, len(digits) - 3, 4)]
                for lit in _literal_strings(data[max(0, m.start() - 4000):m.start()][-400:]):
                    codes += [(lit[i] << 8) | lit[i + 1] for i in range(0, len(lit) - 1, 2)]
                if codes:
                    umap = unicode_maps.get(key or "", {})
                    out.append(Run(base_font=base, cids=codes, page=page_no,
                                   text="".join(umap.get(c, "") for c in codes)))
            pending = []
    return out


def notdef_runs(pdf: Path) -> list[Run]:
    """Runs that drew glyph 0 (`.notdef`) — which is what tofu IS.

    Sound only where CID == GID, which `font_table` establishes per font and
    reports when it cannot. Coverage asks whether a face COULD draw a character;
    this asks what the renderer actually put on the page."""
    return [r for r in runs(pdf) if 0 in r.cids]


def faces_used(pdf: Path) -> set[str]:
    """Faces that actually drew something — distinct from `pdffonts`, which lists
    what is EMBEDDED. A face can be embedded and never used."""
    return {r.family for r in runs(pdf)}


def audit(pdf: Path, anchors: dict[str, str] | None = None,
          expected_faces: set[str] | None = None) -> dict:
    """Audit `pdf`.

    `anchors` maps a source SUBSTRING to the face that text must be drawn in.
    That is the check a document-wide allow-list cannot make: when both faces are
    legitimately used somewhere, a heading falling back to the body face changes
    no set — only the anchored expectation notices."""
    table = font_table(pdf)
    unauditable = sorted(f"{r['base_font'] or k}: {r['reason']}"
                         for k, r in table.items() if not r.get("auditable"))
    all_runs = runs(pdf)
    used = {r.family for r in all_runs}
    notdef = [r for r in all_runs if 0 in r.cids]

    problems: list[str] = []
    if notdef:
        problems.append(
            f"{len(notdef)} run(s) drew glyph 0 (.notdef) — tofu on the page, in: "
            + ", ".join(sorted({r.family for r in notdef})))
    if expected_faces is not None:
        strangers = sorted(used - expected_faces)
        if strangers:
            problems.append(f"unexpected face(s) used: {', '.join(strangers)}")
    for needle, want in (anchors or {}).items():
        matching = [r for r in all_runs if needle in r.text]
        if not matching:
            problems.append(f"anchor {needle!r} was not found in any run's text")
            continue
        got = sorted({r.family for r in matching})
        if got != [want]:
            problems.append(
                f"anchor {needle!r} rendered in {', '.join(got)}, expected {want}")
    return {
        "faces_embedded": sorted(r["base_font"] for r in table.values()),
        "faces_used": sorted(used),
        "unauditable": unauditable,
        "runs": len(all_runs),
        "notdef_runs": len(notdef),
        "problems": problems,
    }
