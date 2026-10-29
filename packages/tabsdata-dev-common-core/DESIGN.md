<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-common-core

The library every toolset carries: the CLI contract implemented once, process launching with
`bin-reqs` enforcement, and the generic building blocks the tool families share. Third-party
dependencies are declared as ranges; each toolset's lock pins them.

## Modules

- `cli.run()` / `render` -- the command contract: `--help`, `--verbose`, `--format json|view`
  (plus any `formats={name: what}` the command renders itself, `_1p fetch`'s `export`; it may be
  the `default_format`, and the renderer is view for it),
  events `ok|error|warn|info|debug` with colours, exit 0/1, the `<temp>/tdd-<cmd>-<stamp>.log`.
  Commands never print; they hand the renderer events, and help is coloured by structure
  (headings bold, terms cyan) on both halves. A message that paints its own pieces instead of
  taking one colour by kind -- `config --show` -- takes them from `render.PAINTS` and is printed
  as it is. On a terminal the renderer also keeps a status block redrawn in place below the
  events (`live(lines)`, `can_live()`): events print above it, the outcome removes it, each line
  is cut to the terminal's width so a redraw never climbs one row short; in JSON or a pipe it
  writes nothing, and the command reports progress as events there. `render.py` exists
  **twice, byte for byte** -- here
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
  marked out -- a built-in default is green, a value the file sets is blue with
  `(built in default: "x")` in white beside it, and `common.sh` paints the same lines with the same
  codes -- then the tables beyond the options, painted by the same rule (a value shown there IS the
  default, so nothing is quoted beside it) -- merged key by key over the defaults the
  command ships, so setting one table cannot hide what another defaults to. Sub-tables come from
  the file alone: a default one is a shape to copy (`[repo."OWNER/NAME"]`), named for nothing that
  exists, so it belongs in the template and never in `--show`.
  Writes are a temporary file in the same directory and one `os.replace`, so an interrupted write
  leaves the previous file rather than half of one. The `config` action itself
  (`--show`/`--default`/`--create [--force]`) is built here from the command's options, which is
  why no command implements one -- and `common.sh` renders the same document for the shell half.
- `proc` -- `run()` (and `popen()`, for a child that is streamed) refuses a binary that is neither pinned by the toolset nor declared in the
  tool's `bin-reqs.txt` (`UndeclaredRequirement`; skipped when `_TDD_TOOL` is unset so tests
  import freely); `tool_argv()`/`run_tool()` reach a sibling tool through `tdd-exe`, never an import.
- `batch` -- parallel child runs on the event model, heaviest first, bounded by `TDD_PARALLELISM`
  (default 10); `parallel.map_bounded()` for plain fan-out. Without a `spawn` it streams: it
  launches each step itself in `Task.cwd`, hands each line to a `Reporter` as it comes, and runs
  each child as a `Tree` (a POSIX session, a Windows job object) so `kill_on_fail` and Ctrl-C stop
  a whole pipeline; `heaviest_first=False` keeps the given order, `workers` overrides the bound.
- `managedvenv` + `launcher` -- run a program inside the venv last activated (`select`: a
  `_TDD_VENV` set by hand, else the venv the shell has active, managed or not, else `tdd venv`'s
  record; `_TDD_VENV_ACTIVATED` tells the first from the last -- see the tdk design doc) and say
  which, as the first event. A managed venv runs through its manager (uv via `VIRTUAL_ENV=DIR uv
  run --active --no-project`, conda via `conda run --prefix DIR DIR/<bin>/CMD`, pyenv via
  `DIR/<bin>/CMD`); any other by path. The venv's directories go first on `PATH`, `<bin>` asked
  of the venv (`bin/`, or `Scripts\` and `.exe` for one built on Windows); refuses when the
  program is not in that venv. mexe and apidoc pick their venv with the same `select`.
  `launcher.run_program` is the same pass-through for a program with no venv to find (`pqt`,
  `jq`): pinned, it is looked for in the tool's own scripts dir only; external, on PATH with
  that dir left out, where the launcher's entry point sits under what may be the program's name.
- `secrets` / `secrets_1p` (1Password through the `op` CLI: every field of a vault as
  `<ITEM_TITLE>__<FIELD_ID>`, normalised to valid env-var names, which is the `<PREFIX>__<KEY>`
  a system's env-sourced options read; plus `_TDD_SYSTEMS`, the prefix list). An item titled
  `_*` is skipped, and skipped before it is read: a shared vault is also where people keep notes
  to themselves, and everything swept lands in the caller's shell as a variable. Items are
  read 16 at a time and 1Password turns some of a burst away, so every read that fails (the
  list, each item, `read_field`'s `op read`) is tried again -- writes are not, as a create run
  twice files two items; an item still unreadable fails the fetch by name -- skipped, it showed
  only later, as a system with options that have no value (a GA Windows run lost BigQuery that
  way). `set_item`
  files one (delete, then create) and `for_upload` reduces an item to what a create may carry.
  The command over them is `tdd _1p` (`fetch`, `push`); `CRYPTO_KEY_ENV`/`CRYPTO_KEY_MIN_LEN` name the descriptor key and
  its minimum length for it, `common.systems.crypto` and both `env` scripts.
  
  `ports`, `passwords`, `docker` (the CLI wrapped rather than an SDK, so it stays standard-library
  only and identical to what a person would type; every failure is a `ToolError` carrying docker's
  own message, and `container_failure()` adds the container's state and last log lines for the
  failure log -- a server that never came up said why on its own stdout), `ssh`,
  `datadir.data_dir()` (`<tdd_dir>/data/<command>`), `latch`, `errors` (`ToolError(message,
  details)`: the message is the terminal's one line, `details` is what the failing system said,
  written to the log under it).
  `ports` never hands out an ephemeral port: its generic range is 30000-32767 (random start),
  20000-29999 being the systems' slots -- [docs/ports.md](../../docs/ports.md).

## Rules

Generic code lives here; family code lives in a `common-<family>`. Nothing here may assume a
checkout, the cwd or an OS path -- resources come from `importlib.resources`.
