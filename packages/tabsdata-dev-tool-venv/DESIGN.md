<!--
Copyright 2026 Tabsdata Inc.
-->

# _venv

`tdd _venv create|delete|list|info|migrate`: the managed venvs of `tdd venv`, everything but
entering one. The leading `_` makes it plumbing -- left out of `tdd help`, listed by `tdd -x`.

## Shape

- Toolset `launchers`; depends on `deps-launchers`, `common-core` (`managedvenv` reads the
  markers for the launchers, and this writes them). `bin-reqs`: `pyenv`, `uv`, `conda`, the
  same three `tdd venv` declares.
- State: `<tdd_dir>/managed-venvs/<type>/<name>/` and its `<name>.json` marker -- the user's,
  which `tdd-install` never touches.

## How it works

- **`tdd venv` drives it for all but what needs the shell.** Activating, deactivating, adopting
  a venv entered by hand, refusing a foreign one and the prompt change the calling shell, so
  they stay in `venv.sh`/`venv.ps1`; building a venv, writing and reading its marker, removing
  it, listing and migrating are here, once, where they were written twice -- in POSIX sh and in
  PowerShell -- and could drift. The shell relays this tool's events as its own (`venv-*`).
- **It knows nothing of the calling shell.** Where the answer depends on the active venv the
  shell says so, `--active NAME`: `delete` refuses the active one (and `--all` while any is
  active), `list` marks it. `create --force` of the active venv is left first by the shell.
- **A venv is described by its own python**, asked, never assumed -- the version it runs and the
  base interpreter it was built from -- found in `bin/`, or `Scripts\` for one built on Windows
  (`python.exe` at the root of a Windows conda env).
- `create`: uv with `--managed-python` (its own interpreters only), `--relocatable` only when
  asked and `UV_VENV_RELOCATABLE` kept out of the call; pyenv as a plain `-m venv` on a pyenv
  interpreter; conda with `--prefix`. `--relocatable` with anything but uv is refused. A failed
  build leaves nothing behind. The marker: `schema`, `name`, `manager`, `manager_version`,
  `python`, `python_requested`, `python_path`, `relocatable`, `created`, `tdd_version`, written
  through a temporary file and one rename.
- `migrate` (and every other subcommand, first) replaces a pre-JSON `<name>.env` by its JSON
  marker: the type from the file, the interpreter probed, relocatable from `pyvenv.cfg`, created
  from the old file's mtime, and a `migrated` stamp.
- xp drives it too: an execute entry with `requirements` gets a one-off venv made here.
