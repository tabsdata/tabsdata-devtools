# tabsdata-devtools

Python dev tools in isolated environments behind one entry point, so tool dependencies never
reach a project's dependencies. Read [docs/design.md](docs/design.md) for the full rationale;
this file is the working contract.

## Read first

- [docs/design.md](docs/design.md) — the design and the reasoning
- [docs/building-a-python-command.md](docs/building-a-python-command.md) and
  [docs/building-a-shell-command.md](docs/building-a-shell-command.md) — the how-to guides
- [docs/command-cli-guidelines.md](docs/command-cli-guidelines.md) — the contract every
  command's CLI must meet: `--long` options, `--help`/`--verbose`, exit 0/1, a failure log in
  `/tmp`, `--format json|view`, `-` between words
- [.claude/DECISIONS.md](.claude/DECISIONS.md) — every design decision, why, and what was
  rejected. Do not relitigate these without a reason.
- [.claude/VERIFIED.md](.claude/VERIFIED.md) — what has been empirically proven and how.
  Treat these as settled facts; re-testing is waste.
- [.claude/OPEN.md](.claude/OPEN.md) — known gaps and candidate next steps.

## Shape

```
tdd            shell function (sourced)  -> front door over both halves
tdd-exe        executable in <tdd_dir>/tdd-venvs/tdd  -> dispatches tools; list, doctor, info
tdd-fn         shell function            -> commands that change the current shell (tdd-env)
tdd-install    executable                -> the only way to build a tdd dir
```

The user-facing surface is deliberately small: `tdd --help | --version | --reqs`, `tdd list`,
`tdd doctor`, `tdd info`, `tdd tdd-env activate --toolset <ts>`, `tdd tdd-env deactivate`, and the
tools. Setup is `tdd-install`; regenerating the catalog is `cargo make gen`; testing is
`cargo make test`. None of those are `tdd` words — see `.claude/DECISIONS.md`.

Packages, all prefixed `tabsdata-dev-`, all under the `tabsdata_dev` PEP 420 namespace:

| Package | Role | Declares |
|---|---|---|
| `-tdd` | the executable | nothing, stdlib only |
| `-shell` | sourced shell commands | nothing, shell files as data |
| `-common-*` | shared library code | third-party **ranges** |
| `-deps-*` | dependency bundle, no logic | third-party **pins** |
| `-tool-*` | one tool | exactly one `-deps-*` + any `-common-*` |
| `-toolset-*` | **GENERATED** meta-package | its `-deps-*` + every tool using it |

The repo ships only **demo** tools, which print their own names and nothing else: `demo-exe1`
(toolset `demo-env1`), `demo-exe2` (toolset `demo-env2`), and the shell functions `demo-fn1`
and `demo-fn2`. The two toolsets pin `packaging` differently on purpose — that conflict is the
reason toolsets exist. Demo commands are hidden from `tdd help` and `tdd list` unless `--demo`
is given; they dispatch, test and report reqs like any other tool.

## Invariants — do not break these

1. **`tabsdata-dev-tdd` has zero third-party dependencies.** Standard library only, forever.
   It reaches Python through `uv`, which it shells out to. If you need YAML or similar, the
   answer is to change the data format, not add a dependency.
2. **`uv` is a hard requirement.** Fail with exactly `uv is a hard requirement, install it`
   via `paths.require_uv()`. Never degrade gracefully.
3. **No uv workspace.** Each `-toolset-*` is an independent project with its own committed
   `uv.lock`. A workspace forces one unified resolution and breaks the entire point.
4. **No absolute paths in `catalog.json`.** Names only. Paths are composed at call time from
   the tdd dir.
5. **Every resource ships inside its package** and is found with `importlib.resources` —
   never an assumed OS location, never cwd, never `__file__` arithmetic that assumes a
   checkout. External binaries are the one exception and need a `bin-reqs.txt` entry — for a
   Python tool at the package root, for a shell command beside its script as
   `<file>.bin-reqs.txt`. Both halves are reported by `tdd --reqs` and enforced at run time.
6. **All envs are relocatable.** Created via `_make_venv()` with `--relocatable` and
   `UV_LINK_MODE=copy`. `tdd-source.sh` locates itself; never bake an absolute `TDD_DIR`.
7. **A tool depends on exactly one `-deps-*`.** That dependency is what assigns it to a
   toolset. There is no separate registration step.
8. **`-toolset-*` packages and `catalog.json` are generated.** Never hand-edit them; run
   `cargo make gen`.
9. **Layout is `src/python/main/` and `src/python/test/`** in every package, with the
   hatchling `only-include` + `sources` mapping.
10. **`VERSION` at the repo root is the only version.** No `pyproject.toml` states one; all
    are `dynamic` and read `../../VERSION`. `tabsdata-dev-tdd` force-includes the file so
    wheels-mode knows it; `tdd-install` stamps `<tdd_dir>/VERSION`; `tdd --version` prints
    that stamp. Never hardcode a version string anywhere else.
11. **Demo status is an explicit marker, never a name convention.** A Python tool sets
    `[tool.tdd] demo = true` in its `pyproject.toml` (the generator carries it into the catalog
    as `"demo": true`); a shell command registers with `tdd_fn_register --demo`. Hiding is a
    listing concern only — nothing but `tdd help`/`tdd list` consults the flag.

## Commands

```bash
cargo make help                  # every task with its options
cargo make install               # wheels + locks -> <dir>/wheels, build envs from them
cargo make install -- --editable # every env editable from this checkout (`dev` is the shortcut)
cargo make check                 # lint + test + reqs, what CI runs
cargo make uninstall             # delete the tdd dir; says which `source` line to drop from ~/.zshrc
cargo make test
```

Requires only `uv` and `cargo-make` — no venv, no active Python. All of them honour
`TDD_DIR` and `-- --dir PATH`; `test` needs an initialized tdd dir (default `~/.tdd`).

`cargo make check` passes. Its `reqs` step is a real gate: declare a binary in a
`bin-reqs.txt` that the machine lacks and it fails. The demo shell commands declare
`whoami`/`hostname` and `uname`/`date`; the demo Python tools declare nothing.

## Conventions

- Every source file starts with the house header — `#`, `# Copyright 2026 Tabsdata Inc.`,
  `#` (an HTML comment in Markdown). Generated `toolset-*` files get it from the generator.
  `VERSION`, `catalog.json` and `uv.lock` are the exceptions: parsed or machine-owned.
- Comments explain **why**, not what. Match the density in the existing modules.
- Docstrings on modules and non-obvious functions; state the reasoning that is not visible
  from the code.
- Tests live in `src/python/test/`, run inside the toolset venv the code ships with.
- `ruff format` and `ruff check` must pass, at the version pinned in `Makefile.toml`. Run
  `cargo make fmt` after editing — it reformats, and stale string-matching patches will
  silently fail against reformatted code.
