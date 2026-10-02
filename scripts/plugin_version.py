#!/usr/bin/env python3
"""Keep the plugin versions in .claude-plugin/marketplace.json moving.

Claude Code keeps users on a plugin's `version` until that string changes, so
a change to a skill directory that leaves the version alone never reaches the
people who installed it.

    python3 scripts/plugin_version.py bump NAME   # raise NAME's patch version and print it
    python3 scripts/plugin_version.py check BASE  # exit 1 if a skill changed since BASE without a higher version

Requires: python3 (stdlib only); check also needs git.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ".claude-plugin/marketplace.json"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class VersionError(Exception):
    pass


def parse(version):
    m = SEMVER.match(version or "")
    if not m:
        raise VersionError(f"version {version!r} is not MAJOR.MINOR.PATCH")
    return tuple(int(p) for p in m.groups())


def bump(root, name):
    path = Path(root) / MARKETPLACE
    data = json.loads(path.read_text())
    entry = next((p for p in data["plugins"] if p["name"] == name), None)
    if entry is None:
        raise VersionError(f"no plugin named {name!r} in {MARKETPLACE}")
    major, minor, patch = parse(entry.get("version"))
    entry["version"] = f"{major}.{minor}.{patch + 1}"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return entry["version"]


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def check(root, base):
    """Return one message per plugin whose source changed since base without a higher version."""
    if git(root, "cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
        raise VersionError(f"base {base!r} is not a commit in this clone")
    old = git(root, "show", f"{base}:{MARKETPLACE}")
    old_versions = {}
    if old.returncode == 0:
        old_versions = {p["name"]: p.get("version") for p in json.loads(old.stdout)["plugins"]}

    problems = []
    for entry in json.loads((Path(root) / MARKETPLACE).read_text())["plugins"]:
        name, source = entry["name"], entry["source"]
        if name not in old_versions:
            continue
        if git(root, "diff", "--quiet", base, "--", source).returncode == 0:
            continue
        if parse(entry.get("version")) <= parse(old_versions[name]):
            problems.append(
                f"{source} changed since {base[:12]} but {name} is still {entry.get('version')}; "
                f"run: python3 scripts/plugin_version.py bump {name}"
            )
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bump", help="raise a plugin's patch version").add_argument("name")
    sub.add_parser("check", help="fail if a changed skill kept its version").add_argument("base")
    args = parser.parse_args(argv)
    try:
        if args.command == "bump":
            print(bump(ROOT, args.name))
            return 0
        problems = check(ROOT, args.base)
    except VersionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
