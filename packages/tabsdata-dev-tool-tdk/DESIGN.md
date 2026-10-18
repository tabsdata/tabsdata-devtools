<!--
Copyright 2026 Tabsdata Inc.
-->

# tdk

`tdd tdk ARGS...`: run tabsdata's `tdk` inside the venv last activated -- a managed one
(`tdd venv create|activate`), run through its manager, or any venv active in the calling shell --
and say first which venv that is, and why.

## Shape

- Toolset `launchers` (pins nothing); depends on `deps-launchers`, `common-core`. Entry point
  is `common.core.launcher.run("tdk")`.
- `bin-reqs`: `tdk` and `uv` required; `conda` optional, checked only for a conda venv. A pyenv
  venv runs its program by path, so pyenv is never called; on Windows only uv venvs are supported.

## How it works

- No options of its own: **every** argument, `--help`/`--format`/`--version` included, goes to
  the program -- the one sanctioned exception to the CLI guidelines.
- Fails with "a venv act- **The venv last activated wins** (`managedvenv.select`), because two venvs with two tabsdata
  versions is exactly when it matters which one ran. `tdd venv activate` really activates, so the
  venv the shell has active -- `VIRTUAL_ENV`, else a conda env other than base -- is the latest:
  the managed one tdd entered, a project venv entered on top of it by hand, or the venv a smoke
  script's own `tdd venv create` activated in its shell, for every `tdd tdk` the script runs
  however deep (the dispatcher passes both variables through untouched). The exception is a
  `_TDD_VENV` set by hand, inline (`_TDD_VENV=X tdd tdk`) or exported: later still. `tdd venv`
  exports the name it activated twice, `_TDD_VENV` and `_TDD_VENV_ACTIVATED`, so a `_TDD_VENV`
  that differs from the second was set by hand; one that matches is only the record and yields to
  the shell. Nothing active and no record: an error naming both ways to get one. Rejected:
  recording the venv once at the outermost `tdd` -- that is `tdd smoke run`, and it would pin the
  caller's venv over the one the script created.
- The choice is the first line out, an `info` event (`venv`, `venv_path`, `venv_manager`,
  `venv_reason`) on stderr in view, so it lands in a caller's log -- xp's `run.log` has it for
  every call -- without touching the program's stdout. Refused: a venv without the program (a
  manager falling back to `PATH` would find this launcher itself), and one of tdd's own toolset
  venvs activated by hand (its `tdk` *is* this launcher).
- Launch: a managed venv through its manager -- uv `VIRTUAL_ENV=DIR uv run --active --no-project`,
  conda `conda run --prefix DIR --no-capture-output DIR/<bin>/tdk` (by path: in a shell where
  that env is active a bare name found this launcher and recursed), pyenv `DIR/<bin>/tdk` --
  each with the venv's directories first on `PATH`. A venv tdd does not manage is active in the
  caller's shell by construction, so whatever activating it set up is inherited: the program by
  path with its directories first is all it takes. `<bin>` is asked of the venv, not the platform
  (`bin/`, or `Scripts\` with `tdk.exe` for one built on Windows; a Windows conda env adds its
  root and `Library\bin`), as `tddsrc.ps1` does.
 true`: with no options of its own there is nothing to configure, so it
  owns no `<command>.toml` and has no `config` action (invariant 11). The program runs in the
  cwd the user is in.
- Only what happens *before* the program runs is the launcher's, and it is reported the
  guidelines' way: a non-zero exit comes back as one error event carrying `status`, and Ctrl-C --
  how a server is stopped -- is one warning and exit 1, with no failure log, because a log for a
  deliberate interrupt is noise.
- `tdk` refuses to run under an AI agent (it checks `CLAUDECODE`); an agent runs it only when the user asks, with that variable unset.
