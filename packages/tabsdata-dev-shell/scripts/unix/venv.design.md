<!--
Copyright 2026 Tabsdata Inc.
-->

# venv

`tdd venv create|activate|deactivate|delete|list`: managed virtualenvs (pyenv, uv or conda)
under `<tdd_dir>/managed-venvs/`, entered and left in the calling shell -- which is why it is a
shell command.

- Layout: `managed-venvs/<type>/<name>/` is the venv, `managed-venvs/<name>.json` its marker:
  `manager` (the type), `manager_version`, `python` (the version the venv runs), `python_requested`
  (what `--python` asked for), `python_path` (the base interpreter it was built from --
  `sys._base_executable`, what `pyvenv.cfg`'s `home` points at; a conda env carries its own, so
  that is its own python), `relocatable`, `created` (UTC), `tdd_version`, `schema`. The version
  and path are asked of the venv's own python once it exists rather than of the tool that made it,
  so the marker says what the venv *is*. Written by jq through a temporary file and one rename;
  read by one jq run per marker (`_tdd_venv_read_marker`), `_tdd_venv_manager_of` for the type
  alone where a `$(...)` needs it. `common.core.managedvenv.marker()` is the launchers' twin.
  Before 2026-09-18 the marker was `<name>.env` holding the type alone; every subcommand runs
  `_tdd_venv_migrate` first (once past `--help`, options parsed), which rewrites each one it
  finds -- type from the file, python probed, `relocatable` from the `relocatable = true` uv
  leaves in `pyvenv.cfg`, `created` from the file's mtime, plus a `migrated` stamp -- and removes
  it, so the two formats never coexist and nothing downstream knows the old one. The Python side
  reads JSON only and, meeting a `.env`, says to run `tdd venv list` once.
- `create` (`--type`, `--python`, `--relocatable`, `--force` to recreate even the active one) ends
  in activation. `--python` defaults to **3.12.13** rather than to whatever each tool would pick on
  its own: uv's default, pyenv's current version and conda's latest are three different
  interpreters from one command, and 3.12.13 is what a tdkserver instance builds its own
  environments with, so a venv made here matches what the product runs. pyenv needs it installed
  (the error says so); uv and conda fetch it.
  A uv venv is built with `--managed-python`: uv's own interpreters only, never the homebrew,
  pyenv or system python that happens to be on PATH under the same version -- so `--type uv`
  always means the same interpreter, whatever the machine has lying around.
  **A venv is bound to its path unless `--relocatable` is given.** Only uv can build one that
  survives a move (`uv venv --relocatable`); `python -m venv` and conda bake the path in, so
  `--relocatable` with `--type pyenv|conda` is an error rather than a flag shrugged off. The
  flag is passed to uv only when asked, and `UV_VENV_RELOCATABLE` is kept out of the call
  (`env -u`): the marker records what the venv is, so the environment must not decide it behind
  the flag's back. The tool envs under `tdd-venvs/` are a different matter -- invariant 6 makes
  every one of them relocatable; a managed venv is the user's, made for one place.
  `delete --name NAME` refuses the active one; `delete --all` removes every managed venv and
  refuses while any is active (the shell would be left standing in a deleted venv).
  `deactivate --force` is idempotent: it asks to be out of any venv, and out is where a shell
  with none active already is, so that is an `ok`. A script wanting a clean shell can put it in
  front of what it does without swallowing a failure that means "already fine" -- and swallowing
  that one hides the failures that mean something, which is how every smoke script used to run a
  plain `deactivate || true` that could not leave a foreign venv anyway.
- Activation exports `_TDD_VENV` (what `tdd tdk|tdkserver|km` read), saves the prompt in
  `_TDD_VENV_PS1` and writes `(<type>/<python>/<name>)` in green after the red `* ` of
  `tdd-source.sh` -- `(<type>/<python>/<name>/reloc)` for a relocatable venv, so the prompt says
  what the venv can stand (`_tdd_venv_mark_text`); the python shown is asked of the venv's own
  interpreter at that moment, not read from the marker: it is what runs now. The managers' own
  prompt markers are silenced. `deactivate` leaves the managed venv and restores the prompt; a
  venv tdd did not activate, or a stale record (recorded, nothing active), is an error pointing
  at `--force`, which leaves it best effort (uv/venv, pyenv-virtualenv, conda) or drops the
  record. A foreign active venv blocks `create`/`activate` -- but a venv found active under
  `managed-venvs/<type>/<name>` with its marker is ours however it was entered (a shell from
  before a reinstall, `bin/activate` sourced by hand) and is **adopted** as the active one first
  (`_tdd_venv_adopt`, every subcommand, after the migration; the prompt to restore is the current
  one minus our marker and the tool's). `managedvenv.adopted()` is the launchers' twin.
- pyenv venvs are plain `python -m venv` on a pyenv interpreter (outside `~/.pyenv/versions`);
  conda gets its shell hook installed on the fly when the rc did not. `--type` defaults to
  `pyenv`. `list` prints every managed venv on one line -- name, type, the python it runs,
  `reloc` or `-`, its path, the base python it was built from, then `(active)` /
  `(missing directory)` -- all from the marker, and the same as JSON fields (`python`,
  `python_path`, `relocatable`, `created` beside `name`, `type`, `path`, `active`, `exists`).
  It is the only subcommand that changes neither the shell nor a venv (the migration rewrites
  markers, once).
- `config` (`--show`/`--default`/`--create [--force]`) comes from the shared layer, over the
  per-action defaults `tdd_defaults_venv` declares -- which is where `--type pyenv`,
  `--python 3.12.13` and `--relocatable false` actually live, so changing them for yourself is a
  line in `venv.toml` (`relocatable = true` under `[options.create]`) rather than a flag on
  every create.
- `bin-reqs`: `pyenv`, `uv`, `conda`.
