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
toolset automatically, so its tests run there too.

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
description = "audit dependency pins"           # becomes the `tdd list` summary
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
`[project.scripts]` entry; a name that is not already a tool, a `tdd` builtin (`list`,
`doctor`, `info`, `help`), or a shell command. No `__init__.py` at `tabsdata_dev/` or
`tabsdata_dev/tool/` — they are namespace packages, and one stray file breaks every other
distribution's contribution. Every file starts with the house copyright header.

`main()` returns an exit code. Parse your own arguments: everything after the tool name reaches
you verbatim. `common-core` gives you `cli.parser()`, `Report` for uniform `[ok]`/`[fail]`
output, `parallel.map_bounded()`, and `proc.run()` — use the last one for every subprocess.

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

Enforcement of `bin-reqs.txt` is skipped when `$TDD_TOOL` is unset, so tests can import the
tool freely — which also means a clean test run says nothing about whether the declarations
are complete. Only `tdd <tool>` dispatch checks them.

## 5. Build and run

```bash
cargo make install -- --editable   # rebuild every env, linked to this checkout
tdd list && tdd audit
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
- **Hide it while it is a sample**: `[tool.tdd] demo = true` keeps it out of `tdd help` and
  `tdd list` unless `--demo` is passed; it still dispatches, tests and reports reqs.
- **Moving or renaming the checkout** breaks every editable env (`.pth` files hold absolute
  paths). `tdd doctor` says so; `cargo make install -- -e` fixes it.
