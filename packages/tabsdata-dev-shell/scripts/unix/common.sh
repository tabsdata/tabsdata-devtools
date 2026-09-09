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
    # The colours the Python half paints (common.core.render.colorize_help): a
    # heading bold, a term -- what stands before a description -- cyan, and
    # nothing when stdout is not a terminal or NO_COLOR is set. Painted onto
    # finished lines, so no column moves.
    _tdd_hl_bold=""
    _tdd_hl_term=""
    _tdd_hl_off=""
    if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
        _tdd_hl_bold="$(printf '\033[1m')"
        _tdd_hl_term="$(printf '\033[36m')"
        _tdd_hl_off="$(printf '\033[0m')"
    fi
    awk -v width="${COLUMNS:-80}" \
        -v bold="$_tdd_hl_bold" -v termcol="$_tdd_hl_term" -v off="$_tdd_hl_off" '
    function paintline(l,   m, start, stop) {
        if (bold == "") return l
        if (l ~ /^[a-z][a-z0-9 \/_-]*:$/) return bold l off
        if (l ~ /^(usage|examples?):( |$)/) {
            m = index(l, ":")
            return bold substr(l, 1, m) off substr(l, m + 1)
        }
        if (match(l, /^  \* [^ ]/) || match(l, /^ {1,6}[^ ]/)) {
            start = RSTART + RLENGTH - 1
            stop = start
            while (stop < length(l) && substr(l, stop + 1, 2) != "  ") stop++
            if (stop < length(l))
                return substr(l, 1, start - 1) termcol substr(l, start, stop - start + 1) off substr(l, stop + 1)
        }
        return l
    }
    function paint(s,   parts, np, i, out) {
        if (bold == "") return s
        np = split(s, parts, "\n")
        out = ""
        for (i = 1; i <= np; i++) out = out (i > 1 ? "\n" : "") paintline(parts[i])
        return out
    }
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
    function entry(term, help,   pad) { indented(2, term, help) }
    # argparse indents a subcommand four and keeps the description column, so
    # `positional arguments:` reads as a list under its SUBCOMMAND heading.
    function entry4(term, help,   pad) { indented(4, term, help) }
    # `pre` replaces the plain indent for an entry that carries a marker. It has
    # to be exactly n wide, so the names stay in one column whether or not they
    # are marked -- the marker sits in the margin, not in the name.
    function indented(n, term, help, pre,   pad) {
        if (pre == "") pre = sp(n)
        if (help == "") { print paint(pre term); return }
        if (length(term) <= HC - n - 2) {
            pad = sprintf("%-" (HC - n) "s", term)
            print paint(wrap(help, pre pad, sp(HC), W))
        } else {
            print pre term
            print wrap(help, sp(HC), sp(HC), W)
        }
    }
    function newblock(type, text, gap) { btype[nb] = type; btext[nb] = text; bgap[nb] = gap; return nb++ }
    function flushpara() { if (para != "") { newblock("para", para, paragap); para = "" } }
    function common() {
        entry("--help, -h", "show this help message and exit")
        entry("--verbose, -v", "show debug events too")
        entry("--format {json,view}", "json is JSON Lines, one event per line (default: view)")
    }
    function section(b,   k) {
        print ""; print paint(btext[b])
        if (btext[b] == "options:") common()
        for (k = 0; k < nent[b]; k++) {
            if (edeep[b, k]) indented(4, eterm[b, k], ehelp[b, k], emark[b, k])
            else entry(eterm[b, k], ehelp[b, k])
        }
    }
    BEGIN { W = width - 2; if (W < 40) W = 40; HC = 24; n = 0; nb = 0; para = "" }
    { lines[n++] = $0 }
    END {
        i = 0
        while (i < n && lines[i] != "") { print paint(lines[i]); i++ }
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
                if (l ~ /^  [^ ]/ || l ~ /^    [^ ]/) {
                    # `  * name` is a four-column entry whose first two columns
                    # hold the marker: same name column as `    name`
                    mark = (l ~ /^  \* [^ ]/) ? "  * " : ""
                    deep = (mark != "" || l ~ /^    [^ ]/)
                    t = substr(l, deep ? 5 : 3)
                    if (match(t, /  +/)) { term = substr(t, 1, RSTART - 1); help = substr(t, RSTART + RLENGTH) }
                    else { term = t; help = "" }
                    k = nent[cur]++; eterm[cur, k] = term; ehelp[cur, k] = help
                    edeep[cur, k] = deep; emark[cur, k] = mark
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
        if (optafter == -1) { print ""; print paint("options:"); common() }
        for (b = 0; b < nb; b++) {
            if (btype[b] == "sec") section(b)
            else { if (bgap[b]) print ""; print (btype[b] == "para") ? wrap(btext[b], "", "", W) : paint(btext[b]) }
            if (b == optafter) { print ""; print paint("options:"); common() }
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
        # ok message (`config --show`: green = built-in default, blue = what
        # the file sets, white = the built-in named beside it; `gsx stacks`:
        # green the stack you are on, blue the others, yellow your branch).
        # The Python half paints with the same four codes (render.PAINTS).
        # Blue is a 256-colour entry, not palette 34/94: themes remap the 16
        # palette colours (34 becomes a near-black navy on dark themes, 94 a
        # grey-white under "minimum contrast" settings) but leave the cube
        # alone, so 38;5;33 is the same azure everywhere.
        green) printf '\033[32m' ;;
        white) printf '\033[37m' ;;
        blue) printf '\033[38;5;33m' ;;
        yellow) printf '\033[33m' ;;
    esac
}

_tdd_color_end() {
    [ -z "${NO_COLOR:-}" ] || return 0
    [ "$2" = 1 ] || return 0
    case "$1" in
        ok | error | warn | debug | green | white | blue | yellow) printf '\033[0m' ;;
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
        # A message that paints itself -- a help listing -- sets _TDD_PRECOLORED,
        # so one colour over the whole of it does not undo its own. The Python
        # half does the same by looking for an escape in the message.
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

# ---------------------------------------------------------------- config
# `tdd <command> config [--show | --default | --create [--force]]`, the same
# action every Python tool gets from common.core.config -- here for the shell
# half. The template is rendered from the command's own tdd_defaults_<name>
# declarations (`sub|--option|value` lines), so it cannot drift from the
# options; what the file sets now comes back from `tdd-exe --defaults-doc`,
# which has the TOML parser this side lacks.
#
#     _tdd_config_action <command> "$@"

# The document `--create` writes and `--default` prints: the [options] tables
# and nothing else, plus whatever the file already sets (--current). No option
# is listed at its built-in value -- that would put today's defaults in the
# reader's copy, where a later change to one would never reach them; `config
# --show` is what lists them. Whatever tables the file keeps of its own are
# carried across, which is what makes `--create --force` a rewrite of the
# template rather than a loss of the reader's file. The twin of
# common.core.config.render_doc -- edit both.
#     _tdd_config_template <command> [--current]
_tdd_config_template() {
    _tdd_cfg_file="$TDD_DIR/$1.toml"
    _tdd_cfg_cur=""
    [ "${2:-}" = --current ] && _tdd_cfg_cur="$(tdd-exe --dir "$TDD_DIR" --defaults-doc "$1" 2>/dev/null)"
    printf '#\n# Copyright 2026 Tabsdata Inc.\n#\n\n'
    printf '# Each subcommand may have an [options.<SUBCOMMAND>] table setting user\n'
    printf '# defaults: key is the option, value is its value, strings in double quotes.\n'
    printf '\n[options]\n'
    _tdd_config_line "$1" - --format view "json is JSON Lines, one event per line (default: view)"
    _tdd_config_line "$1" - --verbose false "show debug events too"
    if command -v "tdd_defaults_$1" >/dev/null 2>&1; then
        "tdd_defaults_$1" | sort -t'|' -k1,1 | while IFS='|' read -r _tdd_cfg_sub _tdd_cfg_opt _tdd_cfg_val; do
            [ -n "$_tdd_cfg_opt" ] || continue
            if [ "$_tdd_cfg_sub" != "$_tdd_cfg_last" ]; then
                case "$_tdd_cfg_sub" in
                    - | "") ;;
                    *) printf '\n[options.%s]\n' "$_tdd_cfg_sub" ;;
                esac
                _tdd_cfg_last="$_tdd_cfg_sub"
            fi
            _tdd_config_line "$1" "$_tdd_cfg_sub" "$_tdd_cfg_opt" "$_tdd_cfg_val" ""
        done
    fi
    # What the command (or the reader) keeps of its own: every table that is not
    # an [options] one, verbatim -- comments and all.
    if [ "${2:-}" = --current ] && [ -f "$_tdd_cfg_file" ]; then
        _tdd_cfg_kept="$(awk '
            /^\[/ { keep = ($0 !~ /^\[options[].]/) }
            keep { print }' "$_tdd_cfg_file")"
        [ -n "$_tdd_cfg_kept" ] && printf '\n%s\n' "$_tdd_cfg_kept"
    fi
    # Explicit: the status of the last conditional is not the status of the
    # template. Without this, a file with no tables of its own to carry across
    # ends on a false test, and `--create --force` refuses with "cannot write".
    return 0
}

# One line of the template: `key = value` when the file sets it (--current),
# nothing at all otherwise -- the built-in default is not written down.
# $1 command, $2 subcommand or -, $3 option, $4 default (unused, kept so the
# call sites stay the declaration they read from), $5 unused.
_tdd_config_line() {
    _tdd_cfg_key="$(_tdd_config_key "$3")"
    case "$2" in
        - | "") _tdd_cfg_path=".options.\"\"" ;;
        *) _tdd_cfg_path=".options.\"$2\"" ;;
    esac
    _tdd_cfg_set=""
    [ -n "$_tdd_cfg_cur" ] && _tdd_cfg_set="$(printf '%s' "$_tdd_cfg_cur" | jq -r "$_tdd_cfg_path.\"$_tdd_cfg_key\" // empty | tostring" 2>/dev/null)"
    [ -n "$_tdd_cfg_set" ] && printf '%s = %s\n' "$_tdd_cfg_key" "$(_tdd_config_toml "$_tdd_cfg_set")"
    return 0
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
            _tdd_cfg_keepcur=""
            [ -e "$_tdd_cfg_file" ] && _tdd_cfg_keepcur="--current"
            if ! _tdd_config_template "$_tdd_cfg_cmd" $_tdd_cfg_keepcur > "$_tdd_cfg_tmp" 2>/dev/null; then
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

# What the options resolve to now: a value at its built-in default in green, a
# value the file sets in blue with that built-in named in white beside it. The
# twin of common.core.config.show -- edit both. The file is read by tdd-exe,
# which has the TOML parser this side lacks.
_tdd_config_show() {
    _tdd_cfg_file="$TDD_DIR/$1.toml"
    _tdd_cfg_doc="$(tdd-exe --dir "$TDD_DIR" --defaults-doc "$1" 2>/dev/null)"
    # The paints are resolved here, where fd 1 is still the command's stdout:
    # inside the $(...) that builds a row it is the capture pipe, so a helper
    # testing `-t 1` there always says "no terminal" -- which is why the value
    # the file sets was never painted at all. Every row carries its own paint
    # and _TDD_PRECOLORED tells the renderer so, exactly as the Python half
    # leaves a message that holds an escape alone.
    _tdd_cfg_tty=0
    [ -t 1 ] && _tdd_cfg_tty=1
    _tdd_cfg_green="$(_tdd_color green "$_tdd_cfg_tty")"
    _tdd_cfg_blue="$(_tdd_color blue "$_tdd_cfg_tty")"
    _tdd_cfg_white="$(_tdd_color white "$_tdd_cfg_tty")"
    _tdd_cfg_off="$(_tdd_color_end green "$_tdd_cfg_tty")"  # every paint ends the same
    _tdd_cfg_rows="${_tdd_cfg_green}$_tdd_cfg_file$([ -f "$_tdd_cfg_file" ] || printf '  (no file yet)')${_tdd_cfg_off}
"
    _tdd_cfg_json=""
    _tdd_cfg_last=""
    { printf '%s\n' "-|--format|view" "-|--verbose|false"; command -v "tdd_defaults_$1" >/dev/null 2>&1 && "tdd_defaults_$1"; } |
        sort -t'|' -k1,1 | {
        while IFS='|' read -r _tdd_cfg_sub _tdd_cfg_opt _tdd_cfg_val; do
            [ -n "$_tdd_cfg_opt" ] || continue
            if [ "$_tdd_cfg_sub" != "$_tdd_cfg_last" ]; then
                # Braces around the paint: `$var[` is an array subscript in zsh.
                case "$_tdd_cfg_sub" in
                    - | "") _tdd_cfg_rows="$_tdd_cfg_rows
${_tdd_cfg_green}[options]${_tdd_cfg_off}
" ;;
                    *) _tdd_cfg_rows="$_tdd_cfg_rows
${_tdd_cfg_green}[options.$_tdd_cfg_sub]${_tdd_cfg_off}
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
                # The built-in is named even when the file sets exactly that:
                # the paint says who is responsible for the value, and the
                # parenthesis what it would be without the line.
                _tdd_cfg_rows="$_tdd_cfg_rows  ${_tdd_cfg_blue}$_tdd_cfg_key = $(_tdd_config_toml "$_tdd_cfg_set")${_tdd_cfg_off}   ${_tdd_cfg_white}(built in default: $(_tdd_config_toml "$_tdd_cfg_val"))${_tdd_cfg_off}
"
                _tdd_cfg_json="$_tdd_cfg_json${_tdd_cfg_json:+,}\"$_tdd_cfg_key\":\"$(_tdd_json_str "$_tdd_cfg_set")\""
            else
                _tdd_cfg_rows="$_tdd_cfg_rows  ${_tdd_cfg_green}$_tdd_cfg_key = $(_tdd_config_toml "$_tdd_cfg_val")${_tdd_cfg_off}
"
            fi
        done
        _TDD_PRECOLORED=1
        _tdd_ok "${_tdd_cfg_rows%
}" "\"config\":\"$(_tdd_json_str "$_tdd_cfg_file")\",\"action\":\"show\",\"changed\":{$_tdd_cfg_json}"
        unset _TDD_PRECOLORED
    }
    unset _tdd_cfg_tty _tdd_cfg_green _tdd_cfg_blue _tdd_cfg_white _tdd_cfg_off
}

_tdd_config_help() {
    _tdd_help_text <<HELP
usage: tdd $1 config [--show | --default | --create [--force]]

The config file of \`tdd $1\`: \$TDD_DIR/$1.toml. Its [options] table holds what
this command's options default to ([options.ACTION] for one action); typed
options always win. Whatever else the command keeps lives in the same file.

options:
  --show       what the options resolve to now; what this file sets is
               highlighted, with the built-in default beside it (default)
  --default    print the default config, the document --create would write
  --create     write the default config; refuses when the file exists
  --force, -f  --create: overwrite an existing file

example: tdd $1 config --create && tdd $1 config --show
HELP
}
