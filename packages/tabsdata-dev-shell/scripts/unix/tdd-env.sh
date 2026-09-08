#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${_TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Entering or leaving a toolset venv changes the current shell, which is exactly
# what an executable cannot do -- hence a shell command rather than a tdd-exe
# builtin. `tdd-env` is a group with two words:
#
#     tdd tdd-env activate --toolset <toolset>
#     tdd tdd-env deactivate

# No `|` in the summary: it is the registry delimiter.
tdd_fn_register tdd-env "activate --toolset <toolset>, or deactivate, a toolset venv in this shell"

# Built-in option defaults: what `tdd tdd-env config` writes as its template,
# and what `--show` compares against.
tdd_defaults_tdd-env() {
    printf '%s\n' "activate|--toolset|"
}

tddfn_tdd-env() {
    _tdd_cmd_reset
    case "${1:-}" in
        config)
            shift
            _TDD_CMD="tdd-env-config"
            _tdd_config_action tdd-env "$@"
            _tdd_rc=$?
            ;;
        activate | deactivate)
            _tdd_sub="$1"
            shift
            _TDD_CMD="tdd-env-$_tdd_sub"
            "_tdd_env_$_tdd_sub" "$@"
            _tdd_rc=$?
            ;;
        --help | -h)
            _tdd_env_help
            _tdd_rc=0
            ;;
        "")
            _tdd_error "a subcommand is required: activate or deactivate (see --help)"
            _tdd_rc=1
            ;;
        *)
            _tdd_error "unknown subcommand: $1 (see --help)"
            _tdd_rc=1
            ;;
    esac
    unset _tdd_sub _tdd_ts _tdd_script
    return "$_tdd_rc"
}

_tdd_env_help() {
    _tdd_help_text <<'HELP'
usage: tdd tdd-env [-h] [-v] [--format {json,view}] SUBCOMMAND ...

enter or leave a toolset venv in this shell -- the envs the Python tools run in

positional arguments:
  SUBCOMMAND
    activate  put a toolset's bin/ first on PATH, in this shell
    deactivate  restore PATH
    config  this command's config file: --show, --default, --create [--force]

example: tdd tdd-env activate --toolset systems
HELP
}

_tdd_env_help_activate() {
    _tdd_help_text <<'HELP'
usage: tdd tdd-env activate --toolset TOOLSET

Put the toolset's bin/ first on PATH, in this shell, exactly as `tdd <tool>`
would arrange it -- which is what makes it useful while developing a tool: the
tool's entry point and its pinned binaries are there without `tdd` in front. It
sources the venv's own bin/activate rather than reimplementing activation.

options:
  --toolset TOOLSET  the toolset to enter (`tdd help` lists them)
HELP
}

_tdd_env_help_deactivate() {
    _tdd_help_text <<'HELP'
usage: tdd tdd-env deactivate

Leave the venv active in this shell and restore PATH. What it calls is the
venv's own `deactivate`, so it leaves whatever is active, toolset or not, and
says so when nothing is.
HELP
}

_tdd_env_activate() {
    _tdd_ts=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --toolset | --toolset=*)
                _tdd_optval "$@" || { _tdd_error "--toolset needs a value"; return 1; }
                _tdd_ts="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_env_help_activate
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ -z "$_tdd_ts" ]; then
        _tdd_error "--toolset is required; toolsets: $(_tdd_toolsets)"
        return 1
    fi
    _tdd_script="$TDD_DIR/tdd-venvs/$_tdd_ts/bin/activate"
    if [ ! -r "$_tdd_script" ]; then
        _tdd_error "no such toolset: $_tdd_ts; toolsets: $(_tdd_toolsets)"
        return 1
    fi
    # shellcheck disable=SC1090
    . "$_tdd_script"
    _tdd_ok "activated $_tdd_ts ($TDD_DIR/tdd-venvs/$_tdd_ts)" \
        "\"toolset\":\"$(_tdd_json_str "$_tdd_ts")\",\"path\":\"$(_tdd_json_str "$TDD_DIR/tdd-venvs/$_tdd_ts")\""
}

_tdd_env_deactivate() {
    while [ $# -gt 0 ]; do
        _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
        shift "$_TDD_CONSUMED"
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_env_help_deactivate
        return 0
    fi
    _tdd_cmd_check || return 1
    if command -v deactivate >/dev/null 2>&1; then
        deactivate
        _tdd_ok "deactivated"
    else
        _tdd_error "no active venv"
        return 1
    fi
}

# Toolset names come from the catalog, not a glob of tdd-venvs/: that directory
# also holds the tdd and shells envs, which are not toolsets.
_tdd_toolsets() {
    "$TDD_DIR/tdd-venvs/tdd/bin/python" -c \
        'import json, sys; print(" ".join(json.load(open(sys.argv[1]))["toolsets"]))' \
        "$TDD_DIR/catalog.json" 2>/dev/null
}
