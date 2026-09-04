"""Discovery tests against synthetic trees; nothing outside the tempdir is read."""

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from skill_forge.discovery import (CODE_NOT_UTF8, CODE_UNREADABLE, KIND_COMMAND,
                                   KIND_SKILL, counts_by_kind, discover)

SKILL_TEXT = "---\nname: demo\ndescription: A demo skill. Use when demoing.\n---\n\nBody\n"


class DiscoveryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="skill-forge-discovery-"))
        self.addCleanup(self.cleanup)
        self.root = self.tmp / "project"
        (self.root / "skills").mkdir(parents=True)
        (self.root / "commands").mkdir(parents=True)

    def cleanup(self):
        for path in self.tmp.rglob("*"):
            try:
                path.chmod(stat.S_IRWXU)
            except OSError:
                pass
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def skill(self, name, text=SKILL_TEXT, root=None):
        folder = (root or self.root) / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "SKILL.md"
        path.write_text(text, encoding="utf-8")
        return path

    def command(self, name, text="body\n", root=None):
        folder = (root or self.root) / "commands"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (name + ".md")
        path.write_text(text, encoding="utf-8")
        return path

    def names(self, result):
        return [(item.kind, item.name) for item in result.artifacts]

    def test_finds_skills_then_commands_in_name_order(self):
        self.skill("zebra")
        self.skill("alpha")
        self.command("second")
        self.command("first")
        result = discover(roots=[self.root])
        self.assertEqual(self.names(result),
                         [(KIND_SKILL, "alpha"), (KIND_SKILL, "zebra"),
                          (KIND_COMMAND, "first"), (KIND_COMMAND, "second")])
        self.assertEqual(counts_by_kind(result), {KIND_SKILL: 2, KIND_COMMAND: 2})

    def test_roots_are_scanned_in_the_order_given(self):
        other = self.tmp / "personal"
        self.skill("one")
        self.skill("two", root=other)
        first = discover(roots=[self.root, other])
        second = discover(roots=[other, self.root])
        self.assertEqual(self.names(first), [(KIND_SKILL, "one"), (KIND_SKILL, "two")])
        self.assertEqual(self.names(second), [(KIND_SKILL, "two"), (KIND_SKILL, "one")])

    def test_skill_carries_bundle_and_text(self):
        self.skill("demo")
        artifact = discover(roots=[self.root]).artifacts[0]
        self.assertEqual(artifact.bundle, self.root / "skills" / "demo")
        self.assertTrue(artifact.is_skill)
        self.assertEqual(artifact.text, SKILL_TEXT)

    def test_directory_without_skill_file_is_ignored(self):
        (self.root / "skills" / "empty").mkdir()
        self.assertEqual(discover(roots=[self.root]).artifacts, [])

    def test_hidden_entries_are_skipped(self):
        self.skill("visible")
        self.skill(".hidden")
        self.command("shown")
        self.command(".secret")
        self.assertEqual(self.names(discover(roots=[self.root])),
                         [(KIND_SKILL, "visible"), (KIND_COMMAND, "shown")])

    def test_non_markdown_command_files_are_ignored(self):
        self.command("keep")
        (self.root / "commands" / "notes.txt").write_text("x", encoding="utf-8")
        self.assertEqual(self.names(discover(roots=[self.root])),
                         [(KIND_COMMAND, "keep")])

    def test_symlinked_skill_directory_is_not_followed(self):
        self.skill("real")
        outside = self.tmp / "outside"
        (outside / "sneaky").mkdir(parents=True)
        (outside / "sneaky" / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
        os.symlink(str(outside / "sneaky"), str(self.root / "skills" / "linked"))
        self.assertEqual(self.names(discover(roots=[self.root])), [(KIND_SKILL, "real")])

    def test_symlinked_command_file_is_deduped_by_realpath(self):
        real = self.command("real")
        os.symlink(str(real), str(self.root / "commands" / "alias.md"))
        result = discover(roots=[self.root])
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(result.artifacts[0].name, "alias")

    def test_same_root_twice_is_deduped(self):
        self.skill("demo")
        result = discover(roots=[self.root, self.root])
        self.assertEqual(len(result.artifacts), 1)

    def test_explicit_paths_come_before_roots_and_dedupe(self):
        first = self.skill("alpha")
        self.command("later")
        result = discover(roots=[self.root], paths=[first])
        self.assertEqual(self.names(result),
                         [(KIND_SKILL, "alpha"), (KIND_COMMAND, "later")])

    def test_explicit_bundle_directory_is_a_skill(self):
        self.skill("alpha")
        result = discover(paths=[self.root / "skills" / "alpha"])
        self.assertEqual(self.names(result), [(KIND_SKILL, "alpha")])

    def test_explicit_root_directory_is_scanned(self):
        self.skill("alpha")
        self.command("beta")
        self.assertEqual(self.names(discover(paths=[self.root])),
                         [(KIND_SKILL, "alpha"), (KIND_COMMAND, "beta")])

    def test_explicit_command_file_outside_any_root(self):
        loose = self.tmp / "loose.md"
        loose.write_text("hello\n", encoding="utf-8")
        self.assertEqual(self.names(discover(paths=[loose])), [(KIND_COMMAND, "loose")])

    def test_missing_explicit_path_is_a_note(self):
        result = discover(paths=[self.tmp / "nope.md"])
        self.assertEqual(result.artifacts, [])
        self.assertEqual([note.code for note in result.notes], [CODE_UNREADABLE])

    def test_non_utf8_file_becomes_a_note(self):
        path = self.root / "commands" / "broken.md"
        path.write_bytes(b"---\ndescription: \xff\xfe bad\n---\n")
        self.skill("fine")
        result = discover(roots=[self.root])
        self.assertEqual(self.names(result), [(KIND_SKILL, "fine")])
        self.assertEqual([note.code for note in result.notes], [CODE_NOT_UTF8])

    def test_unreadable_file_becomes_a_note(self):
        blocked = self.command("blocked")
        blocked.chmod(0o000)
        if os.access(str(blocked), os.R_OK):  # root defeats permission checks
            self.skipTest("file permissions are not enforced for this user")
        result = discover(roots=[self.root])
        self.assertEqual(result.artifacts, [])
        self.assertEqual([note.code for note in result.notes], [CODE_UNREADABLE])

    def test_unreadable_directory_does_not_crash(self):
        self.skill("ok")
        blocked = self.root / "skills" / "blocked"
        blocked.mkdir()
        blocked.chmod(0o000)
        if os.access(str(blocked), os.R_OK):
            self.skipTest("directory permissions are not enforced for this user")
        self.assertEqual(self.names(discover(roots=[self.root])), [(KIND_SKILL, "ok")])
        blocked.chmod(stat.S_IRWXU)

    def test_missing_root_is_empty_not_an_error(self):
        self.assertEqual(discover(roots=[self.tmp / "absent"]).artifacts, [])

    def test_discovery_is_repeatable(self):
        self.skill("alpha")
        self.command("beta")
        self.assertEqual(self.names(discover(roots=[self.root])),
                         self.names(discover(roots=[self.root])))


if __name__ == "__main__":
    unittest.main()
