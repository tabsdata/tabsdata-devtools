<!--
Copyright 2026 Tabsdata Inc.
-->

# _tdd-env

`tdd _tdd-env activate --toolset <ts> | deactivate`: enter or leave a *toolset* venv
(`<tdd_dir>/tdd-venvs/<ts>`) in the calling shell -- for iterating on a tool, so its entry point
and its pinned binaries are on `PATH` without `tdd` in front.

- Reads the toolset list from the catalog, never by globbing `tdd-venvs/` (which also holds
  `tdd` and `shells`). `--toolset` is required, and the refusal lists the ones there are.
- Activation **sources the venv's own `bin/activate`** rather than reimplementing it, so what
  `deactivate` calls is the venv's own function -- which is also why it leaves whatever venv is
  active, toolset or not, and says "no active venv" when there is none.
- Distinct from `venv`, which manages the user's own environments; a toolset venv is tdd's.
- `config` (`--show`/`--default`/`--create [--force]`) comes from the shared layer, over the one
  option `tdd_defaults__tdd-env` declares.
- **Named `_tdd-env` since 2026-09-28** (was `tdd-env`): the leading `_` makes it plumbing, as
  for a Python tool -- a tdd developer's aid, left out of `tdd help` and listed by `tdd -x`, and
  both loaders hide a `_` shell command the same way. It still dispatches as ever; its config
  file is `<tdd_dir>/_tdd-env.toml` and its events `_tdd-env-activate`/`-deactivate`.

## The PowerShell twin

`scripts/powershell/_tdd-env.ps1` sources the venv's own `activate.ps1` for the same reason this
one sources `bin/activate`, and it works for a reason worth writing down: that script is careful
about scope (`New-Variable -Scope global`, `function global:deactivate`), so dot-sourcing it from
inside a function leaves exactly the session-level state it would leave at the prompt. Checked by
running it, not assumed -- a script that is *not* careful that way would vanish with the call.

`VIRTUAL_ENV_DISABLE_PROMPT` is set around the dot-source and restored after, because
`activate.ps1` installs a `global:prompt` of its own otherwise and `tdd-source.ps1` already owns
the prompt. The toolset list comes from the catalog with `ConvertFrom-Json` rather than through
the tdd env's Python: this family needs no external binary, and spending a subprocess inside a
message whose only job is to explain a failure would be the wrong trade.