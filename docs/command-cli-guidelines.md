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
  `--verbose`. Anything else stays long — a short flag is a namespace you cannot get back.

## Every command has

| Option | Meaning |
|---|---|
| `--help`, `-h` | usage, options, and one example; exit 0 |
| `--verbose`, `-v` | more detail about what is happening — never a different *result* |
| `--format json\|view` | output format, default `view` |

Everything after the command word belongs to the command: `tdd <command> --help` is the
command's help, not `tdd`'s.

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

## Output formats

**`view`** is for a person at a terminal: results on stdout, diagnostics and `--verbose` detail
on stderr, colour only if stdout is a tty.

**`json`** is JSON Lines — one JSON object per line, nothing else on stdout. Every object has an
`event` field:

| `event` | when | required fields |
|---|---|---|
| `progress` | something started, advanced or finished mid-run | `step`, plus `status` (`start`/`done`) or `current`/`total` |
| `log` | what `--verbose` would have said | `level`, `message` |
| `result` | the outcome; exactly one, last, on exit 0 | whatever the command produces |
| `error` | the failure; exactly one, last, on exit 1 | `message`, `log` |

A command that reports progress emits one `progress` line per step as it happens, not a
summary at the end — the reader may be a pipe that shows a spinner. Never mix formats: in
`json` mode a subprocess's output goes to the log file or into a field, not to the terminal.

```
{"event": "progress", "step": "sync demo-env1", "status": "start"}
{"event": "progress", "step": "sync demo-env1", "status": "done"}
{"event": "result", "toolsets": 2, "tools": 2}
```

```
{"event": "error", "message": "no such toolset: nope", "log": "/tmp/tdd-tdd-env-20260828-171502-4242.log"}
```

## Applying it

- **Python tools**: take the parser from `common.core.cli` and report through
  `common.core.report`; they are where the mandatory options, the exit-code mapping, the log
  file and both formats are meant to be implemented once. Do not hand-roll a `--format`.
- **Shell commands**: same options, same codes, same log path; `--format json` prints JSON
  Lines with `printf`. A sourced function `return`s the code — never `exit`.
- **`tdd-exe` builtins**: no exceptions for being built in.
