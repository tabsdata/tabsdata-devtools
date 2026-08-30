<!--
Copyright 2026 Tabsdata Inc.
-->

# km

`tdd km ARGS...`: run tabsdata's `km` inside the managed venv named by `_TDD_VENV` (exported
by `tdd venv create|activate`), through that venv's manager, so the tool works whatever the
venv type and without the venv being active in the calling shell.

## Shape

- Toolset `launchers` (pins nothing); depends on `deps-launchers`, `common-core`. Entry point
  is `common.core.launcher.run("km")`.
- `bin-reqs`: `km`, `uv`, `conda`, `pyenv` -- the program and every manager it may run under.

## How it works

- No options of its own: **every** argument, `--help`/`--format`/`--version` included, goes to
  the program -- the one sanctioned exception to the CLI guidelines.
- Fails with "a venv activated with tdd venv is required" when `_TDD_VENV` is unset, and refuses
  when the program is not installed in that venv (a manager falling back to `PATH` would find
  this launcher itself). Launch: uv `VIRTUAL_ENV=DIR uv run --active --no-project`, conda
  `conda run --prefix DIR --no-capture-output`, pyenv `DIR/bin/km` with `bin/` first on `PATH`.
- Same shape as `tdk`/`tdkserver`; nothing specific to `km`.
