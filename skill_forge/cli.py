"""``skill-forge`` command line: lint, list, new.

Default roots are the project's ``./.claude`` first, then the personal config
directory (``$CLAUDE_CONFIG_DIR`` or ``~/.claude``) -- the order Claude Code
itself resolves in. ``new`` deliberately does *not* fall back to the personal
directory: writing into someone's own config uninvited is rude, so it asks for
``--dir`` instead.
"""

import argparse
import json
import os
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import __version__, scaffold
from .discovery import discover
from .frontmatter import parse
from .report import counts_by_severity, format_text, summary_line, to_json
from .rules import ERROR, INFO, WARN, Options, analyze

ENV_CONFIG_DIR = "CLAUDE_CONFIG_DIR"
PROJECT_DIR = ".claude"
DESCRIPTION_WIDTH = 52
BADGES = ((ERROR, "E"), (WARN, "W"), (INFO, "I"))


def config_dir() -> Path:
    """The personal config directory, honouring ``CLAUDE_CONFIG_DIR``."""
    override = os.environ.get(ENV_CONFIG_DIR)
    return Path(override).expanduser() if override else Path.home() / PROJECT_DIR


def default_roots() -> List[Path]:
    roots = []  # type: List[Path]
    project = Path.cwd() / PROJECT_DIR
    if project.is_dir():
        roots.append(project)
    personal = config_dir()
    if personal.is_dir() and os.path.realpath(str(personal)) not in [
            os.path.realpath(str(root)) for root in roots]:
        roots.append(personal)
    return roots


def _short(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home) else text


def _use_color(args: argparse.Namespace) -> bool:
    if args.no_color or os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _exit_code(diagnostics: Sequence) -> int:
    tally = counts_by_severity(diagnostics)
    if tally[ERROR]:
        return 2
    return 1 if tally[WARN] else 0


def _resolve(paths: Sequence[str]) -> Optional[Dict[str, List[Path]]]:
    """Explicit paths win; otherwise fall back to the default roots."""
    if paths:
        return {"roots": [], "paths": [Path(item) for item in paths]}
    roots = default_roots()
    if not roots:
        return None
    return {"roots": roots, "paths": []}


def _no_targets() -> int:
    sys.stderr.write("skill-forge: no ./{0} here and no personal config "
                     "directory; pass a path\n".format(PROJECT_DIR))
    return 2


def _lint(args: argparse.Namespace) -> int:
    targets = _resolve(args.paths)
    if targets is None:
        return _no_targets()
    result = discover(roots=targets["roots"], paths=targets["paths"])
    analysis = analyze(result, Options(style=not args.no_style,
                                       portable=args.portable))
    if args.json:
        json.dump(to_json(analysis), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_text(analysis, color=_use_color(args),
                                     quiet=args.quiet))
    sys.stderr.write("scanned {0} file(s)\n".format(len(analysis.files)))
    return _exit_code(analysis.diagnostics)


def _badges(diagnostics: Sequence) -> str:
    tally = counts_by_severity(diagnostics)
    parts = ["{0}{1}".format(tally[key], mark) for key, mark in BADGES if tally[key]]
    return " ".join(parts) if parts else "-"


def _width(text: str) -> int:
    """Display columns, so Korean and Japanese names still line up."""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1
               for char in text)


def _clip(text: str, limit: int) -> str:
    if _width(text) <= limit:
        return text
    kept, used = [], 0
    for char in text:
        if used + _width(char) > limit - 3:
            break
        kept.append(char)
        used += _width(char)
    return "".join(kept) + "..."


def _rows(result, analysis) -> List[List[str]]:
    grouped = {}  # type: Dict[str, List]
    for item in analysis.diagnostics:
        grouped.setdefault(item.path, []).append(item)
    rows = [["NAME", "KIND", "ROOT", "DESCRIPTION", "DIAGNOSTICS"]]
    for artifact in result.artifacts:
        text = (parse(artifact.text).scalar("description") or "").strip()
        rows.append([artifact.name, artifact.kind, _short(artifact.root),
                     _clip(text.split("\n")[0], DESCRIPTION_WIDTH) or "-",
                     _badges(grouped.get(str(artifact.path), []))])
    return rows


def _table(rows: Sequence[Sequence[str]]) -> str:
    widths = [max(_width(row[column]) for row in rows)
              for column in range(len(rows[0]))]
    lines = []
    for row in rows:
        cells = [row[index] + " " * (widths[index] - _width(row[index]))
                 for index in range(len(row) - 1)]
        lines.append("  ".join(cells + [row[-1]]).rstrip())
    return "\n".join(lines) + "\n"


def _list(args: argparse.Namespace) -> int:
    targets = _resolve(args.roots)
    if targets is None:
        return _no_targets()
    result = discover(roots=targets["roots"], paths=targets["paths"])
    analysis = analyze(result)
    if not result.artifacts:
        sys.stderr.write("skill-forge: no skills or commands found\n")
        return 0
    sys.stdout.write(_table(_rows(result, analysis)))
    sys.stderr.write("{0}\n".format(summary_line(analysis.diagnostics,
                                                 len(analysis.files))))
    return 0


def _new_root(args: argparse.Namespace) -> Path:
    if args.dir:
        return Path(args.dir)
    project = Path.cwd() / PROJECT_DIR
    if project.is_dir():
        return project
    raise scaffold.ScaffoldError(
        "no ./{0} here; pass --dir DIR (it is not written to your personal "
        "config directory unless you name it)".format(PROJECT_DIR), 2)


def _new(args: argparse.Namespace) -> int:
    try:
        scaffold.validate_name(args.name)
        target = scaffold.create(args.name, _new_root(args), command=args.command)
    except scaffold.ScaffoldError as exc:
        sys.stderr.write("skill-forge: {0}\n".format(exc))
        return exc.exit_code
    sys.stdout.write("{0}\n".format(target))
    sys.stderr.write("created; check it with: python3 -m skill_forge lint {0}\n".format(
        target))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-forge",
        description="Scaffold and lint Claude Code skills and commands.")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    lint = subparsers.add_parser("lint", help="check skills and commands")
    lint.add_argument("paths", nargs="*", help="files or directories to check")
    lint.add_argument("--json", action="store_true", help="machine-readable output")
    lint.add_argument("--no-color", action="store_true", help="never colourise")
    lint.add_argument("--no-style", action="store_true",
                      help="drop the style heuristics (F010)")
    lint.add_argument("--portable", action="store_true",
                      help="treat Claude Code extensions as warnings (F040)")
    lint.add_argument("--quiet", action="store_true", help="hide files with no findings")
    lint.set_defaults(handler=_lint)

    catalog = subparsers.add_parser("list", help="catalog what is installed")
    catalog.add_argument("roots", nargs="*", help="root directories to scan")
    catalog.set_defaults(handler=_list)

    new = subparsers.add_parser("new", help="scaffold a new skill or command")
    new.add_argument("name", help="lowercase name, e.g. release-notes")
    new.add_argument("--command", action="store_true",
                     help="create commands/<name>.md instead of a skill bundle")
    new.add_argument("--dir", help="root directory to create it in (default ./.claude)")
    new.set_defaults(handler=_new)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Return the process exit code: 0 clean, 1 warnings, 2 errors or usage."""
    args = build_parser().parse_args(argv)
    return args.handler(args)
