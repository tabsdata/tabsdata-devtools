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
# the rest. A marker from before the JSON (<name>.env, holding the type alone)
# is migrated on sight, the missing facts probed from the venv itself.
#
#     tdd venv create --name NAME [--type pyenv|uv|conda] [--python VERSION] [--relocatable]
#     tdd venv activate --name NAME
#     tdd venv deactivate [--force]
#     tdd venv delete (--name NAME | --all)
#     tdd venv list
#
# Activating and deactivating change this shell, which is why the whole group
# is a shell command. No bin-reqs.txt: which of pyenv, uv or conda is needed
# depends on --type, so each is checked at the point of use.
#
# A uv venv is built on a uv-managed interpreter only (--managed-python), never
# on whatever python happens to be on PATH, and is relocatable only when asked
# (--relocatable, uv's own flag; a pyenv or conda venv cannot be).
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
    printf '%s\n' "create|--type|pyenv" "create|--python|3.12.13" "create|--name|" \
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
    unset _tdd_sub _tdd_name _tdd_type _tdd_python _tdd_dir _tdd_envf _tdd_out _tdd_prefix _tdd_py _tdd_f _tdd_rows _tdd_json _tdd_mark _tdd_current _tdd_prev _tdd_ps1 _tdd_prev_type _tdd_force _tdd_recreated _tdd_kind _tdd_p _tdd_star _tdd_aname _tdd_atype _tdd_adir _tdd_all _tdd_reloc _tdd_pypath _tdd_created _tdd_mver _tdd_probe _tdd_e _tdd_tmpf _tdd_migrated _tdd_relocs
    return "$_tdd_rc"
}

_tdd_venv_root() {
    printf '%s' "$TDD_DIR/managed-venvs"
}

# The marker of the managed venv NAME.
_tdd_venv_marker() {
    printf '%s' "$(_tdd_venv_root)/$1.json"
}

# The manager (type) of NAME from its marker, or nothing. Usable inside $(...),
# which _tdd_venv_read_marker -- setting variables -- is not.
_tdd_venv_manager_of() {
    jq -r '.manager // empty' "$(_tdd_venv_marker "$1")" 2>/dev/null
}

# Everything the marker of NAME records, into _tdd_type, _tdd_py, _tdd_pypath,
# _tdd_reloc (true|false) and _tdd_created; a fact the marker lacks is empty
# (a view shows it as ?). Returns 1 when there is no marker, or it is not
# JSON or names no manager, with nothing set.
_tdd_venv_read_marker() {
    _tdd_envf="$(_tdd_venv_marker "$1")"
    [ -f "$_tdd_envf" ] || return 1
    # One jq run per marker; @sh quotes every value for eval.
    _tdd_e="$(jq -r 'select(.manager != null) | @sh "_tdd_type=\(.manager) _tdd_py=\(.python // "") _tdd_pypath=\(.python_path // "") _tdd_reloc=\(if .relocatable == true then "true" else "false" end) _tdd_created=\(.created // "")"' "$_tdd_envf" 2>/dev/null)" || return 1
    [ -n "$_tdd_e" ] || return 1
    eval "$_tdd_e"
    return 0
}

# What a venv says about itself: its interpreter's version and the base python
# it was built from (sys._base_executable, which pyvenv.cfg's `home` points at;
# a conda env carries its own, so that is the env's python), into _tdd_py and
# _tdd_pypath; both empty when the venv's python does not run. $1 the venv dir.
_tdd_venv_probe() {
    _tdd_py=""
    _tdd_pypath=""
    [ -x "$1/bin/python" ] || return 0
    _tdd_probe="$("$1/bin/python" -c 'import sys; print(sys.version.split()[0]); print(sys._base_executable or sys.executable)' 2>/dev/null)" || return 0
    _tdd_py="${_tdd_probe%%
*}"
    _tdd_pypath="${_tdd_probe#*
}"
    [ "$_tdd_pypath" != "$_tdd_probe" ] || _tdd_pypath=""
    return 0
}

# Write the marker of a venv. Positional, so create and the migration can each
# hand over their own variables:
#
#     _tdd_venv_write_marker NAME TYPE PYTHON PYTHON_PATH RELOCATABLE CREATED REQUESTED [MANAGER_VERSION] [--migrated]
#
# PYTHON is the version the venv runs, REQUESTED what --python asked for,
# RELOCATABLE true or false; an empty fact is null. `--migrated` stamps the
# time this marker replaced a pre-JSON one. Through a temporary file and one
# rename, so an interrupted write never leaves half a marker.
_tdd_venv_write_marker() {
    _tdd_envf="$(_tdd_venv_marker "$1")"
    _tdd_tmpf="$(_tdd_venv_root)/.$1.json.$$.tmp"
    _tdd_migrated=""
    [ "${9:-}" = --migrated ] && _tdd_migrated="$(_tdd_venv_now)"
    jq -n --arg name "$1" --arg manager "$2" --arg python "${3:-}" --arg pypath "${4:-}" \
        --argjson reloc "$([ "${5:-}" = true ] && echo true || echo false)" \
        --arg created "${6:-}" --arg requested "${7:-}" --arg mver "${8:-}" \
        --arg migrated "$_tdd_migrated" --arg tdd "$(cat "$TDD_DIR/VERSION" 2>/dev/null)" '
        def opt: if . == "" then null else . end;
        {schema: 1, name: $name, manager: $manager, manager_version: ($mver | opt),
         python: ($python | opt), python_requested: ($requested | opt),
         python_path: ($pypath | opt), relocatable: $reloc,
         created: ($created | opt), tdd_version: ($tdd | opt)}
        + (if $migrated == "" then {} else {migrated: $migrated} end)' \
        > "$_tdd_tmpf" 2>/dev/null || { rm -f "$_tdd_tmpf"; _tdd_error "cannot write $_tdd_envf"; return 1; }
    mv "$_tdd_tmpf" "$_tdd_envf" || { rm -f "$_tdd_tmpf"; _tdd_error "cannot write $_tdd_envf"; return 1; }
    return 0
}

# Now, as the markers stamp it: UTC, to the second.
_tdd_venv_now() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

# The version of manager $1 (pyenv, uv or conda) as `--version` says it: the
# second word of `uv 0.12.3 (...)`, `pyenv 2.8.4`, `conda 26.3.1`.
_tdd_venv_manager_version() {
    "$1" --version 2>/dev/null | awk 'NR == 1 { print $2 }'
}

# The prompt marker of the active venv: (<type>/<python>/<name>), and /reloc
# inside the parenthesis when it is relocatable, so the prompt says what the
# venv can stand. $1 type, $2 python version, $3 name, $4 relocatable.
_tdd_venv_mark_text() {
    printf '(%s/%s/%s%s)' "$1" "${2:-?}" "$3" "$([ "${4:-}" = true ] && printf '/reloc')"
}

# Markers from before the JSON: <name>.env holding the type alone. Each is
# replaced by a <name>.json on sight -- the type from the file, the interpreter
# probed from the venv, relocatable from what uv wrote in pyvenv.cfg, created
# from the old marker's mtime -- so the two formats never coexist and no reader
# has to know the old one. Every subcommand calls this before adopting, once
# past --help and with its options parsed (so an event here speaks the format
# asked for); `list` therefore writes to disk once, this once. Its variables
# are its own: the caller's --name and --type are already parsed. stat and
# date differ between BSD and GNU: both spellings are tried.
_tdd_venv_migrate() {
    for _tdd_mg_f in $(find "$(_tdd_venv_root)" -maxdepth 1 -name '*.env' 2>/dev/null | sort); do
        _tdd_mg_name="$(basename "$_tdd_mg_f" .env)"
        _tdd_mg_type="$(cat "$_tdd_mg_f" 2>/dev/null)"
        case "$_tdd_mg_type" in
            pyenv | uv | conda) ;;
            *) _tdd_warn "$_tdd_mg_f names an unknown venv manager '$_tdd_mg_type'; left as it is"; continue ;;
        esac
        _tdd_mg_dir="$(_tdd_venv_root)/$_tdd_mg_type/$_tdd_mg_name"
        _tdd_venv_probe "$_tdd_mg_dir"
        _tdd_mg_reloc=false
        grep -q '^relocatable = true' "$_tdd_mg_dir/pyvenv.cfg" 2>/dev/null && _tdd_mg_reloc=true
        _tdd_mg_e="$(stat -f %m "$_tdd_mg_f" 2>/dev/null || stat -c %Y "$_tdd_mg_f" 2>/dev/null)"
        _tdd_mg_created=""
        [ -n "$_tdd_mg_e" ] && _tdd_mg_created="$(date -u -r "$_tdd_mg_e" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "@$_tdd_mg_e" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"
        _tdd_venv_write_marker "$_tdd_mg_name" "$_tdd_mg_type" "$_tdd_py" "$_tdd_pypath" "$_tdd_mg_reloc" "$_tdd_mg_created" "" "" --migrated || return 1
        rm -f "$_tdd_mg_f"
        _tdd_debug "migrated the marker of $_tdd_mg_name ($_tdd_mg_type) to $(_tdd_venv_marker "$_tdd_mg_name")"
    done
    unset _tdd_mg_f _tdd_mg_name _tdd_mg_type _tdd_mg_dir _tdd_mg_reloc _tdd_mg_e _tdd_mg_created _tdd_py _tdd_pypath _tdd_probe
    return 0
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
  --type {pyenv,uv,conda}  the tool that creates it (default: pyenv). A pyenv venv is a plain `python -m venv` on a pyenv interpreter; a uv venv is built on a uv-managed interpreter only, never one found on PATH; conda gets its shell hook installed on the fly when the rc did not
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

# Remove the managed venv NAME of TYPE: conda forgets the prefix first (the rm
# covers a partial env), then the directory and the marker go. Shared by
# delete, delete --all and create --force.
_tdd_venv_remove() {
    if [ "$2" = conda ] && [ -d "$(_tdd_venv_root)/conda/$1" ]; then
        conda env remove -y -q --prefix "$(_tdd_venv_root)/conda/$1" >/dev/null 2>&1
    fi
    rm -rf "$(_tdd_venv_root)/$2/$1" || { _tdd_error "could not remove $(_tdd_venv_root)/$2/$1"; return 1; }
    rm -f "$(_tdd_venv_marker "$1")"
    _tdd_debug "removed $1 ($2)"
    return 0
}

# Resolve _tdd_name to its marker (_tdd_type, _tdd_py, _tdd_pypath, _tdd_reloc,
# _tdd_created) and directory; fail if unknown.
_tdd_venv_resolve() {
    if ! _tdd_venv_read_marker "$_tdd_name"; then
        _tdd_error "no managed venv named $_tdd_name (see tdd venv list)"
        return 1
    fi
    _tdd_dir="$(_tdd_venv_root)/$_tdd_type/$_tdd_name"
    return 0
}

_tdd_venv_create() {
    _tdd_name=""
    _tdd_type="pyenv"
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
    # Only uv builds a venv that survives a move; `python -m venv` and conda
    # both bake the path in, so asking is a mistake worth stopping on rather
    # than a flag to shrug off.
    if [ "$_tdd_reloc" = true ] && [ "$_tdd_type" != uv ]; then
        _tdd_error "--relocatable needs --type uv: a $_tdd_type venv is bound to its path"
        return 1
    fi
    _tdd_relocs=""
    [ "$_tdd_reloc" = true ] && _tdd_relocs=1  # for the messages: `, relocatable` or nothing
    _tdd_envf="$(_tdd_venv_marker "$_tdd_name")"
    _tdd_recreated=""
    if [ -e "$_tdd_envf" ]; then
        _tdd_prev_type="$(_tdd_venv_manager_of "$_tdd_name")"
        if [ "$_tdd_force" != 1 ]; then
            _tdd_error "a managed venv named $_tdd_name already exists (type $_tdd_prev_type); --force recreates it"
            return 1
        fi
        # --force: leave it if it is the active one, then remove it under its
        # OLD type -- the new one may differ -- so nothing stale survives.
        _tdd_info "recreate $_tdd_name (was $_tdd_prev_type)"
        if [ "${_TDD_VENV:-}" = "$_tdd_name" ]; then
            _tdd_venv_leave
            _tdd_debug "deactivated $_tdd_name"
        fi
        _tdd_venv_remove "$_tdd_name" "$_tdd_prev_type" || return 1
        _tdd_recreated="re"
        unset _tdd_prev_type
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

    _tdd_info "create $_tdd_name ($_tdd_type${_tdd_relocs:+, relocatable})"
    _tdd_debug "python: ${_tdd_python:-default}"
    case "$_tdd_type" in
        uv)
            # --managed-python: uv's own interpreters only, fetched when
            # missing -- never the homebrew, pyenv or system python that
            # happens to be on PATH under the same version. The relocatable
            # flag is passed only when asked, and UV_VENV_RELOCATABLE is kept
            # out of it: the marker records what this venv is, so the
            # environment must not decide it behind the flag's back.
            # The options are built as positional parameters (the command's
            # own are all consumed by now): the one way both shells pass an
            # optional argument through intact.
            set -- --managed-python
            [ "$_tdd_reloc" = true ] && set -- "$@" --relocatable
            [ -n "$_tdd_python" ] && set -- "$@" --python "$_tdd_python"
            _tdd_out="$(env -u UV_VENV_RELOCATABLE uv venv "$@" "$_tdd_dir" 2>&1)"
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
    # The marker: what the venv turned out to be, asked of its own python --
    # the version it runs and the base interpreter it was built from -- beside
    # what was asked for and who made it.
    _tdd_venv_probe "$_tdd_dir"
    _tdd_created="$(_tdd_venv_now)"
    _tdd_mver="$(_tdd_venv_manager_version "$_tdd_type")"
    if ! _tdd_venv_write_marker "$_tdd_name" "$_tdd_type" "$_tdd_py" "$_tdd_pypath" "$_tdd_reloc" "$_tdd_created" "$_tdd_python" "$_tdd_mver"; then
        rm -rf "$_tdd_dir"
        return 1
    fi
    _tdd_debug "create $_tdd_name ($_tdd_type): done; python ${_tdd_py:-?} from ${_tdd_pypath:-?}"
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
    _tdd_mark="$(_tdd_ps1_wrap green "$(_tdd_venv_mark_text "$_tdd_atype" "$_tdd_py" "$_tdd_aname" "$(jq -r '.relocatable' "$(_tdd_venv_marker "$_tdd_aname")" 2>/dev/null)")") "
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
    # the prompt does not start with it.
    _tdd_py="$("$_tdd_dir/bin/python" --version 2>&1)"
    _tdd_py="${_tdd_py#Python }"
    _tdd_mark="$(_tdd_ps1_wrap green "$(_tdd_venv_mark_text "$_tdd_type" "$_tdd_py" "$_tdd_name" "$_tdd_reloc")") "
    _tdd_star="$(_tdd_ps1_wrap red '*') "
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
    if [ -n "$_tdd_all" ]; then
        if [ -n "$_tdd_name" ]; then
            _tdd_error "--all and --name are exclusive"
            return 1
        fi
        # None may be active: the same rule as for one, and it keeps this from
        # pulling the venv the shell stands in out from under it.
        if [ -n "${_TDD_VENV:-}" ]; then
            _tdd_error "$_TDD_VENV is active; run tdd venv deactivate first"
            return 1
        fi
        _tdd_rows=""
        _tdd_json=""
        for _tdd_f in $(find "$(_tdd_venv_root)" -maxdepth 1 -name '*.json' 2>/dev/null | sort); do
            _tdd_name="$(basename "$_tdd_f" .json)"
            _tdd_type="$(_tdd_venv_manager_of "$_tdd_name")"
            _tdd_info "delete $_tdd_name ($_tdd_type)"
            _tdd_venv_remove "$_tdd_name" "$_tdd_type" || return 1
            _tdd_rows="$_tdd_rows${_tdd_rows:+, }$_tdd_name ($_tdd_type)"
            _tdd_json="$_tdd_json${_tdd_json:+,}{\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\"}"
        done
        if [ -z "$_tdd_rows" ]; then
            _tdd_ok "no managed venvs to delete" '"deleted":[]'
        else
            _tdd_ok "deleted $_tdd_rows" "\"deleted\":[$_tdd_json]"
        fi
        return 0
    fi
    if [ -z "$_tdd_name" ]; then
        _tdd_error "--name NAME or --all is required"
        return 1
    fi
    _tdd_venv_resolve || return 1
    if [ "${_TDD_VENV:-}" = "$_tdd_name" ]; then
        _tdd_error "$_tdd_name is active; run tdd venv deactivate first"
        return 1
    fi
    _tdd_info "delete $_tdd_name ($_tdd_type)"
    _tdd_venv_remove "$_tdd_name" "$_tdd_type" || return 1
    _tdd_ok "deleted $_tdd_name ($_tdd_type)" "\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\""
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
    _tdd_rows=""
    _tdd_json=""
    # find, not a glob: an unmatched glob is an error in zsh.
    for _tdd_f in $(find "$(_tdd_venv_root)" -maxdepth 1 -name '*.json' 2>/dev/null | sort); do
        _tdd_name="$(basename "$_tdd_f" .json)"
        _tdd_venv_read_marker "$_tdd_name" || continue
        _tdd_dir="$(_tdd_venv_root)/$_tdd_type/$_tdd_name"
        _tdd_mark=""
        [ "${_TDD_VENV:-}" = "$_tdd_name" ] && _tdd_mark="  (active)"
        [ -d "$_tdd_dir" ] || _tdd_mark="$_tdd_mark  (missing directory)"
        # name, type, the python it runs, reloc or -, its path, the base
        # python it was built from: everything the marker knows, one line.
        _tdd_rows="$_tdd_rows$(printf '%-24s %-6s %-9s %-6s %s  %s%s' "$_tdd_name" "$_tdd_type" "${_tdd_py:-?}" "$([ "$_tdd_reloc" = true ] && printf 'reloc' || printf -- '-')" "$_tdd_dir" "${_tdd_pypath:-?}" "$_tdd_mark")
"
        _tdd_json="$_tdd_json${_tdd_json:+,}{\"name\":\"$(_tdd_json_str "$_tdd_name")\",\"type\":\"$_tdd_type\",\"python\":\"$(_tdd_json_str "$_tdd_py")\",\"python_path\":\"$(_tdd_json_str "$_tdd_pypath")\",\"relocatable\":$_tdd_reloc,\"created\":\"$(_tdd_json_str "$_tdd_created")\",\"path\":\"$(_tdd_json_str "$_tdd_dir")\",\"active\":$([ "${_TDD_VENV:-}" = "$_tdd_name" ] && echo true || echo false),\"exists\":$([ -d "$_tdd_dir" ] && echo true || echo false)}"
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
