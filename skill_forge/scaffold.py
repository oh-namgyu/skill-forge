"""Create a new skill bundle or command file without ever overwriting one.

The whole artifact is built inside a ``.skill-forge-tmp-*`` directory in the
same parent, then installed with a single atomic call: ``os.rename`` for a
bundle directory, ``os.link`` for a single command file (plain ``rename``
replaces an existing file silently, which is exactly what must not happen).
The kernel's own EEXIST/ENOTEMPTY is therefore the existence gate -- there is no
check-then-write window. A failed install leaves the target untouched and
removes the temporary directory.

One documented exception: POSIX ``rename`` may replace an *empty* directory, so
an empty ``skills/<name>/`` left behind by something else is taken over.
"""

import os
import re
import shutil
import tempfile
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
NAME_RULE = ("names must match [a-z0-9][a-z0-9_-]{0,63}: lowercase letters, "
             "digits, '-' and '_', no dots and no path separators")
TEMP_PREFIX = ".skill-forge-tmp-"
BUNDLE_MODE = 0o755

SKILL_MD = """---
name: {name}
description: One line on what {name} does. Use when the user asks for that task.
# when_to_use: Extra trigger detail that does not fit the description. Uncomment to use.
---

# {name}

One paragraph on what this skill does and what it leaves behind.

## Steps

1. Restate the goal in one sentence.
2. Do the work.
3. Report what changed.

## References

Keep long material in `references/example.md` and link to it, so this file stays
small and Claude only reads the detail when it is needed.

## Scripts

Executable helpers belong in `scripts/`; `scripts/README.md` explains the rules.
"""

COMMAND_MD = """---
description: One line on what {name} does. Use when the user asks for that task.
---

# {name}

One paragraph on what this command does and what it leaves behind.

## Steps

1. Restate the goal in one sentence.
2. Do the work.
3. Report what changed.
"""

REFERENCE_MD = """# Example reference

Move the long material here: schemas, tables, edge cases, worked examples.

Link to this file from `SKILL.md` so it is loaded only when the skill needs it.
Delete this file once you have real references, and drop the link with it.
"""

SCRIPTS_MD = """# Scripts

Executable helpers live in this directory.

Give each one a shebang (`#!/usr/bin/env python3`, `#!/bin/sh`) and run
`chmod +x` on it, or Claude Code cannot run it. Delete this file once you add a
real script.
"""


class ScaffoldError(Exception):
    """A refusal to create something; ``exit_code`` is what the CLI returns."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def validate_name(name: str) -> None:
    """Reject anything that is not a plain artifact name, before any file I/O."""
    if not NAME_RE.match(name or ""):
        raise ScaffoldError("invalid name '{0}': {1}".format(name, NAME_RULE), 2)


def target_for(name: str, root: Path, command: bool = False) -> Path:
    parent = Path(root) / ("commands" if command else "skills")
    target = parent / (name + ".md" if command else name)
    absolute = os.path.abspath(str(target))
    if os.path.dirname(absolute) != os.path.abspath(str(parent)):
        raise ScaffoldError("refusing to write outside {0}".format(parent), 2)
    return target


def _fill(tmp: Path, name: str, command: bool) -> None:
    if command:
        (tmp / (name + ".md")).write_text(COMMAND_MD.format(name=name),
                                          encoding="utf-8")
        return
    (tmp / "SKILL.md").write_text(SKILL_MD.format(name=name), encoding="utf-8")
    (tmp / "references").mkdir()
    (tmp / "references" / "example.md").write_text(REFERENCE_MD, encoding="utf-8")
    (tmp / "scripts").mkdir()
    (tmp / "scripts" / "README.md").write_text(SCRIPTS_MD, encoding="utf-8")


def _install(tmp: Path, target: Path, command: bool) -> None:
    """The atomic step: the kernel decides whether the target already exists."""
    try:
        if command:
            os.link(str(tmp / target.name), str(target))
        else:
            os.chmod(str(tmp), BUNDLE_MODE)
            os.rename(str(tmp), str(target))
    except OSError as exc:
        raise ScaffoldError("cannot create {0}: {1}".format(
            target, exc.strerror or exc))


def create(name: str, root: Path, command: bool = False) -> Path:
    """Create ``skills/<name>/`` or ``commands/<name>.md`` under ``root``."""
    validate_name(name)
    target = target_for(name, root, command)
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=str(parent)))
    except OSError as exc:
        raise ScaffoldError("cannot use {0}: {1}".format(
            parent, exc.strerror or exc))
    try:
        _fill(tmp, name, command)
        _install(tmp, target, command)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return target
