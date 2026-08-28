#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Managed virtualenvs: created by pyenv, uv or conda, but all of them living
# under $TDD_DIR/managed-venvs/<type>/<name>, each with a <name>.env marker
# whose content is the type. Every subcommand reads the marker to know which
# tool to drive, so the user never has to remember how a venv was made.
#
#     tdd venv create --name NAME [--type pyenv|uv|conda] [--python VERSION]
#     tdd venv activate --name NAME
#     tdd venv deactivate
#     tdd venv delete --name NAME
#     tdd venv list
#
# Activating and deactivating change this shell, which is why the whole group
# is a shell command. No bin-reqs.txt: which of pyenv, uv or conda is needed
# depends on --type, so each is checked at the point of use.
#
# Activation rules: the prompt shows (<type>/<name>); create ends in
# activation; activating while another managed venv is active switches to the
# new one; a venv that tdd did not activate (VIRTUAL_ENV, or a conda env other
# than base) blocks both, and deactivate only ever leaves a managed venv. State
# lives in TDD_VENV_ACTIVE (the name) and TDD_VENV_PS1 (the prompt to restore).

tdd_fn_register venv "create, activate, deactivate, delete or list managed venvs (pyenv, uv or conda)"

# Built-in option defaults, for `tdd defaults --command venv`.
tdd_defaults_venv() {
    printf '%s\n' "create|--type|pyenv" "create|--python|" "create|--name|" \
        "activate|--name|" "delete|--name|"
}

tddfn_venv() {
    _tdd_cmd_reset
    case "${1:-}" in
        create | activate | deactivate | delete | list)
            _tdd_sub="$1"
            shift
            _TDD_CMD="venv-$_tdd_sub"
            "_tdd_venv_$_tdd_sub" "$@"
            _tdd_rc=$?
            ;;
        --help | -h)
            _tdd_venv_help
            _tdd_rc=0
            ;;
        "")
            _tdd_error "a subcommand is required: create, activate, deactivate, delete or list (see --help)"
            _tdd_rc=1
            ;;
        *)
            _tdd_error "unknown subcommand: $1 (see --help)"
            _tdd_rc=1
            ;;
    esac
    unset _tdd_sub _tdd_name _tdd_type _tdd_python _tdd_dir _tdd_envf _tdd_out _tdd_prefix _tdd_py _tdd_f _tdd_rows _tdd_json _tdd_mark _tdd_current _tdd_prev _tdd_ps1 _tdd_prev_type
    return "$_tdd_rc"
}

_tdd_venv_root() {
    printf '%s' "$TDD_DIR/managed-venvs"
}

_tdd_venv_help() {
    _tdd_help_text <<'HELP'
usage: tdd venv create --name NAME [--type {pyenv,uv,conda}]
                       [--python VERSION]
       tdd venv activate --name NAME
       tdd venv deactivate
       tdd venv delete --name NAME
       tdd venv list

Managed virtualenvs, all under $TDD_DIR/managed-venvs/<type>/<name>. A
<name>.env file beside them records the type, so every subcommand knows which
tool to use.

commands:
  create        make a venv and enter it. Refuses while a venv tdd did not
                activate is active; switches from a managed one
  activate      enter it, in this shell; the prompt shows (<type>/NAME).
                Switches if another managed venv is active; refuses if a venv
                tdd did not activate is (deactivate that one first)
  deactivate    leave the active managed venv; never touches a venv tdd did
                not activate
  delete        remove it and its marker; refuses while it is active
  list          every managed venv with its type and path

options:
  --name NAME              the venv
  --type {pyenv,uv,conda}  the tool that creates it (default: pyenv)
  --python VERSION         interpreter for create: pyenv needs it installed
                           already (pyenv install VERSION), uv and conda fetch
                           it (default: the tool's current one)

example: tdd venv create --name scratch --type uv --python 3.12
HELP
}

# Shared argument shape for the --name subcommands. Sets _tdd_name; returns 1
# after reporting the error itself.
_tdd_venv_parse_name() {
    _tdd_name=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --name | --name=*)
                _tdd_optval "$@" || { _tdd_error "--name needs a value"; return 1; }
                _tdd_name="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    return 0
}

# Resolve _tdd_name to its marker, type and directory; fail if unknown.
_tdd_venv_resolve() {
    _tdd_envf="$(_tdd_venv_root)/$_tdd_name.env"
    if [ ! -f "$_tdd_envf" ]; then
        _tdd_error "no managed venv named $_tdd_name (see tdd venv list)"
        return 1
    fi
    _tdd_type="$(cat "$_tdd_envf")"
    _tdd_dir="$(_tdd_venv_root)/$_tdd_type/$_tdd_name"
    return 0
}

_tdd_venv_create() {
    _tdd_name=""
    _tdd_type="pyenv"
    _tdd_python=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --name | --name=*)
                _tdd_optval "$@" || { _tdd_error "--name needs a value"; return 1; }
                _tdd_name="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            --type | --type=*)
                _tdd_optval "$@" || { _tdd_error "--type needs a value"; return 1; }
                _tdd_type="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            --python | --python=*)
                _tdd_optval "$@" || { _tdd_error "--python needs a value"; return 1; }
                _tdd_python="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ -z "$_tdd_name" ]; then
        _tdd_error "--name is required"
        return 1
    fi
    case "$_tdd_name" in
        *[!A-Za-z0-9._-]* | .* | "")
            _tdd_error "invalid name: $_tdd_name (letters, digits, . _ - only; no leading dot)"
            return 1
            ;;
    esac
    case "$_tdd_type" in
        pyenv | uv | conda) ;;
        *)
            _tdd_error "unknown --type: $_tdd_type (pyenv, uv or conda)"
            return 1
            ;;
    esac
    _tdd_envf="$(_tdd_venv_root)/$_tdd_name.env"
    if [ -e "$_tdd_envf" ]; then
        _tdd_error "a managed venv named $_tdd_name already exists (type $(cat "$_tdd_envf"))"
        return 1
    fi
    if ! command -v "$_tdd_type" >/dev/null 2>&1; then
        _tdd_error "$_tdd_type is not on PATH"
        return 1
    fi
    _tdd_dir="$(_tdd_venv_root)/$_tdd_type/$_tdd_name"
    # Creation ends in activation, so anything that would block activating
    # blocks creating -- before a directory exists.
    _tdd_venv_foreign_check || return 1
    mkdir -p "$(_tdd_venv_root)/$_tdd_type" || { _tdd_error "cannot create $(_tdd_venv_root)"; return 1; }

    _tdd_info "create $_tdd_name ($_tdd_type)"
    _tdd_debug "python: ${_tdd_python:-default}"
    case "$_tdd_type" in
        uv)
            if [ -n "$_tdd_python" ]; then
                _tdd_out="$(uv venv --python "$_tdd_python" "$_tdd_dir" 2>&1)"
            else
                _tdd_out="$(uv venv "$_tdd_dir" 2>&1)"
            fi
            _tdd_rc=$?
            ;;
        pyenv)
            # A plain venv built from a pyenv-managed interpreter: pyenv's own
            # virtualenv plugin cannot place an env outside its versions dir.
            if [ -n "$_tdd_python" ]; then
                _tdd_prefix="$(pyenv prefix "$_tdd_python" 2>&1)"
            else
                _tdd_prefix="$(pyenv prefix 2>&1)"
            fi
            if [ $? -ne 0 ]; then
                _tdd_error "pyenv has no ${_tdd_python:-current} version; run: pyenv install ${_tdd_python:-VERSION}" "$_tdd_prefix"
                return 1
            fi
            _tdd_py="$_tdd_prefix/bin/python3"
            [ -x "$_tdd_py" ] || _tdd_py="$_tdd_prefix/bin/python"
            if [ ! -x "$_tdd_py" ]; then
                _tdd_error "no python under pyenv prefix $_tdd_prefix"
                return 1
            fi
            _tdd_out="$("$_tdd_py" -m venv "$_tdd_dir" 2>&1)"
            _tdd_rc=$?
            ;;
        conda)
            _tdd_out="$(conda create -y -q --prefix "$_tdd_dir" "python${_tdd_python:+=$_tdd_python}" 2>&1)"
            _tdd_rc=$?
            ;;
    esac
    if [ "$_tdd_rc" -ne 0 ]; then
        rm -rf "$_tdd_dir"
        _tdd_error "$_tdd_type failed to create $_tdd_name" "$_tdd_out"
        return 1
    fi
    printf '%s\n' "$_tdd_type" > "$_tdd_envf"
    _tdd_debug "create $_tdd_name ($_tdd_type): done"
    _tdd_venv_enter || return 1
    _tdd_ok "created and activated $_tdd_name ($_tdd_type) at $_tdd_dir${_tdd_prev:+ (left $_tdd_prev)}" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"path\":\"$(_tdd_json_str "$_tdd_dir")\",\"python\":\"$(_tdd_json_str "$_tdd_python")\",\"activated\":true${_tdd_prev:+,\"deactivated\":\"$(_tdd_json_str "$_tdd_prev")\"}"
}

# The venv active in this shell right now, managed or not, as a path; empty if
# none. conda's base does not count: after `conda init` it is active in every
# shell, and treating it as a venv would lock conda users out.
_tdd_venv_current() {
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        printf '%s' "$VIRTUAL_ENV"
    elif [ -n "${CONDA_PREFIX:-}" ] && [ "${CONDA_DEFAULT_ENV:-base}" != base ]; then
        printf '%s' "$CONDA_PREFIX"
    fi
}

# Directory of the managed venv recorded in TDD_VENV_ACTIVE.
_tdd_venv_active_dir() {
    _tdd_prev_type="$(cat "$(_tdd_venv_root)/$TDD_VENV_ACTIVE.env" 2>/dev/null)"
    printf '%s' "$(_tdd_venv_root)/$_tdd_prev_type/$TDD_VENV_ACTIVE"
    unset _tdd_prev_type
}

# Leave the recorded managed venv: the tool's own deactivate, then the prompt
# and the record. Shared by deactivate and by activate when switching.
_tdd_venv_leave() {
    case "$(cat "$(_tdd_venv_root)/$TDD_VENV_ACTIVE.env" 2>/dev/null)" in
        conda)
            CONDA_CHANGEPS1=false
            export CONDA_CHANGEPS1
            conda deactivate 2>/dev/null
            unset CONDA_CHANGEPS1
            ;;
        *)
            command -v deactivate >/dev/null 2>&1 && deactivate
            ;;
    esac
    if [ -n "${TDD_VENV_PS1+x}" ]; then
        PS1="$TDD_VENV_PS1"
    fi
    unset TDD_VENV_ACTIVE TDD_VENV_PS1
}

# Refuse when a venv tdd did not activate is in the way: on its own, or on top
# of the recorded managed one. Shared by activate and create, which both must
# fail before changing anything.
_tdd_venv_foreign_check() {
    _tdd_current="$(_tdd_venv_current)"
    if [ -n "${TDD_VENV_ACTIVE:-}" ]; then
        if [ -n "$_tdd_current" ] && [ "$_tdd_current" != "$(_tdd_venv_active_dir)" ]; then
            _tdd_error "a venv tdd did not activate is on top of managed venv $TDD_VENV_ACTIVE ($_tdd_current); deactivate it first"
            return 1
        fi
    elif [ -n "$_tdd_current" ]; then
        _tdd_error "a venv tdd did not activate is active ($_tdd_current); deactivate it first"
        return 1
    fi
    return 0
}

# Enter _tdd_name/_tdd_type/_tdd_dir: leave the recorded managed venv if any
# (into _tdd_prev), source the tool's activation with its prompt marker
# silenced, write ours, record the state. Foreign check already done.
_tdd_venv_enter() {
    _tdd_prev=""
    if [ -n "${TDD_VENV_ACTIVE:-}" ]; then
        _tdd_prev="$TDD_VENV_ACTIVE"
        _tdd_venv_leave
        _tdd_debug "deactivated $_tdd_prev"
    fi
    # The tools would each stamp their own marker on the prompt; keep them
    # quiet and write one consistent (<type>/<name>) ourselves.
    _tdd_ps1="${PS1-}"
    case "$_tdd_type" in
        pyenv | uv)
            VIRTUAL_ENV_DISABLE_PROMPT=1
            # shellcheck disable=SC1091
            . "$_tdd_dir/bin/activate" || { unset VIRTUAL_ENV_DISABLE_PROMPT; _tdd_error "could not source $_tdd_dir/bin/activate"; return 1; }
            unset VIRTUAL_ENV_DISABLE_PROMPT
            ;;
        conda)
            CONDA_CHANGEPS1=false
            export CONDA_CHANGEPS1
            # conda activate needs its shell hook; install it on the fly if
            # the user's rc did not.
            if ! conda activate "$_tdd_dir" 2>/dev/null; then
                eval "$(conda shell."$(_tdd_shell_name)" hook 2>/dev/null)" >/dev/null 2>&1
                _tdd_out="$(conda activate "$_tdd_dir" 2>&1)" || { unset CONDA_CHANGEPS1; _tdd_error "conda could not activate $_tdd_dir" "$_tdd_out"; return 1; }
                conda activate "$_tdd_dir" 2>/dev/null
            fi
            unset CONDA_CHANGEPS1
            ;;
    esac
    TDD_VENV_PS1="$_tdd_ps1"
    PS1="($_tdd_type/$_tdd_name) $_tdd_ps1"
    TDD_VENV_ACTIVE="$_tdd_name"
    export TDD_VENV_ACTIVE
    return 0
}

_tdd_venv_activate() {
    _tdd_venv_parse_name "$@" || return 1
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ -z "$_tdd_name" ]; then
        _tdd_error "--name is required"
        return 1
    fi
    _tdd_venv_resolve || return 1
    if [ ! -d "$_tdd_dir" ]; then
        _tdd_error "$_tdd_name ($_tdd_type) has lost its directory $_tdd_dir; delete and recreate it"
        return 1
    fi
    _tdd_venv_foreign_check || return 1
    if [ "${TDD_VENV_ACTIVE:-}" = "$_tdd_name" ]; then
        _tdd_ok "$_tdd_name ($_tdd_type) is already active" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"path\":\"$(_tdd_json_str "$_tdd_dir")\",\"already_active\":true"
        return 0
    fi
    _tdd_venv_enter || return 1
    _tdd_ok "activated $_tdd_name ($_tdd_type) at $_tdd_dir${_tdd_prev:+ (left $_tdd_prev)}" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"path\":\"$(_tdd_json_str "$_tdd_dir")\"${_tdd_prev:+,\"deactivated\":\"$(_tdd_json_str "$_tdd_prev")\"}"
}

_tdd_venv_deactivate() {
    while [ $# -gt 0 ]; do
        _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
        shift "$_TDD_CONSUMED"
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ -z "${TDD_VENV_ACTIVE:-}" ]; then
        if [ -n "$(_tdd_venv_current)" ]; then
            _tdd_error "no managed venv is active; the active venv ($(_tdd_venv_current)) was not activated by tdd, so it is left alone"
        else
            _tdd_error "no managed venv is active"
        fi
        return 1
    fi
    _tdd_current="$(_tdd_venv_current)"
    if [ -n "$_tdd_current" ] && [ "$_tdd_current" != "$(_tdd_venv_active_dir)" ]; then
        _tdd_error "a venv tdd did not activate is on top of managed venv $TDD_VENV_ACTIVE ($_tdd_current); deactivate it first, or unset TDD_VENV_ACTIVE to drop the record"
        return 1
    fi
    _tdd_name="$TDD_VENV_ACTIVE"
    _tdd_type="$(cat "$(_tdd_venv_root)/$_tdd_name.env" 2>/dev/null)"
    _tdd_venv_leave
    _tdd_ok "deactivated $_tdd_name" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\""
}

_tdd_venv_delete() {
    _tdd_venv_parse_name "$@" || return 1
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ -z "$_tdd_name" ]; then
        _tdd_error "--name is required"
        return 1
    fi
    _tdd_venv_resolve || return 1
    if [ "${TDD_VENV_ACTIVE:-}" = "$_tdd_name" ]; then
        _tdd_error "$_tdd_name is active; run tdd venv deactivate first"
        return 1
    fi
    _tdd_info "delete $_tdd_name ($_tdd_type)"
    if [ "$_tdd_type" = conda ] && [ -d "$_tdd_dir" ]; then
        # Lets conda forget the prefix too; the rm below covers a partial env.
        conda env remove -y -q --prefix "$_tdd_dir" >/dev/null 2>&1
    fi
    rm -rf "$_tdd_dir" || { _tdd_error "could not remove $_tdd_dir"; return 1; }
    rm -f "$_tdd_envf"
    _tdd_debug "delete $_tdd_name ($_tdd_type): done"
    _tdd_ok "deleted $_tdd_name ($_tdd_type)" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\""
}

_tdd_venv_list() {
    while [ $# -gt 0 ]; do
        _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
        shift "$_TDD_CONSUMED"
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_rows=""
    _tdd_json=""
    # find, not a glob: an unmatched glob is an error in zsh.
    for _tdd_f in $(find "$(_tdd_venv_root)" -maxdepth 1 -name '*.env' 2>/dev/null | sort); do
        _tdd_name="$(basename "$_tdd_f" .env)"
        _tdd_type="$(cat "$_tdd_f")"
        _tdd_dir="$(_tdd_venv_root)/$_tdd_type/$_tdd_name"
        _tdd_mark=""
        [ "${TDD_VENV_ACTIVE:-}" = "$_tdd_name" ] && _tdd_mark="  (active)"
        [ -d "$_tdd_dir" ] || _tdd_mark="$_tdd_mark  (missing directory)"
        _tdd_rows="$_tdd_rows$(printf '%-24s %-6s %s%s' "$_tdd_name" "$_tdd_type" "$_tdd_dir" "$_tdd_mark")
"
        _tdd_json="$_tdd_json${_tdd_json:+,}{\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"path\":\"$(_tdd_json_str "$_tdd_dir")\",\"active\":$([ "${TDD_VENV_ACTIVE:-}" = "$_tdd_name" ] && echo true || echo false),\"exists\":$([ -d "$_tdd_dir" ] && echo true || echo false)}"
    done
    if [ -z "$_tdd_rows" ]; then
        _tdd_ok "no managed venvs (create one: tdd venv create --name NAME)" '"venvs":[]'
    else
        _tdd_ok "${_tdd_rows%
}" "\"venvs\":[$_tdd_json]"
    fi
}

_tdd_shell_name() {
    if [ -n "${ZSH_VERSION:-}" ]; then printf 'zsh'; else printf 'bash'; fi
}
