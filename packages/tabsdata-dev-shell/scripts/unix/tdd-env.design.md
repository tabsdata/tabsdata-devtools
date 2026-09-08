<!--
Copyright 2026 Tabsdata Inc.
-->

# tdd-env

`tdd tdd-env activate --toolset <ts> | deactivate`: enter or leave a *toolset* venv
(`<tdd_dir>/tdd-venvs/<ts>`) in the calling shell -- for iterating on a tool, so its entry point
and its pinned binaries are on `PATH` without `tdd` in front.

- Reads the toolset list from the catalog, never by globbing `tdd-venvs/` (which also holds
  `tdd` and `shells`). `--toolset` is required, and the refusal lists the ones there are.
- Activation **sources the venv's own `bin/activate`** rather than reimplementing it, so what
  `deactivate` calls is the venv's own function -- which is also why it leaves whatever venv is
  active, toolset or not, and says "no active venv" when there is none.
- Distinct from `venv`, which manages the user's own environments; a toolset venv is tdd's.
- `config` (`--show`/`--default`/`--create [--force]`) comes from the shared layer, over the one
  option `tdd_defaults_tdd-env` declares.
