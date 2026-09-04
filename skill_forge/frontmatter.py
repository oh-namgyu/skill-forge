"""Deterministic line grammar for SKILL.md / command frontmatter.

This is not a YAML parser. Claude Code reads frontmatter only when the opening
``---`` is the very first line of the file (docs: code.claude.com/docs/en/skills,
fetched 2026-09-04), and every field it recognises is a scalar, a token list or
an opaque nested map. So the grammar handled here is exactly:

``key: scalar`` (quoted or bare; ``#`` is part of the value, never a comment) --
``key:`` followed by indented ``- item`` lines -- ``key: [a, b]`` inline lists --
``metadata:`` / ``hooks:`` (and any key followed by deeper ``key:`` lines) kept
as an opaque raw block.

Anything else -- anchors, aliases, ``?`` keys, ``|``/``>`` block scalars, tabs in
indentation, stray document markers -- produces a line-numbered
``unsupported-syntax`` note and parsing continues with the next line. The same
input always produces an equal ``Frontmatter``.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

BOM = "﻿"
DELIMITER = "---"
OPAQUE_KEYS = ("metadata", "hooks")
UNSUPPORTED = "unsupported-syntax"
DUPLICATE = "duplicate-key"
LATE_DELIMITER_WINDOW = 10

KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.\-]*):(?:[ \t](.*))?$")
BLOCK_SCALAR_RE = re.compile(r"^[|>][-+0-9]*$")


@dataclass
class Note:
    """A line-numbered parser remark (``errors`` are fatal for that line only)."""

    line: int
    kind: str
    message: str


@dataclass
class Field:
    key: str
    line: int
    raw: str
    value: Union[str, List[str]]
    is_list: bool


@dataclass
class OpaqueBlock:
    key: str
    line: int
    raw: str


@dataclass
class Frontmatter:
    present: bool = False
    has_bom: bool = False
    closed: bool = False
    late_delimiter: Optional[int] = None
    fields: Dict[str, Field] = field(default_factory=dict)
    opaque: Dict[str, OpaqueBlock] = field(default_factory=dict)
    key_order: List[str] = field(default_factory=list)
    errors: List[Note] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)
    body: str = ""
    body_start_line: int = 1

    def scalar(self, key: str) -> Optional[str]:
        item = self.fields.get(key)
        if item is None or item.is_list:
            return None
        return item.value  # type: ignore[return-value]

    def has(self, key: str) -> bool:
        return key in self.fields or key in self.opaque

    def line_of(self, key: str) -> Optional[int]:
        if key in self.fields:
            return self.fields[key].line
        if key in self.opaque:
            return self.opaque[key].line
        return None


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _indent(text: str) -> str:
    return text[:len(text) - len(text.lstrip(" \t"))]


def _inline_list(raw: str) -> List[str]:
    inner = raw[1:-1].strip()
    if not inner:
        return []
    return [_unquote(part.strip()) for part in inner.split(",") if part.strip()]


def _split(text: str) -> List[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _find_close(lines: Sequence[str]) -> Optional[int]:
    for index in range(1, len(lines)):
        if lines[index] == DELIMITER:
            return index
    return None


def _late_delimiter(lines: Sequence[str]) -> Optional[int]:
    """Line number of a ``---`` that looks like frontmatter placed too late."""
    if lines and lines[0].strip() == DELIMITER and lines[0] != DELIMITER:
        return 1
    for index, text in enumerate(lines[:LATE_DELIMITER_WINDOW]):
        if not text.strip():
            continue
        if index > 0 and text.strip() == DELIMITER:
            return index + 1
        return None
    return None


class _Parser:
    def __init__(self, block: List[Tuple[int, str]], result: Frontmatter) -> None:
        self.block = block
        self.result = result
        self.index = 0

    def note(self, line: int, kind: str, message: str) -> None:
        self.result.notes.append(Note(line, kind, message))

    def error(self, line: int, message: str) -> None:
        self.result.errors.append(Note(line, "parse-error", message))

    def register(self, key: str, line: int) -> bool:
        if self.result.has(key):
            self.note(line, DUPLICATE, "duplicate key '{0}'".format(key))
            return False
        self.result.key_order.append(key)
        return True

    def set_field(self, key: str, line: int, raw: str,
                  value: Union[str, List[str]], is_list: bool) -> None:
        if self.register(key, line):
            self.result.fields[key] = Field(key, line, raw, value, is_list)

    def set_opaque(self, key: str, line: int, raw: str) -> None:
        if self.register(key, line):
            self.result.opaque[key] = OpaqueBlock(key, line, raw)

    def take_indented(self) -> List[Tuple[int, str]]:
        """Consume the indented (or blank) run that follows the current line."""
        taken = []  # type: List[Tuple[int, str]]
        while self.index < len(self.block):
            _, text = self.block[self.index]
            if text.strip() and not _indent(text):
                break
            taken.append(self.block[self.index])
            self.index += 1
        while taken and not taken[-1][1].strip():
            self.index -= 1
            taken.pop()
        return taken

    def peek_indented(self) -> Optional[str]:
        for _, text in self.block[self.index:]:
            if not text.strip():
                continue
            return text if _indent(text) else None
        return None

    def run(self) -> None:
        for lineno, text in self.block:  # tabs can hide inside consumed runs
            if "\t" in _indent(text):
                self.note(lineno, UNSUPPORTED, "tab used for indentation")
        while self.index < len(self.block):
            lineno, text = self.block[self.index]
            self.index += 1
            self.handle(lineno, text)

    def handle(self, lineno: int, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        if stripped.startswith("#"):
            return
        if stripped in (DELIMITER, "..."):
            self.note(lineno, UNSUPPORTED, "stray document marker inside frontmatter")
            return
        if _indent(text):
            self.error(lineno, "unexpected indentation")
            return
        match = KEY_RE.match(text)
        if match is None:
            self.error(lineno, "line is not 'key: value'")
            return
        self.handle_key(lineno, match.group(1), (match.group(2) or "").strip())

    def handle_key(self, lineno: int, key: str, raw: str) -> None:
        if key in OPAQUE_KEYS:
            self.set_opaque(key, lineno, self.capture(raw))
            return
        if not raw:
            self.handle_empty(lineno, key)
            return
        if raw.startswith("["):
            if raw.endswith("]"):
                self.set_field(key, lineno, raw, _inline_list(raw), True)
            else:
                self.note(lineno, UNSUPPORTED, "unterminated inline list")
                self.set_field(key, lineno, raw, raw, False)
            return
        if raw.startswith("{"):
            self.set_opaque(key, lineno, raw)
            return
        if BLOCK_SCALAR_RE.match(raw):
            self.note(lineno, UNSUPPORTED, "block scalar '{0}' is not read".format(raw))
            self.set_opaque(key, lineno, self.capture(raw))
            return
        if raw[0] in "&*?":
            self.note(lineno, UNSUPPORTED, "anchor, alias or complex key")
        self.set_field(key, lineno, raw, _unquote(raw), False)

    def capture(self, raw: str) -> str:
        rows = [row for _, row in self.take_indented()]
        return "\n".join([raw] + rows) if raw else "\n".join(rows)

    def handle_empty(self, lineno: int, key: str) -> None:
        ahead = self.peek_indented()
        if ahead is None:
            self.set_field(key, lineno, "", "", False)
            return
        head = ahead.strip()
        if head == "-" or head.startswith("- "):
            rows = self.take_indented()
            items = []  # type: List[str]
            for _, row in rows:
                body = row.strip()
                if body and not body.startswith("-"):
                    # a list of maps (``arguments:`` uses this): stay opaque
                    self.set_opaque(key, lineno, "\n".join(one for _, one in rows))
                    return
                if body:
                    items.append(_unquote(body[1:].strip()))
            self.set_field(key, lineno, "", items, True)
            return
        rows = self.take_indented()
        joined = " ".join(row.strip() for _, row in rows if row.strip())
        if head.startswith("["):  # a flow sequence spread over several lines
            if joined.endswith("]"):
                self.set_field(key, lineno, joined, _inline_list(joined), True)
            else:
                self.note(lineno, UNSUPPORTED, "unterminated inline list")
                self.set_field(key, lineno, joined, joined, False)
            return
        if KEY_RE.match(head) is not None:
            self.set_opaque(key, lineno, "\n".join(row for _, row in rows))
            return
        # a plain or quoted scalar continued over several lines: YAML folds it
        self.set_field(key, lineno, joined, _unquote(joined), False)


def parse(text: str) -> Frontmatter:
    """Parse frontmatter out of a file's text; never raises."""
    result = Frontmatter()
    if text.startswith(BOM):
        result.has_bom = True
        text = text[len(BOM):]
    lines = _split(text)
    if not lines or lines[0] != DELIMITER:
        result.body = text
        result.body_start_line = 1
        if not result.has_bom:
            result.late_delimiter = _late_delimiter(lines)
        return result
    result.present = True
    close = _find_close(lines)
    end = len(lines) if close is None else close
    block = [(index + 1, lines[index]) for index in range(1, end)]
    _Parser(block, result).run()
    if close is None:
        result.body_start_line = len(lines) + 1
        return result
    result.closed = True
    result.body = "\n".join(lines[close + 1:])
    result.body_start_line = close + 2
    return result
