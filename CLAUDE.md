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

The user-facing surface: `tdd --help | --version | --reqs`, `tdd doctor`, `tdd info`,
the tools, and on the shell side `tdd tdd-env activate|deactivate` (toolset venvs),
`tdd venv create|activate|deactivate|delete|list` (managed pyenv/uv/conda venvs under
`<tdd_dir>/managed-venvs/`; activation exports `TDD_VENV`), `tdd pycache clean`, and `tdd env set|unset|show`
(`--crypto`/`--secrets` eval `system crypto-key`/`secrets --as export` into the shell; `--td`, `--vars PREFIX`,
`--py-idxx URL`, `--py-default-idx URL` for the TD_ and Python index variables; `show` lists them, `-` marking the unset ones). Setup is
`tdd-install`; regenerating the catalog is `cargo make gen`; testing is `cargo make test`. None
of those are `tdd` words — see `.claude/DECISIONS.md`.

`<tdd_dir>/default-opts/<command>.txt` or `<command>_<action>.txt` presets options;
`tdd-exe --defaults` merges (typed wins, action file wins), the `tdd` function rebuilds argv and
emits the resolved line as `info`. Logic lives in `tabsdata_dev.tdd.defaults`, stdlib, unit-tested.

Every command meets `docs/command-cli-guidelines.md` through one shared layer per side:
shell commands source `scripts/unix/common.sh` (`_tdd_cmd_reset`, `_tdd_common_opt`,
`_tdd_optval`, `_tdd_cmd_check`, `_tdd_ok`, `_tdd_error`, `_tdd_warn`, `_tdd_info`,
`_tdd_debug`); Python tools go through `common.core.cli.run()` and `common.core.render`
(`Event`, `Renderer`); `tdd-exe`, `tdd-install` and the generator through
`tabsdata_dev.tdd.render`, a byte-identical twin of the latter (stdlib-only, cannot import
`common-core`) — a test fails if they diverge; edit both.
Commands never print on their own; the tests check it. A shell command with options declares
their built-in defaults in `tdd_defaults_<name>()` for `tdd defaults --command <name>`.

Packages, all prefixed `tabsdata-dev-`, all under the `tabsdata_dev` PEP 420 namespace:

| Package | Role | Declares |
|---|---|---|
| `-tdd` | the executable | nothing, stdlib only |
| `-shell` | sourced shell commands | nothing, shell files as data |
| `-common-*` | shared library code; joins only the toolsets whose tools depend on it | third-party **ranges** |
| `-deps-*` | dependency bundle, no logic | third-party **pins** |
| `-tool-*` | one tool | exactly one `-deps-*` + any `-common-*` |
| `-toolset-*` | **GENERATED** meta-package | its `-deps-*` + every tool using it |

Real tools: `system` and `domain` (toolset `systems`, Python 3.12, the SQL/object-store/kafka
driver set) manage external systems for testing and the domains inside them; both are thin
entry points over `tabsdata_dev.common.systems`. `domain-sf` (toolset `salesforce`, hidden) is
the same `domain` family running where cumulusci/snowfakery live — `domain` re-dispatches
salesforce data-plane verbs to it. Their state lives in `<tdd_dir>/data/system` and
`data/domain`.

`xp-run` (toolset `systems`, pydantic/pyyaml) is tabsdata-xp's `tdx-xp` ported: the tabsdata-xp `suites/` and
`connections/` trees ship inside the package (`xp/`, excluded from ruff via `ruff.toml`) and are the
default; `--suite <type>/<name>|<type>` is a selector under them or under `--suites-dir DIR`
(`export-suites --dir DIR` copies them out); a suite dir fans out one lane per file; it provisions domains through
`tdd domain create|destroy --manifest` (events parsed), talks to the server through `tdd tdk`
(`proc.tool_argv`, so `TDD_VENV` must name a venv with tabsdata), keeps pointers under
`<tdd_dir>/data/xp-run` and a scratch dir per run under `/tmp/tdd-xp-run/`. `--dry-run` prints
the `tdd tdk`/`tdd domain` lines it would run. tdk refuses to run under an agent (it checks `CLAUDECODE`);
only when the user asks, run it with that variable unset (`env -u CLAUDECODE`), never `tdkserver`.

Launchers: `tdk`, `tdkserver` and `km` (toolset `launchers`, pins nothing) run tabsdata's own CLIs
inside the managed venv named by `$TDD_VENV` (exported by `tdd venv activate`/`create`),
through `common.core.launcher` + `common.core.managedvenv`: `uv run --active --no-project`,
`conda run -p`, or the venv's `bin/` for pyenv. They have no options of their own: every argument,
`--help`/`--format`/`--version` included, goes to the program (the one exception to the
CLI guidelines). They fail with a "venv activated with tdd venv is required"
error when `TDD_VENV` is unset, and refuse to run when the program is not installed in that
venv (a manager falling back to PATH would find the launcher itself). Never run the real
`tdk`/`tdkserver` from an agent session: `tdk` refuses under an AI agent and `tdkserver` is
a server that never returns -- test the launchers with a fake program in a scratch venv.

Demo tools: `demo-exe1` (toolset `demo-env1`), `demo-exe2` (toolset `demo-env2`), and the shell
functions `demo-fn1`/`demo-fn2` print their own names. The two demo toolsets pin `packaging`
differently on purpose. Demo and hidden commands stay out of `tdd help` unless `--demo` is
given; they dispatch, test and report reqs like any other tool.

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
11. **Demo/hidden status is an explicit marker, never a name convention.** A Python tool sets
    `[tool.tdd] demo = true` (a sample) or `hidden = true` (plumbing another tool dispatches
    to) in its `pyproject.toml`; a shell command registers with `tdd_fn_register --demo`.
    Hiding is a listing concern only — nothing but `tdd help` consults the flags.
12. **A `-deps-*` bundle may pin its toolset's interpreter** with `[tool.tdd] python = "3.12"`;
    the generator writes `requires-python` and the catalog's `python` map from it and
    `tdd-install` creates that venv on it. Otherwise the default interpreter is used.
13. **Generic code goes in `common-core`, family code in a `common-<family>`.** Parallel child
    runs (`batch`), free ports, passwords, docker, ssh, 1Password secrets, `data_dir()`,
    latches are `common-core` (stdlib only, in every toolset). Descriptors, backends, models
    and the dispatcher of the system/domain family are `common-systems` (pydantic/pyyaml/
    cryptography ranges), which joins only the toolsets whose tools depend on it.

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
