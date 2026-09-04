# skill-forge

Scaffold, lint and catalog Claude Code skills and commands — the failures that never print an error.

## 한눈 요약

- `SKILL.md` 와 `commands/*.md` 의 **조용한 실패**를 잡아내는 CLI 입니다. Claude Code 는 프론트매터를 못 읽어도 아무 말 없이 그냥 넘어갑니다.
- 대표 사례: 파일 맨 앞의 **BOM 한 글자** 때문에 프론트매터 전체가 무시됩니다. 로그도, 경고도 없습니다.
- 설치할 것이 없습니다. **Python 3.9 이상, 외부 의존성 0개** (표준 라이브러리만).
- 세 가지 명령: `lint` (14개 규칙 검사) / `list` (설치된 스킬·커맨드 목록) / `new` (새 스킬 뼈대 생성, 덮어쓰기 절대 없음).
- 읽기 전용입니다. 파일을 만드는 건 `new` 뿐이고, 그것도 지정한 폴더 안에만. 네트워크 접속은 없습니다.
- 바로 실행: `python3 -m skill_forge lint` → `./.claude` 와 `~/.claude` 를 검사합니다.
- 규칙표(F001~F090)가 이 문서의 핵심입니다. 아래 **Rules reference** 를 보세요.

## What it is

Claude Code loads a skill from `skills/<name>/SKILL.md` and a command from `commands/<name>.md`.
Both read their configuration from YAML frontmatter — and when that frontmatter cannot be read, the
artifact still loads. Silently. With empty metadata. Your skill is installed, listed, and never
triggered, and nothing anywhere says why.

skill-forge is a linter for exactly that class of failure, plus a scaffolder that starts you from a
file which already passes every rule.

```
$ python3 -m skill_forge lint
~/.claude/skills/release-notes/SKILL.md:1 [F001] file starts with a UTF-8 BOM, so the frontmatter is ignored; save the file without a BOM
~/.claude/skills/release-notes/SKILL.md:3 [F010] description has no trigger phrasing such as 'use when ...'
~/.claude/skills/release-notes/SKILL.md:41 [F020] referenced path 'references/format.md' does not exist in the bundle
3 files checked: 1 errors, 2 warnings, 0 infos
```

## Why

**The BOM story.** A skill stops working. The file looks perfect: the first line is `---`, the
frontmatter is valid YAML, the description is good. But an editor saved it UTF-8-with-BOM, so the
first line is not `---` — it is `﻿---`. Claude Code reads frontmatter *only* when the opening
`---` is the file's first line, the byte-order mark breaks that check, and the entire block is
dropped without a message. You cannot see it. `cat` will not show it. Rule **F001** exists because
of that afternoon.

The same shape of failure has several other causes: a blank line above the `---`, an unclosed
block, one line of not-quite-YAML. Every one of them ends the same way — a skill that loads with
empty metadata and never triggers.

**Trigger quality.** The second failure mode is not silent, it is invisible: the frontmatter parses,
but `description` says *what the skill is* instead of *when to use it*, so the model never picks it.
The docs recommend writing the trigger into the description; **F010** checks that you did, and
**F012** checks that the description plus `when_to_use` fits the 1,536-character listing limit.

## Quickstart

Requires **Python 3.9+**. There are **no dependencies** — standard library only.

```sh
git clone https://github.com/oh-namgyu/skill-forge.git
cd skill-forge
python3 -m skill_forge lint          # check ./.claude then ~/.claude
python3 -m skill_forge list          # catalog what is installed
python3 -m skill_forge new my-skill  # scaffold ./.claude/skills/my-skill/
```

With no paths, `lint` and `list` scan the project's `./.claude` first and the personal config
directory second — `$CLAUDE_CONFIG_DIR` if set, otherwise `~/.claude` — the same order Claude Code
resolves in. Pass any file or directory to check just that.

## Commands

| Command | What it does |
| --- | --- |
| `lint [paths...]` | Check skills and commands. Paths may be files, bundle directories or roots. |
| `list [roots...]` | Table of name, kind, root, description and findings per artifact. |
| `new <name> [--command] [--dir DIR]` | Scaffold a skill bundle, or a single command file with `--command`. |

| Flag (`lint`) | Effect |
| --- | --- |
| `--json` | Stable JSON on stdout: `{version, files:[{path, diagnostics}], summary}`. |
| `--quiet` | Hide files with no findings. |
| `--no-style` | Drop the style heuristic (F010). |
| `--portable` | Raise the portability notice (F040) from info to warning. |
| `--no-color` | Never colourise. Colour is off by default unless stdout is a tty (and `NO_COLOR` is respected). |

**Exit codes:** `0` clean (infos allowed) · `1` warnings only · `2` any error, or a usage error.
The report goes to stdout, progress and summary counts to stderr.

`new` writes nothing outside the root you give it. Names must match
`[a-z0-9][a-z0-9_-]{0,63}` — anything with a dot, a slash or an uppercase letter is refused before
a single byte is written. The artifact is built in a temporary directory and installed with one
atomic call, so an existing skill is never overwritten, never partially replaced, and never left
half-written if the tool dies mid-run. With no `--dir` it uses `./.claude` and, if that does not
exist, it asks for `--dir` rather than writing into your personal config directory uninvited.

The generated skill passes `lint` with every rule enabled, including the style heuristics. That is
a test, not a promise: the suite fails if the template ever stops linting clean.

## Rules reference

Fourteen rules. `SKILL.md`-only rules never fire on command files.

| Code | Applies to | Severity | What it means |
| --- | --- | --- | --- |
| **F001** | both | error | The file starts with a UTF-8 BOM. The opening `---` is therefore not the first line and the whole frontmatter is ignored at runtime. |
| **F002** | both | error | The opening `---` is not on line 1 (a blank line or indentation above it), or the frontmatter is never closed. A file with *no* frontmatter is not F002 — every field is optional. |
| **F003** | both | error | A frontmatter line cannot be parsed, with its line number. At runtime this drops every field silently. |
| **F004** | SKILL.md | warn | `name` is present but differs from the directory name. Absent `name` is fine — it defaults to the directory. |
| **F005** | both | warn | No `description`. It is the text Claude uses to decide whether to load the artifact at all. |
| **F010** | both | warn | Trigger quality: the description is under 20 characters, or has no trigger phrasing ("use when", "when the user", "trigger"…). Heuristic, English-only — non-Latin descriptions are only length-checked. Disable with `--no-style`. |
| **F011** | SKILL.md | warn | The body is over 8 KB. Move detail into `references/` and link to it so it is read only when needed. |
| **F012** | both | warn | `description` + `when_to_use` exceeds 1,536 characters, the point at which listings truncate. |
| **F013** | both | error | A boolean field (`disable-model-invocation`, `user-invocable`, `background`) holds something outside `true/false/yes/no/on/off/1/0`. |
| **F020** | SKILL.md | error | A `references/…` or `scripts/…` path referenced from the body does not exist. Only backtick code spans and markdown link targets count; prose mentions, globs and bare directories are ignored. |
| **F021** | SKILL.md | warn | A file in `scripts/` has no execute bit. Shell suffixes always count; `.py`/`.mjs` files need a shebang, so imported modules are not flagged. |
| **F030** | both | warn | A key outside the 21 recognized fields (incl. `version`, shipped in official plugin skills) (typo detection), or `name`/`paths` in a command file, where both are ignored. |
| **F040** | both | info | The artifact uses Claude Code extensions beyond the six-field Agent Skills spec. `--portable` raises this to a warning. |
| **F090** | both | warn | Frontmatter uses YAML this linter deliberately does not interpret: anchors, aliases, `\|`/`>` block scalars, tabs for indentation, stray document markers. |

Two more codes come from reading rather than linting: **F900** (unreadable file) and **F901** (not
valid UTF-8). They are reported as errors per file and never stop the run.

## skill-forge vs `claude plugin validate`

They do different jobs, and using both is the right answer.

`claude plugin validate` is the official validator and the authority on what the runtime accepts. It
validates a **plugin manifest** and the skills inside that plugin, so it needs a
`.claude-plugin/plugin.json`: pointed at a plain `~/.claude` or at a bare skill bundle it exits 1
with *"No manifest found in directory"*. On a real plugin it reports missing frontmatter blocks and
YAML parse failures.

Measured side by side (Claude Code 2.1.227) on one plugin with three deliberately broken skills — a
BOM'd file, a `---` pushed to line 2, and an unparsable frontmatter line:

| Broken file | `claude plugin validate` | skill-forge |
| --- | --- | --- |
| BOM before `---` | warning: *no frontmatter block found* | **F001** error, naming the BOM as the cause |
| `---` on line 2 | warning: *no frontmatter block found* | **F002** error, naming the line, plus F005 |
| unparsable line | error: *YAML frontmatter failed to parse* | **F003** error with the line number, plus F005 |

No disagreement on detection: both tools flagged all three. The differences are that skill-forge
tells you *which* of the three causes you hit, treats all three as errors, and needs no manifest —
and that on the same run it also reported oversized bodies, missing referenced files, unrecognized
keys and weak descriptions, which validation does not cover.

Use `claude plugin validate` to confirm a plugin will package and load. Use skill-forge while you
are authoring, in a repo that has no plugin manifest, or when you want the quality checks.

## Portability

The [Agent Skills](https://agentskills.io) open standard defines six frontmatter fields: `name`,
`description`, `license`, `compatibility`, `metadata`, `allowed-tools`. Everything else Claude Code
accepts — `when_to_use`, `model`, `agent`, `hooks`, `paths`, `argument-hint` and the rest — is a
Claude Code extension.

That is fine, and F040 is only an info notice by default. If you intend a skill to run on other
Agent Skills hosts, run `lint --portable` and every extension becomes a warning you can act on.

## Development

```sh
python3 -m unittest discover -s tests
```

180 tests, standard library only, on Python 3.9 through 3.12. Fixtures are synthetic temporary
directories; no test reads or writes your real config directory.

The rule table in `skill_forge/rules.py` is the single source of truth — the tests iterate over it
and fail unless every rule has both a positive and a negative fixture, so the rule set cannot drift
away from its tests.

Behaviour was verified against the official documentation at
[code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills) as of **2026-09-04**, and
against real skills and commands installed on disk.

## License

MIT — see [LICENSE](LICENSE).
