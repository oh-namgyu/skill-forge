"""Find skill bundles and command files under one or more roots.

Strictly read-only. Two artifact kinds exist (docs: code.claude.com/docs/en/skills,
fetched 2026-09-04):

* skill bundle -- ``<root>/skills/<name>/SKILL.md`` (+ optional ``references/``,
  ``scripts/``)
* command file -- ``<root>/commands/<name>.md``

Order is deterministic: explicit paths in the order given, then each root in the
order given; within a root, skills before commands and names ascending. The
caller decides root precedence (project before personal, for example).
Directories reached through a symlink are never entered; symlinked files are
kept but de-duplicated by real path. Unreadable or non-UTF-8 files become
per-file notes instead of exceptions.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

KIND_SKILL = "skill"
KIND_COMMAND = "command"
SKILL_FILE = "SKILL.md"
SKILLS_DIR = "skills"
COMMANDS_DIR = "commands"
MD_SUFFIX = ".md"

#: Codes for read failures. They are engine diagnostics, not lint rules, so they
#: deliberately live outside the ``rules.RULES`` table.
CODE_UNREADABLE = "F900"
CODE_NOT_UTF8 = "F901"


@dataclass
class Artifact:
    """One discovered SKILL.md or command file, with its text already read."""

    kind: str
    path: Path
    name: str
    root: Path
    bundle: Optional[Path]
    text: str

    @property
    def is_skill(self) -> bool:
        return self.kind == KIND_SKILL


@dataclass
class DiscoveryNote:
    """A file that was found but could not be read."""

    path: Path
    code: str
    message: str


@dataclass
class DiscoveryResult:
    artifacts: List[Artifact] = field(default_factory=list)
    notes: List[DiscoveryNote] = field(default_factory=list)


def _visible(entry: Path) -> bool:
    return not entry.name.startswith(".")


def _is_file(path: Path) -> bool:
    """``Path.is_file`` raises on unreadable parents from 3.12 on; never do that."""
    try:
        return path.is_file()
    except OSError:
        return False


def _listdir(folder: Path) -> List[Path]:
    try:
        return sorted(folder.iterdir(), key=lambda item: item.name)
    except OSError:
        return []


def _read(path: Path) -> Tuple[Optional[str], Optional[DiscoveryNote]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, DiscoveryNote(path, CODE_UNREADABLE,
                                   "cannot read file: {0}".format(exc.strerror or exc))
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, DiscoveryNote(path, CODE_NOT_UTF8,
                                   "file is not valid UTF-8 at byte {0}".format(exc.start))


class _Collector:
    def __init__(self) -> None:
        self.result = DiscoveryResult()
        self._seen = set()  # type: set

    def add(self, kind: str, path: Path, name: str, root: Path,
            bundle: Optional[Path]) -> None:
        try:
            key = (kind, os.path.realpath(str(path)))
        except OSError:
            key = (kind, str(path))
        if key in self._seen:
            return
        self._seen.add(key)
        text, note = _read(path)
        if note is not None:
            self._seen.discard(key)
            self.result.notes.append(note)
            return
        self.result.artifacts.append(
            Artifact(kind=kind, path=path, name=name, root=root, bundle=bundle,
                     text=text or ""))


def _scan_skills(collector: _Collector, root: Path) -> None:
    for bundle in _listdir(root / SKILLS_DIR):
        if not _visible(bundle) or bundle.is_symlink() or not bundle.is_dir():
            continue
        target = bundle / SKILL_FILE
        if _is_file(target):
            collector.add(KIND_SKILL, target, bundle.name, root, bundle)


def _scan_commands(collector: _Collector, root: Path) -> None:
    folder = root / COMMANDS_DIR
    for entry in _listdir(folder):
        if not _visible(entry) or entry.suffix != MD_SUFFIX or not _is_file(entry):
            continue
        collector.add(KIND_COMMAND, entry, entry.stem, root, folder)


def _add_explicit_file(collector: _Collector, path: Path) -> None:
    if path.name == SKILL_FILE:
        bundle = path.parent
        collector.add(KIND_SKILL, path, bundle.name, bundle.parent.parent, bundle)
    elif path.suffix == MD_SUFFIX:
        collector.add(KIND_COMMAND, path, path.stem, path.parent.parent, path.parent)


def _add_explicit_dir(collector: _Collector, path: Path) -> None:
    target = path / SKILL_FILE
    if _is_file(target):
        collector.add(KIND_SKILL, target, path.name, path.parent.parent, path)
        return
    _scan_skills(collector, path)
    _scan_commands(collector, path)


def discover(roots: Sequence[Path] = (),
             paths: Sequence[Path] = ()) -> DiscoveryResult:
    """Collect artifacts from explicit paths first, then from each root."""
    collector = _Collector()
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            _add_explicit_dir(collector, path)
        elif _is_file(path):
            _add_explicit_file(collector, path)
        else:
            collector.result.notes.append(
                DiscoveryNote(path, CODE_UNREADABLE, "path does not exist"))
    for raw in roots:
        root = Path(raw)
        _scan_skills(collector, root)
        _scan_commands(collector, root)
    return collector.result


def counts_by_kind(result: DiscoveryResult) -> Dict[str, int]:
    tally = {KIND_SKILL: 0, KIND_COMMAND: 0}
    for artifact in result.artifacts:
        tally[artifact.kind] = tally.get(artifact.kind, 0) + 1
    return tally
