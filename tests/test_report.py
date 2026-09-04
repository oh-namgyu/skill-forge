"""Report tests: grouped text, colour gating and the stable JSON schema."""

import json
import unittest

from skill_forge.report import (COLORS, RESET, SCHEMA_VERSION, counts_by_code,
                                counts_by_severity, format_diagnostic, format_text,
                                group_by_file, summary_line, to_json)
from skill_forge.rules import ERROR, INFO, WARN, Analysis, Diagnostic

ALPHA = "/tmp/root/skills/alpha/SKILL.md"
BETA = "/tmp/root/commands/beta.md"


def sample():
    return Analysis(
        files=[ALPHA, BETA],
        diagnostics=[
            Diagnostic("F005", WARN, ALPHA, None, "no 'description'"),
            Diagnostic("F001", ERROR, ALPHA, 1, "file starts with a UTF-8 BOM"),
            Diagnostic("F040", INFO, BETA, None, "Claude Code extensions: model"),
        ])


class GroupingTestCase(unittest.TestCase):
    def test_files_keep_discovery_order(self):
        self.assertEqual([entry["path"] for entry in group_by_file(sample())],
                         [ALPHA, BETA])

    def test_files_without_diagnostics_are_kept(self):
        analysis = Analysis(files=[ALPHA, BETA], diagnostics=[])
        self.assertEqual([entry["diagnostics"] for entry in group_by_file(analysis)],
                         [[], []])

    def test_diagnostics_sort_by_line_then_severity_then_code(self):
        codes = [item.code for item in group_by_file(sample())[0]["diagnostics"]]
        self.assertEqual(codes, ["F005", "F001"])

    def test_a_diagnostic_for_an_unlisted_file_is_still_reported(self):
        analysis = Analysis(files=[ALPHA], diagnostics=[
            Diagnostic("F003", ERROR, BETA, 2, "bad line")])
        self.assertEqual([entry["path"] for entry in group_by_file(analysis)],
                         [ALPHA, BETA])


class TextTestCase(unittest.TestCase):
    def test_line_format(self):
        item = Diagnostic("F001", ERROR, ALPHA, 1, "boom")
        self.assertEqual(format_diagnostic(item), ALPHA + ":1 [F001] boom")

    def test_missing_line_number_is_omitted(self):
        item = Diagnostic("F005", WARN, ALPHA, None, "boom")
        self.assertEqual(format_diagnostic(item), ALPHA + " [F005] boom")

    def test_colour_is_opt_in(self):
        item = Diagnostic("F001", ERROR, ALPHA, 1, "boom")
        self.assertNotIn("\033", format_diagnostic(item))
        painted = format_diagnostic(item, color=True)
        self.assertIn(COLORS[ERROR] + "[F001]" + RESET, painted)

    def test_report_groups_and_summarises(self):
        text = format_text(sample())
        lines = text.strip().split("\n")
        self.assertEqual(lines[0], ALPHA + " [F005] no 'description'")
        self.assertEqual(lines[1], ALPHA + ":1 [F001] file starts with a UTF-8 BOM")
        self.assertEqual(lines[2], BETA + " [F040] Claude Code extensions: model")
        self.assertEqual(lines[3], "2 files checked: 1 errors, 1 warnings, 1 infos")
        self.assertTrue(text.endswith("\n"))

    def test_clean_files_are_listed_unless_quiet(self):
        analysis = Analysis(files=[ALPHA], diagnostics=[])
        self.assertIn(ALPHA + ": ok", format_text(analysis))
        self.assertEqual(format_text(analysis, quiet=True),
                         "1 file checked: 0 errors, 0 warnings, 0 infos\n")

    def test_summary_line_singular_and_plural(self):
        self.assertTrue(summary_line([], 1).startswith("1 file checked"))
        self.assertTrue(summary_line([], 3).startswith("3 files checked"))


class CountTestCase(unittest.TestCase):
    def test_counts_by_code(self):
        self.assertEqual(counts_by_code(sample().diagnostics),
                         {"F005": 1, "F001": 1, "F040": 1})

    def test_counts_by_severity_always_has_all_three_keys(self):
        self.assertEqual(counts_by_severity([]), {ERROR: 0, WARN: 0, INFO: 0})
        self.assertEqual(counts_by_severity(sample().diagnostics),
                         {ERROR: 1, WARN: 1, INFO: 1})


class JsonTestCase(unittest.TestCase):
    def test_schema_shape(self):
        payload = to_json(sample())
        self.assertEqual(payload["version"], SCHEMA_VERSION)
        self.assertEqual(sorted(payload), ["files", "summary", "version"])
        self.assertEqual(payload["summary"], {"errors": 1, "warnings": 1, "infos": 1})
        self.assertEqual([entry["path"] for entry in payload["files"]], [ALPHA, BETA])
        first = payload["files"][0]["diagnostics"][0]
        self.assertEqual(sorted(first), ["code", "line", "message", "severity"])
        self.assertIsNone(first["line"])

    def test_payload_is_json_serialisable_and_stable(self):
        first = json.dumps(to_json(sample()), sort_keys=True)
        second = json.dumps(to_json(sample()), sort_keys=True)
        self.assertEqual(first, second)

    def test_empty_analysis(self):
        payload = to_json(Analysis())
        self.assertEqual(payload["files"], [])
        self.assertEqual(payload["summary"], {"errors": 0, "warnings": 0, "infos": 0})


if __name__ == "__main__":
    unittest.main()
