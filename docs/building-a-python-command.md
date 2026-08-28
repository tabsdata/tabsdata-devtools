<!--
Copyright 2026 Tabsdata Inc.
-->

# Building a Python command

A Python command is one package, `packages/tabsdata-dev-tool-<name>/`, that depends on exactly
one dependency bundle (`tabsdata-dev-deps-<toolset>`). That single dependency is what puts it
in a toolset — a venv shared with every other tool naming the same bundle — and there is no
registration step beyond it. Copy `tabsdata-dev-tool-demo-exe1` and drop its
`[tool.tdd] demo = true`. Its options, exit codes and output follow
[command-cli-guidelines.md](command-cli-guidelines.md).

## 1. Pick or create the bundle

**Existing bundle** — your dependencies are already covered, or can be added to it. Adding a
pin to `tabsdata-dev-deps-<toolset>/pyproject.toml` applies to every tool in that toolset;
that is the trade for sharing a venv.

**New bundle** — when your dependencies *cannot co-resolve* with an existing one (a different
major of a shared library), or are heavy enough that you do not want them in every env. Pins
only, no logic; the empty `__init__.py` exists because a distribution needs something to build:

```
packages/tabsdata-dev-deps-legacy/
├── pyproject.toml
└── src/python/main/tabsdata_dev/deps/legacy/__init__.py
```

```toml
[project]
name = "tabsdata-dev-deps-legacy"
dynamic = ["version"]
description = "pins for the legacy toolset"
requires-python = ">=3.11"
dependencies = ["pytest==8.4.2", "packaging==23.2", "pydantic<2"]

[tool.hatch.version]
path = "../../VERSION"
pattern = '^(?P<version>\S+)'

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
only-include = ["src/python/main/tabsdata_dev"]
sources = ["src/python/main"]
```

The name after `tabsdata-dev-deps-` is the toolset name and the env directory:
`deps-legacy` → `toolset-legacy` → `<tdd_dir>/tdd-venvs/legacy`. Keep `pytest` pinned in every
bundle — it is what lets the tool's tests run inside its own env. `common-core` joins every
toolset automatically, so its tests run there too; any other `common-*` joins a toolset only
when one of its tools depends on it.

If the bundle's drivers need a specific interpreter (no wheels for the newest CPython yet),
pin the minor in the bundle and the toolset's venv is created on it:

```toml
[tool.tdd]
python = "3.12"
```

## 2. Create the tool package

```
packages/tabsdata-dev-tool-audit/
├── pyproject.toml
├── bin-reqs.txt                                  # only if you shell out to something external
└── src/python/
    ├── main/tabsdata_dev/tool/audit/__init__.py  # def main() -> int
    └── test/test_audit.py
```

```toml
[project]
name = "tabsdata-dev-tool-audit"
dynamic = ["version"]                           # every package reads the repo-root VERSION
description = "audit dependency pins"           # becomes the `tdd help` summary
requires-python = ">=3.11"
dependencies = ["tabsdata-dev-deps-legacy", "tabsdata-dev-common-core"]

[project.scripts]
audit = "tabsdata_dev.tool.audit:main"          # the key is the word after `tdd`

[tool.hatch.version]
path = "../../VERSION"
pattern = '^(?P<version>\S+)'

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
only-include = ["src/python/main/tabsdata_dev"]
sources = ["src/python/main"]

[tool.pytest.ini_options]
testpaths = ["src/python/test"]

[tool.uv.sources]
tabsdata-dev-common-core = { path = "../tabsdata-dev-common-core", editable = true }
tabsdata-dev-deps-legacy = { path = "../tabsdata-dev-deps-legacy", editable = true }
```

Rules the generator enforces: exactly one `deps-*` dependency; at least one
`[project.scripts]` entry; a name that is not already a tool, a `tdd` builtin (`doctor`,
`info`, `help`), or a shell command. No `__init__.py` at `tabsdata_dev/` or
`tabsdata_dev/tool/` — they are namespace packages, and one stray file breaks every other
distribution's contribution. Every file starts with the house copyright header.

`main()` returns an exit code, and [command-cli-guidelines.md](command-cli-guidelines.md)
says what it must accept and print. `common-core` implements that once — write only the body:

```python
from tabsdata_dev.common.core import cli, render

def body(args, out: render.Renderer) -> int:
    out.info("scanning")                     # shown always; json line or stderr
    out.debug(f"paths: {args.paths}")        # only with --verbose
    if not args.paths:
        return out.error("nothing to audit") # writes the /tmp log, returns 1
    return out.ok("3 pins checked", pins=3)  # the one result, returns 0

def configure(parser):                       # your own options; the common ones exist already
    parser.add_argument("paths", nargs="*")

def main() -> int:
    return cli.run("audit", "audit dependency pins", body, configure=configure)
```

`cli.run()` adds `--help`, `--verbose`/`-v` and `--format json|view`, renders argument errors
and uncaught exceptions as `error` events (traceback in the log), and maps everything onto
exit 0 or 1. `render.Renderer` is the model: every event carries the command name, its kind and
message, plus your fields; json is one line per event, view puts `ok` on stdout and the rest on
stderr, both coloured by kind on a terminal. Do not `print`. For subprocesses use
`proc.run()`; `parallel.map_bounded()` is there for fan-out.

**User defaults: nothing to do.** A user can preset any of your options in
`$TDD_DIR/default-opts/<name>.txt`. `tdd` merges those into the command line *before* dispatch
and prints the resolved invocation, so `sys.argv` already contains them when your tool starts,
with typed options having won. Parse as if the user had typed everything; no file to read, no
flag to check. Keep option names long and `-`-separated so they can be preset at all. (`tdd
defaults --command <name>` cannot yet show argparse built-ins, only the user's file.)

## 3. Declare external binaries

If the tool shells out to anything the toolset does not itself provide, list it in
`bin-reqs.txt`, one bare name per line, `#` comments allowed. Omit the file if there is
nothing to declare.

```
# bin-reqs.txt -- external binaries this tool needs on PATH.
git
rg      # ripgrep
```

A binary is legitimate in exactly two ways: **pinned** by your `deps-*` (it then sits in the
toolset's `bin/`, which `tdd` puts first on `PATH` — a pinned `ruff` needs no entry), or
**declared** here. `common.core.proc.run()` refuses anything else with `UndeclaredRequirement`,
so the file cannot quietly go stale. `tdd --reqs` reports every declaration as `[ok]` or
`[missing]` against the ambient `PATH`, and `cargo make check` fails on a missing one.

Everything else the tool needs — templates, schemas, sample data — ships **inside the
package** and is read with `importlib.resources.files("tabsdata_dev.tool.audit")`. Never a
fixed OS path, never the cwd, never `__file__` arithmetic assuming a checkout: the same code
runs editable, as a wheel, and in a relocated tdd dir.

## 4. Test

`src/python/test/` runs under the toolset's own interpreter, against the exact pins the tool
ships with:

```bash
cargo make test          # everything; each package under the interpreter it ships with
```

Each `common-*` runs once per toolset it is a member of (`common-core` everywhere, a family
library like `common-systems` only where its tools live) — that is its compatibility matrix.

Enforcement of `bin-reqs.txt` is skipped when `$TDD_TOOL` is unset, so tests can import the
tool freely — which also means a clean test run says nothing about whether the declarations
are complete. Only `tdd <tool>` dispatch checks them.

## 5. Build and run

```bash
cargo make install -- --editable   # rebuild every env, linked to this checkout
tdd help && tdd audit
```

No reinstall of `tdd-exe` is needed for a new tool: the generator derives the toolset package,
its `uv.lock`, and the catalog from your `pyproject.toml`, and the catalog is read live in
editable mode. Commit the generated `packages/tabsdata-dev-toolset-<toolset>/` — its lock is
the reproducibility record for that env. Never edit it by hand; `cargo make gen` rewrites it.

## Working on it

- **Source edits are live** in every editable tdd dir at once, `common-core` included.
  **Dependency changes, new tools and new entry points are not** — rerun
  `cargo make install -- -e`.
- **Run the entry point directly** while iterating: `tdd tdd-env activate --toolset legacy` puts
  the toolset's `bin/` on `PATH`, then `audit` works without `tdd`. Prefer that over calling
  `~/.tdd/tdd-venvs/legacy/bin/audit` by path, which does *not* get the toolset's `bin/` on `PATH`
  — a pinned binary then resolves to whatever the ambient shell offers.
- **Calling another tool** goes through the dispatcher, never an import — a tool in one
  toolset cannot import one in another: `proc.run_tool("other", *args)`. No `--dir` is needed;
  `tdd` exports `TDD_DIR` before exec.
- **Hide it while it is a sample**: `[tool.tdd] demo = true` keeps it out of `tdd help` unless
  `--demo` is passed; it still dispatches, tests and reports reqs. `hidden = true` does the
  same for plumbing another tool dispatches to (a sibling in a second toolset, like
  `domain-sf`).
- **Reuse before writing**: `common.core` has the parallel child runner (`batch.execute` with a
  `spawn`), `ports`, `passwords`, `docker`, `ssh`, `secrets` (1Password), `datadir.data_dir()`
  for your state under `<tdd_dir>/data/<command>`, and `latch`. A family of related commands
  that needs to share code across toolsets puts it in its own `common-<family>` (see
  `common-systems`).
- **Moving or renaming the checkout** breaks every editable env (`.pth` files hold absolute
  paths). `tdd doctor` says so; `cargo make install -- -e` fixes it.
