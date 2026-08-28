#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Unsetting environment variables can only be done by the shell that owns
# them, hence a shell command.
#
#     tdd vars unset --dev      every TD_* variable
#     tdd vars unset --pypi     every UV_* / PIP_* index variable
#
# Only exported variables are visible to `env`, so only those are unset;
# a plain shell variable named TD_X stays. That is the same set a child
# process would have seen, which is what these groups are about.

tdd_fn_register vars "unset groups of environment variables in this shell: --dev (TD_*), --pypi (UV/PIP index)"

# Built-in option defaults, for `tdd defaults --command vars`.
tdd_defaults_vars() {
    printf '%s\n' "unset|--dev|false" "unset|--pypi|false"
}

tddfn_vars() {
    _tdd_cmd_reset
    case "${1:-}" in
        unset)
            shift
            _TDD_CMD="vars-unset"
            _tdd_vars_unset "$@"
            _tdd_rc=$?
            ;;
        --help | -h)
            _tdd_vars_help
            _tdd_rc=0
            ;;
        "")
            _tdd_error "a subcommand is required: unset (see --help)"
            _tdd_rc=1
            ;;
        *)
            _tdd_error "unknown subcommand: $1 (see --help)"
            _tdd_rc=1
            ;;
    esac
    unset _tdd_dev _tdd_pypi _tdd_names _tdd_n _tdd_json _tdd_re
    return "$_tdd_rc"
}

_tdd_vars_help() {
    cat <<'HELP'
usage: tdd vars unset (--dev | --pypi) [--dev --pypi]

Unset groups of exported environment variables in this shell.

  --dev     every variable starting with TD_
  --pypi    every UV_* or PIP_* variable naming a package index
            (UV_INDEX, UV_DEFAULT_INDEX, UV_EXTRA_INDEX_URL, PIP_INDEX_URL, ...)

At least one group is required. Common options: --help/-h, --verbose/-v,
--format json|view (default view)

example: tdd vars unset --dev --pypi
HELP
}

_tdd_vars_unset() {
    _tdd_dev=0
    _tdd_pypi=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --dev) _tdd_dev=1; shift ;;
            --pypi) _tdd_pypi=1; shift ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_vars_help
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ "$_tdd_dev" = 0 ] && [ "$_tdd_pypi" = 0 ]; then
        _tdd_error "nothing selected: pass --dev, --pypi or both (see --help)"
        return 1
    fi
    _tdd_re="^$"
    [ "$_tdd_dev" = 1 ] && _tdd_re="$_tdd_re|^TD_"
    [ "$_tdd_pypi" = 1 ] && _tdd_re="$_tdd_re|^(UV|PIP)_.*INDEX"
    # Names only, from lines that look like assignments -- a value holding a
    # newline must not be mistaken for a variable.
    _tdd_names="$(env | awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}' | grep -E "$_tdd_re" | sort)"
    _tdd_json=""
    for _tdd_n in $(printf '%s\n' "$_tdd_names"); do
        unset "$_tdd_n"
        _tdd_debug "unset $_tdd_n"
        _tdd_json="$_tdd_json${_tdd_json:+,}\"$_tdd_n\""
    done
    if [ -z "$_tdd_names" ]; then
        _tdd_ok "nothing to unset" '"unset":[]'
    else
        _tdd_ok "unset: $(printf '%s\n' "$_tdd_names" | tr '\n' ' ' | sed 's/ $//')" "\"unset\":[$_tdd_json]"
    fi
}
