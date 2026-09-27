<!--
Copyright 2026 Tabsdata Inc.
-->

# Building a Python command

A Python command is one package, `packages/tabsdata-dev-tool-<name>/`, depending on exactly one
dependency bundle (`tabsdata-dev-deps-<toolset>`) -- that single dependency puts it in a toolset,
a venv shared with every other tool naming the same bundle; there is no registration step.
Copy `tabsdata-dev-tool-gsx`, the smallest tool with subcommands. Options, exit codes
and output follow [command-cli-guidelines.md](command-cli-guidelines.md).

## 1. Pick or create the bundle

Use an existing bundle when your dependencies are covered or can be added to it (a pin added to
`deps-<toolset>/pyproject.toml` applies to every tool in that toolset -- the trade for sharing a
venv). Create one when they *cannot co-resolve* with an existing bundle or are too heavy to put
in every env. Pins only, no logic; the empty `__init__.py` exists because a distribution needs
something to build:

```toml
[project]
name = "tabsdata-dev-deps-legacy"
dynamic = ["version"]
description = "pins for the legacy toolset"
requires-python = ">=3.11"
dependencies = ["pytest==8.4.2", "packaging==23.2", "pydantic<2"]

[tool.tdd]
python = "3.12"            # optional: the interpreter the toolset's venv is created on

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

`deps-legacy` -> toolset `legacy` -> `<tdd_dir>/tdd-venvs/legacy`. Keep `pytest` pinned: it is
what runs the tool's tests inside its own env.

## 2. Create the tool package

```
packages/tabsdata-dev-tool-audit/
├── pyproject.toml
├── DESIGN.md                                     # section 4
├── bin-reqs.txt                                  # only if you shell out to something external
└── src/python/
    ├── main/tabsdata_dev/tool/audit/__init__.py  # def main() -> int
    └── test/test_audit.py
```

```toml
[project]
name = "tabsdata-dev-tool-audit"
dynamic = ["version"]
description = "audit dependency pins"           # the `tdd help` summary
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

The generator enforces: exactly one `deps-*`; at least one `[project.scripts]` entry; a name that
is not a tool, a builtin (`doctor`, `info`, `help`) or a shell command. No `__init__.py` at
`tabsdata_dev/` or `tabsdata_dev/tool/` (namespace packages). Every file starts with the house
copyright header.

Write only the body; `common-core` implements the contract once:

```python
from tabsdata_dev.common.core import cli, render

def body(args, out: render.Renderer) -> int:
    out.info("scanning")                      # always shown; json line or stderr
    out.debug(f"paths: {args.paths}")         # only with --verbose
    if not args.paths:
        return out.error("nothing to audit")  # writes the /tmp log, returns 1
    return out.ok("3 pins checked", pins=3)   # the one result, returns 0

def configure(parser):                        # your options; the common ones exist already
    parser.add_argument("paths", nargs="*")

def main() -> int:
    return cli.run("audit", "audit dependency pins", body, configure=configure)
```

`cli.run()` adds `--help`, `--verbose`/`-v`, `--format json|view`, renders argument errors and
exceptions as `error` events and maps everything onto exit 0/1. Never `print`. Subprocesses go
through `proc.run()`; another tool through `proc.run_tool()` (never an import -- it lives in
another venv). Keep options long and `-`-separated: a user can preset any of them in
`$TDD_DIR/<name>.toml`, and `tdd` merges those in before your tool starts -- nothing
to do on your side.

## 3. Declare external binaries

Anything the tool shells out to that the toolset does not provide goes in `bin-reqs.txt`, one
bare name per line, `#` comments allowed; omit the file when there is nothing. A binary is
legitimate either **pinned** by your `deps-*` (it sits in the toolset's `bin/`, first on `PATH`)
or **declared** here; `proc.run()` refuses anything else. `tdd <tool>` refuses to dispatch when a
declaration is missing (`--help` excepted); `tdd --reqs` reports; `cargo make check` fails.
Everything else ships inside the package and is read with
`importlib.resources.files("tabsdata_dev.tool.audit")` -- never an OS path, the cwd or
`__file__` arithmetic.

## 4. Write DESIGN.md

Beside `pyproject.toml`, with the house header, short -- a screen at most: what the tool is for
and why it exists; its shape (toolset and why, dependencies, entry point, `bin-reqs`, where its
state lives); and the handful of decisions a reader cannot see from the code. Do not repeat
`--help`. `tabsdata-dev-tool-tdk/DESIGN.md` is the smallest real example; a test fails when a
tool has none.

## 5. Test, build, run

```bash
cargo make test                    # every package under the interpreter it ships with
cargo make install -- --editable   # rebuild every env, linked to this checkout
tdd help && tdd audit
```

Tests in `src/python/test/` run in the toolset venv; `bin-reqs` enforcement is off while
`_TDD_TOOL` is unset, so a clean test run does not prove the declarations complete. Source edits
are live in an editable install; dependency changes, new tools and entry points need
`cargo make install -- -e` (which also regenerates the toolset package and the catalog --
commit them, never edit them). While iterating, `tdd tdd-env activate --toolset legacy` puts the
toolset's `bin/` on `PATH` so `audit` runs without `tdd`. `[tool.tdd] hidden = true` hides
plumbing another tool dispatches to from `tdd help` -- as does a name starting with `_`, the
convention for plumbing (`tdd -x` lists them all); `disabled = true` comments the tool out
(the generator treats the package as absent; the code and tests stay). Reuse before
writing: `common.core` has `batch`, `ports`, `passwords`, `docker`, `ssh`, `secrets`,
`datadir.data_dir()`, `latch`, `managedvenv` + `launcher`; family code goes in a
`common-<family>`.
