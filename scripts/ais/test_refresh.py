"""Specs for refresh.py, run with: python3 -m unittest discover -s scripts/ais

Tests go through build() with small hand-written GFM, the shape pandoc emits,
so they need neither pandoc nor the network.
"""

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import refresh  # noqa: E402
from refresh import SOURCE_JSON, URL, RefreshError, build, compare, read_snapshot, write  # noqa: E402

PREAMBLE = """\
![gpsd logo](gpsd-logo-small.png)

- [Introduction](#_introduction)
- [AIS Payload Interpretation](#_ais_payload_interpretation)
"""

FOOTER = """\
Version 1.58\\
Last updated 2026-09-28 02:51:56 UTC
"""

INTRO = """\
## [Introduction](#_introduction)

This document describes AIS. See [Type 5](#_type_5) for voyage data.
"""

TYPES_1_TO_3 = """\
### [Types 1, 2 and 3: Position Report Class A](#_types_1_2_and_3)

| Field | Len | Description | Member | T | Units |
|---|---|---|---|---|---|
| 0-5 | 6 | Message Type | type | u | Constant: 1-3 |
| 50-59 | 10 | Speed Over Ground | speed | U1 | knots |
"""

TYPE_8 = """\
### [Type 8: Binary Broadcast Message](#_type_8)

Broadcast binary payload.

#### Meteorological and Hydrological Data

Older receivers decode DAC = 001 FID = 11 instead.

A message 8 subtype. DAC = 001 FID = 31. Replaces the older FID = 11 message.

| Field | Len | Description | Member/Type | T | Units |
|---|---|---|---|---|---|
| 56-61 | 6 | FID | fid | u | 31 |
"""

TYPE_11 = """\
### [Type 11: UTC/Date Response](#_type_11)

Identical to message 4, with the type field set to 11.
"""


def other_types():
    """One bare heading per message type the named fixtures leave out."""
    return "".join(f"### [Type {n}: Stub](#_type_{n})\n\nStub.\n\n"
                   for n in refresh.MESSAGE_TYPES if n not in (1, 2, 3, 8, 11))


def page(*sections):
    return PREAMBLE + "\n" + "\n".join(sections) + "\n" + FOOTER


def standard_page(extra=""):
    payload = "## [AIS Payload Interpretation](#_ais_payload_interpretation)\n\nFields.\n"
    return page(INTRO, payload, TYPES_1_TO_3, TYPE_8, TYPE_11, other_types(), extra)


def html_like(md):
    """HTML with as many h2-h4 headings and tables as md has outside code fences."""
    heads = tables = 0
    fenced = False
    for line in md.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"#{2,4} ", line):
            heads += 1
        elif not fenced and re.match(r"\|(-{3,}\|)+$", line):
            tables += 1
    return ("<h2>x</h2>\n" * heads + "<table>\n" * tables).encode()


def build_page(md, converter="pandoc 3.11"):
    return build(html_like(md), md, converter)


def index_row(snapshot, name):
    return next(l for l in snapshot["index.md"].splitlines() if l.startswith(f"| {name} |"))


class SplittingThePage(unittest.TestCase):
    def setUp(self):
        self.snapshot = build_page(standard_page())

    def test_each_top_level_section_and_each_message_type_gets_its_own_file(self):
        self.assertIn("introduction.md", self.snapshot)
        self.assertIn("ais-payload-interpretation.md", self.snapshot)
        self.assertIn("types-1-2-and-3-position-report-class-a.md", self.snapshot)
        self.assertIn("type-8-binary-broadcast-message.md", self.snapshot)
        self.assertIn("type-27-stub.md", self.snapshot)

    def test_a_subsection_stays_in_its_message_type_file(self):
        type_8 = self.snapshot["type-8-binary-broadcast-message.md"]

        self.assertIn("#### Meteorological and Hydrological Data", type_8)
        self.assertNotIn("meteorological-and-hydrological-data.md", self.snapshot)

    def test_a_file_names_its_place_in_the_page_and_links_to_its_anchor(self):
        type_8 = self.snapshot["type-8-binary-broadcast-message.md"].splitlines()

        self.assertEqual(type_8[1], "Path: AIS Payload Interpretation › Type 8: Binary Broadcast Message")
        self.assertEqual(type_8[2], f"Source: {URL}#_type_8")

    def test_in_page_links_point_at_the_gpsd_page_so_they_survive_the_split(self):
        self.assertIn(f"[Type 5]({URL}#_type_5)", self.snapshot["introduction.md"])

    def test_the_site_preamble_and_footer_are_left_out(self):
        text = "".join(self.snapshot.values())

        self.assertNotIn("gpsd-logo-small.png", text)
        self.assertNotIn("Last updated", text)

    def test_a_heading_inside_a_code_block_does_not_start_a_new_file(self):
        code = "## [Local Extensions](#_local)\n\n```\n## not a heading\n```\n"

        snapshot = build_page(standard_page(code))

        self.assertIn("## not a heading", snapshot["local-extensions.md"])
        self.assertNotIn("not-a-heading.md", snapshot)

    def test_two_sections_with_the_same_file_name_are_refused(self):
        twice = INTRO.replace("Introduction", "Standards")

        with self.assertRaisesRegex(RefreshError, "standards.md"):
            build_page(standard_page(twice + "\n" + twice))


class TheIndex(unittest.TestCase):
    def setUp(self):
        self.snapshot = build_page(standard_page())

    def test_lists_the_json_members_of_a_message_types_field_table(self):
        row = index_row(self.snapshot, "types-1-2-and-3-position-report-class-a.md")

        self.assertTrue(row.endswith("| type, speed |"), row)

    def test_tags_a_binary_subsection_with_the_dac_and_fid_its_defining_sentence_gives(self):
        row = index_row(self.snapshot, "type-8-binary-broadcast-message.md")

        self.assertIn("Meteorological and Hydrological Data [dac 1, fid 31]", row)
        self.assertNotIn("fid 11", row)

    def test_points_a_type_without_its_own_table_at_the_type_it_shares_a_layout_with(self):
        row = index_row(self.snapshot, "type-11-utc-date-response.md")

        self.assertTrue(row.endswith("| same layout as type 4 |"), row)


class TheFidelityCheck(unittest.TestCase):
    def test_refuses_a_page_missing_a_message_type(self):
        md = standard_page().replace("### [Type 27: Stub](#_type_27)", "### [Type 99: Stub](#_type_99)")

        with self.assertRaisesRegex(RefreshError, r"message types missing: \[27\]"):
            build_page(md)

    def test_refuses_a_conversion_that_lost_a_heading(self):
        md = standard_page()

        with self.assertRaisesRegex(RefreshError, "heading count"):
            build(html_like(md) + b"<h3>dropped</h3>", md, "pandoc 3.11")

    def test_refuses_a_conversion_that_lost_a_table(self):
        md = standard_page()

        with self.assertRaisesRegex(RefreshError, "table count"):
            build(html_like(md) + b"<table>", md, "pandoc 3.11")

    def test_refuses_a_page_without_the_version_footer(self):
        md = standard_page().replace(FOOTER, "")

        with self.assertRaisesRegex(RefreshError, "footer"):
            build_page(md)


class Provenance(unittest.TestCase):
    def test_source_json_records_what_the_snapshot_was_built_from(self):
        md = standard_page()
        html = html_like(md)

        source = json.loads(build(html, md, "pandoc 3.11")[SOURCE_JSON])

        self.assertEqual(source["doc_version"], "1.58")
        self.assertEqual(source["page_last_updated"], "2026-09-28 02:51:56 UTC")
        self.assertEqual(source["html_sha256"], hashlib.sha256(html).hexdigest())
        self.assertEqual(source["converter"], "pandoc 3.11")

    def test_the_same_page_and_converter_always_give_the_same_snapshot(self):
        md = standard_page()

        self.assertEqual(build_page(md), build_page(md))


class UpdatingReferences(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.refs = Path(tmp.name) / "references"

    def test_writing_leaves_exactly_the_new_snapshot_on_disk(self):
        write({"stale.md": "old\n", SOURCE_JSON: "{}\n"}, self.refs)
        new = build_page(standard_page())

        write(new, self.refs)

        self.assertEqual(read_snapshot(self.refs), new)

    def test_comparing_reports_added_removed_and_changed_files(self):
        old = build_page(standard_page())
        new = build_page(standard_page("## [New Section](#_new)\n\nNew.\n"), converter="pandoc 3.12")
        new["introduction.md"] += "One more line.\n"
        old["gone.md"] = "x\n"

        added, removed, changed = compare(old, new)

        self.assertEqual(added, ["new-section.md"])
        self.assertEqual(removed, ["gone.md"])
        self.assertIn("introduction.md (+1 -0)", changed)
        self.assertIn(f"{SOURCE_JSON} (converter, headings, html_sha256)", changed)

    def test_comparing_a_snapshot_with_itself_reports_nothing(self):
        snapshot = build_page(standard_page())

        self.assertEqual(compare(snapshot, dict(snapshot)), ([], [], []))


if __name__ == "__main__":
    unittest.main()
