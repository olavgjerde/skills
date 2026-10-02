"""Specs for plugin_version.py, run with: python3 -m unittest scripts/test_plugin_version.py"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from plugin_version import MARKETPLACE, VersionError, bump, check  # noqa: E402


def marketplace(*plugins):
    return {"name": "test", "plugins": [{"name": n, "source": f"./skills/{n}", "version": v} for n, v in plugins]}


class Repo:
    def __init__(self, root):
        self.root = Path(root)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def write_marketplace(self, *plugins):
        self.write(MARKETPLACE, json.dumps(marketplace(*plugins), indent=2) + "\n")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "c")
        return self.git("rev-parse", "HEAD").strip()

    def version(self, name):
        data = json.loads((self.root / MARKETPLACE).read_text())
        return next(p["version"] for p in data["plugins"] if p["name"] == name)


class Bump(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(tmp.name)

    def test_raises_only_the_named_plugins_patch_version(self):
        self.repo.write_marketplace(("ais", "1.4.9"), ("other", "2.0.0"))

        self.assertEqual(bump(self.repo.root, "ais"), "1.4.10")

        self.assertEqual(self.repo.version("ais"), "1.4.10")
        self.assertEqual(self.repo.version("other"), "2.0.0")

    def test_refuses_an_unknown_plugin(self):
        self.repo.write_marketplace(("ais", "1.0.0"))
        with self.assertRaises(VersionError):
            bump(self.repo.root, "nope")

    def test_refuses_a_version_it_cannot_increment(self):
        self.repo.write_marketplace(("ais", "1.0"))
        with self.assertRaises(VersionError):
            bump(self.repo.root, "ais")


class Check(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Repo(tmp.name)
        self.repo.write_marketplace(("ais", "1.0.0"), ("other", "1.0.0"))
        self.repo.write("skills/ais/SKILL.md", "v1")
        self.repo.write("skills/other/SKILL.md", "v1")
        self.base = self.repo.commit()

    def test_skill_change_without_a_bump_is_reported(self):
        self.repo.write("skills/ais/SKILL.md", "v2")
        self.repo.commit()

        problems = check(self.repo.root, self.base)

        self.assertEqual(len(problems), 1)
        self.assertIn("ais is still 1.0.0", problems[0])

    def test_skill_change_with_a_bump_passes(self):
        self.repo.write("skills/ais/SKILL.md", "v2")
        bump(self.repo.root, "ais")
        self.repo.commit()

        self.assertEqual(check(self.repo.root, self.base), [])

    def test_a_lower_version_is_reported(self):
        self.repo.write("skills/ais/SKILL.md", "v2")
        self.repo.write_marketplace(("ais", "0.9.0"), ("other", "1.0.0"))
        self.repo.commit()

        self.assertEqual(len(check(self.repo.root, self.base)), 1)

    def test_changes_outside_skill_directories_need_no_bump(self):
        self.repo.write("README.md", "docs")
        self.repo.write("scripts/ais/refresh.py", "tooling")
        self.repo.commit()

        self.assertEqual(check(self.repo.root, self.base), [])

    def test_a_new_plugin_needs_no_bump(self):
        self.repo.write_marketplace(("ais", "1.0.0"), ("other", "1.0.0"), ("new", "1.0.0"))
        self.repo.write("skills/new/SKILL.md", "v1")
        self.repo.commit()

        self.assertEqual(check(self.repo.root, self.base), [])

    def test_an_unknown_base_is_an_error(self):
        with self.assertRaises(VersionError):
            check(self.repo.root, "0" * 40)


if __name__ == "__main__":
    unittest.main()
