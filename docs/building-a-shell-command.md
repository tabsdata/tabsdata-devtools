<!--
Copyright 2026 Tabsdata Inc.
-->

# Building a shell command

A shell command is a function sourced into the caller's shell. Write one only for what an
executable fundamentally cannot do: change the current shell — enter or leave a venv, `cd`,
export a variable. Anything else is a Python command; it gets a real environment, real tests,
and does not have to be written for bash 3.2.

Each command is one file under `packages/tabsdata-dev-shell/scripts/unix/`, sourced by
`tdd-source.sh` at shell start-up. Copy `demo-fn1.sh`. Its options, exit codes and output
follow [command-cli-guidelines.md](command-cli-guidelines.md).

## 1. Register and define

```sh
#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Why this is a shell command and not a Python tool, in a sentence.

tdd_fn_register gitroot "cd to the top of the current git checkout"

tddfn_gitroot() {
    _tdd_cmd_reset
    ...                                          # see section 3
}
```

The first thing every command file does is source `common.sh` through `$TDD_COMMON_SH`, which
`tdd-source.sh` exports before loading any command. It is a no-op the second time; the point is
that the file says what it depends on.

Two conventions, both checked by the shell package's tests: `tdd_fn_register <name> "<summary>"`
and a matching `tddfn_<name>()`. The name is the word after `tdd`; it may contain hyphens and
must not collide with a Python tool or a builtin (`doctor`, `info`, `help`) — the
generator rejects the collision. The summary must not contain `|`: the registry is
pipe-delimited and would truncate it.

Register with `--demo` — `tdd_fn_register --demo <name> "..."` — for a sample that should stay
out of `tdd help` unless `--demo` is passed. It still runs.

A file may register several commands; a group with sub-words is a single command that routes
on `$1` — see `tdd-env.sh`, which handles `activate --toolset <ts>` and `deactivate`.

Declare the built-in defaults of your options next to the registration, so `tdd defaults
--command <name>` can show them against the user's `default-opts/` customizations:

```sh
tdd_defaults_gitroot() {
    printf '%s\n' "-|--depth|1"          # subcommand|--option|value; `-` = no subcommand
}
```

## 2. Declare external binaries

If the function calls anything beyond shell builtins and the tdd envs, list it in
`<file>.bin-reqs.txt` beside the script, one bare name per line, `#` comments allowed. The
file applies to every command the script registers. Omit it if there is nothing to declare.

```
# gitroot.bin-reqs.txt -- external binaries gitroot needs on PATH.
git
```

`common.bin-reqs.txt` beside `common.sh` lists what every command needs because `common.sh`
uses it — today `jq`, which builds every JSON line — and is added to each command's own list.
The loader reads both while sourcing and stores the names in the registry; `tdd-fn` checks each
with `command -v` **before running the command** and refuses with the full list if any is
missing. `tdd --reqs` reports every declaration as `[ok]`/`[missing]` — shell commands
are marked `(shell)` — and `cargo make check` fails on a missing one. Sourcing itself never
fails: a missing binary must not break every shell that sources `tdd-source.sh`.

## 3. Follow the CLI guidelines through the helpers

[command-cli-guidelines.md](command-cli-guidelines.md) applies: `--help`/`-h`, `--verbose`/`-v`,
`--format json|view`, the event model (`ok`, `error`, `warn`, `info`, `debug`, each carrying the
command name), the colours, exit `0` or `1`, and a failure log in `/tmp/`. `common.sh`
implements all of it once; a command only calls the helpers and never prints on its own —
the tests reject a stray `echo`. `demo-fn1.sh` is the smallest example, `venv.sh` the fullest.

```sh
tddfn_gitroot() {
    _tdd_cmd_reset                                   # resets format/verbose/help state
    while [ $# -gt 0 ]; do
        case "$1" in
            --depth | --depth=*)                     # your own option, `--x v` or `--x=v`
                _tdd_optval "$@" || { _tdd_error "--depth needs a value"; return 1; }
                _tdd_depth="$_TDD_OPTVAL"; shift "$_TDD_CONSUMED" ;;
            *)                                       # the common options, or an error
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED" ;;
        esac
    done
    [ "$_TDD_HELP" = 1 ] && { _tdd_help_gitroot; return 0; }
    _tdd_cmd_check || return 1                       # rejects a bad --format
    _tdd_info "git rev-parse"                        # progress: json line / stderr
    _tdd_top="$(git rev-parse --show-toplevel 2>&1)" \
        || { _tdd_error "not inside a git checkout" "$_tdd_top"; return 1; }
    cd "$_tdd_top" || { _tdd_error "cannot cd to $_tdd_top"; return 1; }
    _tdd_ok "$_tdd_top" "\"path\":\"$(_tdd_json_str "$_tdd_top")\""
    unset _tdd_top _tdd_depth
}
```

Two small edits above the loop: `_tdd_optval` handles `--depth v` and `--depth=v`, and every
error names the option. A group (`tdd venv create …`) sets `_TDD_CMD="venv-create"` when it
routes, so events and the log name the subcommand.

| Helper | Does |
|---|---|
| `_tdd_cmd_reset` | start of every command: `--format view`, not verbose, no help yet |
| `_tdd_common_opt "$@"` | consumes `--help`/`-h`, `--verbose`/`-v`, `--format X`/`--format=X`; sets `_TDD_CONSUMED`; returns 1 if `$1` is not one of them |
| `_tdd_optval "$@"` | value of `--opt v` or `--opt=v` into `_TDD_OPTVAL`; returns 1 if missing |
| `_tdd_cmd_check` | after parsing: fails on an invalid `--format` |
| `_tdd_info msg [fields]` | progress, shown always: a json line, or stderr in view |
| `_tdd_warn msg [fields]` | same, yellow |
| `_tdd_debug msg [fields]` | only under `--verbose`, white |
| `_tdd_ok msg [fields]` | the one result, last, green; stdout in view; then return 0 |
| `_tdd_help_text <<'HELP'` | renders `--help` from a declaration on stdin, in argparse's layout (below) |
| `_tdd_error msg [details]` | writes `/tmp/tdd-<cmd>-<stamp>-<pid>.log`, emits the red `error` event with the path (view adds `details: <path>`), returns 1 — always `return 1` right after it |

`fields` is a string of extra JSON members, `"name":"x","count":3`, appended to the json line;
quote values through `_tdd_json_str` (jq-escaped, so tabs, quotes and newlines are safe).
`common.sh` assembles and validates the line with jq; a command never writes JSON by hand.
Colours appear only when the stream is a terminal and `NO_COLOR` is unset.

Subcommand groups (`tdd venv create …`) route on `$1` inside the function and pass the rest
on; `venv.sh` shows the shape, including the cleanup of `_tdd_` temporaries in one place.

### Help, laid out like the Python tools

`--help` must read the same whether the command is Python or shell, so a shell command does
not format its help: it declares it and `_tdd_help_text` renders it as argparse would — usage,
description, `commands:`/`options:` tables with the help text at column 24 and wrapped to the
terminal, epilog. The common options are added to `options:` (or an `options:` section is
created) automatically; never list them yourself.

```sh
_tdd_help_gitroot() {
    _tdd_help_text <<'HELP'
usage: tdd gitroot [--depth N]

cd to the top of the current git checkout.

options:
  --depth N   how many levels to climb at most (default: 1)

example: tdd gitroot && pwd
HELP
}
```

The declaration is line-oriented: the lines up to the first blank one are the usage and are
printed as written; free text is a paragraph and gets re-wrapped (lines indented four or
more are kept verbatim, for examples); a lowercase word ending in `:` at column 0 opens a
section, whose entries are indented two spaces — the term, two or more spaces, the help —
with deeper-indented lines continuing the help of the entry above. `commands:` for the
sub-words of a group, `options:` for options, `example:` in the epilog. `tdd venv --help`
and `tdd defaults --help` are the fullest examples.

### User defaults: nothing to do

A user can preset any of your options in `$TDD_DIR/default-opts/<name>.txt` (or
`<name>_<action>.txt`, e.g. `venv_create.txt`). `tdd` merges those into the argument list *before* your function
runs and prints the resolved command line, so by the time `tddfn_<name>` sees `$@` the defaults
are already there, typed options already having won. Your command parses its arguments exactly
as if the user had typed everything; there is no file to read and no flag to check. The one
thing you provide is the `tdd_defaults_<name>` declaration above, so `tdd defaults` can show
your built-ins next to the user's overrides — and can warn when a user's `<name>_<action>.txt`
names an action you do not have.

## 4. Write for both shells

`tdd-source.sh` and every command run unmodified in **bash 3.2** (macOS `/bin/bash`) and
**zsh**. In practice:

- No arrays, no associative arrays, no `local`-only idioms that differ, no `[[ ]]`-specific
  features you cannot do with `[ ]`, no process substitution.
- Prefix temporaries with `_tdd_` and `unset` them before returning — a sourced function's
  variables leak into the user's shell.
- Quote every expansion. zsh does not word-split an unquoted parameter, so `cmd $args`
  passes one word there and several in bash; build single tokens (`--dir=$x`) or use `"$@"`.
- Write errors to `>&2` and `return` a code; never `exit`, which would close the user's shell.
- Use `$TDD_DIR` for the tdd dir. It is exported by `tdd-source.sh` and follows the tree if
  the dir is moved.

## 5. Test and run

The shell package's tests (`packages/tabsdata-dev-shell/src/python/test/test_shell.py`)
check the conventions above statically: every file sources `common.sh`, registers something,
defines its `tddfn_`, uses the helpers (and never `echo`es), returns only 0 or 1, declares its help
through `_tdd_help_text` (whose layout is itself tested);
no `|` in summaries; every `*.bin-reqs.txt` sits beside a script; the demo commands use what
they declare. Add a case for your command if it has structure worth
pinning down. `cargo make test` runs them.

Scripts are read from the shells env, which in an editable install links this checkout — so a
saved edit is live for the next shell that sources `tdd-source.sh`. In the shell you already
have, re-source it:

```bash
source ~/.tdd/tdd-source.sh
tdd gitroot
tdd --reqs gitroot
```

Adding or renaming a file also needs `cargo make gen` (or any `cargo make install`) so the
catalog — which `tdd --reqs` and the collision check read — knows about it. In a wheels-mode
install, scripts are frozen into the `tabsdata-dev-shell` wheel and need a rebuild.

One file is *not* live even in an editable install: `tddsrc.sh`. `<tdd_dir>/tdd-source.sh` is
a copy of it with the dir baked in, written by `tdd-install`, so an edit to the template (the
loader, the `tdd`/`tdd-fn` functions, default-opts handling) needs `cargo make install -- -e`
and a fresh `source`. `common.sh` and the command files are read from the checkout and are live.
