# Security

## What this tool does

skill-forge runs entirely on your machine and makes **no network request** of any kind. It has no
dependencies beyond the Python standard library, so there is no third-party code in the path.

`lint` and `list` are **strictly read-only**. They open `SKILL.md` and `commands/*.md` files, plus
`os.stat` on the files inside a bundle's `scripts/` and `references/`, and write nothing anywhere.
Directories reached through a symlink are never entered, and discovery never descends past the
`skills/<name>/` and `commands/` layout it is looking for.

`new` is the only command that creates anything, and only under the root you give it (`--dir`, or
`./.claude`). It deliberately does **not** fall back to your personal config directory.

## How `new` avoids destroying your work

- The name must match `[a-z0-9][a-z0-9_-]{0,63}`. Path separators, `..`, dots, leading dashes and
  uppercase letters are refused **before any filesystem call**, and the resolved target is then
  checked to still sit directly inside the intended parent.
- The artifact is built in a `.skill-forge-tmp-*` directory in the same parent and installed with a
  single atomic call — `rename` for a bundle, `link` for a command file, because plain `rename`
  would replace an existing file silently. The kernel's own `EEXIST`/`ENOTEMPTY` is the existence
  gate, so there is no check-then-write window a parallel process could slip through.
- A failed install removes the temporary directory and leaves the existing artifact byte-for-byte
  untouched. There is no `--force`, and nothing is ever deleted.

One documented exception: POSIX `rename` may replace an *empty* directory, so an empty
`skills/<name>/` left behind by something else is taken over.

## What ends up in the output

Diagnostics quote file paths, frontmatter key names, description lengths and line numbers. A
`--json` report contains the same. Skill bodies and command bodies are read but never echoed, apart
from a referenced relative path such as `references/guide.md` in an F020 message.

Paths are printed as given, so a report generated from a home directory contains your account name.
Review a report before pasting it into an issue.

## Reporting a problem

Please report security issues through GitHub issues on this repository — in particular any way
`new` could write outside its target root, or any input that makes a read-only command modify a
file. Describe the shape of the input rather than pasting anything private.
