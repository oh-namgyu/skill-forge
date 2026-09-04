"""Grammar tests for the frontmatter line parser, one branch at a time."""

import unittest

from skill_forge.frontmatter import BOM, DUPLICATE, UNSUPPORTED, parse

BASIC = "---\nname: demo\ndescription: A demo. Use when demoing.\n---\n\n# Title\nbody\n"


class PresenceTestCase(unittest.TestCase):
    def test_frontmatter_needs_the_first_line(self):
        result = parse(BASIC)
        self.assertTrue(result.present)
        self.assertTrue(result.closed)
        self.assertIsNone(result.late_delimiter)
        self.assertEqual(result.scalar("name"), "demo")

    def test_body_and_body_start_line(self):
        result = parse(BASIC)
        self.assertEqual(result.body, "\n# Title\nbody\n")
        self.assertEqual(result.body_start_line, 5)

    def test_a_bom_defeats_the_first_line_rule(self):
        result = parse(BOM + BASIC)
        self.assertTrue(result.has_bom)
        self.assertIsNone(result.late_delimiter)
        self.assertEqual(result.scalar("name"), "demo")

    def test_no_frontmatter_is_all_body(self):
        result = parse("# Title\nbody\n")
        self.assertFalse(result.present)
        self.assertFalse(result.has_bom)
        self.assertIsNone(result.late_delimiter)
        self.assertEqual(result.body, "# Title\nbody\n")
        self.assertEqual(result.body_start_line, 1)

    def test_blank_line_before_the_delimiter_is_reported(self):
        result = parse("\n---\nname: demo\n---\n")
        self.assertFalse(result.present)
        self.assertEqual(result.late_delimiter, 2)

    def test_indented_delimiter_on_line_one_is_reported(self):
        self.assertEqual(parse("  ---\nname: demo\n---\n").late_delimiter, 1)

    def test_horizontal_rule_after_prose_is_not_a_late_delimiter(self):
        self.assertIsNone(parse("# Title\n\n---\n\nmore\n").late_delimiter)

    def test_unclosed_frontmatter(self):
        result = parse("---\nname: demo\ndescription: x\n")
        self.assertTrue(result.present)
        self.assertFalse(result.closed)
        self.assertEqual(result.scalar("name"), "demo")
        self.assertEqual(result.body, "")

    def test_crlf_input_parses_the_same(self):
        self.assertEqual(parse(BASIC.replace("\n", "\r\n")), parse(BASIC))


class GrammarTestCase(unittest.TestCase):
    def parse_block(self, block):
        return parse("---\n" + block + "---\nbody\n")

    def test_bare_and_quoted_scalars(self):
        result = self.parse_block("a: plain\nb: \"quoted\"\nc: 'single'\n")
        self.assertEqual(result.scalar("a"), "plain")
        self.assertEqual(result.scalar("b"), "quoted")
        self.assertEqual(result.scalar("c"), "single")
        self.assertEqual(result.fields["b"].raw, "\"quoted\"")

    def test_hash_is_part_of_the_value_not_a_comment(self):
        result = self.parse_block("description: tag # not a comment\n")
        self.assertEqual(result.scalar("description"), "tag # not a comment")

    def test_whole_line_comment_is_skipped(self):
        result = self.parse_block("# a comment\nname: demo\n")
        self.assertEqual(result.key_order, ["name"])
        self.assertEqual(result.errors, [])

    def test_empty_value_is_an_empty_scalar(self):
        result = self.parse_block("model:\nname: demo\n")
        self.assertEqual(result.scalar("model"), "")
        self.assertFalse(result.fields["model"].is_list)

    def test_inline_list(self):
        result = self.parse_block("allowed-tools: [Read, \"Bash(ls:*)\"]\n")
        item = result.fields["allowed-tools"]
        self.assertTrue(item.is_list)
        self.assertEqual(item.value, ["Read", "Bash(ls:*)"])

    def test_empty_inline_list(self):
        self.assertEqual(self.parse_block("allowed-tools: []\n").fields[
            "allowed-tools"].value, [])

    def test_unterminated_inline_list_is_a_note_and_stays_scalar(self):
        result = self.parse_block("allowed-tools: [Read, Bash\nname: demo\n")
        self.assertEqual([note.kind for note in result.notes], [UNSUPPORTED])
        self.assertFalse(result.fields["allowed-tools"].is_list)
        self.assertEqual(result.scalar("name"), "demo")

    def test_block_list(self):
        result = self.parse_block("allowed-tools:\n  - Read\n  - 'Write'\nname: demo\n")
        item = result.fields["allowed-tools"]
        self.assertTrue(item.is_list)
        self.assertEqual(item.value, ["Read", "Write"])
        self.assertEqual(item.line, 2)
        self.assertEqual(result.scalar("name"), "demo")

    def test_space_separated_scalar_is_left_alone(self):
        self.assertEqual(self.parse_block("allowed-tools: Read Write\n").scalar(
            "allowed-tools"), "Read Write")

    def test_metadata_is_opaque(self):
        result = self.parse_block("metadata:\n  author: someone\n  version: 2\nname: x\n")
        self.assertIn("metadata", result.opaque)
        self.assertNotIn("metadata", result.fields)
        self.assertEqual(result.opaque["metadata"].raw,
                         "  author: someone\n  version: 2")
        self.assertEqual(result.scalar("name"), "x")

    def test_hooks_is_opaque_and_not_interpreted(self):
        result = self.parse_block("hooks:\n  PreToolUse:\n    - matcher: Bash\nname: x\n")
        self.assertIn("hooks", result.opaque)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.key_order, ["hooks", "name"])

    def test_any_nested_map_becomes_opaque(self):
        result = self.parse_block("context:\n  files: 3\nname: x\n")
        self.assertIn("context", result.opaque)
        self.assertEqual(result.scalar("name"), "x")

    def test_inline_flow_map_is_opaque(self):
        result = self.parse_block("metadata: {author: someone}\n")
        self.assertEqual(result.opaque["metadata"].raw, "{author: someone}")

    def test_multiline_quoted_scalar_is_folded(self):
        # real bundles wrap long descriptions over indented continuation lines
        result = self.parse_block("description:\n  \"Solve problems with care.\n"
                                  "  Use when asked to solve one.\"\nname: demo\n")
        self.assertEqual(result.scalar("description"),
                         "Solve problems with care. Use when asked to solve one.")
        self.assertEqual(result.notes, [])
        self.assertEqual(result.scalar("name"), "demo")

    def test_multiline_inline_list_is_a_list(self):
        result = self.parse_block("allowed-tools:\n  [\n    \"Read\",\n"
                                  "    \"Write\"\n  ]\nname: demo\n")
        self.assertEqual(result.fields["allowed-tools"].value, ["Read", "Write"])
        self.assertEqual(result.notes, [])
        self.assertEqual(result.scalar("name"), "demo")

    def test_unterminated_multiline_list_is_a_note(self):
        result = self.parse_block("allowed-tools:\n  [\n    \"Read\",\nname: demo\n")
        self.assertEqual([note.kind for note in result.notes], [UNSUPPORTED])

    def test_duplicate_key_keeps_the_first_and_notes_it(self):
        result = self.parse_block("name: one\nname: two\n")
        self.assertEqual(result.scalar("name"), "one")
        self.assertEqual([note.kind for note in result.notes], [DUPLICATE])


class UnsupportedTestCase(unittest.TestCase):
    def parse_block(self, block):
        return parse("---\n" + block + "---\nbody\n")

    def kinds(self, result):
        return [(note.line, note.kind) for note in result.notes]

    def test_anchor_is_a_note_and_parsing_continues(self):
        result = self.parse_block("base: &anchor value\nname: demo\n")
        self.assertEqual(self.kinds(result), [(2, UNSUPPORTED)])
        self.assertEqual(result.scalar("name"), "demo")

    def test_alias_is_a_note(self):
        self.assertEqual(self.kinds(self.parse_block("model: *base\nname: d\n")),
                         [(2, UNSUPPORTED)])

    def test_block_scalar_is_a_note_and_its_lines_are_swallowed(self):
        result = self.parse_block("description: |\n  line one\n  line two\nname: demo\n")
        self.assertEqual(self.kinds(result), [(2, UNSUPPORTED)])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.scalar("name"), "demo")

    def test_folded_scalar_is_a_note(self):
        self.assertEqual(self.kinds(self.parse_block("description: >-\n  text\nname: d\n")),
                         [(2, UNSUPPORTED)])

    def test_tab_indentation_is_a_note(self):
        result = self.parse_block("allowed-tools:\n\t- Read\nname: demo\n")
        self.assertIn((3, UNSUPPORTED), self.kinds(result))
        self.assertEqual(result.scalar("name"), "demo")

    def test_document_end_marker_is_a_note(self):
        result = self.parse_block("name: demo\n...\ndescription: still read\n")
        self.assertEqual(self.kinds(result), [(3, UNSUPPORTED)])
        self.assertEqual(result.scalar("description"), "still read")

    def test_complex_key_is_a_note(self):
        self.assertEqual(self.kinds(self.parse_block("name: ? weird\n")),
                         [(2, UNSUPPORTED)])

    def test_unparsable_line_is_an_error_not_a_note(self):
        result = self.parse_block("name: demo\njust some prose\ndescription: kept\n")
        self.assertEqual([(note.line, note.kind) for note in result.errors],
                         [(3, "parse-error")])
        self.assertEqual(result.scalar("description"), "kept")

    def test_missing_space_after_colon_is_an_error(self):
        self.assertEqual([note.line for note in self.parse_block("name:demo\n").errors],
                         [2])

    def test_orphan_indented_line_is_an_error(self):
        result = self.parse_block("name: demo\n  stray: value\n")
        self.assertEqual([note.line for note in result.errors], [3])

    def test_block_list_of_maps_stays_opaque(self):
        # ``arguments:`` in real command files is a list of maps; keep it whole
        # instead of pretending it is a token list.
        result = self.parse_block("arguments:\n  - name: path\n    required: true\n"
                                  "name: demo\n")
        self.assertIn("arguments", result.opaque)
        self.assertNotIn("arguments", result.fields)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.opaque["arguments"].raw,
                         "  - name: path\n    required: true")
        self.assertEqual(result.scalar("name"), "demo")


class DeterminismTestCase(unittest.TestCase):
    SAMPLE = ("---\nname: demo\ndescription: Use when demoing.\nallowed-tools:\n"
              "  - Read\n  - Write\nmetadata:\n  author: someone\nbad: &a x\n"
              "junk line\n---\n\nbody\n")

    def test_same_input_gives_an_equal_result(self):
        self.assertEqual(parse(self.SAMPLE), parse(self.SAMPLE))

    def test_key_order_is_declaration_order(self):
        self.assertEqual(parse(self.SAMPLE).key_order,
                         ["name", "description", "allowed-tools", "metadata", "bad"])

    def test_notes_and_errors_are_both_collected(self):
        result = parse(self.SAMPLE)
        self.assertEqual([note.line for note in result.notes], [9])
        self.assertEqual([note.line for note in result.errors], [10])

    def test_empty_input(self):
        result = parse("")
        self.assertFalse(result.present)
        self.assertEqual(result.body, "")


if __name__ == "__main__":
    unittest.main()
