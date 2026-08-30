<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-common-core

The library every toolset carries: the CLI contract implemented once, process launching with
`bin-reqs` enforcement, and the generic building blocks the tool families share. Third-party
dependencies are declared as ranges; each toolset's lock pins them.

## Modules

- `cli.run()` / `render` -- the command contract: `--help`, `--verbose`, `--format json|view`,
  events `ok|error|warn|info|debug` with colours, exit 0/1, the `/tmp/tdd-<cmd>-<stamp>.log`.
- `proc` -- `run()` refuses a binary that is neither pinned by the toolset nor declared in the
  tool's `bin-reqs.txt` (`UndeclaredRequirement`; skipped when `_TDD_TOOL` is unset so tests
  import freely); `tool_argv()`/`run_tool()` reach a sibling tool through `tdd-exe`, never an import.
- `batch` -- parallel child runs on the event model, heaviest first, bounded by `TDD_PARALLELISM`
  (default 10); `parallel.map_bounded()` for plain fan-out.
- `managedvenv` + `launcher` -- run a program inside the `tdd venv` named by `TDD_VENV`: uv via
  `VIRTUAL_ENV=DIR uv run --active --no-project`, conda via `conda run --prefix DIR`, pyenv via
  `DIR/bin/CMD` with `bin/` first on `PATH`; refuses when the program is not in that venv.
- `secrets` (1Password: `<PREFIX>__<KEY>` variables plus `_TDD_SYSTEMS`, the prefix list),
  `ports`, `passwords`, `docker`, `ssh`, `datadir.data_dir()` (`<tdd_dir>/data/<command>`), `latch`.

## Rules

Generic code lives here; family code lives in a `common-<family>`. Nothing here may assume a
checkout, the cwd or an OS path -- resources come from `importlib.resources`.
