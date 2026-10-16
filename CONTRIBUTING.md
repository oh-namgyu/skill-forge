# Contributing to skill-forge

Thanks for your interest! Bug reports, false positives and pull requests are
welcome.

## Development setup

There is nothing to build and nothing to install at runtime.

```sh
python -m pip install pytest          # the only tool the suite needs
python -m pytest tests/ -q            # or: python -m unittest discover -s tests
python -m skill_forge --help
```

CI runs the suite on Python 3.9 and 3.12; please keep both working.

## Guidelines

- **Zero runtime dependencies.** Standard library only. Do not add a
  third-party import, including a YAML parser.
- **The rule table is the source of truth.** Rules live in
  `skill_forge/rules.py`, and the tests fail unless every rule has both a
  positive and a negative fixture. A new or changed rule needs both, plus a
  row in the README's Rules reference.
- **Cite the behaviour.** A rule about what Claude Code does at runtime should
  point to the official documentation or a reproducible observation in the
  PR description.
- **Read-only by default.** Only `new` writes files, only inside the root it
  is given, and never over an existing artifact.
- **Synthetic fixtures only.** Tests use temporary directories and must never
  read or write a real config directory.
- Add a regression test for any bug fix.

## Pull requests

Keep PRs focused on one change, describe what changed and how you verified
it, and make sure the test suite is green before opening one.
