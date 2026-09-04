"""The lint rule table and the engine that applies it.

``RULES`` is the single source of truth: every check below is registered in it,
and the tests iterate over the table so the set cannot drift.

Facts the rules encode were measured from the official documentation
(code.claude.com/docs/en/skills, fetched 2026-09-04):

* frontmatter is read only when the opening ``---`` is the file's first line, so
  a UTF-8 BOM silently disables the whole block (F001, a real-world incident);
* every field is optional, ``description`` is recommended, ``name`` defaults to
  the directory name (F004, F005);
* ``description`` + ``when_to_use`` truncates at 1,536 characters in listings
  (F012), and command files ignore ``name`` and ``paths`` (F030);
* the Agent Skills open standard (agentskills.io) defines six fields, so any
  other field is a Claude Code extension (F040).
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import frontmatter as fm_mod
from .discovery import Artifact, DiscoveryResult, KIND_COMMAND

ERROR = "error"
WARN = "warn"
INFO = "info"
SEVERITY_ORDER = {ERROR: 0, WARN: 1, INFO: 2}

BOTH = "both"
SKILL_ONLY = "SKILL.md"

RECOGNIZED_FIELDS = ("name", "description", "when_to_use", "argument-hint",
                     "arguments", "disable-model-invocation", "user-invocable",
                     "allowed-tools", "disallowed-tools", "model", "effort",
                     "context", "agent", "background", "hooks", "paths", "shell",
                     "metadata", "license", "compatibility",
                     # "version" is not on the docs field table (2026-09-04) but ships
                     # in official plugin skills and passes `claude plugin validate --strict`.
                     "version")
SPEC_FIELDS = ("name", "description", "license", "compatibility", "metadata",
               "allowed-tools")
COMMAND_IGNORED_FIELDS = ("name", "paths")
BOOLEAN_FIELDS = ("disable-model-invocation", "user-invocable", "background")
BOOLEAN_VALUES = ("true", "false", "yes", "no", "on", "off", "1", "0")

DESCRIPTION_MIN = 20
LISTING_LIMIT = 1536
BODY_LIMIT = 8192
TRIGGER_PHRASES = ("use when", "use this when", "when the user", "when you",
                   "whenever", "trigger", "for when", "invoke when", "call when",
                   "if the user", "use for", "used when", "use this skill",
                   "activates when")
#: Rules the engine drops when style checking is off (``--no-style`` later).
STYLE_RULES = ("F010",)

REFERENCE_DIRS = ("references/", "scripts/")
#: Executable by extension. A .py or .mjs file needs a shebang instead: real
#: bundles keep imported modules (utils.py, __init__.py) in scripts/ too (F021).
SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh")
GLOB_CHARS = "*?"
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


@dataclass(frozen=True)
class Rule:
    code: str
    applies: str
    severity: str
    summary: str


@dataclass
class Diagnostic:
    code: str
    severity: str
    path: str
    line: Optional[int]
    message: str


@dataclass
class Options:
    """Engine switches; the CLI maps flags onto these later."""

    style: bool = True
    portable: bool = False


@dataclass
class Analysis:
    files: List[str] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)


RULES = (
    Rule("F001", BOTH, ERROR, "UTF-8 BOM hides the frontmatter"),
    Rule("F002", BOTH, ERROR, "opening '---' is not the first line, or never closes"),
    Rule("F003", BOTH, ERROR, "frontmatter line cannot be parsed"),
    Rule("F004", SKILL_ONLY, WARN, "'name' does not match the directory name"),
    Rule("F005", BOTH, WARN, "'description' is missing"),
    Rule("F010", BOTH, WARN, "description is too short or has no trigger phrasing"),
    Rule("F011", SKILL_ONLY, WARN, "body is large; move detail into references/"),
    Rule("F012", BOTH, WARN, "description + when_to_use exceeds the listing limit"),
    Rule("F013", BOTH, ERROR, "boolean field has a value Claude Code will not accept"),
    Rule("F020", SKILL_ONLY, ERROR, "referenced bundle file does not exist"),
    Rule("F021", SKILL_ONLY, WARN, "script is not executable"),
    Rule("F030", BOTH, WARN, "unrecognized or ignored frontmatter key"),
    Rule("F040", BOTH, INFO, "uses Claude Code extensions beyond the Agent Skills spec"),
    Rule("F090", BOTH, WARN, "unsupported YAML syntax in frontmatter"),
)
RULES_BY_CODE = {rule.code: rule for rule in RULES}


def _mostly_latin(text: str) -> bool:
    """Judge only near-pure Latin text -- the trigger phrases are English.
    Measured on real Korean command files: they carry enough English nouns to
    clear a 60% bar, so the threshold is strict rather than a majority.
    """
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    return sum(1 for char in letters if not char.isascii()) * 10 < len(letters)


def _has_trigger(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in TRIGGER_PHRASES)


class _Check:
    """Diagnostic sink for one artifact; ``add`` enforces the table's metadata."""

    def __init__(self, artifact: Artifact, fm: fm_mod.Frontmatter,
                 options: Options) -> None:
        self.artifact = artifact
        self.fm = fm
        self.options = options
        self.out = []  # type: List[Diagnostic]

    def add(self, code: str, message: str, line: Optional[int] = None,
            severity: Optional[str] = None) -> None:
        rule = RULES_BY_CODE[code]
        if code in STYLE_RULES and not self.options.style:
            return
        if rule.applies == SKILL_ONLY and not self.artifact.is_skill:
            return
        self.out.append(Diagnostic(code, severity or rule.severity,
                                   str(self.artifact.path), line, message))

    def scalar(self, key: str) -> str:
        return self.fm.scalar(key) or ""


def _structure(check: _Check) -> None:
    fm = check.fm
    if fm.has_bom:
        check.add("F001", "file starts with a UTF-8 BOM, so the frontmatter is "
                          "ignored; save the file without a BOM", 1)
    if fm.late_delimiter is not None:
        check.add("F002", "'---' at line {0} is not the first line, so the "
                          "frontmatter is ignored".format(fm.late_delimiter),
                  fm.late_delimiter)
    elif fm.present and not fm.closed:
        check.add("F002", "frontmatter opened at line 1 is never closed by '---'", 1)
    for note in fm.errors:
        check.add("F003", note.message, note.line)
    for note in fm.notes:
        if note.kind == fm_mod.UNSUPPORTED:
            check.add("F090", note.message, note.line)


def _identity(check: _Check) -> None:
    name = check.scalar("name")
    if check.artifact.is_skill and name and name != check.artifact.name:
        check.add("F004", "name '{0}' does not match directory '{1}'".format(
            name, check.artifact.name), check.fm.line_of("name"))
    if not check.fm.has("description"):
        check.add("F005", "no 'description'; Claude uses it to decide when to "
                          "load this artifact")


def _limits(check: _Check) -> None:
    fm = check.fm
    description = check.scalar("description")
    line = fm.line_of("description")
    if description:
        if len(description) < DESCRIPTION_MIN:
            check.add("F010", "description is {0} characters; say what it does and "
                              "when to use it".format(len(description)), line)
        elif _mostly_latin(description) and not _has_trigger(description):
            check.add("F010", "description has no trigger phrasing such as "
                              "'use when ...'", line)
    combined = len(description) + len(check.scalar("when_to_use"))
    if combined > LISTING_LIMIT:
        check.add("F012", "description + when_to_use is {0} characters; listings "
                          "truncate at {1}".format(combined, LISTING_LIMIT), line)
    size = len(fm.body.encode("utf-8"))
    if size > BODY_LIMIT:
        check.add("F011", "body is {0} bytes; move detail into references/ and "
                          "link to it".format(size), fm.body_start_line)


def _fields(check: _Check) -> None:
    fm = check.fm
    for key in fm.key_order:
        if key not in RECOGNIZED_FIELDS:
            check.add("F030", "'{0}' is not a recognized frontmatter field".format(
                key), fm.line_of(key))
        elif check.artifact.kind == KIND_COMMAND and key in COMMAND_IGNORED_FIELDS:
            check.add("F030", "'{0}' is ignored in command files".format(key),
                      fm.line_of(key))
    for key in BOOLEAN_FIELDS:
        value = check.scalar(key)
        if key in fm.fields and value.lower() not in BOOLEAN_VALUES:
            check.add("F013", "{0}: '{1}' is not a boolean; use one of {2}".format(
                key, value, ", ".join(BOOLEAN_VALUES)), fm.line_of(key))
    extensions = [key for key in fm.key_order
                  if key in RECOGNIZED_FIELDS and key not in SPEC_FIELDS]
    if extensions:
        check.add("F040", "Claude Code extensions beyond the Agent Skills spec: "
                          "{0}".format(", ".join(extensions)), None,
                  WARN if check.options.portable else INFO)


def _referenced_paths(body: str, start_line: int) -> List[Tuple[int, str]]:
    """Relative references/ and scripts/ targets in code spans and link targets."""
    found = []  # type: List[Tuple[int, str]]
    seen = set()  # type: set
    for offset, line in enumerate(body.split("\n")):
        candidates = []  # type: List[str]
        for span in CODE_SPAN_RE.findall(line):
            candidates.extend(span.split())
        candidates.extend(LINK_RE.findall(line))
        for raw in candidates:
            token = raw.strip("\"'`,;:").rstrip(".").split("#")[0]
            token = token[2:] if token.startswith("./") else token
            if token.endswith("/") or any(char in token for char in GLOB_CHARS):
                continue  # a directory or glob mention, not a file reference
            if token.startswith(REFERENCE_DIRS) and token not in seen:
                seen.add(token)
                found.append((start_line + offset, token))
    return found


def _looks_executable_source(path: str, name: str) -> bool:
    if name.endswith(SCRIPT_SUFFIXES):
        return True
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def _bundle(check: _Check) -> None:
    bundle = check.artifact.bundle
    if not check.artifact.is_skill or bundle is None:
        return
    for line, token in _referenced_paths(check.fm.body, check.fm.body_start_line):
        if not os.path.exists(os.path.join(str(bundle), token)):
            check.add("F020", "referenced path '{0}' does not exist in the "
                              "bundle".format(token), line)
    scripts = os.path.join(str(bundle), "scripts")
    if not os.path.isdir(scripts):
        return
    for name in sorted(os.listdir(scripts)):
        path = os.path.join(scripts, name)
        if name.startswith(".") or not os.path.isfile(path):
            continue
        if _looks_executable_source(path, name) and not os.access(path, os.X_OK):
            check.add("F021", "scripts/{0} is not executable; run "
                              "'chmod +x'".format(name))


CHECKS = (_structure, _identity, _limits, _fields, _bundle)


def check_artifact(artifact: Artifact, options: Optional[Options] = None,
                   fm: Optional[fm_mod.Frontmatter] = None) -> List[Diagnostic]:
    """Every diagnostic for one artifact, sorted by line then code."""
    parsed = fm_mod.parse(artifact.text) if fm is None else fm
    check = _Check(artifact, parsed, options or Options())
    for rule_check in CHECKS:
        rule_check(check)
    return sorted(check.out, key=lambda item: (item.line or 0, item.code))


def analyze(result: DiscoveryResult,
            options: Optional[Options] = None) -> Analysis:
    """Run the table over a discovery result; unreadable files stay as notes."""
    analysis = Analysis()
    for artifact in result.artifacts:
        analysis.files.append(str(artifact.path))
        analysis.diagnostics.extend(check_artifact(artifact, options))
    for note in result.notes:
        analysis.files.append(str(note.path))
        analysis.diagnostics.append(
            Diagnostic(note.code, ERROR, str(note.path), None, note.message))
    return analysis
