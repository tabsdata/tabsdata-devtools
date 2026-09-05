#
# Copyright 2026 Tabsdata Inc.
#

# common.sh -- what every shell command sources: the parts of
# docs/command-cli-guidelines.md that are the same for all of them.
#
#   the common options      --help/-h, --verbose/-v, --format json|view
#   the help layout         argparse's, from a declaration (_tdd_help_text)
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
# _TDD_COMMON_SH; a command file re-sources it by that name so it is explicit
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

# ---------------------------------------------------------------- prompt

# TEXT coloured for a PROMPT (PS1), in the zero-width form each shell wants --
# bash `\[\e[..m\]`, zsh `%{ESC[..m%}` -- so the cursor position stays right.
# Plain text under NO_COLOR. $1 red|green, $2 the text.
_tdd_ps1_wrap() {
    if [ -n "${NO_COLOR:-}" ]; then
        printf '%s' "$2"
        return 0
    fi
    case "$1" in
        red) _tdd_c=31 ;;
        green) _tdd_c=32 ;;
        *) _tdd_c=0 ;;
    esac
    if [ -n "${ZSH_VERSION:-}" ]; then
        printf '%%{\033[%sm%%}%s%%{\033[0m%%}' "$_tdd_c" "$2"
    else
        printf '\\[\\e[%sm\\]%s\\[\\e[0m\\]' "$_tdd_c" "$2"
    fi
    unset _tdd_c
}

# ---------------------------------------------------------------- help

# Render a command's --help in the layout argparse gives the Python tools --
# usage, description, `commands:`/`options:` tables with the help text at
# column 24 and wrapped to the terminal, epilog -- from a short declaration
# on stdin, so both halves of tdd read the same. The declaration:
#
#   usage: tdd venv create --name NAME       the first lines, up to the first
#          tdd venv list                     blank one, are printed verbatim
#
#   Free text is a paragraph and is re-wrapped; lines indented 4+ are kept.
#
#   commands:                     a section: one lowercase word and a colon
#     create    make a venv       an entry: 2-space indent, the term, two or
#               and enter it      more spaces, the help; deeper lines continue
#   options:                      the help of the entry above
#     --name NAME   the venv
#
#   Text after the sections is the epilog.
#
# The common options are added at the top of `options:` -- created after the
# last section, or after the description, when the declaration has none -- so
# no command repeats them. awk does the layout; common.bin-reqs.txt declares it.
_tdd_help_text() {
    awk -v width="${COLUMNS:-80}" '
    function sp(n) { return sprintf("%" n "s", "") }
    function wrap(text, first, rest, w,   words, nw, i, line, out, ind) {
        nw = split(text, words, / +/); line = ""; out = ""; ind = first
        for (i = 1; i <= nw; i++) {
            if (words[i] == "") continue
            if (line == "") line = words[i]
            else if (length(ind) + length(line) + 1 + length(words[i]) <= w) line = line " " words[i]
            else { out = out ind line "\n"; line = words[i]; ind = rest }
        }
        return out ind line
    }
    function entry(term, help,   pad) {
        if (help == "") { print "  " term; return }
        if (length(term) <= HC - 4) {
            pad = sprintf("%-" (HC - 2) "s", term)
            print wrap(help, "  " pad, sp(HC), W)
        } else {
            print "  " term
            print wrap(help, sp(HC), sp(HC), W)
        }
    }
    function newblock(type, text, gap) { btype[nb] = type; btext[nb] = text; bgap[nb] = gap; return nb++ }
    function flushpara() { if (para != "") { newblock("para", para, paragap); para = "" } }
    function common() {
        entry("-h, --help", "show this help message and exit")
        entry("-v, --verbose", "show debug events too")
        entry("--format {json,view}", "json is JSON Lines, one event per line (default: view)")
    }
    function section(b,   k) {
        print ""; print btext[b]
        if (btext[b] == "options:") common()
        for (k = 0; k < nent[b]; k++) entry(eterm[b, k], ehelp[b, k])
    }
    BEGIN { W = width - 2; if (W < 40) W = 40; HC = 24; n = 0; nb = 0; para = "" }
    { lines[n++] = $0 }
    END {
        i = 0
        while (i < n && lines[i] != "") { print lines[i]; i++ }
        cur = -1; gap = 1; hasopts = 0; lastsec = -1
        for (; i < n; i++) {
            l = lines[i]
            if (l == "") { flushpara(); gap = 1; continue }
            if (l ~ /^[a-z][a-z0-9 -]*:$/) {
                flushpara(); cur = newblock("sec", l, 1); nent[cur] = 0; lastsec = cur
                if (l == "options:") hasopts = 1
                gap = 0; continue
            }
            if (cur >= 0 && l ~ /^ /) {
                if (l ~ /^  [^ ]/) {
                    t = substr(l, 3)
                    if (match(t, /  +/)) { term = substr(t, 1, RSTART - 1); help = substr(t, RSTART + RLENGTH) }
                    else { term = t; help = "" }
                    k = nent[cur]++; eterm[cur, k] = term; ehelp[cur, k] = help
                } else if (nent[cur] > 0) {
                    k = nent[cur] - 1; sub(/^ +/, "", l)
                    ehelp[cur, k] = (ehelp[cur, k] == "" ? l : ehelp[cur, k] " " l)
                }
                gap = 0; continue
            }
            cur = -1
            if (l ~ /^    /) {
                flushpara()
                if (nb > 0 && btype[nb - 1] == "pre") btext[nb - 1] = btext[nb - 1] (gap ? "\n\n" : "\n") l
                else newblock("pre", l, gap)
                gap = 0; continue
            }
            sub(/^ +/, "", l); sub(/ +$/, "", l)
            if (para == "") paragap = gap
            para = (para == "" ? l : para " " l)
            gap = 0
        }
        flushpara()
        optafter = hasopts ? -2 : (lastsec >= 0 ? lastsec : (nb > 0 ? 0 : -1))
        if (optafter == -1) { print ""; print "options:"; common() }
        for (b = 0; b < nb; b++) {
            if (btype[b] == "sec") section(b)
            else { if (bgap[b]) print ""; print (btype[b] == "para") ? wrap(btext[b], "", "", W) : btext[b] }
            if (b == optafter) { print ""; print "options:"; common() }
        }
    }'
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

# A command line for the eyes and for the log, with the value of any option that
# carries a secret replaced: `tdd env set --crypto --value KEY` must not write
# the key into a world-readable /tmp log or echo it back. Both spellings,
# `--opt value` and `--opt=value`.
_tdd_mask_argv() {
    printf '%s' "$1" | sed -E 's/(--(value|password|secret|token|key))([= ])[^ ]*/\1\3****/g'
}

# The failure; exactly one, last, then return 1. Writes the log the guidelines
# require -- what the terminal did not show -- and points at it: view prints
# `details: <path>` after the message, json carries it as "log". $1 message,
# $2 details (e.g. the captured output of a subprocess).
_tdd_error() {
    _tdd_logf="/tmp/tdd-${_TDD_CMD:-shell}-$(date +%Y%m%d-%H%M%S)-$$.log"
    {
        echo "command: tdd $(_tdd_mask_argv "${_TDD_ARGV:-${_TDD_CMD:-}}")"
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

# Cyan, for a value that is not the default -- next to the plain ones around it.
_tdd_color_cyan() {
    [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && printf '\033[36m'
}

_tdd_color_off() {
    [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && printf '\033[0m'
}

# No-op: keeps the row's leading spaces out of the colour run.
_tdd_ps1_noop() {
    :
}

# ---------------------------------------------------------------- config
# `tdd <command> config [--show | --default | --create [--force]]`, the same
# action every Python tool gets from common.core.config -- here for the shell
# half. The template is rendered from the command's own tdd_defaults_<name>
# declarations (`sub|--option|value` lines), so it cannot drift from the
# options; what the file sets now comes back from `tdd-exe --defaults-doc`,
# which has the TOML parser this side lacks.
#
#     _tdd_config_action <command> "$@"

# The default document: every option commented out at its built-in value, so
# the file is a template and a line only becomes a default once uncommented.
_tdd_config_template() {
    _tdd_cfg_file="$TDD_DIR/$1.toml"
    printf '#\n# Copyright 2026 Tabsdata Inc.\n#\n\n'
    printf '# %s configuration -- %s\n#\n' "$1" "$_tdd_cfg_file"
    printf '# Written by `tdd %s config --create`; `--default` prints this document\n' "$1"
    printf '# without writing it, `--show` compares it with what is here now.\n#\n'
    printf '# Every option below is commented out at the value %s uses when you do\n' "$1"
    printf '# not say otherwise. UNCOMMENT a line to make it the default for every\n'
    printf '# `tdd %s` run: typed options always win over it, and an [options.ACTION]\n' "$1"
    printf '# table wins over [options].\n'
    printf '\n[options]\n'
    printf '# json is JSON Lines, one event per line (default: view)\n# format = "view"\n'
    printf '# show debug events too\n# verbose = false\n'
    command -v "tdd_defaults_$1" >/dev/null 2>&1 || return 0
    "tdd_defaults_$1" | sort -t'|' -k1,1 | while IFS='|' read -r _tdd_cfg_sub _tdd_cfg_opt _tdd_cfg_val; do
        [ -n "$_tdd_cfg_opt" ] || continue
        if [ "$_tdd_cfg_sub" != "$_tdd_cfg_last" ]; then
            case "$_tdd_cfg_sub" in
                - | "") ;;
                *) printf '\n[options.%s]\n# only for `tdd %s %s`\n' "$_tdd_cfg_sub" "$1" "$_tdd_cfg_sub" ;;
            esac
            _tdd_cfg_last="$_tdd_cfg_sub"
        fi
        printf '# %s = %s\n' "$(_tdd_config_key "$_tdd_cfg_opt")" "$(_tdd_config_toml "$_tdd_cfg_val")"
    done
}

# `--type` -> `type`: a TOML key is the option's dest, as on the Python side.
_tdd_config_key() {
    _tdd_cfg_k="${1#--}"
    printf '%s' "$(printf '%s' "$_tdd_cfg_k" | tr '-' '_')"
}

# A built-in default as a TOML value: true/false and numbers bare, the rest
# quoted; an empty declaration means "no default", shown as an empty string.
_tdd_config_toml() {
    case "$1" in
        true | false) printf '%s' "$1" ;;
        *[!0-9]* | "") printf '"%s"' "$1" ;;
        *) printf '%s' "$1" ;;
    esac
}

_tdd_config_action() {
    _tdd_cfg_cmd="$1"
    shift
    _tdd_cfg_what="show"
    _tdd_cfg_force=0
    _tdd_cfg_last=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --show) _tdd_cfg_what="show"; shift ;;
            --default) _tdd_cfg_what="default"; shift ;;
            --create) _tdd_cfg_what="create"; shift ;;
            --force | -f) _tdd_cfg_force=1; shift ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_config_help "$_tdd_cfg_cmd"
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_cfg_file="$TDD_DIR/$_tdd_cfg_cmd.toml"
    case "$_tdd_cfg_what" in
        default)
            _tdd_ok "$(_tdd_config_template "$_tdd_cfg_cmd")" "\"config\":\"$(_tdd_json_str "$_tdd_cfg_file")\",\"action\":\"default\""
            ;;
        create)
            if [ -e "$_tdd_cfg_file" ] && [ "$_tdd_cfg_force" != 1 ]; then
                _tdd_error "$_tdd_cfg_file already exists; --force overwrites it"
                return 1
            fi
            # Write and replace: an interrupted write leaves the previous file,
            # never half a config.
            _tdd_cfg_tmp="$TDD_DIR/.$_tdd_cfg_cmd.toml.$$.tmp"
            mkdir -p "$TDD_DIR" || { _tdd_error "cannot create $TDD_DIR"; return 1; }
            if ! _tdd_config_template "$_tdd_cfg_cmd" > "$_tdd_cfg_tmp" 2>/dev/null; then
                rm -f "$_tdd_cfg_tmp"
                _tdd_error "cannot write $_tdd_cfg_file"
                return 1
            fi
            mv "$_tdd_cfg_tmp" "$_tdd_cfg_file" || { rm -f "$_tdd_cfg_tmp"; _tdd_error "cannot write $_tdd_cfg_file"; return 1; }
            _tdd_ok "wrote $_tdd_cfg_file" "\"config\":\"$(_tdd_json_str "$_tdd_cfg_file")\",\"action\":\"create\""
            ;;
        *)
            _tdd_config_show "$_tdd_cfg_cmd"
            ;;
    esac
}

# What the options resolve to now: the built-in value, or -- highlighted -- the
# one the file sets. The file is read by tdd-exe, which has the TOML parser.
_tdd_config_show() {
    _tdd_cfg_file="$TDD_DIR/$1.toml"
    _tdd_cfg_doc="$(tdd-exe --dir "$TDD_DIR" --defaults-doc "$1" 2>/dev/null)"
    _tdd_cfg_rows="$_tdd_cfg_file$([ -f "$_tdd_cfg_file" ] || printf '  (no file yet)')
"
    _tdd_cfg_json=""
    _tdd_cfg_last=""
    { printf '%s\n' "-|--format|view" "-|--verbose|false"; command -v "tdd_defaults_$1" >/dev/null 2>&1 && "tdd_defaults_$1"; } |
        sort -t'|' -k1,1 | {
        while IFS='|' read -r _tdd_cfg_sub _tdd_cfg_opt _tdd_cfg_val; do
            [ -n "$_tdd_cfg_opt" ] || continue
            if [ "$_tdd_cfg_sub" != "$_tdd_cfg_last" ]; then
                case "$_tdd_cfg_sub" in
                    - | "") _tdd_cfg_rows="$_tdd_cfg_rows
[options]
" ;;
                    *) _tdd_cfg_rows="$_tdd_cfg_rows
[options.$_tdd_cfg_sub]
" ;;
                esac
                _tdd_cfg_last="$_tdd_cfg_sub"
            fi
            _tdd_cfg_key="$(_tdd_config_key "$_tdd_cfg_opt")"
            case "$_tdd_cfg_sub" in
                - | "") _tdd_cfg_path=".options.\"\"" ;;
                *) _tdd_cfg_path=".options.\"$_tdd_cfg_sub\"" ;;
            esac
            _tdd_cfg_set="$(printf '%s' "$_tdd_cfg_doc" | jq -r "$_tdd_cfg_path.\"$_tdd_cfg_key\" // empty | tostring" 2>/dev/null)"
            if [ -n "$_tdd_cfg_set" ]; then
                _tdd_cfg_rows="$_tdd_cfg_rows  $(_tdd_ps1_noop)$(_tdd_color_cyan)$_tdd_cfg_key = $(_tdd_config_toml "$_tdd_cfg_set")$(_tdd_color_off)   (default $(_tdd_config_toml "$_tdd_cfg_val"))
"
                _tdd_cfg_json="$_tdd_cfg_json${_tdd_cfg_json:+,}\"$_tdd_cfg_key\":\"$(_tdd_json_str "$_tdd_cfg_set")\""
            else
                _tdd_cfg_rows="$_tdd_cfg_rows  $_tdd_cfg_key = $(_tdd_config_toml "$_tdd_cfg_val")
"
            fi
        done
        _tdd_ok "${_tdd_cfg_rows%
}" "\"config\":\"$(_tdd_json_str "$_tdd_cfg_file")\",\"action\":\"show\",\"changed\":{$_tdd_cfg_json}"
    }
}

_tdd_config_help() {
    _tdd_help_text <<HELP
usage: tdd $1 config [--show | --default | --create [--force]]

The config file of \`tdd $1\`: \$TDD_DIR/$1.toml. Its [options] table holds what
this command's options default to ([options.ACTION] for one action); typed
options always win. Whatever else the command keeps lives in the same file.

options:
  --show       what the options resolve to now; what the file sets is
               highlighted, everything else is the built-in default (default)
  --default    print the default config, the document --create would write
  --create     write the default config; refuses when the file exists
  -f, --force  --create: overwrite an existing file

example: tdd $1 config --create && tdd $1 config --show
HELP
}
