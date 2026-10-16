# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-04

Initial public release.

### Added

- `python -m skill_forge lint [paths...]` checks Claude Code skills
  (`SKILL.md`) and commands (`commands/*.md`) against 14 rules, F001-F090,
  for frontmatter that Claude Code silently ignores (a UTF-8 BOM, a misplaced
  or unclosed `---`, unparseable lines), weak or oversized descriptions,
  oversized bodies, missing referenced files, scripts without an execute bit,
  invalid boolean values, unrecognized keys, portability beyond the Agent
  Skills spec and YAML features the linter does not interpret. Unreadable
  files and invalid UTF-8 are reported as F900 and F901.
- `lint` options: `--json` (stable JSON schema), `--quiet`, `--no-style`,
  `--portable` and `--no-color` (`NO_COLOR` is honoured).
- `python -m skill_forge list [roots...]` catalogs installed skills and
  commands with their findings.
- `python -m skill_forge new <name>` scaffolds a skill bundle, or a command
  file with `--command`. Names are validated, the result is installed with one
  atomic call into the given root, and an existing artifact is never
  overwritten. The template passes `lint` with every rule enabled.
- With no paths, `lint` and `list` scan `./.claude` and then
  `$CLAUDE_CONFIG_DIR` or `~/.claude`.
- Exit codes `0` (clean), `1` (warnings only) and `2` (errors or usage
  error).
- Standard library only, Python 3.9+, no network access.
