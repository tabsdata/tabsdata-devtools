#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${_TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Managed virtualenvs: created by pyenv, uv or conda, but all of them living
# under $TDD_DIR/managed-venvs/<type>/<name>, each with a <name>.json marker
# beside the type directories: the manager (type), the interpreter it runs
# (version and the base python it was built from), whether it is relocatable,
# when it was made. Every subcommand reads the marker to know which tool to
# drive, so the user never has to remember how a venv was made; `list` shows
# the rest.
#
# All of that is `tdd _venv`, the Python half: building a venv, writing,
# reading and migrating its marker, removing it, listing them. What stays here
# is what only a shell can do -- enter a venv, leave one, adopt one entered by
# hand, refuse a foreign one, paint the prompt -- and each subcommand's events
# are ours, relayed from `_venv` where it did the work (_tdd_venv_py).
#
#     tdd venv create --name NAME [--type pyenv|uv|conda] [--python VERSION] [--relocatable]
#     tdd venv activate --name NAME
#     tdd venv deactivate [--force]
#     tdd venv delete (--name NAME | --all)
#     tdd venv list
#
# Activating and deactivating change this shell, which is why the whole group
# is a shell command. venv.bin-reqs.txt requires uv alone, tdd's own hard
# requirement; pyenv and conda are optional, checked when a venv of their
# --type is created or entered.
#
# How each manager builds a venv -- uv on its own interpreters only
# (--managed-python), relocatable only when asked; pyenv as a plain venv on a
# pyenv interpreter; conda by prefix -- is `tdd _venv create`'s.
#
# Activation rules: the prompt shows (<type>/<python>/<name>), with /reloc
# appended for a relocatable venv; create ends in activation; activating while
# another managed venv is active switches to the new one; a venv that tdd did
# not activate (VIRTUAL_ENV, or a conda env other than base) blocks both --
# unless it lives under managed-venvs/<type>/<name> with its marker, in which
# case it is ours however it was entered and is adopted as the active one.
# deactivate leaves the managed venv; a venv tdd did not activate, or a stale
# record, is refused with a pointer to --force, which leaves it best effort
# from what the tool left in the environment (venv/uv, pyenv-virtualenv,
# conda) or drops the record. State lives in _TDD_VENV (the name),
# _TDD_VENV_ACTIVATED (the same name, exported only by this file: a _TDD_VENV
# that differs from it was set by hand, after, and the launchers obey it
# rather than the shell's venv) and _TDD_VENV_PS1 (the prompt to restore).

tdd_fn_register venv "create, activate, deactivate, delete or list managed venvs (pyenv, uv or conda)"

# Built-in option defaults: what `tdd venv config` writes as its template,
# and what `--show` compares against.
tdd_defaults_venv() {
    printf '%s\n' "create|--type|uv" "create|--python|3.12.13" "create|--name|" \
        "create|--force|false" "create|--relocatable|false" "deactivate|--force|false" \
        "activate|--name|" "delete|--name|" "delete|--all|false"
}

tddfn_venv() {
    _tdd_cmd_reset
    case "${1:-}" in
        config)
            shift
            _TDD_CMD="venv-config"
            _tdd_config_action venv "$@"
            _tdd_rc=$?
            ;;
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
    unset _tdd_sub _tdd_name _tdd_type _tdd_python _tdd_dir _tdd_envf _tdd_out _tdd_prefix _tdd_py _tdd_f _tdd_rows _tdd_json _tdd_mark _tdd_current _tdd_prev _tdd_ps1 _tdd_prev_type _tdd_force _tdd_recreated _tdd_kind _tdd_p _tdd_star _tdd_aname _tdd_atype _tdd_adir _tdd_all _tdd_reloc _tdd_pypath _tdd_created _tdd_mver _tdd_probe _tdd_e _tdd_tmpf _tdd_migrated _tdd_relocs _tdd_venv_ev _tdd_venv_rc _tdd_venv_quiet
    return "$_tdd_rc"
}

_tdd_venv_root() {
    printf '%s' "$TDD_DIR/managed-venvs"
}

# `tdd _venv SUB ...`, the Python half, which does everything here but enter
# and leave a venv: it builds them, writes, reads and migrates their markers,
# removes and lists them. Its progress (info, warn, debug) is relayed as ours;
# its last event is kept in _tdd_venv_ev for the caller, and a failure is our
# error -- unless _tdd_venv_quiet is set, for a lookup whose miss is an answer.
# Returns 0 when the last event is an ok.
_tdd_venv_py() {
    _tdd_venv_ev=""
    [ "${_TDD_VERBOSE:-0}" = 1 ] && set -- "$@" --verbose
    _tdd_venv_out="$(tdd-exe _venv "$@" --format json 2>/dev/null)"
    _tdd_venv_rc=1
    while IFS= read -r _tdd_venv_line; do
        case "$_tdd_venv_line" in "{"*) ;; *) continue ;; esac
        case "$(printf '%s' "$_tdd_venv_line" | jq -r '.event' 2>/dev/null)" in
            info) [ -n "${_tdd_venv_quiet:-}" ] || _tdd_info "$(printf '%s' "$_tdd_venv_line" | jq -r '.message')" ;;
            warn) _tdd_warn "$(printf '%s' "$_tdd_venv_line" | jq -r '.message')" ;;
            debug) _tdd_debug "$(printf '%s' "$_tdd_venv_line" | jq -r '.message')" ;;
            ok) _tdd_venv_ev="$_tdd_venv_line"; _tdd_venv_rc=0 ;;
            error) _tdd_venv_ev="$_tdd_venv_line"; _tdd_venv_rc=1 ;;
        esac
    done <<EOF
$_tdd_venv_out
EOF
    if [ "$_tdd_venv_rc" -ne 0 ] && [ -z "${_tdd_venv_quiet:-}" ]; then
        if [ -n "$_tdd_venv_ev" ]; then
            _tdd_error "$(printf '%s' "$_tdd_venv_ev" | jq -r '.message')"
        else
            _tdd_error "tdd _venv $1 failed with no word on why (run: tdd -x _venv $1 --help)"
        fi
    fi
    unset _tdd_venv_out _tdd_venv_line
    return "$_tdd_venv_rc"
}

# A field of the kept event, raw (jq -r); empty when it has none.
_tdd_venv_field() {
    printf '%s' "$_tdd_venv_ev" | jq -r --arg k "$1" '.[$k] // empty | tostring'
}

# The kept ok as ours: its message, and its fields as our event's.
_tdd_venv_relay() {
    _tdd_ok "$(printf '%s' "$_tdd_venv_ev" | jq -r '.message')" \
        "$(printf '%s' "$_tdd_venv_ev" | jq -c 'del(.command, .event, .message, .log)' | sed 's/^{//; s/}$//')"
}

# The manager (type) of NAME from its marker, or nothing. Usable inside $(...),
# which _tdd_venv_read_marker -- setting variables -- is not.
_tdd_venv_manager_of() {
    tdd-exe _venv info --name "$1" --format json 2>/dev/null | jq -r 'select(.event == "ok") | .type'
}

# Everything the marker of NAME records, into _tdd_type, _tdd_py, _tdd_pypath,
# _tdd_reloc (true|false), _tdd_created and _tdd_dir, asked of `_venv info`;
# a fact the marker lacks is empty. Returns 1 when there is no such venv, with
# nothing set.
_tdd_venv_read_marker() {
    _tdd_venv_quiet=1
    _tdd_venv_py info --name "$1"
    _tdd_venv_rc=$?
    unset _tdd_venv_quiet
    [ "$_tdd_venv_rc" -eq 0 ] || return 1
    _tdd_type="$(_tdd_venv_field type)"
    _tdd_py="$(_tdd_venv_field python)"
    _tdd_pypath="$(_tdd_venv_field python_path)"
    _tdd_reloc="$(_tdd_venv_field relocatable)"
    _tdd_created="$(_tdd_venv_field created)"
    _tdd_dir="$(_tdd_venv_field path)"
    return 0
}

# The prompt marker of the active venv: (<type>/<python>/<name>), and /reloc
# inside the parenthesis when it is relocatable, so the prompt says what the
# venv can stand. $1 type, $2 python version, $3 name, $4 relocatable.
_tdd_venv_mark_text() {
    printf '(%s/%s/%s%s)' "$1" "${2:-?}" "$3" "$([ "${4:-}" = true ] && printf '/reloc')"
}

# Markers from before the JSON (<name>.env, the type alone) are replaced by
# `_venv migrate` on sight, so no reader has to know the old one. Every
# subcommand calls this before adopting, once past --help with its options
# parsed.
_tdd_venv_migrate() {
    _tdd_venv_py migrate
}

_tdd_venv_help() {
    _tdd_help_text <<'HELP'
usage: tdd venv [-h] [-v] [--format {json,view}] SUBCOMMAND ...

managed virtualenvs (pyenv, uv or conda) under $TDD_DIR/managed-venvs, entered and left in the
calling shell

positional arguments:
  SUBCOMMAND
    create  make a venv and enter it
    activate  enter one, in this shell
    deactivate  leave the active managed venv
    delete  remove a venv, or every one of them
    list  every managed venv with its type, python, whether relocatable, path and base python
    config  this command's config file: --show, --default, --create [--force]

A <name>.json file beside them records the type, the python it runs and was built from,
whether it is relocatable and when it was made, so every subcommand -- and the tdk launchers
-- know which tool to use. The active one is named by _TDD_VENV; a managed venv found active
without that record (a shell from before a reinstall, bin/activate sourced by hand) is adopted
as the active one.

example: tdd venv create --name scratch --type uv --python 3.12.13 --relocatable
HELP
}

_tdd_venv_help_create() {
    _tdd_help_text <<'HELP'
usage: tdd venv create --name NAME [--type {pyenv,uv,conda}] [--python VERSION] [--relocatable] [--force]

Make a venv and enter it. Refuses while a venv tdd did not activate is active; switches from a
managed one. With --force an existing NAME is deleted first, even the active one.

options:
  --name NAME  the venv
  --type {pyenv,uv,conda}  the tool that creates it (default: uv; pyenv and conda are not supported on Windows). A pyenv venv is a plain `python -m venv` on a pyenv interpreter; a uv venv is built on a uv-managed interpreter only, never one found on PATH; conda gets its shell hook installed on the fly when the rc did not
  --python VERSION  the interpreter (default: 3.12.13, what a tdkserver instance builds its own environments with). pyenv needs it installed already (pyenv install VERSION); uv and conda fetch it
  --relocatable  make the venv relocatable: it keeps working after being moved or copied (uv venvs only; the prompt ends in /reloc). Without it the venv is bound to its path, whatever UV_VENV_RELOCATABLE says
  --force, -f  delete NAME first if it exists, leaving it if it is the active one
HELP
}

_tdd_venv_help_activate() {
    _tdd_help_text <<'HELP'
usage: tdd venv activate --name NAME

Enter it, in this shell: the prompt shows (<type>/PYTHON/NAME) in green -- (<type>/PYTHON/NAME/reloc)
for a relocatable venv -- and _TDD_VENV=NAME is exported (with _TDD_VENV_ACTIVATED=NAME, which
tells this record from a _TDD_VENV set by hand). `tdd tdk`, `tdd tdkserver` and `tdd km` run in
the venv last activated: this one, until another is activated on top of it. Switches if another
managed venv is active; refuses if a venv tdd did not activate is -- deactivate that one first.

options:
  --name NAME  the venv
HELP
}

_tdd_venv_help_deactivate() {
    _tdd_help_text <<'HELP'
usage: tdd venv deactivate [--force]

Leave the active managed venv and restore the prompt. A venv tdd did not activate, or a stale
record (recorded, nothing active), is an error that says so.

options:
  --force, -f  leave it anyway, best effort -- venv and uv through their own deactivate, pyenv-virtualenv through `pyenv deactivate`, conda through `conda deactivate` -- or drop the stale record
HELP
}

_tdd_venv_help_delete() {
    _tdd_help_text <<'HELP'
usage: tdd venv delete (--name NAME | --all)

Remove a venv and its marker. Refuses while it is active: the shell would be left standing in
a deleted venv.

options:
  --name NAME  the venv
  --all  every managed venv instead of one, and none of them may be active
HELP
}

_tdd_venv_help_list() {
    _tdd_help_text <<'HELP'
usage: tdd venv list

Every managed venv, one line each: name, type, the python version it runs, `reloc` when it is
relocatable (`-` when not), its path, and the base python it was built from -- all from its
<name>.json marker. The only subcommand that changes neither the shell nor a venv.
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

# Resolve _tdd_name to its marker (_tdd_type, _tdd_py, _tdd_pypath, _tdd_reloc,
# _tdd_created) and directory; fail if unknown.
_tdd_venv_resolve() {
    if ! _tdd_venv_read_marker "$_tdd_name"; then
        _tdd_error "no managed venv named $_tdd_name (see tdd venv list)"
        return 1
    fi
    return 0
}

_tdd_venv_create() {
    _tdd_name=""
    _tdd_type="uv"
    # One interpreter across every venv tdd makes, whichever tool makes it --
    # otherwise `--type uv` and `--type pyenv` hand you different Pythons from
    # the same command. 3.12.13 is what a tdkserver instance builds its own
    # environments with, so a venv made here matches what the product runs.
    _tdd_python="3.12.13"
    _tdd_force=0
    # Bound to its path unless asked otherwise: a venv that keeps working
    # after a move is uv's --relocatable, and the default is to not want it.
    _tdd_reloc=false
    while [ $# -gt 0 ]; do
        case "$1" in
            --name | --name=*)
                _tdd_optval "$@" || { _tdd_error "--name needs a value"; return 1; }
                _tdd_name="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            --force | -f)
                _tdd_force=1
                shift
                ;;
            --relocatable)
                _tdd_reloc=true
                shift
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
        _tdd_venv_help_create
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_venv_migrate || return 1
    _tdd_venv_adopt
    if [ -z "$_tdd_name" ]; then
        _tdd_error "--name is required"
        return 1
    fi
    # Creation ends in activation, so anything that would block activating
    # blocks creating -- before `_venv` builds anything.
    _tdd_venv_foreign_check || return 1
    # --force of the active venv: leave it first, since `_venv` is about to
    # remove it from under this shell.
    if [ "$_tdd_force" = 1 ] && [ "${_TDD_VENV:-}" = "$_tdd_name" ]; then
        _tdd_venv_leave
        _tdd_debug "deactivated $_tdd_name"
    fi
    # The options as positional parameters (the command's own are all consumed
    # by now): the one way both shells pass an optional argument through intact.
    set -- --name "$_tdd_name" --type "$_tdd_type" --python "$_tdd_python"
    [ "$_tdd_reloc" = true ] && set -- "$@" --relocatable
    [ "$_tdd_force" = 1 ] && set -- "$@" --force
    _tdd_venv_py create "$@" || return 1
    _tdd_dir="$(_tdd_venv_field path)"
    _tdd_created="$(_tdd_venv_field created)"
    _tdd_pypath="$(_tdd_venv_field python_path)"
    _tdd_recreated=""
    [ "$(_tdd_venv_field recreated)" = true ] && _tdd_recreated="re"
    _tdd_relocs=""
    [ "$_tdd_reloc" = true ] && _tdd_relocs=1  # for the messages: `, relocatable` or nothing
    _tdd_venv_enter || return 1
    _tdd_ok "${_tdd_recreated}created and activated $_tdd_name ($_tdd_type, python ${_tdd_py:-?}${_tdd_relocs:+, relocatable}) at $_tdd_dir${_tdd_prev:+ (left $_tdd_prev)}" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"path\":\"$(_tdd_json_str "$_tdd_dir")\",\"python\":\"$(_tdd_json_str "${_tdd_py:-}")\",\"python_requested\":\"$(_tdd_json_str "$_tdd_python")\",\"python_path\":\"$(_tdd_json_str "${_tdd_pypath:-}")\",\"relocatable\":$_tdd_reloc,\"created\":\"$(_tdd_json_str "$_tdd_created")\",\"activated\":true,\"recreated\":$([ -n "$_tdd_recreated" ] && echo true || echo false)${_tdd_prev:+,\"deactivated\":\"$(_tdd_json_str "$_tdd_prev")\"}"
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

# Whether a venv's activation left its `deactivate` FUNCTION behind. `command
# -v` is not enough: pyenv-virtualenv installs a `deactivate` shim on PATH that
# only prints "must be sourced" when run.
_tdd_venv_has_deactivate_fn() {
    case "$(type deactivate 2>/dev/null)" in
        *function*) return 0 ;;
    esac
    return 1
}

# Directory of the managed venv recorded in _TDD_VENV.
_tdd_venv_active_dir() {
    printf '%s' "$(_tdd_venv_root)/$(_tdd_venv_manager_of "$_TDD_VENV")/$_TDD_VENV"
}

# A managed venv active without its record -- a shell that entered it before a
# reinstall renamed the record, `source bin/activate` by hand, a script -- is
# still ours: its path is <root>/<type>/<name> and <name>.json says <type>.
# Adopt it as the recorded one, so create/activate switch from it and
# deactivate leaves it as managed instead of refusing it as foreign. The prompt
# to restore is the current one minus any marker of ours or the tool's, best
# effort. Every subcommand calls this first, once past --help and after
# _tdd_venv_migrate, so the marker it reads is JSON.
_tdd_venv_adopt() {
    [ -z "${_TDD_VENV:-}" ] || return 0
    _tdd_current="$(_tdd_venv_current)"
    [ -n "$_tdd_current" ] || return 0
    _tdd_aname="${_tdd_current##*/}"
    _tdd_atype="${_tdd_current%/*}"
    _tdd_atype="${_tdd_atype##*/}"
    _tdd_adir="$(_tdd_venv_root)/$_tdd_atype/$_tdd_aname"
    [ "$_tdd_current" = "$_tdd_adir" ] || return 0
    [ "$(_tdd_venv_manager_of "$_tdd_aname")" = "$_tdd_atype" ] || return 0
    _tdd_py="$("$_tdd_adir/bin/python" --version 2>&1)"
    _tdd_py="${_tdd_py#Python }"
    _tdd_mark="$(_tdd_ps1_wrap green "$(_tdd_venv_mark_text "$_tdd_atype" "$_tdd_py" "$_tdd_aname" "$(tdd-exe _venv info --name "$_tdd_aname" --format json 2>/dev/null | jq -r 'select(.event == "ok") | .relocatable')")") "
    _TDD_VENV_PS1="${PS1-}"
    _TDD_VENV_PS1="${_TDD_VENV_PS1/"$_tdd_mark"/}"
    # venv's own marker: "(name) " up to Python 3.12, the bare name from 3.13
    case "${VIRTUAL_ENV_PROMPT:-}" in
        "") ;;
        "("*) _TDD_VENV_PS1="${_TDD_VENV_PS1/"$VIRTUAL_ENV_PROMPT"/}" ;;
        *) _TDD_VENV_PS1="${_TDD_VENV_PS1/"($VIRTUAL_ENV_PROMPT) "/}" ;;
    esac
    [ -n "${CONDA_PROMPT_MODIFIER:-}" ] && _TDD_VENV_PS1="${_TDD_VENV_PS1/"$CONDA_PROMPT_MODIFIER"/}"
    _TDD_VENV="$_tdd_aname"
    _TDD_VENV_ACTIVATED="$_tdd_aname"
    export _TDD_VENV _TDD_VENV_ACTIVATED
    _tdd_debug "adopted $_tdd_aname ($_tdd_atype): active in this shell without a record"
    return 0
}

# Leave the recorded managed venv: the tool's own deactivate, then the prompt
# and the record. Shared by deactivate and by activate when switching.
_tdd_venv_leave() {
    case "$(_tdd_venv_manager_of "$_TDD_VENV")" in
        conda)
            CONDA_CHANGEPS1=false
            export CONDA_CHANGEPS1
            conda deactivate 2>/dev/null
            unset CONDA_CHANGEPS1
            ;;
        *)
            _tdd_venv_has_deactivate_fn && deactivate
            ;;
    esac
    if [ -n "${_TDD_VENV_PS1+x}" ]; then
        PS1="$_TDD_VENV_PS1"
    fi
    unset _TDD_VENV _TDD_VENV_ACTIVATED _TDD_VENV_PS1
}

# Refuse when a venv tdd did not activate is in the way: on its own, or on top
# of the recorded managed one. Shared by activate and create, which both must
# fail before changing anything.
_tdd_venv_foreign_check() {
    _tdd_current="$(_tdd_venv_current)"
    if [ -n "${_TDD_VENV:-}" ]; then
        if [ -n "$_tdd_current" ] && [ "$_tdd_current" != "$(_tdd_venv_active_dir)" ]; then
            _tdd_error "a venv tdd did not activate is on top of managed venv $_TDD_VENV ($_tdd_current); leave it first -- its own tool's deactivate, or \`tdd venv deactivate --force\`"
            return 1
        fi
    elif [ -n "$_tdd_current" ]; then
        _tdd_error "a venv tdd did not activate is active ($_tdd_current); leave it first -- its own tool's deactivate, or \`tdd venv deactivate --force\`"
        return 1
    fi
    return 0
}

# Enter _tdd_name/_tdd_type/_tdd_dir (_tdd_reloc says whether it is
# relocatable): leave the recorded managed venv if any (into _tdd_prev), source
# the tool's activation with its prompt marker silenced, write ours, record the
# state. Foreign check already done.
_tdd_venv_enter() {
    _tdd_prev=""
    if [ -n "${_TDD_VENV:-}" ]; then
        _tdd_prev="$_TDD_VENV"
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
    _TDD_VENV_PS1="$_tdd_ps1"
    # The active managed venv, in green, with the interpreter it runs (asked of
    # the venv's own python rather than read from the marker: it is what runs
    # now) and /reloc when it is relocatable -- placed after the red `* `
    # tdd-source.sh put first, so that stays first; ahead of everything when
    # the prompt does not start with it. The marker is the one tdd-source.sh
    # remembered, since TD_TDD_PROMPT may have made it something else.
    _tdd_py="$("$_tdd_dir/bin/python" --version 2>&1)"
    _tdd_py="${_tdd_py#Python }"
    _tdd_mark="$(_tdd_ps1_wrap green "$(_tdd_venv_mark_text "$_tdd_type" "$_tdd_py" "$_tdd_name" "$_tdd_reloc")") "
    _tdd_star="${_TDD_PROMPT_MARK:-}"
    case "$_tdd_ps1" in
        "$_tdd_star"*) PS1="$_tdd_star$_tdd_mark${_tdd_ps1#"$_tdd_star"}" ;;
        *) PS1="$_tdd_mark$_tdd_ps1" ;;
    esac
    _TDD_VENV="$_tdd_name"
    _TDD_VENV_ACTIVATED="$_tdd_name"
    export _TDD_VENV _TDD_VENV_ACTIVATED
    return 0
}

_tdd_venv_activate() {
    _tdd_venv_parse_name "$@" || return 1
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help_activate
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_venv_migrate || return 1
    _tdd_venv_adopt
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
    if [ "${_TDD_VENV:-}" = "$_tdd_name" ]; then
        _tdd_ok "$_tdd_name ($_tdd_type) is already active" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"path\":\"$(_tdd_json_str "$_tdd_dir")\",\"relocatable\":$_tdd_reloc,\"already_active\":true"
        return 0
    fi
    _tdd_venv_enter || return 1
    _tdd_ok "activated $_tdd_name ($_tdd_type$([ "$_tdd_reloc" = true ] && printf ', relocatable')) at $_tdd_dir${_tdd_prev:+ (left $_tdd_prev)}" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"path\":\"$(_tdd_json_str "$_tdd_dir")\",\"relocatable\":$_tdd_reloc${_tdd_prev:+,\"deactivated\":\"$(_tdd_json_str "$_tdd_prev")\"}"
}

# What is active and how it got there, for deactivate. Sets _tdd_kind to
# conda | pyenv | uv | venv and _tdd_current to the prefix; empty kind = none.
# Best effort: conda leaves CONDA_PREFIX, pyenv-virtualenv PYENV_VIRTUAL_ENV,
# and a venv's pyvenv.cfg says whether uv made it or which interpreter did.
_tdd_venv_detect() {
    _tdd_kind=""
    _tdd_current="$(_tdd_venv_current)"
    [ -n "$_tdd_current" ] || return 0
    if [ -n "${CONDA_PREFIX:-}" ] && [ "$_tdd_current" = "$CONDA_PREFIX" ]; then
        _tdd_kind="conda"
    elif [ -n "${PYENV_VIRTUAL_ENV:-}" ] && [ "$_tdd_current" = "$PYENV_VIRTUAL_ENV" ]; then
        _tdd_kind="pyenv"
    elif grep -q '^uv = ' "$_tdd_current/pyvenv.cfg" 2>/dev/null; then
        _tdd_kind="uv"
    elif grep -q '^home = .*/\.pyenv/' "$_tdd_current/pyvenv.cfg" 2>/dev/null; then
        _tdd_kind="pyenv"
    else
        _tdd_kind="venv"
    fi
    return 0
}

# Leave a venv tdd did not activate, by the tool's own means when it left one
# behind, otherwise by undoing what activation does: bin/ off PATH, the
# variables gone. Returns 1 if something is still active afterwards.
_tdd_venv_leave_foreign() {
    case "$_tdd_kind" in
        conda)
            if ! conda deactivate 2>/dev/null; then
                eval "$(conda shell."$(_tdd_shell_name)" hook 2>/dev/null)" >/dev/null 2>&1
                conda deactivate 2>/dev/null
            fi
            ;;
        pyenv)
            if [ -n "${PYENV_VIRTUAL_ENV:-}" ] && command -v pyenv >/dev/null 2>&1; then
                pyenv deactivate 2>/dev/null || eval "$(pyenv sh-deactivate 2>/dev/null)" 2>/dev/null
            fi
            ;;
    esac
    if [ -n "${VIRTUAL_ENV:-}" ] && _tdd_venv_has_deactivate_fn; then
        deactivate 2>/dev/null
    fi
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        # No deactivate function: activation was done by hand, undo it by hand.
        _tdd_p=":$PATH:"
        _tdd_p="${_tdd_p//:$VIRTUAL_ENV\/bin:/:}"
        _tdd_p="${_tdd_p#:}"
        PATH="${_tdd_p%:}"
        export PATH
        unset VIRTUAL_ENV VIRTUAL_ENV_PROMPT _tdd_p
        hash -r 2>/dev/null
    fi
    [ -z "$(_tdd_venv_current)" ]
}

_tdd_venv_deactivate() {
    _tdd_force=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --force | -f)
                _tdd_force=1
                shift
                ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help_deactivate
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_venv_migrate || return 1
    _tdd_venv_adopt
    _tdd_venv_detect
    if [ -n "${_TDD_VENV:-}" ] && [ -n "$_tdd_current" ] && [ "$_tdd_current" = "$(_tdd_venv_active_dir)" ]; then
        # The recorded (or just adopted) managed venv, active: the ordinary case.
        _tdd_name="$_TDD_VENV"
        _tdd_type="$(_tdd_venv_manager_of "$_tdd_name")"
        _tdd_venv_leave
        _tdd_ok "deactivated $_tdd_name" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"managed\":true"
        return 0
    fi
    if [ -n "${_TDD_VENV:-}" ] && [ -z "$_tdd_current" ]; then
        # A stale record: the venv was left behind tdd's back (its own deactivate,
        # a deleted directory). Only --force drops it -- the state is not what the
        # record says, and the user should know before it is rewritten.
        if [ "$_tdd_force" != 1 ]; then
            _tdd_error "$_TDD_VENV is recorded as the active managed venv but no venv is active: a stale record; tdd venv deactivate --force drops it"
            return 1
        fi
        _tdd_name="$_TDD_VENV"
        _tdd_type="$(_tdd_venv_manager_of "$_tdd_name")"
        _tdd_venv_leave
        _tdd_ok "dropped the stale record of $_tdd_name (no venv was active)" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"managed\":true,\"stale\":true"
        return 0
    fi
    if [ -z "$_tdd_current" ]; then
        # --force asks to be out of any venv, and out is where we are: an ok,
        # so a script can put it in front of whatever needs a clean shell
        # without having to swallow a failure that means "already fine".
        if [ "$_tdd_force" = 1 ]; then
            _tdd_ok "no venv was active" '"managed":false,"already":true'
            return 0
        fi
        _tdd_error "no venv is active"
        return 1
    fi
    # Something tdd did not activate -- possibly on top of the managed one, whose
    # record then stays for the next deactivate. Left only with --force: tdd did
    # not set it up, so it does not tear it down unasked.
    # conda names a prefix-activated env by its full path; the last component
    # is what the prompt shows.
    _tdd_name="$(basename "$_tdd_current")"
    if [ "$_tdd_kind" = conda ]; then
        case "${CONDA_DEFAULT_ENV:-}" in
            "" | */*) ;;
            *) _tdd_name="$CONDA_DEFAULT_ENV" ;;
        esac
    fi
    if [ "$_tdd_force" != 1 ]; then
        _tdd_error "$_tdd_name ($_tdd_kind, $_tdd_current) is active but tdd did not activate it${_TDD_VENV:+ -- on top of the managed venv $_TDD_VENV}; tdd venv deactivate --force leaves it anyway"
        return 1
    fi
    _tdd_info "deactivate $_tdd_name ($_tdd_kind, not managed by tdd)"
    if ! _tdd_venv_leave_foreign; then
        _tdd_error "could not deactivate $_tdd_current ($_tdd_kind); it is still active" "kind: $_tdd_kind
VIRTUAL_ENV=${VIRTUAL_ENV:-}
CONDA_PREFIX=${CONDA_PREFIX:-}
PYENV_VIRTUAL_ENV=${PYENV_VIRTUAL_ENV:-}"
        return 1
    fi
    _tdd_ok "deactivated $_tdd_name ($_tdd_kind, not managed by tdd)${_TDD_VENV:+; managed venv $_TDD_VENV is still recorded, deactivate again to leave it}" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_kind\",\"path\":\"$(_tdd_json_str "$_tdd_current")\",\"managed\":false"
}

_tdd_venv_delete() {
    _tdd_name=""
    _tdd_all=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --all)
                _tdd_all=1
                shift
                ;;
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
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help_delete
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_venv_migrate || return 1
    _tdd_venv_adopt
    # `_venv` refuses the active venv, and --all while any is: it is told
    # which one this shell stands in.
    set -- --active "${_TDD_VENV:-}"
    [ -n "$_tdd_all" ] && set -- "$@" --all
    [ -n "$_tdd_name" ] && set -- "$@" --name "$_tdd_name"
    _tdd_venv_py delete "$@" || return 1
    _tdd_venv_relay
}

_tdd_venv_list() {
    while [ $# -gt 0 ]; do
        _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
        shift "$_TDD_CONSUMED"
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_venv_help_list
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_venv_migrate || return 1
    _tdd_venv_adopt
    _tdd_venv_py list --active "${_TDD_VENV:-}" || return 1
    _tdd_venv_relay
}

_tdd_shell_name() {
    if [ -n "${ZSH_VERSION:-}" ]; then printf 'zsh'; else printf 'bash'; fi
}
