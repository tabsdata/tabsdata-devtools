<!--
Copyright 2026 Tabsdata Inc.
-->

# Command CLI guidelines

The contract every command meets -- `tdd-exe` builtins, Python tools and shell commands alike.
A command that does not is a bug.

## Names

Commands, subcommands and options are lower-case, `-` between words (`tdd-env`, `--from-wheels`);
never `_`, never camelCase. An option is always a long `--name`, taking `--name value` or
`--name=value`. Short forms exist only for `-h` (`--help`), `-v` (`--verbose`) and `-f`
(`--force`). Long names are also what lets a user preset any option in
`<tdd_dir>/default-opts/<command>.txt` / `<command>_<action>.txt`; `tdd` merges those in, typed
options winning, and announces the resolved line -- commands do nothing for it.

## Every command has

| Option | Meaning |
|---|---|
| `--help`, `-h` | usage, description, options, one example, in argparse's layout on both sides; exit 0 |
| `--verbose`, `-v` | more detail about what is happening, never a different result |
| `--format json\|view` | output format, default `view` |

Everything after the command word belongs to the command, and `--help` is shown even when its
`bin-reqs` are missing. The one exception: the launchers (`tdd tdk|tdkserver|km`) own no options
-- everything reaches the program they run; only their own failures before it follow this contract.

## Exit codes and the failure log

`0`: did what was asked. `1`: anything else -- no `2`, no `127`, no passing a subprocess's code
through. On `1` the command writes `/tmp/tdd-<command>-<YYYYmmdd-HHMMSS>-<pid>.log` -- command
line, cwd, `TDD_DIR`, version, time, error, traceback, complete subprocess output -- and names it:
`details: <path>` on stderr in view, the `log` field of the `error` line in json. The terminal
keeps *what* went wrong; the file has the *why*.

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
