<!--
Copyright 2026 Tabsdata Inc.
-->

# pqt

`tdd pqt ARGS...`: run `parquet-tools ARGS` (`show`, `csv`, `inspect` a parquet file, local or
`s3://`) and hand its output and status straight back.

## Shape

- Toolset `xp`; depends on `deps-xp`, `common-core`. Entry point
  `common.core.launcher.run_program("pqt", "parquet-tools", pinned=True)`. No `bin-reqs`: the
  program is pinned, so it sits in the toolset's scripts dir.
- `launcher = true`: every argument is the program's, so no options, no `pqt.toml`, no `config`.

## Decisions

- **The `xp` toolset, not one of its own.** `deps-xp` already pins `parquet-tools==0.2.16`
  (xp's check scripts read table versions with it), and nothing a separate venv would change:
  parquet-tools caps pandas below 3 and that pin is why xp left `systems` -- a third copy of the
  same resolution would be weight for nothing. If xp ever needs a parquet-tools this tool cannot
  live with, that is when `pqt` gets a toolset.
- **Looked for in its own venv only.** A parquet-tools elsewhere on PATH -- a user's pipx copy
  on another pandas -- does not stand in for the pinned one.
- **The name is `pqt`**, short for parquet-tools; `parquet-tools` itself would shadow the
  program in the toolset's scripts dir, both being entry points there.
- A non-zero exit is one error event carrying `status`, and tdd exits 1: the launcher contract
  (`tdk`'s). The program's own stdout is untouched, so `tdd pqt csv F | ...` pipes.
