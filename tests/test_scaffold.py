"""Scaffold tests: name validation, template quality and atomic installation."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from skill_forge import scaffold
from skill_forge.discovery import KIND_COMMAND, KIND_SKILL, discover
from skill_forge.rules import Options, check_artifact

VALID_NAMES = ("a", "demo", "demo-skill", "demo_skill", "release-notes-2",
               "0start", "x" * 64)
INVALID_NAMES = ("", "../escape", "/absolute", "a/b", ".", "..", ".hidden",
                 "Demo", "demo skill", "demo.md", "-leading", "x" * 65, "démo")


class NameTestCase(unittest.TestCase):
    def test_valid_names_are_accepted(self):
        for name in VALID_NAMES:
            with self.subTest(name):
                self.assertIsNone(scaffold.validate_name(name))

    def test_invalid_names_are_refused_as_usage_errors(self):
        for name in INVALID_NAMES:
            with self.subTest(name):
                with self.assertRaises(scaffold.ScaffoldError) as caught:
                    scaffold.validate_name(name)
                self.assertEqual(caught.exception.exit_code, 2)


class CreateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="skill-forge-scaffold-"))
        self.addCleanup(lambda: shutil.rmtree(str(self.tmp), ignore_errors=True))
        self.root = self.tmp / ".claude"

    def temps(self, folder):
        if not folder.is_dir():
            return []
        return [name for name in os.listdir(str(folder))
                if name.startswith(scaffold.TEMP_PREFIX)]

    def lint(self, root, kind):
        artifacts = discover(roots=[root]).artifacts
        self.assertEqual([item.kind for item in artifacts], [kind])
        return check_artifact(artifacts[0])

    def test_skill_bundle_layout(self):
        target = scaffold.create("demo-skill", self.root)
        self.assertEqual(target, self.root / "skills" / "demo-skill")
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertTrue((target / "references" / "example.md").is_file())
        self.assertTrue((target / "scripts" / "README.md").is_file())
        self.assertEqual(self.temps(target.parent), [])

    def test_generated_skill_lints_clean_with_style_rules_on(self):
        scaffold.create("demo-skill", self.root)
        self.assertEqual(self.lint(self.root, KIND_SKILL), [])

    def test_generated_command_lints_clean_with_style_rules_on(self):
        scaffold.create("demo-command", self.root, command=True)
        self.assertEqual(self.lint(self.root, KIND_COMMAND), [])

    def test_generated_skill_lints_clean_in_portable_mode(self):
        scaffold.create("demo-skill", self.root)
        artifact = discover(roots=[self.root]).artifacts[0]
        self.assertEqual(check_artifact(artifact, Options(portable=True)), [])

    def test_name_is_written_into_the_template(self):
        target = scaffold.create("release-notes", self.root)
        text = (target / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: release-notes", text)
        self.assertNotIn("{name}", text)

    def test_bundle_directory_is_group_readable(self):
        target = scaffold.create("demo-skill", self.root)
        self.assertEqual(os.stat(str(target)).st_mode & 0o777, scaffold.BUNDLE_MODE)

    def test_command_file_is_a_single_markdown_file(self):
        target = scaffold.create("demo-command", self.root, command=True)
        self.assertEqual(target, self.root / "commands" / "demo-command.md")
        self.assertTrue(target.is_file())
        self.assertEqual(self.temps(target.parent), [])

    def test_existing_bundle_is_never_overwritten(self):
        target = scaffold.create("demo-skill", self.root)
        (target / "SKILL.md").write_text("mine\n", encoding="utf-8")
        with self.assertRaises(scaffold.ScaffoldError) as caught:
            scaffold.create("demo-skill", self.root)
        self.assertEqual(caught.exception.exit_code, 1)
        self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "mine\n")
        self.assertEqual(self.temps(target.parent), [])

    def test_existing_command_file_is_never_overwritten(self):
        target = scaffold.create("demo-command", self.root, command=True)
        target.write_text("mine\n", encoding="utf-8")
        with self.assertRaises(scaffold.ScaffoldError):
            scaffold.create("demo-command", self.root, command=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "mine\n")
        self.assertEqual(self.temps(target.parent), [])

    def test_a_target_appearing_during_the_build_still_loses(self):
        """The race the tempdir exists to close: someone creates the target
        after validation, while the bundle is still being filled in."""
        original = scaffold._fill
        target = self.root / "skills" / "demo-skill"

        def racing_fill(tmp, name, command):
            original(tmp, name, command)
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("theirs\n", encoding="utf-8")

        scaffold._fill = racing_fill
        self.addCleanup(setattr, scaffold, "_fill", original)
        with self.assertRaises(scaffold.ScaffoldError):
            scaffold.create("demo-skill", self.root)
        self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "theirs\n")
        self.assertEqual(self.temps(target.parent), [])

    def test_invalid_name_creates_nothing(self):
        with self.assertRaises(scaffold.ScaffoldError):
            scaffold.create("../escape", self.root)
        self.assertFalse(self.root.exists())

    def test_target_for_refuses_to_leave_the_parent(self):
        with self.assertRaises(scaffold.ScaffoldError) as caught:
            scaffold.target_for("../escape", self.root)
        self.assertEqual(caught.exception.exit_code, 2)

    def test_missing_parents_are_created(self):
        deep = self.tmp / "a" / "b" / ".claude"
        target = scaffold.create("demo-skill", deep)
        self.assertTrue(target.is_dir())

    def test_unwritable_root_is_a_scaffold_error(self):
        self.root.mkdir()
        self.root.chmod(0o500)
        self.addCleanup(self.root.chmod, 0o700)
        if os.access(str(self.root), os.W_OK):  # root defeats permission checks
            self.skipTest("directory permissions are not enforced for this user")
        with self.assertRaises(scaffold.ScaffoldError) as caught:
            scaffold.create("demo-skill", self.root)
        self.assertEqual(caught.exception.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
