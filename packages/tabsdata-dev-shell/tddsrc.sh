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

# The shared helpers (options, events, colours, failure log) live in the shell
# package, beside the command files; tdd itself uses them for its own output,
# so they are loaded before anything else here can speak.
_tdd_locate_common() {
    _tdd_py="$TDD_DIR/tdd-venvs/shells/bin/python"
    [ -x "$_tdd_py" ] || return 1
    _tdd_scripts="$("$_tdd_py" -c \
        'from tabsdata_dev.shell import scripts_dir; print(scripts_dir())' 2>/dev/null)"
    [ -n "$_tdd_scripts" ] && [ -r "$_tdd_scripts/common.sh" ] || return 1
    _TDD_COMMON_SH="$_tdd_scripts/common.sh"
    export _TDD_COMMON_SH
    _TDD_COMMON_DIR="$TDD_DIR"
    # Re-sourcing tdd-source.sh must reload everything -- that is how a shell
    # picks up a reinstall. common.sh guards against being sourced twice within
    # one load (each command file sources it by name); this file owns the load,
    # so it lifts the guard first.
    unset _TDD_COMMON_LOADED
    # shellcheck disable=SC1090
    . "$_TDD_COMMON_SH"
}
if ! _tdd_locate_common; then
    echo "tdd: no shell env at $TDD_DIR/tdd-venvs/shells; run tdd-install" >&2
fi
unset _tdd_py _tdd_scripts

# tdd-exe lives in its own venv inside the tdd dir, so nothing needs to be
# installed globally and no venv has to be active for `tdd` to work. Wrapping
# it as a function keeps that env's other binaries off PATH.
tdd-exe() {
    if [ ! -x "$TDD_DIR/tdd-venvs/tdd/bin/tdd-exe" ]; then
        _TDD_CMD=tdd
        _tdd_error "no tdd-exe env at $TDD_DIR/tdd-venvs/tdd; run tdd-install"
        return 1
    fi
    # The envs are relocatable but their interpreter is not inside the tree:
    # bin/python symlinks to the uv-managed Python by absolute path. If that is
    # gone -- a tdd dir unzipped on another machine, or a removed uv Python --
    # tdd-exe cannot even start, so no Python-side check could ever report it.
    # -e follows the symlink, so a dangling one fails here.
    if [ ! -e "$TDD_DIR/tdd-venvs/tdd/bin/python" ]; then
        _TDD_CMD=tdd
        _tdd_error "the interpreter for $TDD_DIR/tdd-venvs/tdd is unreachable: this tdd dir was built for a different machine or its uv Python was removed; rebuild here with tdd-install, or restore it with: uv python install"
        return 1
    fi
    "$TDD_DIR/tdd-venvs/tdd/bin/tdd-exe" "$@"
}

# Registry of sourced commands, as newline-separated "name|summary|kind|reqs".
# kind is empty on this side (every sourced command is a shell one); reqs is
# the space-separated content of the bin-reqs.txt beside the file that
# registered the command -- the loader fills _TDD_FN_REQS before sourcing each
# file. Summaries must not contain "|".
TDD_FN_COMMANDS=""
_TDD_FN_REQS=""

tdd_fn_register() {
    TDD_FN_COMMANDS="${TDD_FN_COMMANDS}$1|$2||$_TDD_FN_REQS
"
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
    # common.sh was loaded at the top of this file (see _tdd_locate_common) and
    # exported as _TDD_COMMON_SH, so each command file can source it by name.
    # What common.sh itself needs (jq); every command inherits it.
    _tdd_common_reqs=""
    if [ -r "$_tdd_scripts/common.bin-reqs.txt" ]; then
        _tdd_common_reqs="$(_tdd_read_reqs "$_tdd_scripts/common.bin-reqs.txt")"
    fi
    for _tdd_f in "$_tdd_scripts"/*.sh; do
        [ -r "$_tdd_f" ] || continue
        [ "$(basename "$_tdd_f")" != common.sh ] || continue
        # External binaries a command needs are declared in <file>.bin-reqs.txt
        # beside it, one bare name per line, # comments allowed -- the same
        # contract as a Python tool's bin-reqs.txt. They are checked when the
        # command is run, not here: sourcing must stay cheap and never fail.
        _TDD_FN_REQS="$_tdd_common_reqs"
        _tdd_r="${_tdd_f%.sh}.bin-reqs.txt"
        if [ -r "$_tdd_r" ]; then
            _TDD_FN_REQS="$_TDD_FN_REQS $(_tdd_read_reqs "$_tdd_r")"
        fi
        _TDD_FN_REQS="${_TDD_FN_REQS# }"
        # shellcheck disable=SC1090
        . "$_tdd_f"
    done
    unset _tdd_py _tdd_scripts _tdd_f _tdd_r _tdd_common_reqs _TDD_FN_REQS
}

# The bare names in a bin-reqs.txt, space-separated.
_tdd_read_reqs() {
    sed -e 's/#.*//' "$1" | tr -s '[:space:]' ' ' | sed -e 's/^ //' -e 's/ $//'
}

_tdd_fn_has() {
    printf '%s\n' "$TDD_FN_COMMANDS" | grep -q "^$1|"
}

# Refuse to run a command whose declared binaries are not all on PATH. Failing
# up front with the whole list beats failing halfway through with a bare
# "command not found" -- and it is what makes the declaration honest.
_tdd_fn_check_reqs() {
    # Help never depends on what the machine has installed.
    for _tdd_a in "$@"; do
        case "$_tdd_a" in --help | -h) unset _tdd_a; return 0 ;; esac
    done
    unset _tdd_a
    _tdd_missing=""
    for _tdd_b in $(printf '%s\n' "$TDD_FN_COMMANDS" | grep "^$1|" | cut -d'|' -f4); do
        _tdd_p="$(command -v "$_tdd_b" 2>/dev/null)" || { _tdd_missing="$_tdd_missing
  $_tdd_b  not found"; continue; }
        # A pyenv shim stands in for every program any pyenv version ever had;
        # only `pyenv which` says whether the CURRENT one provides it.
        case "$_tdd_p" in
            */shims/*)
                if grep -q pyenv "$_tdd_p" 2>/dev/null && command -v pyenv >/dev/null 2>&1; then
                    _tdd_real="$(pyenv which "$_tdd_b" 2>/dev/null)"
                    # wired = a real program, not the shim itself or another shim
                    case "$_tdd_real" in
                        "" | "$_tdd_p" | */shims/*) _tdd_missing="$_tdd_missing
  $_tdd_b  pyenv shim at $_tdd_p is not wired (pyenv which $_tdd_b finds no program)" ;;
                    esac
                fi
                ;;
        esac
    done
    if [ -n "$_tdd_missing" ]; then
        _tdd_cmd_reset
        _TDD_CMD="$1"
        _tdd_n="$(printf '%s\n' "$_tdd_missing" | grep -c '^  ')"
        _tdd_error "$1 needs $_tdd_n required binar$([ "$_tdd_n" = 1 ] && echo 'y that is' || echo 'ies that are') not on PATH:$_tdd_missing
install $([ "$_tdd_n" = 1 ] && echo it || echo them); \`tdd --reqs $1\` lists every requirement"
        unset _tdd_missing _tdd_b _tdd_p _tdd_real _tdd_n
        return 1
    fi
    unset _tdd_missing _tdd_b
    return 0
}

# ---------------------------------------------------------------- help

# Commands from both halves, merged and sorted alphabetically, as one ok event.
# view: the usage plus a listing, shell commands marked with * because they
# behave differently -- they can change this shell. json: a "commands" array.
_tdd_help() {
    _TDD_CMD=tdd
    _tdd_rows="$(_tdd_help_rows)"
    if [ "$_TDD_FORMAT" = json ]; then
        _tdd_ok "$(printf '%s\n' "$_tdd_rows" | grep -c .) commands" \
            "\"tdd_dir\":\"$(_tdd_json_str "$TDD_DIR")\",\"commands\":$(_tdd_rows_json "$_tdd_rows"),\"config\":{\"file\":\"$(_tdd_json_str "$TDD_DIR/<command>.toml")\",\"tables\":[\"options\",\"options.<action>\"],\"syntax\":\"a TOML key per option, typed options win\",\"action\":\"tdd <command> config --create|--default|--show\"}"
    else
        # The listing paints itself the way every help does -- a heading bold, a
        # command name cyan -- so the ok event must not wrap it in green. The
        # terminal test belongs out here: inside $(...) fd 1 is the capture pipe.
        _tdd_hb=""
        _tdd_hc=""
        _tdd_ho=""
        if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
            _tdd_hb="$(printf '\033[1m')"
            _tdd_hc="$(printf '\033[36m')"
            _tdd_ho="$(printf '\033[0m')"
        fi
        _tdd_head="commands (* runs in this shell):"
        _TDD_PRECOLORED=1
        _tdd_ok "${_tdd_hb}usage:${_tdd_ho} tdd [--dir TDD_PATH] [--format json|view] [--verbose] <command> [args...]

${_tdd_hb}${_tdd_head}${_tdd_ho}
$(printf '%s\n' "$_tdd_rows" | awk -F'\t' -v c="$_tdd_hc" -v o="$_tdd_ho" '{ printf "  %s %s%-13s%s %s\n", $2, c, $1, o, $3 }')

${_tdd_hb}command config:${_tdd_ho} $TDD_DIR/<command>.toml -- its [options] and [options.<action>]
  tables are what that command's options default to; typed options win
  \`tdd <command> config --create\` writes one, \`--show\` says what applies

TDD_DIR=$TDD_DIR"
        unset _TDD_PRECOLORED _tdd_hb _tdd_hc _tdd_ho
    fi
    unset _tdd_rows _tdd_head
}

# Rows as name<TAB>marker<TAB>summary<TAB>kind, sorted.
_tdd_help_rows() {
    {
        printf '%s\n' "$TDD_FN_COMMANDS" | while IFS='|' read -r _n _s _k _r; do
            [ -n "$_n" ] || continue
            printf '%s\t*\t%s\tshell\n' "$_n" "$_s"
        done
        tdd-exe --porcelain 2>/dev/null | while IFS='|' read -r _n _k _s; do
            [ -n "$_n" ] && printf '%s\t \t%s\t%s\n' "$_n" "$_s" "$_k"
        done
    } | sort -f
}

_tdd_rows_json() {
    printf '%s\n' "$1" | jq -Rsc 'split("\n") | map(select(length > 0) | split("\t")
        | {name: .[0], shell: (.[1] == "*"), summary: .[2], kind: .[3]})'
}

_tdd_fn_help() {
    _TDD_CMD=tdd-fn
    _tdd_rows="$(printf '%s\n' "$TDD_FN_COMMANDS" | while IFS='|' read -r _n _s _k _r; do
        [ -n "$_n" ] || continue
        printf '%s\t*\t%s\tshell\n' "$_n" "$_s"
    done | sort -f)"
    if [ "$_TDD_FORMAT" = json ]; then
        _tdd_ok "$(printf '%s\n' "$_tdd_rows" | grep -c .) shell commands" "\"commands\":$(_tdd_rows_json "$_tdd_rows")"
    else
        _tdd_ok "shell commands (run in this shell):
$(printf '%s\n' "$_tdd_rows" | awk -F'\t' '{ printf "  %-14s %s\n", $1, $3 }')"
    fi
    unset _tdd_rows
}

# Merge the command's configured default options into the argument list, then
# say what it resolved to. The file is <tdd_dir>/<command>.toml ([options], and
# [options.<action>] for one action); the merge itself -- typed options win, the
# action's table wins over the command's -- is tdd-exe's job, so it is one
# testable piece of Python; this side only rebuilds the argument list and says
# what it resolved to. Sets _TDD_RESOLVED (one argument per line) and
# _TDD_DEFAULTS_SRC. Returns 0 when defaults applied, 1 when none exist, 2 on
# an invalid file (already reported).
_tdd_apply_defaults() {
    _tdd_dd="$TDD_DIR/$1.toml"
    # No file, no work: the common case is not worth a subprocess.
    [ -f "$_tdd_dd" ] || return 1
    _tdd_derr="$(mktemp)"
    _tdd_dout="$(tdd-exe --defaults "$@" 2>"$_tdd_derr")"
    if [ $? -ne 0 ]; then
        _tdd_cmd_reset
        _TDD_CMD="$1"
        _tdd_error "invalid default options for $1 in $_tdd_dd" "$(cat "$_tdd_derr")"
        rm -f "$_tdd_derr"
        unset _tdd_dd _tdd_derr _tdd_dout
        return 2
    fi
    rm -f "$_tdd_derr"
    if [ -z "$_tdd_dout" ]; then
        unset _tdd_dd _tdd_derr _tdd_dout
        return 1
    fi
    _tdd_nl='
'
    _TDD_DEFAULTS_SRC="${_tdd_dout%%$_tdd_nl*}"
    _TDD_DEFAULTS_SRC="${_TDD_DEFAULTS_SRC#\# }"
    _TDD_RESOLVED="${_tdd_dout#*$_tdd_nl}"
    unset _tdd_dd _tdd_derr _tdd_dout _tdd_nl
    return 0
}

# ---------------------------------------------------------------- dispatch

# The shell half of the pair: the same role as tdd-exe, for sourced functions.
tdd-fn() {
    if [ $# -eq 0 ]; then
        _tdd_cmd_reset
        _tdd_fn_help
        return 0
    fi
    case "$1" in
        -h | --help | help | list)
            _tdd_cmd_reset
            _tdd_scan_common "$@"
            _tdd_fn_help
            return 0
            ;;
    esac
    if _tdd_fn_has "$1"; then
        _tdd_cmd="$1"
        shift
        _tdd_fn_check_reqs "$_tdd_cmd" "$@" || return $?
        # For every event and the failure log: the command word, and the
        # command line as typed. A group refines _TDD_CMD to its subcommand.
        _TDD_CMD="$_tdd_cmd"
        _TDD_ARGV="$_tdd_cmd $*"
        "tddfn_$_tdd_cmd" "$@"
        return $?
    fi
    _tdd_cmd_reset
    _TDD_CMD=tdd-fn
    _tdd_error "unknown shell command: $1 (see tdd-fn help)"
    return 1
}

# --format/--verbose wherever they appear among the arguments, into the
# renderer state; for the listings, whose options are not positional.
_tdd_scan_common() {
    _tdd_prev=""
    for _tdd_a in "$@"; do
        case "$_tdd_a" in
            --format=json) _TDD_FORMAT=json ;;
            --format=view) _TDD_FORMAT=view ;;
            --verbose | -v) _TDD_VERBOSE=1 ;;
            json | view) [ "$_tdd_prev" = --format ] && _TDD_FORMAT="$_tdd_a" ;;
        esac
        _tdd_prev="$_tdd_a"
    done
    unset _tdd_prev _tdd_a
}

# The front door. Routes to tdd-fn when the command is a sourced one, and to
# tdd-exe otherwise, so a caller never has to know which half owns a command.
tdd() {
    _tdd_cmd_reset
    _TDD_CMD=tdd
    _tdd_dir_args=""
    # _TDD_TOOL is tdd-exe's word to the tool it execs, never meant for a shell:
    # one that got exported here would make every tool believe it is another.
    if [ -n "${_TDD_TOOL+x}" ]; then
        _tdd_warn "_TDD_TOOL was set in this shell (${_TDD_TOOL}); it is tdd's private variable and is ignored"
        unset _TDD_TOOL
    fi
    # Leading options are tdd's own; --format/--verbose also travel on to the
    # command that runs, appended after its word, so `tdd --format json venv
    # list` and `tdd venv list --format json` are the same request.
    _tdd_pass=""
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
            --format | --format=* | --verbose | -v)
                _tdd_common_opt "$@" || break
                _tdd_pass="$_tdd_pass --format=$_TDD_FORMAT"
                [ "$_TDD_VERBOSE" = 1 ] && _tdd_pass="$_tdd_pass --verbose"
                shift "$_TDD_CONSUMED"
                ;;
            *) break ;;
        esac
    done
    # The helpers must come from the dir in effect -- a --dir just given, or a
    # TDD_DIR changed since this file was sourced -- and the variable is private:
    # a missing or stale value is simply recomputed.
    if [ "${_TDD_COMMON_DIR:-}" != "$TDD_DIR" ] || [ ! -r "${_TDD_COMMON_SH:-}" ]; then
        _tdd_locate_common || _tdd_warn "no shell env at $TDD_DIR/tdd-venvs/shells; run tdd-install"
    fi
    if [ -n "$_TDD_BAD_FORMAT" ]; then
        _tdd_error "--format must be json or view, got $_TDD_BAD_FORMAT"
        unset _tdd_pass
        return 1
    fi
    # Deduplicate what accumulated across repeated options.
    if [ -n "$_tdd_pass" ]; then
        _tdd_pass="--format=$_TDD_FORMAT"
        [ "$_TDD_VERBOSE" = 1 ] && _tdd_pass="$_tdd_pass --verbose"
    fi

    if [ $# -eq 0 ]; then
        _tdd_help
        unset _tdd_pass
        return 0
    fi
    case "$1" in
        -h | --help | help)
            _tdd_scan_common "$@"
            _tdd_help
            unset _tdd_pass
            return 0
            ;;
        -V | --version | --reqs)
            # shellcheck disable=SC2086
            tdd-exe $_tdd_dir_args $_tdd_pass "$@"
            unset _tdd_pass
            return $?
            ;;
    esac

    _tdd_apply_defaults "$@"
    _tdd_drc=$?
    if [ "$_tdd_drc" -eq 2 ]; then
        unset _tdd_drc
        return 1
    fi
    if [ "$_tdd_drc" -eq 0 ]; then
        _tdd_word="$1"
        # Rebuild the argument list from the resolved lines: split on newline
        # only, and with globbing off so a value like *.py stays literal.
        _tdd_ifs="$IFS"
        IFS='
'
        _tdd_glob=1
        case $- in *f*) _tdd_glob=0 ;; esac
        set -f
        # The resolved lines are the arguments after the command word, so put
        # the word back in front.
        # shellcheck disable=SC2046
        set -- "$_tdd_word" $(printf '%s\n' "$_TDD_RESOLVED")
        [ "$_tdd_glob" = 1 ] && set +f
        IFS="$_tdd_ifs"
        # Say what will run, as an info event of the command about to run, in
        # the format it will use.
        _tdd_cmd_reset
        _TDD_CMD="$_tdd_word"
        case "${2:-}" in -* | "") ;; *) _TDD_CMD="$_tdd_word-$2" ;; esac
        _tdd_prev=""
        for _tdd_a in "$@"; do
            case "$_tdd_a" in
                --format=json) _TDD_FORMAT=json ;;
                json) [ "$_tdd_prev" = --format ] && _TDD_FORMAT=json ;;
            esac
            _tdd_prev="$_tdd_a"
        done
        _tdd_info "resolved: tdd $(_tdd_mask_argv "$*")" "\"defaults\":\"$(_tdd_json_str "$_TDD_DEFAULTS_SRC")\""
        unset _tdd_word _tdd_ifs _tdd_glob _tdd_prev _tdd_a _TDD_RESOLVED _TDD_DEFAULTS_SRC
    fi
    unset _tdd_drc

    if _tdd_fn_has "$1"; then
        # shellcheck disable=SC2086
        tdd-fn "$@" $_tdd_pass
        _tdd_rc=$?
        unset _tdd_pass
        return "$_tdd_rc"
    fi
    # shellcheck disable=SC2086
    tdd-exe $_tdd_dir_args "$@" $_tdd_pass
    _tdd_rc=$?
    unset _tdd_pass
    return "$_tdd_rc"
}

_tdd_load_commands

# ---------------------------------------------------------------- prompt
# A red `* ` at the very start of the prompt says tdd is loaded in this shell;
# `tdd venv` writes its marker after it. Re-sourcing (a reinstall, a new tdd
# dir) must not stack stars, and must REPLACE the one there -- an older
# tdd-source.sh may have written a different form -- so the marker written last
# time is remembered and removed first, wherever a venv marker left it (also
# from the prompt a venv activation saved to restore). A prompt theme that
# rewrites PS1 afterwards wins; source this file after it in that case.
_tdd_star="$(_tdd_ps1_wrap red '*') "
if [ -n "${_TDD_PROMPT_MARK:-}" ]; then
    PS1="${PS1/"$_TDD_PROMPT_MARK"/}"
    [ -n "${_TDD_VENV_PS1:-}" ] && _TDD_VENV_PS1="${_TDD_VENV_PS1/"$_TDD_PROMPT_MARK"/}"
else
    # Before the marker was remembered it was written without the space.
    _tdd_old="$(_tdd_ps1_wrap red '*')"
    PS1="${PS1/"$_tdd_old"/}"
    [ -n "${_TDD_VENV_PS1:-}" ] && _TDD_VENV_PS1="${_TDD_VENV_PS1/"$_tdd_old"/}"
    unset _tdd_old
fi
PS1="$_tdd_star${PS1-}"
[ -n "${_TDD_VENV_PS1:-}" ] && _TDD_VENV_PS1="$_tdd_star$_TDD_VENV_PS1"
_TDD_PROMPT_MARK="$_tdd_star"
unset _tdd_star

# ---------------------------------------------------------------- aliases
# Commands typed often enough to earn a bare name in the shell. Each is an
# alias for `tdd <command>`, so every option, default and event stays the
# command's -- nothing is duplicated here. Written as functions rather than
# with `alias`: a shell alias is not expanded in a non-interactive shell, and
# these have to work the same in a script.
#
#     alias                command
gsx() {
    tdd gsx "$@"
}

# ---------------------------------------------------------------- hello
# One line, blank lines around it, in interactive shells only, so a shell that
# sources this from its rc says which tdd it got, from where (the version
# tdd-install stamped in <TDD_DIR>/VERSION) and how to start. A non-interactive shell -- a smoke script, scp or rsync
# over ssh reading the rc -- stays silent: output there breaks the protocol.
case $- in
    *i*)
        _tdd_v="$(cat "$TDD_DIR/VERSION" 2>/dev/null)"
        printf '\ntdd %s installed at %s -- tdd -h for help\n\n' "${_tdd_v:-?}" "$TDD_DIR"
        unset _tdd_v
        ;;
esac
