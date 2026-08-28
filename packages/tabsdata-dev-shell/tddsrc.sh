#
# Copyright 2026 Tabsdata Inc.
#

# tddsrc.sh -- defines the `tdd` shell function.
#
#     source ~/.tdd/tdd-source.sh
#
# Installed to <TDD_DIR>/tdd-source.sh by `tdd-install`, with the dir baked in so
# that several tdd dirs can each carry a tdd-source.sh pointing at themselves.
#
# Why a sourced function at all: `tdd-exe` is a real executable and therefore
# can never change the calling shell. Commands that must -- entering or leaving
# a toolset venv -- live as shell functions instead. `tdd` is the single front
# door over both.
#
# Works in bash 3.2 and zsh: no associative arrays, no process substitution.

# Locate ourselves rather than trusting a baked path: the whole point of the
# relocatable envs is that this tree can be moved, copied or unzipped anywhere,
# and a hardcoded TDD_DIR would defeat that on the first move. The baked value
# is only a fallback for shells that expose no script path.
if [ -n "${BASH_SOURCE:-}" ]; then
    _tdd_self="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
    _tdd_self="${(%):-%x}"
else
    _tdd_self=""
fi

if [ -n "$_tdd_self" ] && [ -f "$_tdd_self" ]; then
    TDD_DIR="$(cd "$(dirname "$_tdd_self")" && pwd)"
else
    TDD_DIR="${TDD_DIR:-__TDD_DIR__}"
fi
unset _tdd_self
export TDD_DIR

# tdd-exe lives in its own venv inside the tdd dir, so nothing needs to be
# installed globally and no venv has to be active for `tdd` to work. Wrapping
# it as a function keeps that env's other binaries off PATH.
tdd-exe() {
    if [ ! -x "$TDD_DIR/tdd-venvs/tdd/bin/tdd-exe" ]; then
        echo "tdd: no tdd-exe env at $TDD_DIR/tdd-venvs/tdd; run tdd-install" >&2
        return 2
    fi
    # The envs are relocatable but their interpreter is not inside the tree:
    # bin/python symlinks to the uv-managed Python by absolute path. If that is
    # gone -- a tdd dir unzipped on another machine, or a removed uv Python --
    # tdd-exe cannot even start, so no Python-side check could ever report it.
    # -e follows the symlink, so a dangling one fails here.
    if [ ! -e "$TDD_DIR/tdd-venvs/tdd/bin/python" ]; then
        echo "tdd: the interpreter for $TDD_DIR/tdd-venvs/tdd is unreachable." >&2
        echo "     This tdd dir was built for a different machine or its uv" >&2
        echo "     Python was removed. Rebuild here with tdd-install," >&2
        echo "     or restore it with: uv python install" >&2
        return 2
    fi
    "$TDD_DIR/tdd-venvs/tdd/bin/tdd-exe" "$@"
}

# Registry of sourced commands, as newline-separated "name|summary|kind|reqs".
# kind is "demo" for commands registered with --demo, otherwise empty: demo
# commands exist to show the shape of one and are left out of the listings
# unless asked for with --demo; they still run like any other. reqs is the
# space-separated content of the bin-reqs.txt beside the file that registered
# the command -- the loader fills _TDD_FN_REQS before sourcing each file.
# Summaries must not contain "|".
TDD_FN_COMMANDS=""
_TDD_FN_REQS=""

tdd_fn_register() {
    _tdd_kind=""
    if [ "$1" = "--demo" ]; then
        _tdd_kind="demo"
        shift
    fi
    TDD_FN_COMMANDS="${TDD_FN_COMMANDS}$1|$2|$_tdd_kind|$_TDD_FN_REQS
"
    unset _tdd_kind
}

# ---------------------------------------------------------------- loading

_tdd_load_commands() {
    _tdd_py="$TDD_DIR/tdd-venvs/shells/bin/python"
    if [ ! -x "$_tdd_py" ]; then
        echo "tdd: no shell env at $TDD_DIR/tdd-venvs/shells; run tdd-install" >&2
        unset _tdd_py
        return 1
    fi
    _tdd_scripts="$("$_tdd_py" -c \
        'from tabsdata_dev.shell import scripts_dir; print(scripts_dir())')"
    if [ -z "$_tdd_scripts" ] || [ ! -d "$_tdd_scripts" ]; then
        echo "tdd: shell command dir not found" >&2
        unset _tdd_py _tdd_scripts
        return 1
    fi
    for _tdd_f in "$_tdd_scripts"/*.sh; do
        [ -r "$_tdd_f" ] || continue
        # External binaries a command needs are declared in <file>.bin-reqs.txt
        # beside it, one bare name per line, # comments allowed -- the same
        # contract as a Python tool's bin-reqs.txt. They are checked when the
        # command is run, not here: sourcing must stay cheap and never fail.
        _TDD_FN_REQS=""
        _tdd_r="${_tdd_f%.sh}.bin-reqs.txt"
        if [ -r "$_tdd_r" ]; then
            _TDD_FN_REQS="$(sed -e 's/#.*//' "$_tdd_r" | tr -s '[:space:]' ' ' \
                | sed -e 's/^ //' -e 's/ $//')"
        fi
        # shellcheck disable=SC1090
        . "$_tdd_f"
    done
    unset _tdd_py _tdd_scripts _tdd_f _tdd_r _TDD_FN_REQS
}

_tdd_fn_has() {
    printf '%s\n' "$TDD_FN_COMMANDS" | grep -q "^$1|"
}

# Refuse to run a command whose declared binaries are not all on PATH. Failing
# up front with the whole list beats failing halfway through with a bare
# "command not found" -- and it is what makes the declaration honest.
_tdd_fn_check_reqs() {
    _tdd_missing=""
    for _tdd_b in $(printf '%s\n' "$TDD_FN_COMMANDS" | grep "^$1|" | cut -d'|' -f4); do
        command -v "$_tdd_b" >/dev/null 2>&1 || _tdd_missing="$_tdd_missing $_tdd_b"
    done
    if [ -n "$_tdd_missing" ]; then
        echo "tdd $1: missing required binaries:$_tdd_missing" >&2
        echo "  (declared in the shell command's bin-reqs.txt; see tdd --reqs)" >&2
        unset _tdd_missing _tdd_b
        return 127
    fi
    unset _tdd_missing _tdd_b
    return 0
}

# ---------------------------------------------------------------- help

# Commands from both halves, merged and sorted alphabetically. Shell ones are
# marked with * because they behave differently: they can change this shell.
# Pass --demo to include the demo commands; both halves filter on the same
# flag, tdd-exe on its catalog entry and this side on the registry's kind.
_tdd_help() {
    _tdd_show="${1:-}"
    echo "usage: tdd [--dir TDD_PATH] <command> [args...]"
    echo
    if [ "$_tdd_show" = "--demo" ]; then
        echo "commands, demo included (* runs in this shell):"
    else
        echo "commands (* runs in this shell; --demo includes the demo commands):"
    fi
    {
        printf '%s\n' "$TDD_FN_COMMANDS" | while IFS='|' read -r _n _s _k _r; do
            [ -n "$_n" ] || continue
            [ "$_k" = "demo" ] && [ "$_tdd_show" != "--demo" ] && continue
            printf '%s\t*\t%s\n' "$_n" "$_s"
        done
        # shellcheck disable=SC2086
        tdd-exe list --porcelain $_tdd_show 2>/dev/null | while IFS='|' read -r _n _k _s; do
            [ -n "$_n" ] && printf '%s\t \t%s\n' "$_n" "$_s"
        done
    } | sort -f | awk -F'\t' '{ printf "  %s %-13s %s\n", $2, $1, $3 }'
    echo
    echo "TDD_DIR=$TDD_DIR"
    unset _tdd_show
}

_tdd_fn_help() {
    _tdd_show="${1:-}"
    echo "shell commands (run in this shell):"
    printf '%s\n' "$TDD_FN_COMMANDS" | sort -f | while IFS='|' read -r _n _s _k _r; do
        [ -n "$_n" ] || continue
        [ "$_k" = "demo" ] && [ "$_tdd_show" != "--demo" ] && continue
        printf '  %-14s %s\n' "$_n" "$_s"
    done
    unset _tdd_show
}

# "--demo" if it appears among the arguments, else empty.
_tdd_demo_flag() {
    for _tdd_a in "$@"; do
        if [ "$_tdd_a" = "--demo" ]; then
            unset _tdd_a
            printf '%s' "--demo"
            return 0
        fi
    done
    unset _tdd_a
    return 0
}

# ---------------------------------------------------------------- dispatch

# The shell half of the pair: the same role as tdd-exe, for sourced functions.
tdd-fn() {
    if [ $# -eq 0 ]; then
        _tdd_fn_help
        return 0
    fi
    case "$1" in
        -h | --help | help | list)
            _tdd_fn_help "$(_tdd_demo_flag "$@")"
            return 0
            ;;
    esac
    if _tdd_fn_has "$1"; then
        _tdd_cmd="$1"
        shift
        _tdd_fn_check_reqs "$_tdd_cmd" || return $?
        "tddfn_$_tdd_cmd" "$@"
        return $?
    fi
    echo "tdd-fn: unknown shell command: $1" >&2
    return 2
}

# The front door. Routes to tdd-fn when the command is a sourced one, and to
# tdd-exe otherwise, so a caller never has to know which half owns a command.
tdd() {
    _tdd_dir_args=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --dir)
                # One token, not "--dir $2": zsh does not word-split an
                # unquoted parameter, so the two-word form reached tdd-exe as
                # a single argument there.
                TDD_DIR="$2"
                _tdd_dir_args="--dir=$2"
                shift 2
                ;;
            --dir=*)
                TDD_DIR="${1#--dir=}"
                _tdd_dir_args="$1"
                shift
                ;;
            *) break ;;
        esac
    done

    if [ $# -eq 0 ]; then
        _tdd_help
        return 0
    fi
    case "$1" in
        -h | --help | help)
            _tdd_help "$(_tdd_demo_flag "$@")"
            return 0
            ;;
    esac

    if _tdd_fn_has "$1"; then
        tdd-fn "$@"
        return $?
    fi
    # shellcheck disable=SC2086
    tdd-exe $_tdd_dir_args "$@"
    return $?
}

_tdd_load_commands
