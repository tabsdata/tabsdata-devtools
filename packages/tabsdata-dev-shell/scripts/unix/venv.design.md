<!--
Copyright 2026 Tabsdata Inc.
-->

# venv

`tdd venv create|activate|deactivate|delete|list`: managed virtualenvs (pyenv, uv or conda)
under `<tdd_dir>/managed-venvs/`, entered and left in the calling shell -- which is why it is a
shell command.

- Layout: `managed-venvs/<name>.env` holds the type, `managed-venvs/<type>/<name>/` the venv.
  `create` (`--type`, `--python`, `--force` to recreate even the active one) ends in activation.
- Activation exports `_TDD_VENV` (what `tdd tdk|tdkserver|km` read), saves the prompt in
  `_TDD_VENV_PS1` and writes `(<type>/<python>/<name>)` in green after the red `* ` of
  `tdd-source.sh`; the managers' own prompt markers are silenced. `deactivate` leaves whatever
  is active -- managed, or best effort a venv activated by hand (uv/venv, pyenv-virtualenv,
  conda) -- and restores the prompt. A foreign active venv blocks `create`/`activate` -- but a
  venv found active under `managed-venvs/<type>/<name>` with its marker is ours however it was
  entered (a shell from before a reinstall, `bin/activate` sourced by hand) and is **adopted**
  as the active one first (`_tdd_venv_adopt`, every subcommand; the prompt to restore is the
  current one minus our marker and the tool's). `managedvenv.adopted()` is the launchers' twin.
- pyenv venvs are plain `python -m venv` on a pyenv interpreter (outside `~/.pyenv/versions`);
  conda gets its shell hook installed on the fly when the rc did not.
- `bin-reqs`: `pyenv`, `uv`, `conda`.
