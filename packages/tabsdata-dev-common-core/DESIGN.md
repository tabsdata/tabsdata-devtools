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
  Commands never print; they hand the renderer events, and help is coloured by structure
  (headings bold, terms cyan) on both halves. `render.py` exists **twice, byte for byte** -- here
  for the tools and as `tabsdata_dev.tdd.render` for `tdd-exe`, which is standard-library only and
  cannot import this package; a test in `-tdd` fails when the two diverge.
- `config` -- `<tdd_dir>/<command>.toml`, every command's own file: `[options]` defaults merged
  under what was typed (`[options.<action>]` for one action), plus whatever else the command keeps
  there itself. The document is **derived from the command's argparse parser**, so the tables it
  offers cannot drift from the options -- but it **lists none of them**: the `[options]` and
  `[options.<action>]` headers, whatever the file already sets, and a two-line note saying what
  goes in them. Writing every option at its built-in value would leave a copy of today's defaults
  in the reader's file, where a later change to one would never reach them, and discovery is
  `config --show`'s job: it prints every option with its default and marks the ones the file sets.
  A command that keeps tables of its own supplies them commented at their defaults
  (`config_tables`), written **after** the options -- there, uncommenting one is valid TOML and
  survives, which it would not be up in the header, where the text is regenerated on every write.
  Once the command has written real tables, those are what a rewrite carries across.
  `config --show` answers what is in effect: every option with its default, the ones the file sets
  highlighted, then the tables beyond the options -- merged key by key over the defaults the
  command ships, so setting one table cannot hide what another defaults to. Sub-tables come from
  the file alone: a default one is a shape to copy (`[repo."OWNER/NAME"]`), named for nothing that
  exists, so it belongs in the template and never in `--show`.
  Writes are a temporary file in the same directory and one `os.replace`, so an interrupted write
  leaves the previous file rather than half of one. The `config` action itself
  (`--show`/`--default`/`--create [--force]`) is built here from the command's options, which is
  why no command implements one -- and `common.sh` renders the same document for the shell half.
- `proc` -- `run()` refuses a binary that is neither pinned by the toolset nor declared in the
  tool's `bin-reqs.txt` (`UndeclaredRequirement`; skipped when `_TDD_TOOL` is unset so tests
  import freely); `tool_argv()`/`run_tool()` reach a sibling tool through `tdd-exe`, never an import.
- `batch` -- parallel child runs on the event model, heaviest first, bounded by `TDD_PARALLELISM`
  (default 10); `parallel.map_bounded()` for plain fan-out.
- `managedvenv` + `launcher` -- run a program inside the `tdd venv` named by `_TDD_VENV` (or, without
  the record, the managed venv `VIRTUAL_ENV`/`CONDA_PREFIX` points at: `adopted()`): uv via
  `VIRTUAL_ENV=DIR uv run --active --no-project`, conda via `conda run --prefix DIR`, pyenv via
  `DIR/bin/CMD` with `bin/` first on `PATH`; refuses when the program is not in that venv.
- `secrets` / `secrets_1p` (1Password through the `op` CLI: every field of a vault as
  `<ITEM_TITLE>__<FIELD_ID>`, normalised to valid env-var names, which is the `<PREFIX>__<KEY>`
  a system's env-sourced options read; plus `_TDD_SYSTEMS`, the prefix list). An item titled
  `_*` is skipped, and skipped before it is read: a shared vault is also where people keep notes
  to themselves, and everything swept lands in the caller's shell as a variable.
  
  `ports`, `passwords`, `docker` (the CLI wrapped rather than an SDK, so it stays standard-library
  only and identical to what a person would type; every failure is a `ToolError` carrying docker's
  own message), `ssh`, `datadir.data_dir()` (`<tdd_dir>/data/<command>`), `latch`, `errors`.
  `ports` never hands out an ephemeral port: its generic range is 30000-32767 (random start),
  20000-29999 being the systems' slots -- [docs/ports.md](../../docs/ports.md).

## Rules

Generic code lives here; family code lives in a `common-<family>`. Nothing here may assume a
checkout, the cwd or an OS path -- resources come from `importlib.resources`.
