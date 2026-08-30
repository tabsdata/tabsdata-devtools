#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${_TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# What a command's options default to, and where each default comes from:
# the command's own built-in value (white) or a line in
# $TDD_DIR/default-opts/<command>.txt / <command>_<action>.txt (blue).
#
#     tdd defaults --command venv
#
# A shell command declares its built-ins with a tdd_defaults_<name> function
# printing `subcommand|--option|value` lines (`-` for no subcommand); the
# common --format/--verbose are known for every command. A Python tool keeps
# its built-ins in argparse, so only its customized file can be shown.
#
# Reads the same files `tdd` applies, so a shell command is the natural home;
# it also has to know the shell registry to find the declaring functions.

tdd_fn_register defaults "show a command's option defaults: built-in in white, customized in blue"

tddfn_defaults() {
    _tdd_cmd_reset
    _tdd_target=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --command | --command=*)
                _tdd_optval "$@" || { _tdd_error "--command needs a value"; return 1; }
                _tdd_target="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_defaults_help
        unset _tdd_target
        return 0
    fi
    _tdd_cmd_check || { unset _tdd_target; return 1; }
    # The directory is checked on every run, with or without --command: a
    # misspelled directory or file silently does nothing, and that silence is
    # what these warnings exist to break.
    _tdd_defaults_audit
    if [ -n "$_tdd_target" ]; then
        _tdd_defaults_show "$_tdd_target"
        _tdd_rc=$?
    else
        _tdd_defaults_summary
        _tdd_rc=$?
    fi
    unset _tdd_target _tdd_rows _tdd_json _tdd_tty _tdd_line _tdd_sub _tdd_opt _tdd_val _tdd_src _tdd_f _tdd_paint _tdd_n _tdd_last _tdd_head _tdd_from _tdd_dd _tdd_base _tdd_stem _tdd_cmd _tdd_action _tdd_actions _tdd_cmds
    return "$_tdd_rc"
}

_tdd_defaults_help() {
    _tdd_help_text <<'HELP'
usage: tdd defaults [--command NAME]

Show what a command's options default to and where each value comes from.
Options typed on the command line always win over these. Without --command:
check the directory and list the commands that have customizations. Every run
warns about a missing directory and about files that name no command or action.

options:
  --command NAME   a command `tdd help --demo` lists

sources:
  built-in     the command's own default (white)
  customized   your value from a file in $TDD_DIR/default-opts/ (blue); it
               overrides the built-in

files:
  <command>.txt            every action of <command>
  <command>_<action>.txt   one action only

Each file, under $TDD_DIR/default-opts/, holds ONE OPTION PER LINE, as it would
be typed; # starts a comment:

    # default-opts/venv_create.txt
    --type conda
    --python 3.12.13

example: tdd defaults --command venv
HELP
}

# Warnings about the default-opts directory itself: absent (every default is
# then a built-in), a file without .txt, a file naming no command or no action,
# a line carrying two options. Never fails: these are the user's files.
_tdd_defaults_audit() {
    _tdd_dd="$TDD_DIR/default-opts"
    if [ ! -d "$_tdd_dd" ]; then
        _tdd_warn "no $_tdd_dd/ directory: every default is a built-in one (create it and add <command>.txt or <command>_<action>.txt files)"
        return 0
    fi
    for _tdd_f in $(find "$_tdd_dd" -maxdepth 1 -mindepth 1 2>/dev/null | sort); do
        _tdd_base="$(basename "$_tdd_f")"
        case "$_tdd_base" in
            *.txt) ;;
            *)
                _tdd_warn "default-opts/$_tdd_base is ignored: default files end in .txt"
                continue
                ;;
        esac
        _tdd_stem="${_tdd_base%.txt}"
        _tdd_cmd="${_tdd_stem%%_*}"
        _tdd_action=""
        [ "$_tdd_stem" != "$_tdd_cmd" ] && _tdd_action="${_tdd_stem#*_}"
        if ! _tdd_defaults_known "$_tdd_cmd"; then
            _tdd_warn "default-opts/$_tdd_base names no command: '$_tdd_cmd' (see tdd help --demo)"
            continue
        fi
        if [ -n "$_tdd_action" ] && command -v "tdd_defaults_$_tdd_cmd" >/dev/null 2>&1; then
            _tdd_actions="$("tdd_defaults_$_tdd_cmd" | cut -d'|' -f1 | grep -v '^-$' | sort -u | tr '\n' ' ')"
            case " $_tdd_actions" in
                *" $_tdd_action "*) ;;
                *) _tdd_warn "default-opts/$_tdd_base: $_tdd_cmd has no action '$_tdd_action' (actions: ${_tdd_actions% })" ;;
            esac
        fi
        grep -nE '^[[:space:]]*--[^[:space:]]+([[:space:]]+|=)[^#]*[[:space:]]--' "$_tdd_f" | while IFS=: read -r _tdd_n _tdd_line; do
            _tdd_warn "default-opts/$_tdd_base:$_tdd_n holds two options on one line; one option per line"
        done
    done
    return 0
}

# Without --command: which commands have customizations.
_tdd_defaults_summary() {
    _tdd_dd="$TDD_DIR/default-opts"
    # Only commands that exist: the audit above has already warned about the rest.
    _tdd_cmds=""
    for _tdd_cmd in $(find "$_tdd_dd" -maxdepth 1 -name '*.txt' 2>/dev/null | sed -e 's|.*/||' -e 's/\.txt$//' -e 's/_.*//' | sort -u); do
        _tdd_defaults_known "$_tdd_cmd" && _tdd_cmds="$_tdd_cmds $_tdd_cmd"
    done
    _tdd_cmds="${_tdd_cmds# }"
    if [ -z "$_tdd_cmds" ]; then
        _tdd_ok "no customized defaults; every command uses its built-in ones (tdd defaults --command <name> shows them)" '"commands":[]'
    else
        _tdd_ok "customized defaults for: $_tdd_cmds (tdd defaults --command <name> for the details)" \
            "\"commands\":$(printf '%s\n' $_tdd_cmds | jq -Rsc 'split("\n") | map(select(length > 0))')"
    fi
}

# Is $1 something `tdd` would run: a shell command, or a tool or builtin
# tdd-exe knows?
_tdd_defaults_known() {
    _tdd_fn_has "$1" && return 0
    tdd-exe --porcelain --demo 2>/dev/null | cut -d'|' -f1 | grep -qx -- "$1"
}

# Rows for one command: built-ins (declared by tdd_defaults_<name>, plus the
# common options), then the customized files, each customized line replacing
# a built-in of the same action and option.
_tdd_defaults_show() {
    if ! _tdd_defaults_known "$1"; then
        _tdd_error "unknown command: $1 (see tdd help --demo)"
        return 1
    fi
    _tdd_rows=""
    if command -v "tdd_defaults_$1" >/dev/null 2>&1; then
        _tdd_rows="$("tdd_defaults_$1")
"
    elif ! _tdd_fn_has "$1"; then
        _tdd_info "$1 is a Python tool or a builtin: its own built-in defaults live in the tool; only the common options and your customizations are shown"
    fi
    _tdd_rows="${_tdd_rows}-|--format|view
-|--verbose|false
"
    # built-in|action|opt|val, then customized|action|opt|val|file
    _tdd_rows="$(printf '%s' "$_tdd_rows" | awk -F'|' 'NF >= 2 { print "built-in|" $1 "|" $2 "|" $3 }')
"
    for _tdd_f in $(find "$TDD_DIR/default-opts" -maxdepth 1 \( -name "$1.txt" -o -name "$1_*.txt" \) 2>/dev/null | sort); do
        _tdd_sub="$(basename "$_tdd_f" .txt)"
        _tdd_sub="${_tdd_sub#"$1"}"
        _tdd_sub="${_tdd_sub#_}"
        [ -n "$_tdd_sub" ] || _tdd_sub="-"
        while IFS= read -r _tdd_line; do
            _tdd_line="$(printf '%s' "$_tdd_line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]#.*$//' -e 's/^#.*$//')"
            [ -n "$_tdd_line" ] || continue
            case "$_tdd_line" in
                *=*) _tdd_opt="${_tdd_line%%=*}"; _tdd_val="${_tdd_line#*=}" ;;
                *" "*) _tdd_opt="${_tdd_line%% *}"; _tdd_val="${_tdd_line#* }" ;;
                *) _tdd_opt="$_tdd_line"; _tdd_val="true" ;;
            esac
            # a customized value replaces the built-in row for the same option
            _tdd_rows="$(printf '%s' "$_tdd_rows" | awk -F'|' -v s="$_tdd_sub" -v o="$_tdd_opt" \
                '!($1 == "built-in" && $2 == s && $3 == o)')
customized|$_tdd_sub|$_tdd_opt|$_tdd_val|$(basename "$_tdd_f")
"
        done < "$_tdd_f"
    done
    # command-wide rows ("-") first, then each action, options alphabetical
    _tdd_rows="$(printf '%s' "$_tdd_rows" | grep . | sort -t'|' -k2,2 -k3,3)"

    _tdd_n="$(printf '%s\n' "$_tdd_rows" | grep -c .)"
    _tdd_json="$(printf '%s\n' "$_tdd_rows" | jq -Rsc --arg cmd "$1" 'split("\n") | map(select(length > 0) | split("|")
        | {command: $cmd, action: (if .[1] == "-" then null else .[1] end), option: .[2], value: .[3],
           source: (if .[0] == "built-in" then "built-in" else "default-opts/" + .[4] end)})')"
    if [ "$_TDD_FORMAT" = json ]; then
        _tdd_ok "$_tdd_n option defaults for $1" "\"target\":\"$(_tdd_json_str "$1")\",\"defaults\":$_tdd_json"
        return 0
    fi
    # view: a heading per command/action, one row per option, the source spelled
    # out. Legend and headings in ok-green, rows white (built-in) or blue
    # (customized); each piece paints itself, and the message is marked
    # pre-coloured so the renderer does not wrap it in green a second time.
    _tdd_tty=0
    [ -t 1 ] && _tdd_tty=1
    _TDD_PRECOLORED=1
    _tdd_ok "$(
        printf '%soption defaults for %s   (white: built-in, blue: from %s/default-opts)%s\n' \
            "$(_tdd_color ok "$_tdd_tty")" "$1" "$TDD_DIR" "$(_tdd_color_end ok "$_tdd_tty")"
        _tdd_last=""
        printf '%s\n' "$_tdd_rows" | while IFS='|' read -r _tdd_src _tdd_sub _tdd_opt _tdd_val _tdd_f; do
            if [ "$_tdd_sub" != "$_tdd_last" ]; then
                if [ "$_tdd_sub" = "-" ]; then
                    _tdd_head="$1 (every action)"
                else
                    _tdd_head="$1 $_tdd_sub"
                fi
                printf '\n%s%s%s\n' "$(_tdd_color ok "$_tdd_tty")" "$_tdd_head" "$(_tdd_color_end ok "$_tdd_tty")"
                _tdd_last="$_tdd_sub"
            fi
            if [ "$_tdd_src" = built-in ]; then
                _tdd_paint=white
                _tdd_from="built-in"
            else
                _tdd_paint=blue
                _tdd_from="default-opts/$_tdd_f"
            fi
            printf '%s  %-22s %-16s %s%s\n' "$(_tdd_color "$_tdd_paint" "$_tdd_tty")" \
                "$_tdd_opt" "${_tdd_val:-<none>}" "$_tdd_from" "$(_tdd_color_end "$_tdd_paint" "$_tdd_tty")"
        done
    )"
    unset _TDD_PRECOLORED
}
