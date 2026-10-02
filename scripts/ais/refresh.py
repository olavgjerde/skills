#!/usr/bin/env python3
"""Rebuild skills/ais/references/ from the gpsd AIVDM/AIVDO page.

Maintainer tool: users get new references through a skill/plugin update, not
by running this. The scheduled workflow .github/workflows/refresh-ais.yml runs it
and opens a pull request when the page changes.

Pipeline: fetch HTML -> pandoc (GFM) -> split on headings -> fidelity check.
Without --apply it builds in memory, prints what would change and the page's
sha256, and writes nothing. --apply SHA256 takes that hash, so only the page the
dry run showed is applied; it builds into .staging/ (files plus SOURCE.json) and
swaps that in as references/, keeping the old tree in .references-old/ until
the swap succeeds.

Requires: python3 (stdlib only), pandoc on PATH.
"""

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://gpsd.io/AIVDM.html"
SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "ais"
REFS = SKILL_DIR / "references"
STAGING = SKILL_DIR / ".staging"
BACKUP = SKILL_DIR / ".references-old"
# SOURCE.json lives inside references/ so one rename swaps the files and their provenance together.
SOURCE_JSON = "SOURCE.json"
# SOURCE.json fields that change on every run; ignored when comparing builds.
VOLATILE = {"fetched_at"}

# H2 sections whose H3 children each get their own file (one file per message type).
SPLIT_H3_UNDER = {"AIS Payload Interpretation"}

HEADING_LINK = re.compile(r"^(#{1,6}) \[(.+)\]\(#([^)\s]+)\)\s*$")
HEADING_PLAIN = re.compile(r"^(#{1,6}) (.+?)\s*$")
TABLE_SEP = re.compile(r"^\|( ?:?-{3,}:? ?\|)+ *$")
FOOTER_VERSION = re.compile(r"^Version ([\d.]+)\\?$")
FOOTER_UPDATED = re.compile(r"^Last updated (.+)$")
TYPE_HEADING = re.compile(r"^Types? ((?:\d+|,|and|\s)+)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
SAME_LAYOUT = re.compile(r"[Ii]dentical to (?:message|a type) (\d+)")
# pandoc appends the table's attributes to its caption: "Table 12. Cargo Unit Codes {.tableblock ...}".
CAPTION = re.compile(r"^(Table \d+\..*?) \{\.tableblock[^}]*\}\s*$")
# Defining sentence of a type 6/8 sub-message: "A message 8 subtype. DAC = 001 FID = 31. ..."
DAC_FID = re.compile(r"\bDAC = (\d+(?: or \d+)*) FID = (\d+)\b")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "olavgjerde-skills ais refresh"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"fetch failed: HTTP {e.code} {e.reason} ({url}); nothing written.")
    except OSError as e:  # URLError, timeouts, connection resets
        sys.exit(f"fetch failed: {getattr(e, 'reason', e)} ({url}); nothing written.")


def to_gfm(html_bytes):
    try:
        out = subprocess.run(
            ["pandoc", "-f", "html", "-t", "gfm-raw_html", "--wrap=none"],
            input=html_bytes, capture_output=True, check=True,
        )
    except FileNotFoundError:
        sys.exit("pandoc not found: install it (brew install pandoc / apt install pandoc); nothing written.")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="replace").strip()
        sys.exit(f"pandoc failed (exit {e.returncode}): {err}; nothing written.")
    return out.stdout.decode("utf-8")


def pandoc_version():
    out = subprocess.run(["pandoc", "--version"], capture_output=True, text=True, encoding="utf-8", check=True)
    return out.stdout.splitlines()[0]


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60].rstrip("-")


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
        if inside:
            current["lines"].append(line)
            continue
        # Make in-page links absolute so they survive the split.
        line = re.sub(r"\]\(#([^)\s]+)\)", lambda x: f"]({URL}#{x.group(1)})", line)
        c = CAPTION.match(line)
        out = current["lines"]
        if c:
            # Move the caption above its table, where the HTML shows it, so it
            # cannot read as the start of whatever follows the table.
            end = len(out)
            while end and not out[end - 1].strip():
                end -= 1
            start = end
            while start and out[start - 1].startswith("|"):
                start -= 1
            if start < end:
                del out[end:]
                out[start:start] = [c.group(1), ""]
                continue
            line = c.group(1)
        out.append(line)
    return blocks, version, last_updated


def group_files(blocks):
    """Group heading blocks into output files."""
    files, h2 = [], None
    for b in blocks:
        if b["level"] == 2:
            h2 = b
            files.append({"path": [b], "anchor": b["anchor"], "blocks": [b]})
        elif b["level"] == 3 and h2 and h2["plain"] in SPLIT_H3_UNDER:
            files.append({"path": [h2, b], "anchor": b["anchor"], "blocks": [b]})
        else:
            files[-1]["blocks"].append(b)
    return files


def members_in(text):
    """JSON member names from field tables (the 'Member' column = gpsdecode keys)."""
    found, col = [], None
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
            if re.fullmatch(r"[a-z][a-z0-9_]*", name) and name not in found:
                found.append(name)
    return found


def dac_fid(lines):
    """'dac D, fid F' of a type 6/8 sub-message, or None.

    Only the first match in the defining "A message N subtype." sentence is
    trusted: later prose mentions other FIDs ("... but FID = 31"), and some
    field tables have typos.
    """
    first = next((l for l in lines if l.startswith("A message ") and DAC_FID.search(l)), "")
    m = DAC_FID.search(first)
    if not m:
        return None
    dacs = " or ".join(str(int(d)) for d in m.group(1).split(" or "))
    return f"dac {dacs}, fid {int(m.group(2))}"


def render(files, version):
    out = {}
    index_rows = []
    for f in files:
        # Slug only, no position prefix: an upstream section added or removed
        # must not rename every later file.
        name = f"{slugify(f['path'][-1]['plain'])}.md"
        if name in out or name == "index.md":
            sys.exit(f"Duplicate file name {name}; nothing written.")
        src = f"{URL}#{f['anchor']}" if f["anchor"] else URL
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
        same = None if mem else SAME_LAYOUT.search(text)
        if same:
            # Types 11 and 13 have no table of their own, only a pointer to another type.
            mem = [f"same layout as type {same.group(1)}"]
        index_rows.append((name, f["path"][-1]["title"], subs, mem))

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
    # Cells hold markdown; escape only pipes that are not escaped already.
    cell = lambda xs: re.sub(r"(?<!\\)((?:\\\\)*)\|", r"\1\\|", ", ".join(xs))
    for name, title, subs, mem in index_rows:
        idx.append(f"| {name} | {cell([title])} | {cell(subs)} | {cell(mem)} |")
    out["index.md"] = "\n".join(idx) + "\n"
    return out


def fidelity(html, blocks, version, last_updated):
    """Fail loudly instead of silently dropping content (the defuddle failure mode)."""
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
    types = set()
    for b in blocks:
        m = TYPE_HEADING.match(b["plain"])
        if m:
            types.update(int(n) for n in re.findall(r"\d+", m.group(1)))
    missing = sorted(set(range(1, 28)) - types)
    if missing:
        errors.append(f"message types missing: {missing}")
    return errors, {"headings": md_heads, "tables": md_tables}


def diff_summary(new, refs):
    paths = [*refs.glob("*.md"), refs / SOURCE_JSON] if refs.exists() else []
    old = {p.name: p.read_text(encoding="utf-8") for p in paths if p.is_file()}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = []
    for name in sorted(set(new) & set(old)):
        if name == SOURCE_JSON:
            # Report the fields that differ, not the timestamp every run rewrites.
            a, b = json.loads(old[name]), json.loads(new[name])
            keys = sorted(k for k in a.keys() | b.keys() if k not in VOLATILE and a.get(k) != b.get(k))
            if keys:
                changed.append(f"{name} ({', '.join(keys)})")
        elif new[name] != old[name]:
            d = list(difflib.unified_diff(old[name].splitlines(), new[name].splitlines(), lineterm="", n=0))
            plus = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
            minus = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
            changed.append(f"{name} (+{plus} -{minus})")
    return added, removed, changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", metavar="SHA256",
                    help="replace references/ with the new build; SHA256 is the hash the reviewed dry run printed")
    ap.add_argument("--html", type=Path, help="use a local HTML file instead of fetching")
    args = ap.parse_args()

    raw = args.html.read_bytes() if args.html else fetch(URL)
    sha256 = hashlib.sha256(raw).hexdigest()
    if args.apply is not None and args.apply.strip().lower() != sha256:
        sys.exit(f"HTML sha256 is {sha256}, not {args.apply}: the page changed since the dry run."
                 " Run the dry run again and review it; nothing written.")
    html = raw.decode("utf-8", errors="replace")
    md = to_gfm(raw)
    blocks, version, last_updated = parse(md)

    errors, counts = fidelity(html, blocks, version, last_updated)
    if errors:
        print("Fidelity check FAILED; nothing written:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    files = render(group_files(blocks), version)
    n_md = len(files)
    if args.html:
        # File name only: SOURCE.json is tracked, and a full path leaks the local layout.
        origin = {"source": "local file", "html_file": args.html.name}
    else:
        origin = {"source": "fetched",
                  "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    files[SOURCE_JSON] = json.dumps({
        "url": URL,
        "doc_version": version,
        "page_last_updated": last_updated,
        **origin,
        "html_sha256": sha256,
        "converter": pandoc_version(),
        "headings": counts["headings"],
        "tables": counts["tables"],
    }, indent=2) + "\n"

    # references/ missing with a backup present means an --apply was interrupted
    # mid-swap: the backup is the only copy, so compare against it and restore it.
    orphan = BACKUP.exists() and not REFS.exists()
    if orphan:
        print("references/ is missing but .references-old/ exists (an interrupted --apply);"
              " comparing against the backup. --apply restores it first.")
    base = BACKUP if orphan else REFS
    added, removed, changed = diff_summary(files, base)

    print(f"gpsd doc v{version}, page last updated {last_updated}")
    print(f"HTML sha256: {sha256}")
    print(f"Fidelity OK: {counts['headings']} headings, {counts['tables']} tables, types 1-27 present")
    print(f"{n_md} files built, plus {SOURCE_JSON}")
    if not (added or removed or changed):
        print(f"No changes against {base.name}/.")
    for label, items in (("added", added), ("removed", removed), ("changed", changed)):
        for item in items:
            print(f"  {label}: {item}")

    if args.apply is None:
        print(f"Dry run; nothing written. Re-run with --apply {sha256} to replace references/.")
        return

    if orphan:
        BACKUP.rename(REFS)
        print("Restored references/ from .references-old/.")
    elif BACKUP.exists():
        shutil.rmtree(BACKUP)  # stale: references/ is intact
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir()
    for name, text in files.items():
        (STAGING / name).write_text(text, encoding="utf-8")
    # Move the old tree aside rather than deleting it, so a failed swap can be undone.
    had_refs = REFS.exists()
    if had_refs:
        REFS.rename(BACKUP)
    try:
        STAGING.rename(REFS)
    except OSError:
        if had_refs:
            BACKUP.rename(REFS)
        raise
    if had_refs:
        shutil.rmtree(BACKUP)
    print(f"Applied: references/ updated, {SOURCE_JSON} included.")


if __name__ == "__main__":
    main()
