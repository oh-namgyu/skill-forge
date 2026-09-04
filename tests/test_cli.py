"""CLI tests: exit codes, flags, default roots and the guarded ``new`` command.

Every test runs inside a temporary directory with ``CLAUDE_CONFIG_DIR`` pointed
at a temporary personal root, so the real config directory is never read.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from skill_forge import scaffold
from skill_forge.cli import (ENV_CONFIG_DIR, _width, config_dir, default_roots,
                             main)

CLEAN = ("---\nname: {0}\ndescription: Tidy markdown tables. Use when the user "
         "asks to format a table.\n---\n\nbody\n")
NO_DESCRIPTION = "---\nname: {0}\n---\n\nbody\n"
BOM_SKILL = "﻿" + CLEAN


class CliTestCase(unittest.TestCase):
    def setUp(self):
        # resolved: on macOS /var is a symlink, and os.getcwd() reports /private/var
        self.tmp = Path(tempfile.mkdtemp(prefix="skill-forge-cli-")).resolve()
        self.addCleanup(self.cleanup)
        self.previous_dir = os.getcwd()
        self.previous_env = os.environ.get(ENV_CONFIG_DIR)
        self.project = self.tmp / "work"
        self.personal = self.tmp / "personal"
        self.personal.mkdir(parents=True)
        self.project.mkdir(parents=True)
        os.chdir(str(self.project))
        os.environ[ENV_CONFIG_DIR] = str(self.personal)

    def cleanup(self):
        os.chdir(self.previous_dir)
        if self.previous_env is None:
            os.environ.pop(ENV_CONFIG_DIR, None)
        else:
            os.environ[ENV_CONFIG_DIR] = self.previous_env
        for path in self.tmp.rglob("*"):
            try:
                path.chmod(0o700)
            except OSError:
                pass
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def skill(self, name, text=CLEAN, root=None):
        folder = (root or self.project / ".claude") / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(text.format(name), encoding="utf-8")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()


class LintTestCase(CliTestCase):
    def test_clean_tree_exits_zero(self):
        self.skill("demo")
        code, out, err = self.run_cli("lint")
        self.assertEqual(code, 0)
        self.assertIn("0 errors, 0 warnings", out)
        self.assertIn("scanned 1 file(s)", err)

    def test_info_only_still_exits_zero(self):
        self.skill("demo", CLEAN.replace("---\n\nbody", "model: opus\n---\n\nbody"))
        code, out, _ = self.run_cli("lint")
        self.assertEqual(code, 0)
        self.assertIn("F040", out)

    def test_warnings_exit_one(self):
        self.skill("demo", NO_DESCRIPTION)
        code, out, _ = self.run_cli("lint")
        self.assertEqual(code, 1)
        self.assertIn("F005", out)

    def test_errors_exit_two(self):
        self.skill("demo", BOM_SKILL)
        code, out, _ = self.run_cli("lint")
        self.assertEqual(code, 2)
        self.assertIn("F001", out)

    def test_explicit_path_overrides_the_default_roots(self):
        self.skill("demo", BOM_SKILL)
        self.skill("other", CLEAN, root=self.personal)
        target = self.personal / "skills" / "other"
        code, out, _ = self.run_cli("lint", str(target))
        self.assertEqual(code, 0)
        self.assertNotIn("demo", out)

    def test_missing_targets_is_a_usage_error(self):
        os.environ[ENV_CONFIG_DIR] = str(self.tmp / "absent")
        code, _, err = self.run_cli("lint")
        self.assertEqual(code, 2)
        self.assertIn("no ./.claude", err)

    def test_json_output_is_well_formed(self):
        self.skill("demo", NO_DESCRIPTION)
        code, out, _ = self.run_cli("lint", "--json")
        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["files"][0]["diagnostics"][0]["code"], "F005")

    def test_no_style_drops_the_heuristic_rule(self):
        self.skill("demo", "---\nname: demo\ndescription: tidy\n---\n\nbody\n")
        self.assertEqual(self.run_cli("lint")[0], 1)
        code, out, _ = self.run_cli("lint", "--no-style")
        self.assertEqual(code, 0)
        self.assertNotIn("F010", out)

    def test_portable_escalates_the_extension_notice(self):
        self.skill("demo", CLEAN.replace("---\n\nbody", "model: opus\n---\n\nbody"))
        self.assertEqual(self.run_cli("lint")[0], 0)
        self.assertEqual(self.run_cli("lint", "--portable")[0], 1)

    def test_quiet_hides_clean_files(self):
        self.skill("demo")
        self.assertIn(": ok", self.run_cli("lint")[1])
        self.assertNotIn(": ok", self.run_cli("lint", "--quiet")[1])

    def test_output_is_never_coloured_off_a_tty(self):
        self.skill("demo", BOM_SKILL)
        self.assertNotIn("\033", self.run_cli("lint")[1])
        self.assertNotIn("\033", self.run_cli("lint", "--no-color")[1])

    def test_unreadable_file_is_reported_not_raised(self):
        (self.project / ".claude" / "commands").mkdir(parents=True)
        (self.project / ".claude" / "commands" / "bad.md").write_bytes(b"\xff\xfe\n")
        code, out, _ = self.run_cli("lint")
        self.assertEqual(code, 2)
        self.assertIn("F901", out)


class RootTestCase(CliTestCase):
    def test_project_root_comes_before_the_personal_root(self):
        self.skill("demo")
        self.skill("other", root=self.personal)
        self.assertEqual(default_roots(),
                         [self.project / ".claude", self.personal])
        out = self.run_cli("lint")[1]
        self.assertLess(out.index("demo"), out.index("other"))

    def test_personal_root_alone_is_used(self):
        self.skill("other", root=self.personal)
        self.assertEqual(default_roots(), [self.personal])
        self.assertEqual(self.run_cli("lint")[0], 0)

    def test_config_dir_follows_the_environment(self):
        self.assertEqual(config_dir(), self.personal)
        os.environ.pop(ENV_CONFIG_DIR)
        self.assertEqual(config_dir(), Path.home() / ".claude")

    def test_the_same_root_is_not_scanned_twice(self):
        os.environ[ENV_CONFIG_DIR] = str(self.project / ".claude")
        self.skill("demo")
        self.assertEqual(default_roots(), [self.project / ".claude"])
        self.assertIn("scanned 1 file(s)", self.run_cli("lint")[2])


class ListTestCase(CliTestCase):
    def test_catalog_lists_name_kind_and_findings(self):
        self.skill("demo")
        self.skill("broken", NO_DESCRIPTION)
        code, out, err = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("NAME", out.split("\n")[0])
        rows = [line for line in out.split("\n") if line.startswith("broken")]
        self.assertEqual(len(rows), 1)
        self.assertIn("skill", rows[0])
        self.assertIn("1W", rows[0])
        self.assertIn("2 files checked", err)

    def test_clean_entries_show_a_dash(self):
        self.skill("demo")
        row = [line for line in self.run_cli("list")[1].split("\n")
               if line.startswith("demo")][0]
        self.assertTrue(row.endswith("-"))
        self.assertIn("Tidy markdown tables", row)

    def test_wide_characters_keep_the_columns_aligned(self):
        self.skill("demo")
        self.skill("검토", CLEAN.replace("Tidy markdown tables.", "표 정리."))
        rows = [line for line in self.run_cli("list")[1].split("\n") if line]
        # columns line up by display width, not character count
        heads = set(_width(line.split("skill")[0]) for line in rows[1:])
        self.assertEqual(len(heads), 1)
        self.assertNotEqual(len(set(line.index("skill") for line in rows[1:])), 1)

    def test_explicit_roots_are_accepted(self):
        self.skill("other", root=self.personal)
        self.assertIn("other", self.run_cli("list", str(self.personal))[1])

    def test_empty_root_is_not_an_error(self):
        (self.project / ".claude").mkdir()
        code, out, err = self.run_cli("list")
        self.assertEqual((code, out), (0, ""))
        self.assertIn("no skills or commands", err)


class NewTestCase(CliTestCase):
    def test_new_skill_is_created_and_lints_clean(self):
        (self.project / ".claude").mkdir()
        code, out, _ = self.run_cli("new", "demo-skill")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(),
                         str(self.project / ".claude" / "skills" / "demo-skill"))
        self.assertEqual(self.run_cli("lint")[0], 0)

    def test_new_command_is_created_and_lints_clean(self):
        (self.project / ".claude").mkdir()
        self.assertEqual(self.run_cli("new", "demo-command", "--command")[0], 0)
        self.assertTrue((self.project / ".claude" / "commands" /
                         "demo-command.md").is_file())
        self.assertEqual(self.run_cli("lint")[0], 0)

    def test_dir_flag_chooses_the_root(self):
        code, out, _ = self.run_cli("new", "demo-skill", "--dir", str(self.personal))
        self.assertEqual(code, 0)
        self.assertTrue((self.personal / "skills" / "demo-skill").is_dir())
        self.assertEqual(out.strip(), str(self.personal / "skills" / "demo-skill"))

    def test_without_a_project_directory_it_asks_for_dir(self):
        code, out, err = self.run_cli("new", "demo-skill")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("--dir", err)
        self.assertFalse((self.personal / "skills").exists())

    def test_dangerous_names_are_refused_before_any_file_is_written(self):
        (self.project / ".claude").mkdir()
        for name in ("../escape", "/absolute", "a/b", ".", "..", "demo.md", "Demo"):
            with self.subTest(name):
                code, out, err = self.run_cli("new", name)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("invalid name", err)
        self.assertFalse((self.project / ".claude" / "skills").exists())
        self.assertFalse((self.tmp / "escape").exists())

    def test_existing_target_exits_one_and_keeps_the_original(self):
        (self.project / ".claude").mkdir()
        self.run_cli("new", "demo-skill")
        target = self.project / ".claude" / "skills" / "demo-skill" / "SKILL.md"
        target.write_text("mine\n", encoding="utf-8")
        code, out, err = self.run_cli("new", "demo-skill")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("cannot create", err)
        self.assertEqual(target.read_text(encoding="utf-8"), "mine\n")

    def test_no_temporary_directory_survives_a_failure(self):
        (self.project / ".claude").mkdir()
        self.run_cli("new", "demo-skill")
        self.run_cli("new", "demo-skill")
        parent = self.project / ".claude" / "skills"
        leftovers = [name for name in os.listdir(str(parent))
                     if name.startswith(scaffold.TEMP_PREFIX)]
        self.assertEqual(leftovers, [])


class UsageTestCase(CliTestCase):
    def assert_usage_error(self, *argv):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli(*argv)
        self.assertEqual(caught.exception.code, 2)

    def test_no_command_is_a_usage_error(self):
        self.assert_usage_error()

    def test_unknown_command_is_a_usage_error(self):
        self.assert_usage_error("polish")

    def test_unknown_flag_is_a_usage_error(self):
        self.assert_usage_error("lint", "--deep")

    def test_new_without_a_name_is_a_usage_error(self):
        self.assert_usage_error("new")

    def test_version_exits_zero(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("--version")
        self.assertEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
