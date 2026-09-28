<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-tdd

The executable half: `tdd-exe` (dispatch, `help`, `_doctor`, `info`, `--reqs`, `--defaults`,
`--porcelain`) and `tdd-install` (the only way to build a tdd dir), plus the generator
(`cargo make gen`). Standard library only, forever: it is what exists before any toolset does.

## Shape

- Entry points `tdd-exe`, `tdd-install`; module `tabsdata_dev.tdd`; env `<tdd_dir>/tdd-venvs/tdd`.
- `catalog.json` ships as package data: toolsets, members, tools (toolset, summary, reqs, flags),
  shell commands, interpreter pins, a fingerprint. Names only, never paths.
- `VERSION` is force-included so a wheels install knows its version without a checkout.

## How it works

- **Dispatch execs, never activates**: `<tdd_dir>/tdd-venvs/<toolset>/bin/<tool>` with the
  toolset's `bin/` first on `PATH`, `TDD_DIR` and `_TDD_TOOL` exported. Everything after the
  command word reaches the tool verbatim. Before exec, every `bin-reqs` binary must resolve
  (a pyenv/asdf/mise shim only if its manager wires it) unless `-h`/`--help` is among the args.
- **Defaults** (`defaults.py`): the `[options]` / `[options.<action>]` tables of
  `<tdd_dir>/<cmd>.toml` merged
  under the typed options, appended -- or inserted before a `--`, after which nothing is an
  option (a tool's free-form tail, `tdd mexe ... -- git log --output x`); the `tdd` function only
  rebuilds argv from `tdd-exe --defaults`.
- **Generator** (`discover.py`, `generate.py`): reads every `tool-*`/`deps-*`/`common-*`
  `pyproject.toml` and the shell scripts, writes the `toolset-*` packages and the catalog, and
  rejects layout mistakes (one `deps-*` per tool, name collisions, bad `bin-reqs`, lock drift).
  A tool with `[tool.tdd] disabled = true` is skipped whole, before any check: commented out.
- **Install** (`initialize.py`): one relocatable venv per toolset (`uv venv --relocatable`,
  `UV_LINK_MODE=copy`), editable from the checkout or from `<dir>/wheels` with hashed locks;
  copies the catalog (the "initialized" marker), stamps `VERSION`, writes `tdd-source.sh`.
- **Output** goes through `render.py`, a byte-identical twin of `common.core.render` (a test
  fails when they diverge) because this package cannot import `common-core`.
