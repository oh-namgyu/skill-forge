"""Table-driven rule tests: every rule in ``RULES`` gets a positive and a
negative fixture, so a rule cannot change without its fixture pair changing.

``SilentFailureTestCase`` reproduces mistakes Claude Code accepts without
complaining (docs: code.claude.com/docs/en/skills, fetched 2026-09-04): a BOM
hides the frontmatter, a ``---`` on line two is not frontmatter at all, the
listing truncates at 1,536 characters, and command files ignore name/paths.
"""

import os
import shutil
import stat
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from skill_forge.discovery import KIND_COMMAND, KIND_SKILL, discover
from skill_forge.frontmatter import BOM
from skill_forge.report import counts_by_code
from skill_forge.rules import (BOOLEAN_VALUES, ERROR, INFO, RULES, SEVERITY_ORDER,
                               SKILL_ONLY, WARN, Options, analyze, check_artifact)

GOOD_SKILL = ("---\nname: demo\ndescription: Tidy markdown tables. Use when the "
              "user asks to format a table.\n---\n\n# Demo\n\nSteps here.\n")
GOOD_COMMAND = ("---\ndescription: Tidy markdown tables. Use when the user asks "
                "to format a table.\n---\n\nSteps here.\n")


def with_field(base, line):
    """Insert one frontmatter line just before the closing delimiter."""
    head, _, tail = base.partition("---\n")
    body_head, _, body = tail.partition("---\n")
    return "---\n" + body_head + line + "\n---\n" + body


@dataclass
class Case:
    text: str
    kind: str = KIND_SKILL
    name: str = "demo"
    extras: Dict[str, str] = field(default_factory=dict)
    executable: Tuple[str, ...] = ()
    options: Optional[Options] = None


LONG_DESCRIPTION = "Use when the user " + "x" * 1600
CASES = {
    "F001": (Case(BOM + GOOD_SKILL), Case(GOOD_SKILL)),
    "F002": (Case("\n" + GOOD_SKILL), Case(GOOD_SKILL)),
    "F003": (Case(with_field(GOOD_SKILL, "just some prose")), Case(GOOD_SKILL)),
    "F004": (Case(GOOD_SKILL.replace("name: demo", "name: other")), Case(GOOD_SKILL)),
    "F005": (Case("---\nname: demo\n---\n\nbody\n"), Case(GOOD_SKILL)),
    "F010": (Case("---\nname: demo\ndescription: tidy\n---\n\nbody\n"),
             Case(GOOD_SKILL)),
    "F011": (Case(GOOD_SKILL + "padding line\n" * 900), Case(GOOD_SKILL)),
    "F012": (Case(with_field(GOOD_SKILL, "when_to_use: " + LONG_DESCRIPTION)),
             Case(with_field(GOOD_SKILL, "when_to_use: Use when formatting."))),
    "F013": (Case(with_field(GOOD_SKILL, "user-invocable: maybe")),
             Case(with_field(GOOD_SKILL, "user-invocable: yes"))),
    "F020": (Case(GOOD_SKILL + "\nSee `references/guide.md`.\n"),
             Case(GOOD_SKILL + "\nSee `references/guide.md`.\n",
                  extras={"references/guide.md": "guide\n"})),
    "F021": (Case(GOOD_SKILL, extras={"scripts/run.sh": "#!/bin/sh\necho hi\n"}),
             Case(GOOD_SKILL, extras={"scripts/run.sh": "#!/bin/sh\necho hi\n"},
                  executable=("scripts/run.sh",))),
    "F030": (Case(with_field(GOOD_SKILL, "descriptoin: typo")), Case(GOOD_SKILL)),
    "F040": (Case(with_field(GOOD_SKILL, "model: opus")), Case(GOOD_SKILL)),
    "F090": (Case(with_field(GOOD_SKILL, "agent: *base")), Case(GOOD_SKILL)),
}


class RuleTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="skill-forge-rules-"))
        self.addCleanup(lambda: shutil.rmtree(str(self.tmp), ignore_errors=True))
        self.serial = 0

    def build(self, case):
        """Materialise one case in its own root and return the artifact."""
        self.serial += 1
        root = self.tmp / "root{0}".format(self.serial)
        if case.kind == KIND_SKILL:
            bundle = root / "skills" / case.name
            bundle.mkdir(parents=True)
            path = bundle / "SKILL.md"
        else:
            bundle = root / "commands"
            bundle.mkdir(parents=True)
            path = bundle / (case.name + ".md")
        path.write_text(case.text, encoding="utf-8")
        for relative, content in case.extras.items():
            target = bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            mode = stat.S_IRWXU if relative in case.executable else 0o600
            target.chmod(mode)
        found = discover(roots=[root]).artifacts
        self.assertEqual(len(found), 1)
        return found[0]

    def codes(self, case):
        return [item.code for item in check_artifact(self.build(case), case.options)]

    def test_every_rule_has_a_fixture_pair(self):
        self.assertEqual(sorted(CASES), sorted(rule.code for rule in RULES))

    def test_rule_metadata_is_well_formed(self):
        for rule in RULES:
            with self.subTest(rule.code):
                self.assertIn(rule.severity, SEVERITY_ORDER)
                self.assertIn(rule.applies, ("both", SKILL_ONLY))
                self.assertTrue(rule.summary)

    def test_positive_fixtures_fire_their_rule(self):
        for code, (positive, _) in sorted(CASES.items()):
            with self.subTest(code):
                self.assertIn(code, self.codes(positive))

    def test_negative_fixtures_stay_silent(self):
        for code, (_, negative) in sorted(CASES.items()):
            with self.subTest(code):
                self.assertNotIn(code, self.codes(negative))

    def test_clean_artifacts_have_no_diagnostics(self):
        self.assertEqual(self.codes(Case(GOOD_SKILL)), [])
        self.assertEqual(self.codes(Case(GOOD_COMMAND, kind=KIND_COMMAND)), [])

    def test_diagnostics_are_sorted_by_line(self):
        artifact = self.build(Case("---\nnope\nalso nope\n---\n\nbody\n"))
        lines = [item.line for item in check_artifact(artifact)]
        self.assertEqual(lines, sorted(lines, key=lambda value: value or 0))


class ScopeTestCase(RuleTestCase):
    SKILL_ONLY_CODES = tuple(rule.code for rule in RULES if rule.applies == SKILL_ONLY)

    def test_skill_only_rules_never_fire_on_command_files(self):
        text = ("---\nname: other\ndescription: Tidy tables. Use when the user "
                "asks.\n---\n\nSee `references/missing.md`.\n" + "pad\n" * 3000)
        codes = self.codes(Case(text, kind=KIND_COMMAND))
        for code in self.SKILL_ONLY_CODES:
            with self.subTest(code):
                self.assertNotIn(code, codes)

    def test_missing_name_is_not_an_f004(self):
        codes = self.codes(Case("---\ndescription: Tidy tables. Use when asked "
                                "to format.\n---\n\nbody\n"))
        self.assertNotIn("F004", codes)

    def test_file_without_frontmatter_is_f005_not_f002(self):
        codes = self.codes(Case("# Title\n\nJust a body.\n"))
        self.assertEqual(codes, ["F005"])

    def test_style_option_disables_the_heuristic_rule(self):
        case = Case("---\nname: demo\ndescription: tidy\n---\n\nbody\n",
                    options=Options(style=False))
        self.assertNotIn("F010", self.codes(case))

    def test_portable_option_escalates_the_portability_notice(self):
        artifact = self.build(Case(with_field(GOOD_SKILL, "model: opus")))
        default = check_artifact(artifact)[0]
        portable = check_artifact(artifact, Options(portable=True))[0]
        self.assertEqual((default.code, default.severity), ("F040", INFO))
        self.assertEqual((portable.code, portable.severity), ("F040", WARN))

    def test_spec_only_frontmatter_has_no_portability_notice(self):
        text = ("---\nname: demo\ndescription: Tidy tables. Use when asked.\n"
                "license: MIT\nallowed-tools: [Read]\n---\n\nbody\n")
        self.assertNotIn("F040", self.codes(Case(text)))

    def test_every_accepted_boolean_form_passes(self):
        for value in BOOLEAN_VALUES + tuple(v.upper() for v in BOOLEAN_VALUES):
            with self.subTest(value):
                case = Case(with_field(GOOD_SKILL, "background: " + value))
                self.assertNotIn("F013", self.codes(case))

    def test_all_three_boolean_fields_are_checked(self):
        for key in ("disable-model-invocation", "user-invocable", "background"):
            with self.subTest(key):
                case = Case(with_field(GOOD_SKILL, key + ": sometimes"))
                self.assertIn("F013", self.codes(case))

    def test_korean_description_is_not_flagged_for_missing_triggers(self):
        text = ("---\nname: demo\ndescription: 마크다운 표를 정리한다. 사용자가 "
                "표 정리를 요청하면 실행.\n---\n\nbody\n")
        self.assertEqual(self.codes(Case(text)), [])


class ReferenceTestCase(RuleTestCase):
    def refs(self, body, extras=None):
        return self.codes(Case(GOOD_SKILL + body, extras=extras or {}))

    def test_prose_mention_is_not_a_reference(self):
        self.assertEqual(self.refs("\nThe references/guide.md file explains it.\n"), [])

    def test_markdown_link_target_is_a_reference(self):
        self.assertIn("F020", self.refs("\nSee [guide](references/guide.md).\n"))

    def test_command_line_inside_a_code_span_is_split(self):
        self.assertIn("F020", self.refs("\nRun `python scripts/build.py --all`.\n"))

    def test_existing_script_reference_passes(self):
        codes = self.refs("\nRun `scripts/build.py`.\n",
                          extras={"scripts/build.py": "print('hi')\n"})
        self.assertEqual(codes, [])

    def test_link_anchor_is_stripped_before_the_check(self):
        codes = self.refs("\nSee [part](references/guide.md#part).\n",
                          extras={"references/guide.md": "x\n"})
        self.assertEqual(codes, [])

    def test_unrelated_paths_are_ignored(self):
        self.assertEqual(self.refs("\nSee `/etc/hosts` and `other/file.md`.\n"), [])

    def test_globs_and_bare_directories_are_not_file_references(self):
        # real bundles write `scripts/` and `scripts/*.py` as generic mentions
        self.assertEqual(self.refs("\nPut them in `scripts/`, e.g. `scripts/*.py`.\n"),
                         [])

    def test_only_shell_scripts_and_shebangs_need_an_exec_bit(self):
        quiet = {"scripts/data.json": "{}\n", "scripts/__init__.py": "",
                 "scripts/utils.py": "\"\"\"helpers\"\"\"\n"}
        for relative, content in sorted(quiet.items()):
            with self.subTest(relative):
                self.assertEqual(self.refs("\n", extras={relative: content}), [])
        loud = {"scripts/tool.py": "#!/usr/bin/env python3\n", "scripts/go.sh": "echo\n"}
        for relative, content in sorted(loud.items()):
            with self.subTest(relative):
                self.assertEqual(self.refs("\n", extras={relative: content}), ["F021"])

    def test_reference_line_numbers_point_into_the_body(self):
        artifact = self.build(Case(GOOD_SKILL + "\nSee `references/gone.md`.\n"))
        found = [item for item in check_artifact(artifact) if item.code == "F020"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].line, 10)  # body line, not a frontmatter line


class SilentFailureTestCase(RuleTestCase):
    """Mistakes Claude Code accepts silently; the linter must not."""

    def test_bom_makes_the_whole_frontmatter_invisible(self):
        codes = self.codes(Case(BOM + GOOD_SKILL))
        self.assertEqual(codes, ["F001"])

    def test_delimiter_on_the_second_line_is_not_frontmatter(self):
        codes = self.codes(Case("\n" + GOOD_SKILL))
        self.assertIn("F002", codes)
        self.assertIn("F005", codes)

    def test_listing_truncation_limit(self):
        case = Case(with_field(GOOD_SKILL, "when_to_use: " + LONG_DESCRIPTION))
        message = [item.message for item in check_artifact(self.build(case))
                   if item.code == "F012"][0]
        self.assertIn("1536", message)

    def test_command_file_name_and_paths_are_ignored(self):
        text = with_field(with_field(GOOD_COMMAND, "name: other"), "paths: src/**")
        found = [item for item in check_artifact(self.build(
            Case(text, kind=KIND_COMMAND))) if item.code == "F030"]
        self.assertEqual(len(found), 2)
        self.assertTrue(all("ignored in command files" in item.message
                            for item in found))

    def test_skill_files_keep_name_and_paths(self):
        text = with_field(GOOD_SKILL, "paths: src/**")
        self.assertNotIn("F030", self.codes(Case(text)))


class AnalyzeTestCase(RuleTestCase):
    def test_analyze_reports_files_and_read_failures(self):
        root = self.tmp / "tree"
        bundle = root / "skills" / "demo"
        bundle.mkdir(parents=True)
        (bundle / "SKILL.md").write_text(GOOD_SKILL, encoding="utf-8")
        (root / "commands").mkdir()
        (root / "commands" / "broken.md").write_bytes(b"---\ndesc: \xff\n---\n")
        analysis = analyze(discover(roots=[root]))
        self.assertEqual(len(analysis.files), 2)
        self.assertEqual(counts_by_code(analysis.diagnostics), {"F901": 1})
        self.assertEqual(analysis.diagnostics[0].severity, ERROR)

    def test_analyze_reports_a_missing_explicit_path_as_f900(self):
        analysis = analyze(discover(paths=[self.tmp / "nope" / "SKILL.md"]))
        self.assertEqual(counts_by_code(analysis.diagnostics), {"F900": 1})

    def test_analyze_is_repeatable(self):
        root = self.tmp / "tree2"
        bundle = root / "skills" / "demo"
        bundle.mkdir(parents=True)
        (bundle / "SKILL.md").write_text(BOM + GOOD_SKILL, encoding="utf-8")
        first = analyze(discover(roots=[root]))
        second = analyze(discover(roots=[root]))
        self.assertEqual(first, second)

    def test_analysing_a_missing_root_writes_nothing(self):
        before = sorted(os.listdir(str(self.tmp)))
        analyze(discover(roots=[self.tmp / "absent"]))
        self.assertEqual(sorted(os.listdir(str(self.tmp))), before)


if __name__ == "__main__":
    unittest.main()
