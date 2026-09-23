<!--
Copyright 2026 Tabsdata Inc.
-->

# tdkserver

`tdd tdkserver ARGS...`: run tabsdata's `tdkserver` inside the managed venv named by `_TDD_VENV` (exported
by `tdd venv create|activate`), through that venv's manager, so the tool works whatever the
venv type and without the venv being active in the calling shell.

## Shape

- Toolset `launchers` (pins nothing); depends on `deps-launchers`, `common-core`. Entry point
  is `common.core.launcher.run("tdkserver")`.
- `bin-reqs`: `tdkserver`, `uv`, `conda`, `pyenv` -- the program and every manager it may run under.

## How it works

- No options of its own: **every** argument, `--help`/`--format`/`--version` included, goes to
  the program -- the one sanctioned exception to the CLI guidelines.
- Fails with "a venv activated with tdd venv is required" when `_TDD_VENV` is unset and no
  managed venv is active by path (`managedvenv.adopted()`: `VIRTUAL_ENV`/`CONDA_PREFIX` exactly
  `managed-venvs/<manager>/<name>` with its marker), and refuses
  when the program is not installed in that venv (a manager falling back to `PATH` would find
  this launcher itself). Launch: uv `VIRTUAL_ENV=DIR uv run --active --no-project`, conda
  `conda run --prefix DIR --no-capture-output DIR/bin/tdkserver` with `bin/` first on `PATH` (by
  path: in a shell where that env is active a bare name found this launcher and recursed), pyenv `DIR/bin/tdkserver` with `bin/` first on `PATH`.
- `[tool.tdd] launcher = true`: with no options of its own there is nothing to configure, so it
  owns no `<command>.toml` and has no `config` action (invariant 11). The program runs in the
  cwd the user is in.
- Only what happens *before* the program runs is the launcher's, and it is reported the
  guidelines' way: a non-zero exit comes back as one error event carrying `status`, and Ctrl-C --
  how a server is stopped -- is one warning and exit 1, with no failure log, because a log for a
  deliberate interrupt is noise.
- `tdkserver` starts a server and does not return; agents never run the real one -- test with a fake program in a scratch venv.
