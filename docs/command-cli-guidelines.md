<!--
Copyright 2026 Tabsdata Inc.
-->

# Command CLI guidelines

The contract every command meets — `tdd-exe` builtins, Python tools, and shell commands
alike. A command that does not is a bug. Short, because each rule is absolute.

## Names

- Commands, subcommands and options are lower-case; multi-word names take `-` as the
  separator: `tdd-env`, `--from-wheels`, `--toolset`. Never `_`, never camelCase.
- An option is always a long `--name`. Values as `--name value` or `--name=value`; both must
  work.
- Short forms exist only for the common options, and only these: `-h` for `--help`, `-v` for
  `--verbose`, `-f` for `--force`. Anything else stays long — a short flag is a namespace you cannot get back.

## Every command has

| Option | Meaning |
|---|---|
| `--help`, `-h` | usage, description, options, and one example, in argparse's layout on both sides (`_tdd_help_text` renders it for shell commands); exit 0 |
| `--verbose`, `-v` | more detail about what is happening — never a different *result* |
| `--format json\|view` | output format, default `view` |

Everything after the command word belongs to the command: `tdd <command> --help` is the
command's help, not `tdd`'s. The one exception to the rules below are the launchers (`tdd tdk`,
`tdd tdkserver`, `tdd km`): they own no options, so `--help`, `--format` and everything else reach the
program they run; only their own failures before it runs follow this contract.

Because every option is a long `--name`, a user can preset it: `tdd` merges
`<tdd_dir>/default-opts/<command>.txt` or `<command>_<action>.txt` (one `--name value` per line)
into the invocation, with
typed options taking precedence, and announces the resolved command line as an `info` event.
**Commands do nothing for this** — the defaults are already in the arguments they receive — it
is one more reason options must follow the naming rules. `tdd defaults --command <name>` shows
what applies; a shell command declares its built-ins for it (see the shell guide).

## Exit codes

- `0`: the command did what was asked.
- `1`: anything else — bad arguments, a missing binary, a failed subprocess, an exception.

There is no `2`, no `127`, no passing a subprocess's code through. A caller checks one thing.

## Failure log

When a command exits `1` it writes a log file to `/tmp/` and prints where it is. The file
holds what the terminal did not: the full command line, the working directory, `TDD_DIR` and
the version, the time, the error message, the traceback if there was one, and the complete
stdout/stderr of any subprocess involved.

```
/tmp/tdd-<command>-<YYYYmmdd-HHMMSS>-<pid>.log
```

In `view` format the last line on stderr is `details: /tmp/tdd-…log`; in `json` format the
path is the `log` field of the `error` line. The terminal keeps one line of *what* went wrong;
the file has the *why*.

## Events

Everything a command says is an **event**: which command, what kind, a message, and optional
fields. Commands never print; they emit events through the renderer, which decides how each
looks in each format.

| `event` | when | shown |
|---|---|---|
| `ok` | the outcome; exactly one, last, then exit 0 | always |
| `error` | the failure; exactly one, last, then exit 1; carries `log` | always |
| `warn` | something the user should notice while the command works | always |
| `info` | progress: what is happening now | always |
| `debug` | detail for diagnosing | only with `--verbose` |

Every event has `command` — the command's qualified name, `-`-joined, the same one the log
file uses (`venv-create`, `demo-exe1`) — `event`, and `message`. Progress is emitted as
`info` lines *as it happens*, one per step, not summarised at the end: the reader may be a pipe
drawing a spinner. Never mix formats: in `json` mode a subprocess's output goes into the log
or a field, never to the terminal.

## Output formats

**`json`** is JSON Lines: one object per event on stdout, nothing else on stdout.

```
{"command": "venv-create", "event": "info", "message": "create scratch (uv)"}
{"command": "venv-create", "event": "debug", "message": "python: 3.12"}
{"command": "venv-create", "event": "ok", "message": "created scratch (uv) at …", "name": "scratch", "type": "uv"}
```

```
{"command": "venv-activate", "event": "error", "message": "no managed venv named nope", "log": "/tmp/tdd-venv-activate-20260828-171502-4242.log"}
```

**`view`** is for a person at a terminal: the `ok` message on stdout, every other event on
stderr, so `$(tdd …)` captures the result and nothing else. An `error` is followed by
`details: <log path>` on stderr.

## Colours

By event kind, the same in both formats — a JSON line on a terminal is still read by a person:

| kind | colour |
|---|---|
| `ok` | green |
| `error` | red |
| `warn` | yellow |
| `info` | plain |
| `debug` | white |

Only when the stream being written is a terminal, and never when `NO_COLOR` is set; a pipe
never sees an escape code. Two further paints exist for rows *inside* a message, not for event
kinds: white for a built-in value and blue for a customized one (`tdd defaults`). That blue is a
256-colour entry (`38;5;33`), not palette blue: terminal themes remap the 16 palette colours —
plain blue turns near-black on dark themes, bright blue grey-white under "minimum contrast" —
but leave the colour cube alone.

## Applying it

- **Python tools**: `common.core.render` is the model (`Event`) and the renderer (`Renderer`:
  `ok`/`error`/`warn`/`info`/`debug`); `common.core.cli.run()` wraps the command body so the
  mandatory options, the exit-code mapping, argument errors, exceptions and the failure log are
  handled once. Do not hand-roll a `--format` or print directly.
- **Shell commands**: source `common.sh` (`${TDD_COMMON_SH}`) and use its helpers —
  `_tdd_cmd_reset`, `_tdd_common_opt`, `_tdd_optval`, `_tdd_cmd_check`, then `_tdd_ok`,
  `_tdd_error`, `_tdd_warn`, `_tdd_info`, `_tdd_debug`. `common.sh` builds every JSON line
  with **jq**, so jq is a requirement of every shell command (`common.bin-reqs.txt`); a command
  never touches JSON itself. A sourced function `return`s the code — never `exit`. The tests
  reject a command file that prints on its own.
- **`tdd` itself, `tdd-install`, `cargo make gen`**: no exception for being the front door or
  a build step. The shell function uses `common.sh`; `tdd-exe`, `tdd-install` and the generator
  use `tabsdata_dev.tdd.render`, a byte-identical twin of `common.core.render` (they cannot
  import `common-core`), kept identical by a test. `tdd-install` captures every `uv` step's
  output: `debug` on success, the error log on failure. The only plain output left is the
  `--porcelain`/`--defaults` plumbing the shell reads, and `--help` text.
