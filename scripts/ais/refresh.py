#!/usr/bin/env python3
"""Rebuild skills/ais/references/ from the gpsd AIVDM/AIVDO page.

Maintainer tool: users get new references through a skill/plugin update, not
by running this. The scheduled workflow .github/workflows/refresh-ais.yml runs it
and opens a pull request when the page changes.

Pipeline: fetch HTML -> pandoc (GFM) -> split on headings -> fidelity check ->
write references/. The snapshot is a pure function of the page bytes, the
pandoc version and this script: an unchanged page rewrites nothing, and git
shows exactly what an upstream change did. Review with git diff; undo with
git checkout. --check builds and reports without writing, and exits 1 if
references/ would change.

Requires: python3 (stdlib only), pandoc on PATH.
"""

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://gpsd.io/AIVDM.html"
SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "ais"
REFS = SKILL_DIR / "references"
SOURCE_JSON = "SOURCE.json"
MESSAGE_TYPES = range(1, 28)

HEADING_LINK = re.compile(r"^(#{1,6}) \[(.+)\]\(#([^)\s]+)\)\s*$")
HEADING_PLAIN = re.compile(r"^(#{1,6}) (.+?)\s*$")
TABLE_SEP = re.compile(r"^\|( ?:?-{3,}:? ?\|)+ *$")
FOOTER_VERSION = re.compile(r"^Version ([\d.]+)\\?$")
FOOTER_UPDATED = re.compile(r"^Last updated (.+)$")
# Message-type headings; each H3 one gets its own file.
TYPE_HEADING = re.compile(r"^Types? ((?:\d+|,|and|\s)+)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
IN_PAGE_LINK = re.compile(r"\]\(#([^)\s]+)\)")
SAME_LAYOUT = re.compile(r"[Ii]dentical to (?:message|a type) (\d+)")
# Defining sentence of a type 6/8 sub-message: "A message 8 subtype. DAC = 001 FID = 31. ..."
DAC_FID = re.compile(r"\bDAC = (\d+(?: or \d+)*) FID = (\d+)\b")

# The GFM writer prints a table caption (with the table's attributes) below the
# table; put it above, where the HTML shows it, so it cannot read as the start
# of whatever follows the table.
CAPTION_FILTER = """
function Table(t)
  if #t.caption.long == 0 then return nil end
  local out = pandoc.List()
  for _, b in ipairs(t.caption.long) do
    out:insert(b.t == "Plain" and pandoc.Para(b.content) or b)
  end
  t.caption = {long = {}}
  out:insert(t)
  return out
end
"""


class RefreshError(Exception):
    """The page could not be fetched, converted, or turned into a faithful snapshot."""


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "olavgjerde-skills ais refresh"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RefreshError(f"fetch failed: HTTP {e.code} {e.reason} ({url})") from e
    except OSError as e:  # URLError, timeouts, connection resets
        raise RefreshError(f"fetch failed: {getattr(e, 'reason', e)} ({url})") from e


def to_gfm(html_bytes):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            lua = Path(tmp, "captions.lua")  # pandoc reads filters only from files
            lua.write_text(CAPTION_FILTER, encoding="utf-8")
            out = subprocess.run(
                ["pandoc", "-f", "html", "-t", "gfm-raw_html", "--wrap=none", "--lua-filter", lua],
                input=html_bytes, capture_output=True, check=True,
            )
    except FileNotFoundError as e:
        raise RefreshError("pandoc not found: install it (brew install pandoc / apt install pandoc)") from e
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="replace").strip()
        raise RefreshError(f"pandoc failed (exit {e.returncode}): {err}") from e
    return out.stdout.decode("utf-8")


def pandoc_version():
    out = subprocess.run(["pandoc", "--version"], capture_output=True, encoding="utf-8", check=True)
    return out.stdout.splitlines()[0]


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60].rstrip("-")


def message_types(title):
    """Type numbers a message-type heading covers ("Types 1, 2 and 3: ..." -> [1, 2, 3]); [] otherwise."""
    m = TYPE_HEADING.match(title)
    return [int(n) for n in re.findall(r"\d+", m.group(1))] if m else []


def unescape(text):
    """Plain text of an inline markdown string: drop every CommonMark backslash escape."""
    return re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", text)


def fenced(lines):
    """Yield (line, inside) pairs; inside is True for fence lines and the code between them."""
    fence = None
    for line in lines:
        # CommonMark fences: close only on the same character, at least as long, with no info string.
        f = FENCE.match(line)
        if f and fence is None and not (f.group(1)[0] == "`" and "`" in f.group(2)):
            fence = f.group(1)
            yield line, True
        elif f and fence and f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) and not f.group(2).strip():
            fence = None
            yield line, True
        else:
            yield line, fence is not None


def parse(md):
    """Return (blocks, version, last_updated).

    blocks: list of dicts {level, title, plain, anchor, lines} for every heading
    from the first H2 onward; preamble (logo, nav, TOC) and the site footer are
    dropped. title keeps pandoc's markdown escapes; plain is the unescaped text.
    """
    lines = md.splitlines()

    version = last_updated = None
    while lines and not lines[-1].strip():
        lines.pop()
    if (len(lines) >= 2 and (mu := FOOTER_UPDATED.match(lines[-1]))
            and (mv := FOOTER_VERSION.match(lines[-2]))):
        last_updated, version = mu.group(1), mv.group(1)
        lines = lines[:-2]

    blocks, current = [], None
    for line, inside in fenced(lines):
        m = None if inside else (HEADING_LINK.match(line) or HEADING_PLAIN.match(line))
        if m and len(m.group(1)) >= 2:
            level = len(m.group(1))
            if current is None and level != 2:
                continue  # sub-heading in the preamble; the fidelity count will flag it
            title = m.group(2)
            anchor = m.group(3) if m.re is HEADING_LINK else None
            current = {"level": level, "title": title, "plain": unescape(title), "anchor": anchor, "lines": []}
            blocks.append(current)
            continue
        if current is None:
            continue  # preamble before the first H2
        if not inside:
            # Make in-page links absolute so they survive the split.
            line = IN_PAGE_LINK.sub(rf"]({URL}#\1)", line)
        current["lines"].append(line)
    return blocks, version, last_updated


def group_files(blocks):
    """Group heading blocks into output files: one per H2, and one per message type."""
    files, h2 = [], None
    for b in blocks:
        if b["level"] == 2:
            h2 = b
            files.append({"path": [b], "blocks": [b]})
        elif b["level"] == 3 and message_types(b["plain"]):
            files.append({"path": [h2, b], "blocks": [b]})
        else:
            files[-1]["blocks"].append(b)
    return files


def members_in(text):
    """JSON member names from field tables (the 'Member' column = gpsdecode keys)."""
    found, col = {}, None  # dict as an ordered set
    for line in text.splitlines():
        if not line.startswith("|"):
            col = None
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if col is None:
            # Header is "Member" or "Member/Type" depending on the table.
            col = next((i for i, c in enumerate(cells) if c.startswith("Member")), -1)
            continue
        if col >= 0 and not TABLE_SEP.match(line) and col < len(cells):
            name = cells[col].strip("`")
            if re.fullmatch(r"[a-z][a-z0-9_]*", name):
                found[name] = None
    return list(found)


def dac_fid(lines):
    """'dac D, fid F' of a type 6/8 sub-message, or None.

    Only the first match in the defining "A message N subtype." sentence is
    trusted: later prose mentions other FIDs ("... but FID = 31"), and some
    field tables have typos.
    """
    for l in lines:
        if l.startswith("A message ") and (m := DAC_FID.search(l)):
            dacs = " or ".join(str(int(d)) for d in m.group(1).split(" or "))
            return f"dac {dacs}, fid {int(m.group(2))}"
    return None


def table_cell(xs):
    """Join markdown into one table cell, escaping only pipes not escaped already."""
    return re.sub(r"(?<!\\)((?:\\\\)*)\|", r"\1\\|", ", ".join(xs))


def render(files, version):
    out = {}
    idx = [
        "<!-- generated by scripts/ais/refresh.py; do not edit -->",
        f"# AIVDM/AIVDO reference index (gpsd doc v{version})",
        "",
        "Open only the files a question needs. `Members` are the JSON keys gpsdecode prints.",
        "The same key appears under many types with different units, so find a decoded",
        "message's field table by its `type` value in the Section column, not by key.",
        "Type 6 and 8 subsections are tagged `[dac D, fid F]` from the sentence that",
        "defines each sub-message; match a decoded `dac`/`fid` against these as integers.",
        "",
        "| File | Section | Subsections | Members |",
        "|---|---|---|---|",
    ]
    for f in files:
        head = f["path"][-1]
        # Slug only, no position prefix: an upstream section added or removed
        # must not rename every later file.
        name = f"{slugify(head['plain'])}.md"
        if name in out or name == "index.md":
            raise RefreshError(f"two sections map to file name {name}")
        src = f"{URL}#{head['anchor']}" if head["anchor"] else URL
        body = []
        for b in f["blocks"]:
            body.append(f"{'#' * b['level']} {b['title']}")
            body.extend(b["lines"])
        text = "\n".join(body).strip() + "\n"
        header = (
            f"<!-- generated by scripts/ais/refresh.py from {URL} (v{version}); do not edit -->\n"
            f"Path: {' › '.join(b['title'] for b in f['path'])}\n"
            f"Source: {src}\n\n"
        )
        out[name] = header + text
        subs = []
        for b in f["blocks"][1:]:
            tag = dac_fid(b["lines"])
            subs.append(f"{b['title']} [{tag}]" if tag else b["title"])
        mem = members_in(text)
        if not mem and (same := SAME_LAYOUT.search(text)):
            # Types 11 and 13 have no table of their own, only a pointer to another type.
            mem = [f"same layout as type {same.group(1)}"]
        idx.append(f"| {name} | {table_cell([head['title']])} | {table_cell(subs)} | {table_cell(mem)} |")
    out["index.md"] = "\n".join(idx) + "\n"
    return out


def fidelity(html, blocks, version, last_updated):
    """Fail loudly instead of silently dropping content."""
    errors = []
    if version is None or last_updated is None:
        errors.append("page footer (Version / Last updated) not recognized")
    html_heads = len(re.findall(r"<h[2-4][\s>]", html))
    md_heads = sum(1 for b in blocks if 2 <= b["level"] <= 4)
    if html_heads != md_heads:
        errors.append(f"heading count: html {html_heads} vs markdown {md_heads}")
    html_tables = len(re.findall(r"<table[\s>]", html))
    # Count only what is emitted: blocks from the first H2 on, outside code fences.
    md_tables = sum(1 for b in blocks for l, inside in fenced(b["lines"]) if not inside and TABLE_SEP.match(l))
    if html_tables != md_tables:
        errors.append(f"table count: html {html_tables} vs markdown {md_tables}")
    types = {n for b in blocks for n in message_types(b["plain"])}
    missing = sorted(set(MESSAGE_TYPES) - types)
    if missing:
        errors.append(f"message types missing: {missing}")
    return errors, {"headings": md_heads, "tables": md_tables}


def build(html_bytes, md, converter):
    """The snapshot as {file name: text}: one file per section, index.md and SOURCE.json.

    html_bytes is the page exactly as fetched, md its pandoc GFM conversion,
    converter pandoc's version line. The same inputs always give the same
    snapshot. Raises RefreshError when the fidelity check fails.
    """
    blocks, version, last_updated = parse(md)
    html = html_bytes.decode("utf-8", errors="replace")
    errors, counts = fidelity(html, blocks, version, last_updated)
    if errors:
        raise RefreshError("fidelity check failed:\n" + "\n".join(f"  - {e}" for e in errors))
    files = render(group_files(blocks), version)
    files[SOURCE_JSON] = json.dumps({
        "url": URL,
        "doc_version": version,
        "page_last_updated": last_updated,
        "html_sha256": hashlib.sha256(html_bytes).hexdigest(),
        "converter": converter,
        "headings": counts["headings"],
        "tables": counts["tables"],
    }, indent=2) + "\n"
    return files


def read_snapshot(refs):
    """The snapshot on disk, in the shape build returns; {} if refs does not exist."""
    paths = [*refs.glob("*.md"), refs / SOURCE_JSON]
    return {p.name: p.read_text(encoding="utf-8") for p in paths if p.is_file()}


def compare(old, new):
    """(added, removed, changed) file names between two snapshots, changed ones annotated."""
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = []
    for name in sorted(new.keys() & old.keys()):
        if new[name] == old[name]:
            continue
        if name == SOURCE_JSON:
            # Name the fields, e.g. html_sha256 or converter (a different local pandoc).
            a, b = json.loads(old[name]), json.loads(new[name])
            changed.append(f"{name} ({', '.join(sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k)))})")
            continue
        plus = minus = 0
        sm = difflib.SequenceMatcher(None, old[name].splitlines(), new[name].splitlines())
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "equal":
                minus += i2 - i1
                plus += j2 - j1
        changed.append(f"{name} (+{plus} -{minus})")
    return added, removed, changed


def write(snapshot, refs):
    """Make refs hold exactly snapshot: write new and changed files, delete stale ones.

    No staging or backup: references/ is tracked in git, which shows and undoes the change.
    """
    old = read_snapshot(refs)
    refs.mkdir(parents=True, exist_ok=True)
    for name in old.keys() - snapshot.keys():
        (refs / name).unlink()
    for name, text in snapshot.items():
        if old.get(name) != text:
            (refs / name).write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report what would change and write nothing; exit 1 if references/ is out of date")
    ap.add_argument("--html", type=Path, help="use a local HTML file instead of fetching")
    args = ap.parse_args()

    try:
        raw = args.html.read_bytes() if args.html else fetch(URL)
        new = build(raw, to_gfm(raw), pandoc_version())
    except (RefreshError, OSError) as e:  # OSError: an unreadable --html file
        print(f"{e}\nNothing written.", file=sys.stderr)
        sys.exit(2)

    src = json.loads(new[SOURCE_JSON])
    print(f"gpsd doc v{src['doc_version']}, page last updated {src['page_last_updated']}")
    print(f"HTML sha256: {src['html_sha256']}")
    print(f"Fidelity OK: {src['headings']} headings, {src['tables']} tables,"
          f" types {MESSAGE_TYPES[0]}-{MESSAGE_TYPES[-1]} present")
    print(f"{len(new) - 1} files built, plus {SOURCE_JSON}")

    added, removed, changed = compare(read_snapshot(REFS), new)
    if not (added or removed or changed):
        print("references/ is up to date.")
        return
    for label, items in (("added", added), ("removed", removed), ("changed", changed)):
        for item in items:
            print(f"  {label}: {item}")
    if args.check:
        print("--check: nothing written.")
        sys.exit(1)
    write(new, REFS)
    print("references/ updated; review with git diff.")


if __name__ == "__main__":
    main()
