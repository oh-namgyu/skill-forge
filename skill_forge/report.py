"""Render an ``Analysis`` as grouped text or as a stable JSON structure.

Text output is one diagnostic per line, ``path:line [CODE] message``, grouped by
file in discovery order with a summary last. Colour is opt-in: the engine takes
a boolean and the CLI decides whether the stream is a tty.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .rules import (ERROR, INFO, SEVERITY_ORDER, WARN, Analysis, Diagnostic)

SCHEMA_VERSION = 1
RESET = "\033[0m"
COLORS = {ERROR: "\033[31m", WARN: "\033[33m", INFO: "\033[36m"}
PLURALS = ((ERROR, "errors"), (WARN, "warnings"), (INFO, "infos"))


def counts_by_code(diagnostics: Iterable[Diagnostic]) -> Dict[str, int]:
    tally = {}  # type: Dict[str, int]
    for item in diagnostics:
        tally[item.code] = tally.get(item.code, 0) + 1
    return tally


def counts_by_severity(diagnostics: Iterable[Diagnostic]) -> Dict[str, int]:
    tally = {ERROR: 0, WARN: 0, INFO: 0}
    for item in diagnostics:
        tally[item.severity] = tally.get(item.severity, 0) + 1
    return tally


def group_by_file(analysis: Analysis) -> List[Dict[str, Any]]:
    """One entry per discovered file, in discovery order, diagnostics sorted."""
    grouped = {path: [] for path in analysis.files}  # type: Dict[str, List[Diagnostic]]
    order = list(analysis.files)
    for item in analysis.diagnostics:
        if item.path not in grouped:
            grouped[item.path] = []
            order.append(item.path)
        grouped[item.path].append(item)
    entries = []  # type: List[Dict[str, Any]]
    for path in order:
        items = sorted(grouped[path],
                       key=lambda one: (one.line or 0,
                                        SEVERITY_ORDER.get(one.severity, 9), one.code))
        entries.append({"path": path, "diagnostics": items})
    return entries


def _paint(text: str, severity: str, color: bool) -> str:
    if not color:
        return text
    return "{0}{1}{2}".format(COLORS.get(severity, ""), text, RESET)


def format_diagnostic(item: Diagnostic, color: bool = False) -> str:
    where = item.path if item.line is None else "{0}:{1}".format(item.path, item.line)
    tag = _paint("[{0}]".format(item.code), item.severity, color)
    return "{0} {1} {2}".format(where, tag, item.message)


def summary_line(diagnostics: Sequence[Diagnostic], files: int) -> str:
    tally = counts_by_severity(diagnostics)
    parts = ["{0} {1}".format(tally[key], label) for key, label in PLURALS]
    noun = "file" if files == 1 else "files"
    return "{0} {1} checked: {2}".format(files, noun, ", ".join(parts))


def format_text(analysis: Analysis, color: bool = False,
                quiet: bool = False) -> str:
    """Grouped text report; ``quiet`` hides files that have no diagnostics."""
    lines = []  # type: List[str]
    for entry in group_by_file(analysis):
        items = entry["diagnostics"]
        if not items:
            if not quiet:
                lines.append("{0}: ok".format(entry["path"]))
            continue
        for item in items:
            lines.append(format_diagnostic(item, color))
    lines.append(summary_line(analysis.diagnostics, len(group_by_file(analysis))))
    return "\n".join(lines) + "\n"


def to_json(analysis: Analysis) -> Dict[str, Any]:
    """Stable schema: {version, files:[{path, diagnostics}], summary}."""
    tally = counts_by_severity(analysis.diagnostics)
    files = []  # type: List[Dict[str, Any]]
    for entry in group_by_file(analysis):
        files.append({
            "path": entry["path"],
            "diagnostics": [_diagnostic_json(item) for item in entry["diagnostics"]],
        })
    return {
        "version": SCHEMA_VERSION,
        "files": files,
        "summary": {"errors": tally[ERROR], "warnings": tally[WARN],
                    "infos": tally[INFO]},
    }


def _diagnostic_json(item: Diagnostic) -> Dict[str, Optional[Any]]:
    return {"code": item.code, "severity": item.severity, "line": item.line,
            "message": item.message}
