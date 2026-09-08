<!--
Copyright 2026 Tabsdata Inc.
-->

# Command CLI guidelines

The contract every command meets -- `tdd-exe` builtins, Python tools and shell commands alike.
A command that does not is a bug.

## Names

Commands, subcommands and options are lower-case, `-` between words (`tdd-env`, `--from-wheels`);
never `_`, never camelCase. An option is always a long `--name`, taking `--name value` or
`--name=value`. Short forms exist only for `-h` (`--help`), `-v` (`--verbose`), `-f`
(`--force`), `-y` (`--yes`, on a command that otherwise asks) and `-V` (`--version`, on `tdd`
itself) -- every command that has the long form accepts the short one. Long names are also what
lets a user preset any option in
`<tdd_dir>/<command>.toml` (`[options]`, `[options.<action>]`); `tdd` merges those in, typed
options winning, and announces the resolved line -- commands do nothing for it.

## Every command has

| Option | Meaning |
|---|---|
| `--help`, `-h` | argparse's page, on both sides and at every level, `tdd`'s own builtins included; exit 0. `tdd --help full` prints tdd's page and then every command's. `usage: tdd <command> ...` naming the command as it is run, the description, `positional arguments:` with the subcommands nested under `SUBCOMMAND` one line each, then `options:`, then an example. A subcommand answers `-h` for itself, with its own description and its own options. Headings bold and terms cyan on a terminal, plain in a pipe (`render.colorize_help`; the shell's `_tdd_help_text` lays out and paints the same) |
| `--verbose`, `-v` | more detail about what is happening, never a different result |
| `--force`, `-f` / `--yes`, `-y` | where a command has them: overwrite or drop-first / do not ask |
| `--format json\|view` | output format, default `view`. A command that *renders* something -- a descriptor, a set of secrets -- adds its own shapes here rather than a second flag (`tdd system info --format export\|unset\|1p`): the runner consumes only `json`/`view`, so the extra value reaches the command's parser and leaves the envelope on `view` |
| `config` | the command's config file, `<tdd_dir>/<command>.toml`: `--show` (default), `--default`, `--create [--force]` |

`config` is an action, not an option, and comes from the shared layer on both sides
(`common.core.config` / `_tdd_config_action`): its template is built from the command's own
options, so it cannot drift. `--show` prints what the options resolve to now, one paint per value:
a built-in default in green, a value the file sets in blue with `(built in default: "x")` in white
beside it -- on a terminal only, plain in a pipe and under `NO_COLOR`, and the same lines on both
halves. `--default` prints the document `--create` would write; `--create` writes
it, refusing an existing file unless `--force`, always through a temporary file and one rename.

Everything after the command word belongs to the command, and `--help` is shown even when its
`bin-reqs` are missing. The one exception: the launchers (`tdd tdk|tdkserver|km`) own no options
-- everything reaches the program they run; only their own failures before it follow this contract.

## Exit codes and the failure log

`0`: did what was asked. `1`: anything else -- no `2`, no `127`, no passing a subprocess's code
through. On `1` the command writes `/tmp/tdd-<command>-<YYYYmmdd-HHMMSS>-<pid>.log` -- command
line, cwd, `TDD_DIR`, version, time, error, traceback, complete subprocess output -- and names it:
`details: <path>` on stderr in view, the `log` field of the `error` line in json. The terminal
keeps *what* went wrong; the file has the *why*.

**The why includes what the failing system said.** A driver's one-line summary is what the
terminal gets; the log gets everything behind it, pulled at the raise site and carried as
`ToolError(message, details)`. A database: SQLSTATE, the server's DETAIL/HINT/CONTEXT, the
schema/table/constraint it named, the statement that failed, and the connection target with the
password stripped (`common.systems.diagnostics.db_failure`). A container: its state, exit code
and last log lines (`core.docker.container_failure`) -- a server that never came up wrote the
reason to its own stdout, and "did not become ready" is the one thing that cannot say it.
Collecting diagnostics never raises: it runs while something is already going wrong, and an
exception there would replace the failure it was explaining. The smoke scripts do the same for a
cluster (`common_k8s_report`): pods, jobs, the namespace's events and every failed pod's logs --
init containers included -- into the run's log, while the namespace still exists.

The cluster smoke scripts are not commands and take no `<tdd_dir>/<command>.toml`, but their help
is painted by the same rules (`common_help`): a heading bold, a term cyan -- and an option they
**require** red, because a page with six mandatory options should say so where the eye already is.
They require what cannot be guessed (`--name`, `--kube-config`, `--kube-context`,
`--kube-namespace`, `--td-version`, `--uv-index`) and never write to the kubeconfig they are
given: the run copies it, makes the copy current on its own context and namespace, and points
tdkserver at the copy -- because tdkserver reads both from the current context, and its
`venv update`, `config` and `delete` take no `--context` to say otherwise.

## Events

Everything a command says is an event -- `command` (the `-`-joined qualified name the log uses,
`venv-create`), `event`, `message`, optional fields -- emitted through the renderer, never printed.

| `event` | when | shown |
|---|---|---|
| `ok` | the outcome; exactly one, last, then exit 0 | always, green |
| `error` | the failure; exactly one, last, then exit 1; carries `log` | always, red |
| `warn` | something to notice while the command works | always, yellow |
| `info` | progress, as it happens, one line per step | always, plain |
| `debug` | detail for diagnosing | only with `--verbose`, white |

**json** is JSON Lines on stdout and nothing else there; **view** puts the `ok` message on stdout
and every other event on stderr, so `$(tdd ...)` captures the result. Never mix: in json a
subprocess's output goes to the log or a field. Colours only on a terminal and never under
`NO_COLOR`; two extra paints exist for rows inside a message -- white built-in, blue (`38;5;33`,
themes leave the colour cube alone) customized.

## Applying it

- **Python**: `common.core.cli.run()` + `render.Renderer` (`ok/error/warn/info/debug`) handle the
  options, exit mapping, argument errors, exceptions and the log once. No hand-rolled `--format`,
  no `print`.
- **Shell**: source `common.sh` (`$_TDD_COMMON_SH`) and use `_tdd_cmd_reset`, `_tdd_common_opt`,
  `_tdd_optval`, `_tdd_cmd_check`, `_tdd_ok/_tdd_error/_tdd_warn/_tdd_info/_tdd_debug`,
  `_tdd_help_text`; JSON is built with jq (hence `common.bin-reqs.txt`); `return`, never `exit`.
- **`tdd`, `tdd-install`, the generator**: no exception for being the front door. They use
  `tabsdata_dev.tdd.render`, the byte-identical twin of `common.core.render`. The only plain
  output left is the `--porcelain`/`--defaults` plumbing the shell reads, and `--help`.
