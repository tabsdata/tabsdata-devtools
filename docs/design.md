<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-devtools

Dev tools in isolated environments behind one entry point, so tool dependencies never reach
a project's dependencies.

This document is the *why* and the *how it works*. The step-by-step guides are
[building-a-python-command.md](building-a-python-command.md) and
[building-a-shell-command.md](building-a-shell-command.md); every command follows
[command-cli-guidelines.md](command-cli-guidelines.md); install instructions are in the
[README](../README.md).

## Three pieces

1. **`tdd`** — a shell function, sourced. The front door. Routes to either half below, so a
   caller never has to know which one owns a command.
2. **`tdd-exe`** — a real executable, living in its own venv inside the tdd dir. Dispatches
   tools, builds envs, reports requirements.
3. **`tdd-fn`** — the shell half: commands sourced into the caller's shell, for the thing
   an executable fundamentally cannot do: enter or leave a venv.

Nothing is installed globally and no venv has to be active. `uv` is the single hard
requirement; everything else lives under the tdd dir.

```bash
uv run --no-project --with-editable packages/tabsdata-dev-tdd tdd-install
source ~/.tdd/tdd-source.sh
```

`tdd-install` exists to break a bootstrap cycle: `tdd` is a shell function, so it cannot
exist until `tdd-source.sh` has been sourced, and `tdd-source.sh` does not exist until something has
written it. `tdd-install` is a real executable that performs the whole setup and then tells
you what to source. It is also the *only* way to build a tdd dir: there is no `tdd init`,
because nobody wants envs rebuilt from inside a tool invocation, and re-running `tdd-install`
is the documented way to pick up a dependency change.

## Naming

Every distribution and directory is prefixed `tabsdata-dev-`. Every module lives under the
`tabsdata_dev` import namespace, a native PEP 420 namespace package — so no `__init__.py` at
`tabsdata_dev/`, `tabsdata_dev/tool/`, `tabsdata_dev/common/`, or `tabsdata_dev/deps/`, only
at the leaves.

| Distribution | Import path |
|---|---|
| `tabsdata-dev-tdd` | `tabsdata_dev.tdd` |
| `tabsdata-dev-shell` | `tabsdata_dev.shell` |
| `tabsdata-dev-common-core` | `tabsdata_dev.common.core` |
| `tabsdata-dev-deps-demo-env1` | `tabsdata_dev.deps.demo_env1` |
| `tabsdata-dev-tool-demo-exe1` | `tabsdata_dev.tool.demo_exe1` |
| `tabsdata-dev-toolset-demo-env1` | *(no code)* |

Hyphens in a distribution name become underscores in its module path; the tool *name* (the
`[project.scripts]` key, what you type after `tdd`) keeps the hyphen.

Inside every package the layout is `src/python/main/` for code and `src/python/test/` for
tests, which needs an explicit hatchling mapping:

```toml
[tool.hatch.build.targets.wheel]
only-include = ["src/python/main/tabsdata_dev"]
sources = ["src/python/main"]

[tool.pytest.ini_options]
testpaths = ["src/python/test"]
```

`sources` rebases wheel paths onto `src/python/main`, so the distribution contributes
`tabsdata_dev/...` and the namespace merges across packages.

## The CLI

```
tdd [--dir TDD_PATH] [--format json|view] [--verbose] <command> [args...]
```

`--dir` defaults to `$TDD_DIR`, then `~/.tdd`. `<command>` is a shell command, a `tdd-exe`
builtin, or a tool name; everything after it reaches the tool verbatim. `--format` and
`--verbose` before the word apply to `tdd`'s own output *and* travel on to the command
(appended after its word), so `tdd --format json venv list` and `tdd venv list --format json`
are the same request. `tdd` itself speaks the event model too: `help`, `--version`, `info` are
one `ok` event each (`help` in json carries a `commands` array and a `default_opts` object);
`doctor` and `--reqs` emit an `info`/`warn` line per check and end in `ok` or `error`; every
failure — unknown command, bad `--format`, uninitialized dir, missing binary — is an `error`
with a log, exit 1.

The whole surface, deliberately small:

| | |
|---|---|
| `tdd --help` / `--version` / `--reqs [tool]` | options handled before any command word |
| `tdd doctor` | validate the tdd dir against the shipped catalog |
| `tdd info` | what the dir is: wheels or source install (and where the checkout is), version, envs |
| `tdd tdd-env activate --toolset <ts>` / `tdd tdd-env deactivate` | `*` shell — enter or leave a *toolset* venv |
| `tdd venv create\|activate\|deactivate\|delete\|list` | `*` shell — *managed* venvs (pyenv, uv or conda) under `managed-venvs/`; create ends in activation; prompt shows `(<type>/<name>)`; activate switches; a venv tdd did not activate blocks both |
| `tdd pycache clean [--package-prefixes …] [--all]` | `*` shell — purge uv and pip caches by package prefix |
| `tdd system <verb> …` | external systems for testing: create/destroy/status/purge/restart/fetch-bin/connect, plus types/list/info/manifest/upgrade/secrets/crypto-key |
| `tdd env set\|unset\|show …` | `*` shell — the variables tdd manages in this shell: `--crypto`/`--secrets` (eval `system crypto-key`/`secrets --as export`), `--td`, `--vars PREFIX`, `--py-idxx URL`, `--py-default-idx URL`; `show` lists them, `-` marking the unset ones |
| `tdd xp-run <verb> …` | run tabsdata example suites (bundled; `--suite <type>/<name>|<type>`, `--suites-dir DIR`, `export-suites`): domains via `tdd domain`, server via `tdd tdk` |
| `tdd tdk ARGS…`, `tdd tdkserver ARGS…`, `tdd km ARGS…` | run tabsdata's CLIs inside the managed venv `$TDD_VENV` names, through its manager |
| `tdd domain <verb> …` | domains inside systems: create/destroy/status/models/create-model/create-data/modify-data, plus list/info/manifest/upgrade |
| `tdd defaults --command <name>` | `*` shell — a command's option defaults: built-in (white) vs customized (blue) |
| `tdd <tool> [args…]` | dispatch |

Every shell command follows [command-cli-guidelines.md](command-cli-guidelines.md) through
`scripts/unix/common.sh` (options, the event model, colours, the failure log); every Python
tool through `common.core.cli.run()` and `common.core.render`. The same model on both sides:
`command` + `event` (`ok`, `error`, `warn`, `info`, `debug`) + `message` + fields, one line
each, green/red/yellow/plain/white on a terminal. `tdd-exe`, `tdd-install` and the generator
cannot import `common-core`, so `tabsdata_dev.tdd.render` is a byte-identical twin of
`common.core.render`, kept identical by a test. `tdd-install` runs every `uv` step with its
output captured — `debug` under `--verbose`, the error log on failure — so `tdd-install
--format json` is a clean event stream.

What is *not* a `tdd` word, and why: **setup** is `tdd-install` (above); **regenerating the
catalog** is `cargo make gen`, a build step that must run before wheels are built and never
from a finished install; **testing** is `cargo make test`, which reads each tool's toolset out
of the catalog itself. All three exist as code inside `tabsdata-dev-tdd`; none needs to be
reachable from a user's prompt.

### Default options

`<tdd_dir>/default-opts/<command>.txt` — and, for a group, `<command>_<action>.txt` — holds
options `tdd` adds to every invocation of that command. The separator is `_` because command
names use `-` (`tdd-env_activate.txt` is unambiguous; a hyphen would not be):

```
# default-opts/venv_create.txt
--type uv
--python=3.12
```

**One option per line** — `--name value`, `--name=value` or `--flag`; `#` comments; two options
on one line are rejected. What is typed
wins: an option named on the command line (in either spelling, `-v` counting as `--verbose`)
drops the default entirely rather than appearing twice; the action's file wins over the
command's. Whenever a file applied, `tdd` first emits an `info` event, in the format the
command will use, saying what will run:

```
$ tdd venv create --name scratch
resolved: tdd venv create --name scratch --type uv --python=3.12
create scratch (uv)
created scratch (uv) at ~/.tdd/managed-venvs/uv/scratch
```

The merge is `tdd-exe --defaults <command> [args…]` — stdlib Python, unit-tested, one place —
and the `tdd` function only rebuilds its argument list from the result and prints the line.
Both halves get defaults this way without knowing they exist. A malformed file is an error
(exit 1, with the log) rather than a silently ignored line. `tdd help` ends with the dir, file
names and syntax, and `tdd defaults --command <name>` shows what applies to a command, grouped
by action — its built-in values in white, the customized ones in blue with the file they came
from; an unknown `<name>` is an error. Every `tdd defaults` run also audits the directory and
warns about what would otherwise silently do nothing: no `default-opts/` at all (every default
is then built-in), a file without `.txt`, a
file naming no command or no action of that command, a line carrying two options. Without
`--command` it lists the commands that have customizations. Shell
commands declare their built-ins with a `tdd_defaults_<name>` function (`sub|--option|value`
lines); a Python tool's built-ins live in argparse, so only its customized file is shown.

`tdd help` merges both halves into one alphabetical listing, marking shell commands with `*`
because they behave differently — they can change the current shell:

```
commands (* runs in this shell; --demo includes the demo commands):
    doctor        validate TDD_PATH against the installed catalog
    info          describe TDD_PATH: install kind, checkout, version, envs
    list          list available tools; --demo includes the demo tools
  * tdd-env       activate --toolset <toolset>, or deactivate, a toolset venv in this shell
```

The merge works off `tdd-exe --porcelain [--demo]`, which emits `name|kind|summary`, plus the
shell registry the sourced files build up. `tdd-fn` on its own lists only the shell half.

### Demo tools

The repo ships four sample commands, two per half, and nothing else: `demo-exe1` and
`demo-exe2` are Python tools living in the `demo-env1` and `demo-env2` toolsets; `demo-fn1`
and `demo-fn2` are sourced shell functions. Each prints its own name; the shell ones add a
detail fetched through two external binaries (`whoami`/`hostname`, `uname`/`date`) so that the
`bin-reqs.txt` machinery is exercised end to end. They exist to show the shape of a command
and to run every piece of machinery — two toolsets with conflicting pins, `common-*` in each,
a shell half, declared binaries — without pretending to be useful.

Because they are not useful, they stay out of `tdd help` unless asked for:

```
tdd help --demo        # or: tdd --help --demo
tdd-fn help --demo
```

Hiding is a *listing* concern only. A demo tool dispatches, tests, and reports requirements
like any other; `tdd demo-exe1` works whether or not it is listed.

The marker is explicit rather than a name convention. A Python tool sets it in its own
`pyproject.toml`, and the generator carries it into the catalog as `"demo": true`:

```toml
[tool.tdd]
demo = true
```

A shell command passes `--demo` when it registers; the registry carries it as the `kind` field
and both listings filter on it:

```sh
tdd_fn_register --demo demo-fn1 "demo shell command: prints its name, then whoami@hostname"
```

**A tdd dir must be explicitly initialized.** Using an uninitialized dir is an error telling
you to run `tdd-install --dir foo` — never a lazy build, which would turn a tool invocation
into a surprise multi-minute stall.

## Layout

```
tabsdata-devtools/
├── Makefile.toml                          # cargo-make tasks; `cargo make help` lists them
├── README.md                              # splash page: install, then `tdd --help`
├── VERSION                                # the one release version, e.g. 0.1.0
├── docs/
│   ├── design.md                          #   this file
│   ├── command-cli-guidelines.md          #   options, exit codes, --format, failure logs
│   ├── building-a-python-command.md
│   └── building-a-shell-command.md
└── packages/
    ├── tabsdata-dev-tdd/                  # the executable — stdlib only
    │   ├── pyproject.toml                 #   dependencies = []
    │   │                                  #   scripts: tdd-exe, tdd-install
    │   └── src/python/
    │       ├── main/tabsdata_dev/tdd/
    │       │   ├── __main__.py            #   CLI: --dir, --reqs, builtin vs tool
    │       │   ├── install.py             #   tdd-install entry point
    │       │   ├── paths.py               #   dir/repo resolution, require_uv
    │       │   ├── catalog.py             #   read / copy / compare catalogs
    │       │   ├── catalog.json           #   GENERATED, committed, shipped as data
    │       │   ├── discover.py            #   scan packages/ and the shell scripts, parse bin-reqs.txt
    │       │   ├── generate.py            #   emit toolset-*/pyproject.toml + catalog
    │       │   ├── initialize.py           #   build every env; copy catalog; write source.sh
    │       │   ├── defaults.py            #   default-opts/<command>.txt merge (typed options win)
    │       │   ├── dispatch.py            #   execve into the toolset venv
    │       │   ├── reqs.py                #   [ok]/[missing] binary report
    │       │   └── version.py             #   VERSION: shipped copy vs. the tdd dir's stamp
    │       └── test/{test_discover, test_defaults, test_main, test_render_twin, test_version}.py
    ├── tabsdata-dev-shell/                # the sourced half
    │   ├── pyproject.toml
    │   ├── tddsrc.sh                      #   template for <tdd_dir>/tdd-source.sh
    │   ├── scripts/unix/                  #   one file per shell command, plus
    │   │   ├── common.sh                  #     options, events, colours, failure log -- sourced by all
    │   │   ├── common.bin-reqs.txt        #       jq: what common.sh needs; folded into every command
    │   │   ├── tdd-env.sh                 #     tdd-env activate --toolset <ts> / tdd-env deactivate
    │   │   ├── venv.sh                    #     venv create/activate/deactivate/delete/list (managed)
    │   │   ├── pycache.sh                 #     pycache clean; pycache.bin-reqs.txt declares uv
    │   │   ├── env.sh                     #     env set|unset|show: crypto key, secrets, TD_*, Python index vars
    │   │   ├── defaults.sh                #     defaults --command <name>: built-in vs customized
    │   │   ├── demo-fn1.sh                #     demo-fn1, registered --demo
    │   │   ├── demo-fn1.bin-reqs.txt      #       whoami, hostname
    │   │   ├── demo-fn2.sh                #     demo-fn2, registered --demo
    │   │   └── demo-fn2.bin-reqs.txt      #       uname, date
    │   └── src/python/
    │       ├── main/tabsdata_dev/shell/__init__.py   # locates the assets above
    │       └── test/test_shell.py
    ├── tabsdata-dev-common-core/          # in every toolset
    │   ├── pyproject.toml                 #   deps = ["rich>=13"]  ← a RANGE, not a pin
    │   └── src/python/
    │       ├── main/tabsdata_dev/common/core/
    │       │   ├── cli.py                 #   parser with the mandatory options; run() wrapper
    │       │   ├── render.py              #   Event model + Renderer: json/view, colours, failure log
    │       │   ├── proc.py                #   process launching + req enforcement; run_tool()
    │       │   ├── batch.py               #   parallel child runs, heaviest first, on the event model
    │       │   ├── ports.py / passwords.py / docker.py / ssh.py / secrets*.py
    │       │   ├── datadir.py             #   <tdd_dir>/data/<command>
    │       │   ├── latch.py               #   --latch FILE for background waits
    │       │   └── parallel.py            #   bounded map
    ├── tabsdata-dev-common-systems/       # the system/domain family (pydantic, pyyaml, cryptography ranges)
    │   └── src/python/main/tabsdata_dev/common/systems/
    │       ├── dispatch.py, main.py       #   the CLI over the backend registry
    │       ├── descriptor.py, crypto.py, manifest.py, store.py, naming.py, options.py
    │       ├── batch.py, console.py, cli.py, datagen.py, emit.py, sql_runner.py
    │       ├── models/<name>/             #   entities.json, datagenerator.py, data files
    │       └── systems/<slug>/            #   backend.py [+ domain/ overrides, models/<name>/*.ddl]
    ├── tabsdata-dev-deps-systems/         # python 3.12; SQL dialects+drivers, object stores, kafka, polars
    ├── tabsdata-dev-deps-salesforce/      # python 3.12; cumulusci-plus, snowfakery (sqlalchemy<2)
    ├── tabsdata-dev-tool-system/          # `system`  -> common.systems.main.run("system"); bin-reqs: docker, op
    ├── tabsdata-dev-tool-domain/          # `domain`; bin-reqs: docker, op
    ├── tabsdata-dev-deps-launchers/       # toolset `launchers`: pins nothing but pytest
    ├── tabsdata-dev-tool-tdk/             # `tdk`       -> common.core.launcher.run("tdk"); bin-reqs: tdk, uv, conda
    ├── tabsdata-dev-tool-tdkserver/       # `tdkserver` -> same, for tdkserver
    ├── tabsdata-dev-tool-km/              # `km`        -> same, for km
    ├── tabsdata-dev-tool-xp-run/          # `xp-run`    -> tabsdata_dev.tool.xp_run (tdx-xp ported; systems toolset); bin-reqs: tdk, tdkserver
    ├── tabsdata-dev-tool-domain-sf/       # `domain-sf` (hidden), toolset salesforce
    │       └── test/test_common.py
    ├── tabsdata-dev-deps-demo-env1/       # NO logic, PINS only
    │   ├── pyproject.toml                 #   pytest==8.4.2, packaging==24.0
    │   └── src/python/main/tabsdata_dev/deps/demo_env1/__init__.py
    ├── tabsdata-dev-deps-demo-env2/       #   pytest==8.4.2, packaging==25.0  ← conflicts on purpose
    ├── tabsdata-dev-tool-demo-exe1/       # no bin-reqs.txt: it shells out to nothing
    │   ├── pyproject.toml                 #   deps = [deps-demo-env1, common-core]
    │   │                                  #   [project.scripts] demo-exe1 = "...tool.demo_exe1:main"
    │   │                                  #   [tool.tdd] demo = true
    │   └── src/python/{main/tabsdata_dev/tool/demo_exe1/, test/}
    ├── tabsdata-dev-tool-demo-exe2/       #   demo-env2 toolset, same shape
    ├── tabsdata-dev-toolset-demo-env1/    # GENERATED — pyproject.toml + committed uv.lock
    └── tabsdata-dev-toolset-demo-env2/    # GENERATED
```

A tdd dir, created by `tdd-install`:

```
~/.tdd/                                    # or whatever --dir points at
├── catalog.json                           # copied here — also the "initialized" marker
├── VERSION                                # stamped by tdd-install; what `tdd --version` prints
├── config.toml                            # reserved for per-tool config; NOT a locator
├── tdd-source.sh                          # tddsrc.sh with this dir baked in
├── wheels/                                # wheels + locks (wheels mode only)
├── data/                                  # per-command state: data/<command>/ (system, domain)
├── default-opts/                          # <command>.txt / <command>_<action>.txt: options tdd adds
├── managed-venvs/                         # `tdd venv`: <name>.env markers + <type>/<name>/ envs
│   ├── scratch.env                        #   content: uv | pyenv | conda
│   └── uv/scratch/
└── tdd-venvs/
    ├── tdd/                               # tdd-exe itself
    ├── shells/                            # tabsdata-dev-shell, sourced from here
    ├── demo-env1/                         # venv for tabsdata-dev-toolset-demo-env1
    └── demo-env2/                         # venv for tabsdata-dev-toolset-demo-env2
```

Four envs, two of which are not toolsets. Anything enumerating toolsets reads
`catalog["toolsets"]` rather than globbing `tdd-venvs/` — the glob was a real bug once.

## The package roles

| Package | Written by | Declares | Contains code |
|---|---|---|---|
| `tabsdata-dev-tdd` | you | nothing — stdlib only | yes |
| `tabsdata-dev-shell` | you | nothing — shell files as data | no logic |
| `tabsdata-dev-common-*` | you | third-party **ranges** | yes |
| `tabsdata-dev-deps-*` | you | third-party **pins** | no |
| `tabsdata-dev-tool-*` | you | exactly one `deps-*` + any `common-*` | yes, + `[project.scripts]` |
| `tabsdata-dev-toolset-*` | generator | its `deps-*` + every tool using it | no |

`deps-*` and `toolset-*` exist separately because the arrows point opposite ways:

```mermaid
graph LR
  T1[tool-demo-exe1] --> D[deps-demo-env1]
  T2[tool-another] --> D
  TS[toolset-demo-env1] --> D
  TS --> T1
  TS --> T2
  T1 --> C[common-core]
  T2 --> C
  TS -.one uv.lock<br/>one venv.-> E["TDD_PATH/tdd-venvs/demo-env1"]
```

`deps-demo-env1` is depended on **by** tools, so each tool is honest and installable alone.
`toolset-demo-env1` depends **on** tools, so one sync materializes the whole env. (The repo
ships one tool per demo toolset; `tool-another` stands for any further tool naming the same
bundle.)

## No absolute paths in the catalog

```json
{
  "schema": 1,
  "fingerprint": "5f4dc79beb727ee7",
  "toolsets": ["demo-env1", "demo-env2"],
  "members": {
    "demo-env1": ["tabsdata-dev-common-core", "tabsdata-dev-deps-demo-env1",
                  "tabsdata-dev-tool-demo-exe1"]
  },
  "tools": {
    "demo-exe1": {"toolset": "demo-env1", "package": "tabsdata-dev-tool-demo-exe1",
                  "summary": "demo tool in the demo-env1 toolset: prints its name",
                  "reqs": [], "demo": true}
  },
  "shell": {
    "demo-fn1": {"file": "demo-fn1.sh", "reqs": ["whoami", "hostname"], "demo": true,
                 "summary": "demo shell command: prints its name, then whoami@hostname"}
  }
}
```

`shell` is read statically from the shell package's scripts. It is not used for dispatch — the
registry `tdd-source.sh` builds while sourcing is the runtime truth — but it lets `tdd --reqs`
report both halves on a machine where nothing is sourced yet, and it lets the generator reject
a Python tool named after a shell command.

`tdd-exe` composes the target at call time as `<tdd_dir>/tdd-venvs/<toolset>/bin/<name>`. Since
the tdd dir arrives on the command line or from the default, nothing needs to be persisted
to find it — a tdd dir is self-describing and relocatable, and `config.toml` stays free for
per-tool configuration.

`members` lists every first-party distribution in each toolset. Wheels-mode installs need it
explicitly, because they install with `--no-deps` to keep the exported lock authoritative,
and `--no-deps` also blocks *first-party* resolution. Leaving it out silently produced envs
missing `common-core` — the tools imported fine at build time and failed at run time.

`fingerprint` hashes tools, members and shell commands, so `doctor` and dispatch can say the
envs predate the current tool set rather than dying on a missing executable.

## The system / domain family

`tdd system` and `tdd domain` are the port of `tdx-system` / `tdx-domain` from tabsdata-os's
devutils: ~30 backends (docker-run and compose databases, object stores, warehouses, kafka,
credential-only services), encrypted descriptors, YAML manifests, a batch runner, deterministic
data generation with per-system DDL. What changed in the port, and why:

- **One shared library, `tabsdata-dev-common-systems`** (`tabsdata_dev.common.systems`), holds
  the whole family — descriptors, registry, backends, models, the dispatcher — and the tools
  are thin entry points naming which command they are. Two toolsets need the same code
  (below), and a tool may only depend on one `deps-*`, so shared code has to be a `common-*`.
  The generator now puts a `common-*` **only in the toolsets whose tools depend on it**, so
  this library does not land in the demo envs.
- **Toolsets replace the three self-managed venvs.** The original re-exec'd every command into
  one of `~/.uv/envs/_tdx-sys-{a,b,c}` chosen from raw argv. Here `systems` (the driver set,
  `deps-systems`) is where every system verb and most domain verbs run, and `salesforce`
  (`deps-salesforce`: cumulusci-plus, snowfakery — sqlalchemy<2, which the driver set's
  dialects contradict) is where the org's data plane runs. A backend declares the toolset each
  plane needs (`sys_toolset` / `dom_toolset`, formerly `sys_env` / `dom_env`); a model may
  override it (`models/<model>/model.json`); when that is not the toolset `domain` runs in, it
  re-dispatches the invocation through `tdd-exe` to the sibling tool of that toolset —
  `domain-sf`, a hidden tool in `salesforce`. The driver-free venv `c` had no reason to exist
  once envs are built ahead of time. Both toolsets pin Python 3.12 (`[tool.tdd] python`):
  several drivers ship no wheels for the newest CPython.
- **Generic pieces moved to `common-core`**, for any command to use: the parallel child runner
  (`batch`, on the event model), free ports (`ports`), `passwords`, `docker`, `ssh`, 1Password
  `secrets`, `data_dir()` and `latch`. `common.systems` keeps `shell`/`ssh` shims so the
  backends' imports read as before.
- **State moved to `<tdd_dir>/data/system` and `data/domain`** (was `$TD_BACKENDS_DIR`,
  `~/.tabsdatax/{systems2,domains2}`); `--sys-dir` / `--domain-dir` still override.
- **Output follows the guidelines** through the family's `console` adapter: `out`/`good` are
  `info`, `bad`/`warn` are `warn`, the last `good` line becomes the run's `ok` message (held
  back so it prints once), and `console.result()` records what `--out json` used to print —
  the `ok` event now carries it. The chatty verbs still run under an fd-level detail log
  (`/tmp/tdd-<tool>-<verb>-<name>-<stamp>.log`) so subprocess output never reaches the event
  stream; that same file is the failure log. Batch children run through `tdd-exe` in view
  mode with their output captured.
- **`system crypto-key`** is new: what `envx set-crypto` did — `op read
  op://$ONE_PASSWORD_EMPLOYEE_VAULT/DevSecrets/TD_BACKENDS_CRYPTO_KEY`, at least 12
  characters — as a verb next to `secrets`, so the key that every other verb needs is
  fetched the same way as the rest. The shell command **`tdd env set --crypto` /
  `--secrets`** runs the Python verb with `--as export` and `eval`s the lines into the
  current shell (`--secrets` defaults its `--vault` to `1p:$ONE_PASSWORD_DEV_XP_VAULT`);
  `tdd env unset --secrets` reads `TD_BACKENDS_SYSTEMS` for the prefixes to remove.
- **Option changes forced by the guidelines**, otherwise names are as they were: `-f` is gone
  (`--force`); `--out json` is gone (`--format json`); `info`'s and `secrets`' own
  `--format`/`--out json|export|unset` became `--as`; `clear-venvs` is gone; the parallelism
  variable is `TDD_PARALLELISM`; exit codes are 0/1 (usage errors included).

## Two rules that make it work

**1. No uv workspace.** A workspace forces one unified resolution — two toolsets with
conflicting pins simply fail to lock:

```
× No solution found when resolving dependencies:
╰─▶ Because deps-demo-env1 depends on packaging==24.0 and deps-demo-env2
    depends on packaging==25.0, we can conclude that they are incompatible.
```

Each `toolset-*` is an independent project with its own committed `uv.lock`. Verified:

```
tdd-venvs/demo-env1   packaging=24.0
tdd-venvs/demo-env2   packaging=25.0
```

**2. `tdd-exe` execs, it does not activate.** Console scripts in a venv carry an absolute
interpreter shebang, so activation is never needed and `uv run` only adds latency:

```python
env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
env["TDD_DIR"] = str(dir_)
env["TDD_TOOL"] = tool
os.execve(str(exe), [str(exe), *argv], env)
```

The tool inherits the caller's cwd, which is what file-touching tools need. The toolset's own
`bin/` goes first on `PATH` so a tool shelling out finds its own pinned binaries;
`$TDD_DIR` and `$TDD_TOOL` let it reach sibling tools and its own catalog entry.

Parse only what precedes the command, then hand everything after it to the tool verbatim —
otherwise `tdd demo-exe1 --check` has its `--check` eaten by the dispatcher.

## Shell commands

`tdd-exe` can never change the calling shell. Commands that must live as shell functions
instead, one file per command under `packages/tabsdata-dev-shell/scripts/unix/`, sourced by
`tdd-source.sh` at start-up. `tdd-env` is the one real command — a group routing `activate
--toolset <ts>` and `deactivate` inside one function; the how-to is
[building-a-shell-command.md](building-a-shell-command.md).

Each file registers with `tdd_fn_register [--demo] <name> "<summary>"` and defines
`tddfn_<name>`. The registry is a newline-separated string of `name|summary|kind|reqs` rather
than an associative array, so `tdd-source.sh` works in bash 3.2 as well as zsh — which is also
why a summary must not contain `|`. `reqs` is filled by the loader from the `<file>.bin-reqs.txt`
beside each script, and checked by `tdd-fn` just before the command runs.

The files ship inside `tabsdata-dev-shell`, installed into `<tdd_dir>/tdd-venvs/shells`, and
`tdd-source.sh` asks that env's python where they landed rather than hardcoding a site-packages
path. `tdd-source.sh` itself is `tddsrc.sh` with `__TDD_DIR__` substituted at install time —
which is what lets several tdd dirs each carry a `tdd-source.sh` pointing at itself.

`tdd-exe` is reached through a wrapper function pointing at `<tdd_dir>/tdd-venvs/tdd/bin/tdd-exe`,
so that env's other binaries stay off `PATH`. The `tdd` function passes `--dir` on as a single
`--dir=<path>` token: zsh does not word-split unquoted parameters, and the two-word form
reached `tdd-exe` as one argument there.

## External binary requirements

Both halves declare the binaries they need in a `bin-reqs.txt` — a Python tool at its package
root, a shell command beside its script as `<file>.bin-reqs.txt`; `common.bin-reqs.txt` holds
what `common.sh` itself needs (`jq`) and is folded into every shell command's list, by the
loader and by the generator alike. One bare name per line,
blank lines and `#` comments ignored; a line carrying a path or a version specifier is rejected
as a mistake. That is the entire format, and it is why the file is `.txt`: no parser, no
dependency, no schema to version. **The file is owned by the command's author** — nothing
generates it. The demo Python tools have none; the demo shell commands declare
`whoami`/`hostname` and `uname`/`date`.

`tdd --reqs [name]` reports per binary, marks shell commands `(shell)`, and exits non-zero if
anything is missing:

```
demo-exe1:  (no external requirements)
demo-fn1 (shell):
  [ok]      whoami               /usr/bin/whoami
  [missing] hostname
```

Reqs come from the **catalog**, not the source tree, so this works before any env is built
and from a wheel install — checking a fresh machine's prerequisites is exactly when nothing
exists yet. The lookup is a plain `shutil.which` against the ambient `PATH`, deliberately
*not* the augmented `PATH` a tool receives at exec time. `cargo make check` runs it, so a
declared-but-absent binary fails CI: the gate doing its job.

### Enforced, not trusted

A declaration that nothing checks goes stale on the author's machine and fails on someone
else's. Each half enforces it the way its shape allows:

- **Python: a choke point.** `common-core` owns process launching, so `proc.run()` refuses a
  binary that is neither *pinned* by the toolset (a `deps-*` pin sits in the toolset's `bin/`,
  which is why a pinned `ruff` needs no entry) nor *declared*. Anything else raises
  `UndeclaredRequirement`. Skipped when `$TDD_TOOL` is absent, so tools stay importable under
  a bare `pytest` and runnable directly during development — and so a clean direct run is not
  evidence the declarations are complete.
- **Shell: a pre-check.** A function has no single place its external calls go through, so
  `tdd-fn` runs `command -v` on every declared name *before* calling `tddfn_<name>` and refuses
  with the full list (an `error` event, exit 1). Sourcing never checks anything: it must stay cheap and must
  not fail, or one missing binary would break every shell that sources `tdd-source.sh`.

## What the build requires

Install instructions are in the [README](../README.md). What they rest on:

**`uv` and `cargo-make`. Nothing else.** No venv, no active Python — verified with a `PATH`
containing only those two plus coreutils and no `python` at all:

```
python      = NONE
VIRTUAL_ENV = <unset>
---
cargo make wheels     ->  7 wheels + 4 locks
cargo make install    ->  4 envs built
```

Every task reaches Python through `uv`, which brings its own interpreter. `uv` is a hard
requirement everywhere and says so plainly rather than failing obscurely:

```
tdd: uv is a hard requirement, install it
```

Sourcing belongs in **`~/.zshrc`**, not `~/.zprofile`. `tdd` is a shell *function*, and
functions are not exported to child shells — `.zprofile` runs only for login shells, so a
`tdd` defined there would vanish in any nested `zsh`, tmux pane, or subshell. `.zshrc` runs
for every interactive shell, which is exactly the scope a function needs.

One wrinkle on this machine: `uv` on `PATH` resolves to a **pyenv shim**
(`~/.pyenv/shims/uv`) rather than `/opt/homebrew/bin/uv`. That works in an interactive shell
where pyenv is initialized, but it fails in a minimal environment — a cron job, a CI runner,
a `env -i` shell — with `pyenv: uv: command not found`. Worth knowing before wiring any of
this into automation.

## One version

`VERSION` at the repo root holds the release version and nothing else — a bare `0.1.0`. It
is the single source in three places:

- **Every wheel.** No `pyproject.toml` states a version; each declares `dynamic = ["version"]`
  and reads `../../VERSION` through hatchling's regex source. Bump the file and every wheel
  follows. The generated `toolset-*` projects have no build backend, so the generator writes
  the value in for them.
- **Inside `tabsdata-dev-tdd`.** The file is force-included as package data, so a wheels-mode
  install — which has no checkout — still knows what it is. Editable installs read the root
  file directly, the same asymmetry `tabsdata_dev.shell` absorbs for its scripts.
- **In the tdd dir.** `tdd-install` stamps `<tdd_dir>/VERSION`, and `tdd --version` reports
  *that*: it describes what was built there, which in editable mode can lag the checkout until
  the next init. Before any init it falls back to the shipped copy. `tdd doctor` shows both when
  they differ, as a note rather than a failure.

`cargo make wheels` also drops the file beside the wheels, so `ls target/wheels` (or
`<tdd_dir>/wheels`) says which release is staged without unzipping anything.

The one constraint: wheels build only from a checkout, because `../../VERSION` has to exist.
That is already true of everything else here.

## Two init modes, one catalog

| | `tdd-install` (default) | `tdd-install --from-wheels` |
|---|---|---|
| for | developing the tools | shipping a pinned tool set |
| driven by | `cargo make install -- --editable` (`cargo make dev`) | `cargo make install` |
| first-party code | editable links into the checkout | wheels from `<dir>/wheels` |
| third-party code | each toolset's committed `uv.lock` | exported lock, pinned **and hashed** |
| needs a checkout | yes | **no** |
| source edits | live everywhere instantly | require a rebuild |
| repo moved or deleted | every env breaks | envs unaffected |

Wheels mode installs the exported lock first with `--require-hashes`, then the first-party
wheels with `--no-deps` so the resolver never reopens a decision the lock already made. The
locks are produced by `uv export` per toolset with every first-party package excluded, so
they carry exactly the transitive third-party closure:

```
demo-env1.lock   packaging==24.0   (third-party closure, hashed)
demo-env2.lock   packaging==25.0
tdd.lock         empty — stdlib only
shells.lock      empty — no dependencies
```

An absent lock is an error rather than a fallback: silently resolving fresh is the failure
this mode exists to prevent.

One trap in this mode: **uv caches wheels by filename**, and a rebuilt first-party wheel keeps
its name because `VERSION` did not change, so a second `cargo make install` once silently kept
the previous build's `tdd-exe`. Two guards, on purpose: `cargo make install` starts by evicting
every `tabsdata-dev-*` package from the uv cache (`uv cache clean`), and `tdd-install` itself
passes `--refresh` on the first-party step so a standalone `tdd-install --from-wheels` on a
staged dir is safe too. Third-party wheels are immutable per version, so their cache stays in
use.

## Rule: tools bundle their resources

**Every resource a tool needs ships inside its own package and is located through the
installed package. Never from an assumed or fixed location in the OS.**

That means templates, schemas, config defaults, SQL files, shell snippets, sample data — all
of it inside the distribution, found with `importlib.resources`:

```python
from importlib.resources import files

TEMPLATE = files("tabsdata_dev.tool.audit").joinpath("templates/report.md").read_text()
```

Forbidden, all of them for the same reason:

| Anti-pattern | Why it fails |
|---|---|
| `/usr/local/share/tdd/report.md` | not installed by anything; absent on a fresh machine |
| `~/.tdd/templates/report.md` | the tdd dir holds envs, not tool assets; `--dir` moves it |
| `open("templates/report.md")` | depends on the caller's cwd, and tools inherit it |
| `Path(__file__).parents[4] / "templates"` | assumes a source checkout; wheels have no `src/python/main` |
| `os.environ["TDD_HOME"] + "/..."` | a fixed OS location wearing a variable's clothing |

The reason is that the same code has to run in three different shapes, and only
package-relative lookup survives all of them:

1. an **editable** install, where the files are still in the checkout,
2. a **wheel** inside a toolset venv, where they sit in site-packages,
3. a **relocated** tdd dir, unzipped at a path nobody predicted.

`tabsdata_dev.shell` is the worked example. It carries `tddsrc.sh` and `scripts/unix/*.sh`,
and exposes `scripts_dir()` / `source_template()` rather than letting anything guess a path —
which is why `tdd-source.sh` asks the shells env where its command files are instead of
hardcoding a site-packages layout. It also has to absorb a real asymmetry: `force-include`
puts those files beside the module in a wheel, but an editable install copies nothing, so
they stay at the package root. The lookup checks both.

`bin-reqs.txt` is the deliberate exception, and it proves the rule. External binaries are the
one class of resource that genuinely cannot be bundled — so they get an explicit declaration,
a `[missing]` report, and runtime enforcement, rather than a silent assumption that
something exists at some path.

## Relocatable environments

Every env `tdd-exe` creates is built with `uv venv --relocatable` and `UV_LINK_MODE=copy`, so
uv rewrites the console-script shebangs to resolve the interpreter relative to the script:

```sh
#!/bin/sh
'''exec' "$(dirname -- "$(realpath -- "$0")")"/'python3' "$0" "$@"
```

`tdd-source.sh` locates itself rather than trusting a baked path, so `TDD_DIR` follows the
tree wherever it lands. A hardcoded value would have defeated the whole thing on the first
move.

**What this buys: a tdd dir can be moved, renamed, copied or zipped anywhere on a machine and
keeps working, with no reinstall.** Verified — built at one path, zipped, unzipped under a
different name at a different path, then run:

```
TDD_DIR resolved to: .../moved/tdd        (built at .../reloc)
tdd help --demo                      -> demo-exe1, demo-exe2, ...
tdd demo-exe2                        -> demo-exe2
tdd tdd-env activate --toolset demo-env2 -> prefix: .../moved/tdd/tdd-venvs/demo-env2
```

**What it does not buy: machine independence.** The interpreter is not inside the tree.
`bin/python` is a symlink to the uv-managed Python by absolute path:

```
bin/python -> /Users/tucu/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14
home = /Users/tucu/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin
```

Move that dir away and the venv stops working. So a zipped tdd dir runs on another machine
only if it has the same uv Python at the same absolute path — which in practice means the same
username and `uv python install` of the same version. Otherwise: `uv python install`, or
rebuild with `tdd-install`.

That failure has to be reported from the shell side. With the interpreter gone `tdd-exe`
cannot start at all, so no Python-side check could ever run; the `tdd-exe` wrapper in
`tdd-source.sh` tests for a dangling `bin/python` and says so plainly:

```
tdd: the interpreter for .../tdd-venvs/tdd is unreachable.
     This tdd dir was built for a different machine or its uv
     Python was removed. Rebuild here with tdd-install,
     or restore it with: uv python install
```

`tdd doctor` checks the interpreter of every *other* env, where tdd-exe's own env being
healthy means it can actually run.

Two further notes:

- **Editable mode is not relocatable.** `.pth` files hold absolute paths into the checkout.
  Relocation is a property of wheels mode; editable trees stay put.
- **True machine independence would mean bundling a Python distribution** into the tdd dir and
  pointing every `pyvenv.cfg` at it. That is a real option and not much work, but it is not
  what is built today — see the open items.

## Keeping the common floor consistent

`common-*` declares ranges and every toolset locks independently, so the shared floor can
diverge — but only through **lockfile timing skew**: `toolset-demo-env1` locked in January and
`toolset-demo-env2` added in June resolve `rich>=13` differently, and the committed locks then
disagree. Toolsets locked in one operation resolve identically.

So the fix is a habit plus a check, both in place. Re-lock everything in one pass with
`tdd-install --relock`, and `cargo make gen` compares the committed locks:

```
warning: rich drifted across toolsets (demo-env1=15.0.0, demo-env2=13.7.1); run `tdd-install --relock`
```

The check ignores anything a `deps-*` bundle pins deliberately — `packaging` being 24.0 in
`demo-env1` and 25.0 in `demo-env2` is the entire point of having two toolsets, not drift.

## cargo-make tasks

| Task | What it does |
|---|---|
| `cargo make help` | every task with its options (also the default task) |
| `cargo make install` | wheels + locks → `<dir>/wheels`, then build every env from them |
| `cargo make install -- --editable` (`-e`) | every env editable from this checkout instead; `cargo make dev` is the shortcut |
| `cargo make uninstall` | delete the tdd dir; print the `source` line to remove from `~/.zshrc` |
| `cargo make gen` | regenerate the toolset packages and the catalog |
| `cargo make wheels` | wheels + exported locks into `target/wheels/` |
| `cargo make test` | every package's tests, each in the right env |
| `cargo make lint` / `fmt` | ruff over `packages/`, at the version pinned in `Makefile.toml` |
| `cargo make reqs` | `tdd-exe --reqs` for every tool |
| `cargo make check` | lint + test + reqs — what CI runs |
| `cargo make clean` | drop build artifacts and caches |

`install` and `uninstall` take an optional target dir. Note the `--`: cargo-make forwards
task arguments after it.

```bash
cargo make install -- --dir /tmp/t2
cargo make uninstall -- --dir /tmp/t2
```

`uninstall` is an `rm -rf` of a caller-supplied path, so it refuses any directory without a
`catalog.json` — the marker `tdd-install` writes — rather than trusting a mistyped `--dir` or a
stray `TDD_DIR`. It does not edit shell rc files; it prints the `source .../tdd-source.sh` line
to remove and points at any rc file that contains it.

Ordering rules baked into the task graph, because getting them wrong ships something subtly
wrong:

- **`wheels` depends on `gen`.** The catalog is package data inside `tabsdata-dev-tdd`, so
  building wheels first would ship a stale catalog. `gen` runs
  `python -m tabsdata_dev.tdd.generate` from an ephemeral `uv run` env, so it works before
  anything is installed.
- **`install` runs `tdd-install` out of the wheel it just built**, not the source tree, so a
  wheels-mode install is genuinely non-editable. With `--editable` it skips `wheels` entirely
  and runs `tdd-install` from an ephemeral env linked to the checkout — so `wheels` is invoked
  from inside the task rather than declared as a dependency.
- **Re-running `install` over an existing tdd dir rebuilds it.** `_make_venv()` passes
  `uv venv --clear`; without it uv refuses to overwrite an existing venv, which made the
  documented "re-run `tdd-install` after a dependency change" fail.

## Gotchas found while building this

- Hatchling cannot infer wheel contents for a `src/python/main` layout; without
  `only-include` + `sources` the build fails with *"Unable to determine which files to
  ship"*.
- **`force-include` has no effect on an editable install.** The shell package's `tddsrc.sh`
  and `scripts/` are force-included into the wheel beside the module, but an editable install
  copies nothing, so they stay at the package root. `tabsdata_dev.shell` checks both
  locations rather than assuming one.
- Namespace packages need **no** `__init__.py` at `tabsdata_dev/`, `tool/`, `common/`, or
  `deps/`. One stray `__init__.py` in a shared prefix breaks every other distribution's
  contribution.
- A `deps-*` package with no logic still needs something to build — an empty
  `__init__.py` is enough.
- `uv pip install --no-deps` blocks first-party resolution too, which is why the catalog
  carries `members`.
- Don't glob `tdd-venvs/` to find toolsets; `tdd-venvs/` also holds `tdd` and `shells`.
- `cargo make --quiet` silences the *task's* output too, not only cargo-make's own banners.
  `cargo make help` under `--quiet` prints nothing.
- Let a wrapped tool write to the terminal directly. Capturing `ruff`'s output and
  re-emitting it through `rich` mangles the formatting for no gain.

## Generator checks

Enforced by `cargo make gen` / `tdd-install`:

- exactly one `tabsdata-dev-deps-*` per tool — zero or two is an error
- every tool declares at least one `[project.scripts]` entry point
- no duplicate tool names across toolsets
- no tool name that is a builtin (`doctor`, `info`, `help`) or a shell command — they
  share one argument position, and the shell function checks its own registry first, so a
  collision would shadow the tool silently
- every shell script registers at least one command; no two register the same name
- every `bin-reqs.txt` line, in either half, is a bare binary name; a shell `*.bin-reqs.txt`
  has a script beside it to apply to
- every toolset has a matching `deps-*` bundle
- shared dependencies have not drifted across toolset locks

Worth adding next: verify a tool's imports resolve to its own `deps-*` or a `common-*`.
Pants enforces exactly this for its resolves, and it is the one guarantee the package layout
alone cannot give you.

