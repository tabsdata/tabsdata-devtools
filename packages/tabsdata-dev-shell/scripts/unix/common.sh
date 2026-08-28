#
# Copyright 2026 Tabsdata Inc.
#

# common.sh -- what every shell command sources: the parts of
# docs/command-cli-guidelines.md that are the same for all of them.
#
#   the common options      --help/-h, --verbose/-v, --format json|view
#   the event model         command + event (ok, error, warn, info, debug)
#                           + message [+ fields], one line each
#   the two renderings      json: one JSON object per line on stdout
#                           view: ok on stdout, the rest on stderr
#   the colours             ok green, error red, warn yellow, debug white,
#                           info plain -- both formats, only on a tty
#   the failure log         /tmp/tdd-<command>-<stamp>-<pid>.log
#
# JSON is built by jq -- the one place a shell command touches JSON -- so a
# message with a tab, a quote or a newline still yields a valid line. jq is
# therefore a requirement of every shell command: common.bin-reqs.txt beside
# this file declares it, and the loader adds those names to each command's own.
#
# tdd-source.sh sources this before any command file and exports its path as
# TDD_COMMON_SH; a command file re-sources it by that name so it is explicit
# about what it depends on. The guard makes that a no-op.
#
# Works in bash 3.2 and zsh. Every temporary is _tdd_-prefixed and unset.

if [ -n "${_TDD_COMMON_LOADED:-}" ]; then
    return 0
fi
_TDD_COMMON_LOADED=1

# ---------------------------------------------------------------- options

# Start of every command: default format, not verbose, no help yet. _TDD_CMD
# is set by the dispatcher to the command word; a group refines it to the
# subcommand (venv -> venv-create) so every event and the log say which.
_tdd_cmd_reset() {
    _TDD_FORMAT="view"
    _TDD_VERBOSE=0
    _TDD_HELP=0
    _TDD_CONSUMED=0
    _TDD_BAD_FORMAT=""
}

# Consume a common option at $1 (and $2). Sets _TDD_CONSUMED to how many
# arguments it took; returns 1 if $1 is not a common option.
_tdd_common_opt() {
    case "$1" in
        --help | -h) _TDD_HELP=1; _TDD_CONSUMED=1 ;;
        --verbose | -v) _TDD_VERBOSE=1; _TDD_CONSUMED=1 ;;
        --format | --format=*)
            _tdd_optval "$@" || _TDD_OPTVAL=""
            case "$_TDD_OPTVAL" in
                view | json) _TDD_FORMAT="$_TDD_OPTVAL" ;;
                *) _TDD_BAD_FORMAT="${_TDD_OPTVAL:-<missing>}" ;;
            esac
            ;;
        *) return 1 ;;
    esac
    return 0
}

# Value of an option written `--opt value` or `--opt=value` at $1 [$2], in
# _TDD_OPTVAL; _TDD_CONSUMED says how many arguments it took. Returns 1 when
# the value is missing.
_tdd_optval() {
    case "$1" in
        *=*) _TDD_OPTVAL="${1#*=}"; _TDD_CONSUMED=1 ;;
        *)
            if [ $# -lt 2 ]; then
                _TDD_OPTVAL=""
                _TDD_CONSUMED=1
                return 1
            fi
            _TDD_OPTVAL="$2"
            _TDD_CONSUMED=2
            ;;
    esac
    return 0
}

# After parsing: the one common-option error that cannot be reported inline.
_tdd_cmd_check() {
    if [ -n "$_TDD_BAD_FORMAT" ]; then
        _tdd_error "--format must be json or view, got $_TDD_BAD_FORMAT"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------- rendering

# A string as JSON text, without the surrounding quotes -- for callers that
# assemble extra fields: "name":"$(_tdd_json_str "$name")".
_tdd_json_str() {
    jq -rn --arg v "$1" '$v | tojson | .[1:-1]'
}

# ANSI colour for an event kind, or nothing. $2 is 1 when the target stream is
# a terminal -- decided by the caller with [ -t N ], because inside $(...) fd 1
# is the capture pipe and the test would always say no. NO_COLOR wins.
_tdd_color() {
    [ -z "${NO_COLOR:-}" ] || return 0
    [ "$2" = 1 ] || return 0
    case "$1" in
        ok) printf '\033[32m' ;;
        error) printf '\033[31m' ;;
        warn) printf '\033[33m' ;;
        debug) printf '\033[37m' ;;
        # Not event kinds: paints for a command that colours rows inside its
        # ok message (tdd defaults: white = built-in, blue = customized).
        # Blue is a 256-colour entry, not palette 34/94: themes remap the 16
        # palette colours (34 becomes a near-black navy on dark themes, 94 a
        # grey-white under "minimum contrast" settings) but leave the cube
        # alone, so 38;5;33 is the same azure everywhere.
        white) printf '\033[37m' ;;
        blue) printf '\033[38;5;33m' ;;
    esac
}

_tdd_color_end() {
    [ -z "${NO_COLOR:-}" ] || return 0
    [ "$2" = 1 ] || return 0
    case "$1" in
        ok | error | warn | debug | white | blue) printf '\033[0m' ;;
    esac
}

# One event. $1 kind, $2 message, $3 extra json fields (no braces, may be
# empty). json: a line on stdout for every kind. view: ok on stdout, the rest
# on stderr. Both coloured by kind when that stream is a terminal.
_tdd_emit() {
    _tdd_tty1=0
    _tdd_tty2=0
    [ -t 1 ] && _tdd_tty1=1
    [ -t 2 ] && _tdd_tty2=1
    if [ "$_TDD_FORMAT" = json ]; then
        # Fields arrive as JSON members; jq validates them along the way, so a
        # malformed set yields a line without them, saying so, rather than a
        # broken line.
        _tdd_line="$(jq -cn --arg command "${_TDD_CMD:-}" --arg event "$1" --arg message "$2" \
            --argjson fields "{${3:-}}" \
            '{command: $command, event: $event, message: $message} + $fields' 2>&1)" \
            || _tdd_line="$(jq -cn --arg command "${_TDD_CMD:-}" --arg event "$1" \
                --arg message "$2" --arg why "$(printf '%s' "$_tdd_line" | head -1)" \
                '{command: $command, event: $event, message: $message, fields_dropped: $why}')"
        printf '%s%s%s\n' "$(_tdd_color "$1" "$_tdd_tty1")" "$_tdd_line" "$(_tdd_color_end "$1" "$_tdd_tty1")"
        unset _tdd_line
    elif [ "$1" = ok ]; then
        # A command whose ok message paints its own rows (tdd defaults) sets
        # _TDD_PRECOLORED so the message is not wrapped in green on top.
        if [ "${_TDD_PRECOLORED:-0}" = 1 ]; then
            printf '%s\n' "$2"
        else
            printf '%s%s%s\n' "$(_tdd_color ok "$_tdd_tty1")" "$2" "$(_tdd_color_end ok "$_tdd_tty1")"
        fi
    else
        printf '%s%s%s\n' "$(_tdd_color "$1" "$_tdd_tty2")" "$2" "$(_tdd_color_end "$1" "$_tdd_tty2")" >&2
    fi
    unset _tdd_tty1 _tdd_tty2
}

# The outcome; exactly one, last, then return 0. $1 message, $2 json fields.
_tdd_ok() {
    _tdd_emit ok "$1" "${2:-}"
    return 0
}

# Something worth knowing while working; always shown.
_tdd_info() {
    _tdd_emit info "$1" "${2:-}"
}

_tdd_warn() {
    _tdd_emit warn "$1" "${2:-}"
}

# Detail for --verbose only.
_tdd_debug() {
    [ "$_TDD_VERBOSE" = 1 ] || return 0
    _tdd_emit debug "$1" "${2:-}"
}

# The failure; exactly one, last, then return 1. Writes the log the guidelines
# require -- what the terminal did not show -- and points at it: view prints
# `details: <path>` after the message, json carries it as "log". $1 message,
# $2 details (e.g. the captured output of a subprocess).
_tdd_error() {
    _tdd_logf="/tmp/tdd-${_TDD_CMD:-shell}-$(date +%Y%m%d-%H%M%S)-$$.log"
    {
        echo "command: tdd ${_TDD_ARGV:-${_TDD_CMD:-}}"
        echo "cwd:     $(pwd)"
        echo "TDD_DIR: $TDD_DIR"
        echo "version: $(cat "$TDD_DIR/VERSION" 2>/dev/null)"
        echo "time:    $(date)"
        echo "error:   $1"
        if [ -n "${2:-}" ]; then
            echo
            echo "details:"
            printf '%s\n' "$2"
        fi
    } > "$_tdd_logf" 2>/dev/null
    _tdd_emit error "$1" "\"log\":\"$(_tdd_json_str "$_tdd_logf")\""
    if [ "$_TDD_FORMAT" != json ]; then
        _tdd_tty2=0
        [ -t 2 ] && _tdd_tty2=1
        printf '%sdetails: %s%s\n' "$(_tdd_color error "$_tdd_tty2")" "$_tdd_logf" "$(_tdd_color_end error "$_tdd_tty2")" >&2
        unset _tdd_tty2
    fi
    unset _tdd_logf
    return 1
}
