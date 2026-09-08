<!--
Copyright 2026 Tabsdata Inc.
-->

# venv

`tdd venv create|activate|deactivate|delete|list`: managed virtualenvs (pyenv, uv or conda)
under `<tdd_dir>/managed-venvs/`, entered and left in the calling shell -- which is why it is a
shell command.

- Layout: `managed-venvs/<name>.env` holds the type, `managed-venvs/<type>/<name>/` the venv.
  `create` (`--type`, `--python`, `--force` to recreate even the active one) ends in activation.
  `--python` defaults to **3.12.13** rather than to whatever each tool would pick on its own:
  uv's default, pyenv's current version and conda's latest are three different interpreters
  from one command, and 3.12.13 is what a tdkserver instance builds its own environments with,
  so a venv made here matches what the product runs. pyenv needs it installed (the error says
  so); uv and conda fetch it.
  `delete --name NAME` refuses the active one; `delete --all` removes every managed venv and
  refuses while any is active (the shell would be left standing in a deleted venv).
  `deactivate --force` is idempotent: it asks to be out of any venv, and out is where a shell
  with none active already is, so that is an `ok`. A script wanting a clean shell can put it in
  front of what it does without swallowing a failure that means "already fine" -- and swallowing
  that one hides the failures that mean something, which is how every smoke script used to run a
  plain `deactivate || true` that could not leave a foreign venv anyway.
- Activation exports `_TDD_VENV` (what `tdd tdk|tdkserver|km` read), saves the prompt in
  `_TDD_VENV_PS1` and writes `(<type>/<python>/<name>)` in green after the red `* ` of
  `tdd-source.sh`; the managers' own prompt markers are silenced. `deactivate` leaves the
  managed venv and restores the prompt; a venv tdd did not activate, or a stale record
  (recorded, nothing active), is an error pointing at `--force`, which leaves it best effort
  (uv/venv, pyenv-virtualenv, conda) or drops the record. A foreign active venv blocks `create`/`activate` -- but a
  venv found active under `managed-venvs/<type>/<name>` with its marker is ours however it was
  entered (a shell from before a reinstall, `bin/activate` sourced by hand) and is **adopted**
  as the active one first (`_tdd_venv_adopt`, every subcommand; the prompt to restore is the
  current one minus our marker and the tool's). `managedvenv.adopted()` is the launchers' twin.
- pyenv venvs are plain `python -m venv` on a pyenv interpreter (outside `~/.pyenv/versions`);
  conda gets its shell hook installed on the fly when the rc did not. `--type` defaults to
  `pyenv`. `list` prints every managed venv with its type and path, which is the only subcommand
  that touches neither the shell nor the disk.
- `config` (`--show`/`--default`/`--create [--force]`) comes from the shared layer, over the
  per-action defaults `tdd_defaults_venv` declares -- which is where `--type pyenv` and
  `--python 3.12.13` actually live, so changing them for yourself is a line in `venv.toml`
  rather than a flag on every create.
- `bin-reqs`: `pyenv`, `uv`, `conda`.
