<!--
Copyright 2026 Tabsdata Inc.
-->

# tdd-env

`tdd tdd-env activate --toolset <ts> | deactivate`: enter or leave a *toolset* venv
(`<tdd_dir>/tdd-venvs/<ts>`) in the calling shell -- for iterating on a tool, so its entry point
and its pinned binaries are on `PATH` without `tdd` in front.

- Reads the toolset list from the catalog, never by globbing `tdd-venvs/` (which also holds
  `tdd` and `shells`).
- Distinct from `venv`, which manages the user's own environments; a toolset venv is tdd's.
