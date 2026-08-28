#
# Copyright 2026 Tabsdata Inc.
#

# Entering or leaving a toolset venv changes the current shell, which is exactly
# what an executable cannot do -- hence a shell command rather than a tdd-exe
# builtin. `tdd-env` is a group with two words:
#
#     tdd tdd-env activate --toolset <toolset>
#     tdd tdd-env deactivate

# No `|` in the summary: it is the registry delimiter.
tdd_fn_register tdd-env "activate --toolset <toolset>, or deactivate, a toolset venv in this shell"

tddfn_tdd-env() {
    case "${1:-}" in
        activate)
            shift
            _tdd_env_activate "$@"
            ;;
        deactivate)
            shift
            if [ $# -ne 0 ]; then
                _tdd_env_usage
                return 2
            fi
            _tdd_env_deactivate
            ;;
        *)
            _tdd_env_usage
            return 2
            ;;
    esac
}

_tdd_env_usage() {
    echo "usage: tdd tdd-env activate --toolset <toolset>" >&2
    echo "       tdd tdd-env deactivate" >&2
    echo "toolsets: $(_tdd_toolsets)" >&2
}

_tdd_env_activate() {
    _tdd_ts=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --toolset)
                if [ $# -lt 2 ]; then
                    _tdd_env_usage
                    unset _tdd_ts
                    return 2
                fi
                _tdd_ts="$2"
                shift 2
                ;;
            --toolset=*)
                _tdd_ts="${1#--toolset=}"
                shift
                ;;
            *)
                _tdd_env_usage
                unset _tdd_ts
                return 2
                ;;
        esac
    done
    if [ -z "$_tdd_ts" ]; then
        _tdd_env_usage
        unset _tdd_ts
        return 2
    fi
    _tdd_script="$TDD_DIR/tdd-venvs/$_tdd_ts/bin/activate"
    if [ ! -r "$_tdd_script" ]; then
        echo "tdd tdd-env activate: no such toolset: $_tdd_ts" >&2
        echo "  toolsets: $(_tdd_toolsets)" >&2
        unset _tdd_ts _tdd_script
        return 2
    fi
    # shellcheck disable=SC1090
    . "$_tdd_script"
    echo "activated $_tdd_ts ($TDD_DIR/tdd-venvs/$_tdd_ts)"
    unset _tdd_ts _tdd_script
}

_tdd_env_deactivate() {
    if command -v deactivate >/dev/null 2>&1; then
        deactivate
        echo "deactivated"
    else
        echo "tdd tdd-env deactivate: no active venv" >&2
        return 1
    fi
}

# Toolset names come from the catalog, not a glob of tdd-venvs/: that directory also
# holds the tdd and shells envs, which are not toolsets.
_tdd_toolsets() {
    "$TDD_DIR/tdd-venvs/tdd/bin/python" -c \
        'import json, sys; print(" ".join(json.load(open(sys.argv[1]))["toolsets"]))' \
        "$TDD_DIR/catalog.json" 2>/dev/null
}
