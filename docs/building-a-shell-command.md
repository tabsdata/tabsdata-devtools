<!--
Copyright 2026 Tabsdata Inc.
-->

# Building a shell command

A shell command is a function sourced into the caller's shell. Write one only for what an
executable cannot do: change the current shell -- enter or leave a venv, export a variable, `cd`.
Anything else is a Python command. Each command is one file under
`packages/tabsdata-dev-shell/scripts/unix/`; copy `tdd-env.sh`, the smallest one. Options, exit codes and output
follow [command-cli-guidelines.md](command-cli-guidelines.md).

## 1. Register and define

```sh
#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${_TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Why this is a shell command and not a Python tool, in a sentence.

tdd_fn_register gitroot "cd to the top of the current git checkout"

tdd_defaults_gitroot() {                       # built-in option values, for `config`
    printf '%s\n' "-|--depth|1"              # subcommand|--option|value; `-` = none
}

tddfn_gitroot() {
    _tdd_cmd_reset
    while [ $# -gt 0 ]; do
        case "$1" in
            --depth | --depth=*)               # your option, `--x v` or `--x=v`
                _tdd_optval "$@" || { _tdd_error "--depth needs a value"; return 1; }
                _tdd_depth="$_TDD_OPTVAL"; shift "$_TDD_CONSUMED" ;;
            *)                                 # the common options, or an error
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED" ;;
        esac
    done
    [ "$_TDD_HELP" = 1 ] && { _tdd_help_gitroot; return 0; }
    _tdd_cmd_check || return 1                 # rejects a bad --format
    _tdd_info "git rev-parse"
    _tdd_top="$(git rev-parse --show-toplevel 2>&1)" \
        || { _tdd_error "not inside a git checkout" "$_tdd_top"; return 1; }
    cd "$_tdd_top" || { _tdd_error "cannot cd to $_tdd_top"; return 1; }
    _tdd_ok "$_tdd_top" "\"path\":\"$(_tdd_json_str "$_tdd_top")\""
    unset _tdd_top _tdd_depth
}

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

Conventions the shell tests check: the file sources `common.sh` first; `tdd_fn_register <name>
"<summary>"` (no `|` in the summary -- the registry
is pipe-delimited) and a matching `tddfn_<name>`; the name must not collide with a tool or a
builtin. A group routes on `$1` and sets `_TDD_CMD="venv-create"` so events and the log name the
subcommand (`venv.sh` is the fullest example). Help is *declared*, not formatted: `_tdd_help_text`
renders usage, paragraphs, `commands:`/`options:` sections and an epilog in argparse's layout,
adding the common options itself.

| Helper | Does |
|---|---|
| `_tdd_cmd_reset` | start of every command: view format, not verbose, no help yet |
| `_tdd_common_opt "$@"` | consumes `--help`/`-h`, `--verbose`/`-v`, `--format X`; sets `_TDD_CONSUMED`; 1 if `$1` is none of them |
| `_tdd_optval "$@"` | value of `--opt v` / `--opt=v` into `_TDD_OPTVAL`; 1 if missing |
| `_tdd_cmd_check` | after parsing: fails on an invalid `--format` |
| `_tdd_info` / `_tdd_warn` / `_tdd_debug msg [fields]` | progress (always / yellow / only with `--verbose`) |
| `_tdd_ok msg [fields]` | the one result, last, green; stdout in view |
| `_tdd_error msg [details]` | writes `/tmp/tdd-<cmd>-<stamp>-<pid>.log`, red `error` event with the path; always `return 1` right after |
| `_tdd_help_text <<'HELP'` | renders `--help` from a declaration on stdin |

`fields` is extra JSON members (`"name":"x","count":3`); quote values through `_tdd_json_str`.
`common.sh` builds every line with jq; a command never writes JSON or `echo`es. Defaults from
`<tdd_dir>/<name>.toml` arrive merged into `$@` -- nothing to do beyond `tdd_defaults_<name>`,
which is also what `tdd <name> config --create` writes as the template.

## 2. Declare external binaries

Anything beyond shell builtins and the tdd envs goes in `<file>.bin-reqs.txt` beside the script,
one bare name per line (`common.bin-reqs.txt` -- `jq`, `awk` -- is added to every command).
`tdd-fn` checks them with `command -v` before running the command and refuses with the full list
(`--help` excepted); `tdd --reqs` reports; `cargo make check` fails on a missing one. Sourcing
itself never checks anything.

## 3. Write `<name>.design.md`

Beside the script, with the house header, short: why it has to be a shell command, what it
changes in the shell and how (variables, prompt, files), and the decisions a reader cannot see
from the code. Do not repeat `--help`. `tdd-env.design.md` is the smallest real example; a test
fails when a script has none.

## 4. Write for both shells

Everything runs unmodified in **bash 3.2** and **zsh**: no arrays, no `[[ ]]`-only features, no
process substitution; prefix temporaries with `_tdd_` and `unset` them before returning (a
sourced function leaks into the user's shell); quote every expansion (zsh does not word-split, so
build single tokens like `--dir=$x`); `return` a code, never `exit`; use `$TDD_DIR` for the tdd dir.

## 5. Test and run

`packages/tabsdata-dev-shell/src/python/test/test_shell.py` checks the conventions statically;
add a case when your command has structure worth pinning. In an editable install a saved edit is
live for the next shell that sources `tdd-source.sh` (re-`source` the current one); adding or
renaming a file needs `cargo make gen` (or any install) so the catalog knows it. `tddsrc.sh` is
the exception -- `<tdd_dir>/tdd-source.sh` is a copy written at install, so an edit to the loader
needs `cargo make install -- -e` and a fresh `source`.
