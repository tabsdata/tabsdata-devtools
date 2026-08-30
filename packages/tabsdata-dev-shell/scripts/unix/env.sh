#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${_TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Setting and unsetting variables in the caller's shell is the one thing a
# Python tool cannot do, so this one command owns every variable tdd manages:
#
#     crypto     _TDD_CRYPTO_KEY            from 1Password, via `tdd system crypto-key`
#     secrets    <PREFIX>__<KEY>..., _TDD_SYSTEMS   via `tdd system secrets`; the latter lists
#                                                  the prefixes, which is how unset knows what to remove
#     td         TD_*                              (unset only)
#     vars       <PREFIX>*                         (unset only)
#     py-idx     UV_INDEX, PIP_EXTRA_INDEX_URL     the extra Python package index, with UV_INDEX_STRATEGY=
#                                                  unsafe-best-match so uv considers it (+ legacy UV_EXTRA_INDEX_URL on unset)
#     py-default-idx  UV_DEFAULT_INDEX, PIP_INDEX_URL  the default index (+ legacy UV_INDEX_URL on unset)
#
# `set` exports, `unset` removes, `show` lists them all (`-` marks unset) in
# three sorted groups: TD (everything starting with TD that is set, the two
# above always), PyPi (the index variables), Secrets.

tdd_fn_register env "set, unset or show this shell's crypto key, 1Password secrets, TD_ and Python index variables"

# Built-in option defaults, for `tdd defaults --command env`.
tdd_defaults_env() {
    printf '%s\n' "set|--vault|crypto: \${ONE_PASSWORD_EMPLOYEE_VAULT:-Employee}; secrets: 1p:\${ONE_PASSWORD_DEV_XP_VAULT}" \
        "set|--item|DevSecrets" "set|--field|TD_BACKENDS_CRYPTO_KEY" "set|--force|false" "show|--reveal|false"
}

_TDD_VARS_CRYPTO="_TDD_CRYPTO_KEY"
_TDD_VARS_SYSTEMS="_TDD_SYSTEMS"
_TDD_VARS_PY_EXTRA="UV_INDEX PIP_EXTRA_INDEX_URL"
_TDD_VARS_PY_EXTRA_LEGACY="UV_EXTRA_INDEX_URL"
# An extra index only matters if uv may pick a package from it over the
# default one; the default strategy never does.
_TDD_VARS_PY_STRATEGY="UV_INDEX_STRATEGY"
_TDD_VARS_PY_STRATEGY_VALUE="unsafe-best-match"
_TDD_VARS_PY_DEFAULT="UV_DEFAULT_INDEX PIP_INDEX_URL"
_TDD_VARS_PY_DEFAULT_LEGACY="UV_INDEX_URL"

tddfn_env() {
    _tdd_cmd_reset
    case "${1:-}" in
        set | unset | show)
            _tdd_sub="$1"
            shift
            _TDD_CMD="env-$_tdd_sub"
            "_tdd_vars_$_tdd_sub" "$@"
            _tdd_rc=$?
            ;;
        --help | -h)
            _tdd_vars_help
            _tdd_rc=0
            ;;
        "")
            _tdd_error "a subcommand is required: set, unset or show (see --help)"
            _tdd_rc=1
            ;;
        *)
            _tdd_error "unknown subcommand: $1 (see --help)"
            _tdd_rc=1
            ;;
    esac
    unset _tdd_sub _tdd_crypto _tdd_secrets _tdd_td _tdd_prefixes _tdd_py_extra _tdd_py_default _tdd_vault _tdd_item _tdd_field _tdd_reveal \
        _tdd_force _tdd_kept _tdd_args _tdd_lines _tdd_err _tdd_names _tdd_n _tdd_json _tdd_v _tdd_p _tdd_rows _tdd_set_names _tdd_unset_names _tdd_row _tdd_val _tdd_shown
    return "$_tdd_rc"
}

_tdd_vars_help() {
    _tdd_help_text <<'HELP'
usage: tdd env set (--crypto | --secrets | --py-idx URL | --py-default-idx URL)...
                   [--vault VAULT] [--item ITEM] [--field FIELD] [--force]
       tdd env unset (--crypto | --secrets | --td | --vars PREFIX | --py-idx
                     | --py-default-idx)...
       tdd env show [--reveal]

Set, unset or show the environment variables tdd manages, in THIS shell: the
descriptor crypto key, the 1Password secrets, the TD_ variables and the Python
package index variables. Several selections may be combined in one call.

commands:
  set        export the selected variables; the crypto key and the secrets come
             from 1Password through `tdd system crypto-key` and `tdd system
             secrets` (--as export, eval'd here; nothing is written to disk)
  unset      remove the selected variables
  show       every variable these commands handle, NAME=value when set, -NAME
             when not, in three sorted groups: TD (every variable starting with
             TD), PyPi (the index variables) and Secrets

options:
  --crypto             _TDD_CRYPTO_KEY, the key that encrypts the system
                       and domain descriptors; set reads op://VAULT/ITEM/FIELD --
                       only when the variable is not already set, unless --force
  --secrets            every <PREFIX>__<KEY> secret of a shared vault plus
                       _TDD_SYSTEMS, the list of prefixes -- which is what
                       unset reads to know what to remove
  --vault VAULT        set --crypto: the 1Password vault (default:
                       $ONE_PASSWORD_EMPLOYEE_VAULT, else Employee); set
                       --secrets: the provider ref, 1p:VAULT (default:
                       1p:$ONE_PASSWORD_DEV_XP_VAULT). Not with both at once
  --item ITEM          set --crypto: item in the vault (default: DevSecrets)
  --field FIELD        set --crypto: field of the item (default:
                       TD_BACKENDS_CRYPTO_KEY, the 1Password field's name)
  -f, --force          set --crypto: fetch from 1Password even if
                       _TDD_CRYPTO_KEY is already set
  --td                 unset: every variable starting with TD_ (tabsdata's);
                       tdd's own _TDD_SYSTEMS and _TDD_CRYPTO_KEY are not
                       among them -- --secrets and --crypto remove those
  --vars PREFIX        unset: every variable starting with PREFIX (repeatable).
                       TDD_DIR, the tdd dir itself, is never unset
  --py-idx [URL]       the extra Python package index: UV_INDEX and
                       PIP_EXTRA_INDEX_URL, plus UV_INDEX_STRATEGY=unsafe-best-match
                       so uv considers it (set needs URL; unset also clears the
                       legacy UV_EXTRA_INDEX_URL)
  --py-default-idx [URL]
                       the default Python package index: UV_DEFAULT_INDEX and
                       PIP_INDEX_URL (set needs URL; unset also clears the
                       legacy UV_INDEX_URL)
  --reveal             show: print credential values instead of masking them

example: tdd env set --crypto --secrets && tdd env show
HELP
}

# Names of the exported variables matching an extended regex, one per line.
# From lines that look like assignments -- a value holding a newline must not
# be mistaken for a variable.
_tdd_vars_names() {
    env | awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}' | grep -E "$1" | sort
}

# Run `tdd-exe system <verb> ...` with --as export and eval its lines here;
# appends the names it set to _tdd_set_names. Returns 1 after reporting.
_tdd_vars_apply() {
    _tdd_err="$(mktemp)"
    _tdd_lines="$(tdd-exe system "$@" --as export 2>"$_tdd_err")"
    if [ $? -ne 0 ]; then
        _tdd_error "tdd system $1 failed: $(grep -v '^details:' "$_tdd_err" | tail -1)" "$(cat "$_tdd_err")"
        rm -f "$_tdd_err"
        return 1
    fi
    rm -f "$_tdd_err"
    if [ -z "$_tdd_lines" ]; then
        _tdd_error "tdd system $1 returned nothing to export"
        return 1
    fi
    eval "$_tdd_lines"
    _tdd_set_names="$_tdd_set_names $(printf '%s\n' "$_tdd_lines" | sed -n 's/^export \([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' | tr '\n' ' ')"
    return 0
}

_tdd_vars_set() {
    _tdd_crypto=0
    _tdd_secrets=0
    _tdd_py_extra=""
    _tdd_py_default=""
    _tdd_vault=""
    _tdd_item=""
    _tdd_field=""
    _tdd_force=0
    _tdd_set_names=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --crypto) _tdd_crypto=1; shift ;;
            --secrets) _tdd_secrets=1; shift ;;
            --force | -f) _tdd_force=1; shift ;;
            --vault | --vault=*)
                _tdd_optval "$@" || { _tdd_error "--vault needs a value"; return 1; }
                _tdd_vault="$_TDD_OPTVAL"; shift "$_TDD_CONSUMED" ;;
            --item | --item=*)
                _tdd_optval "$@" || { _tdd_error "--item needs a value"; return 1; }
                _tdd_item="$_TDD_OPTVAL"; shift "$_TDD_CONSUMED" ;;
            --field | --field=*)
                _tdd_optval "$@" || { _tdd_error "--field needs a value"; return 1; }
                _tdd_field="$_TDD_OPTVAL"; shift "$_TDD_CONSUMED" ;;
            --py-idx | --py-idx=*)
                _tdd_optval "$@" || { _tdd_error "--py-idx needs a URL"; return 1; }
                _tdd_py_extra="$_TDD_OPTVAL"; shift "$_TDD_CONSUMED" ;;
            --py-default-idx | --py-default-idx=*)
                _tdd_optval "$@" || { _tdd_error "--py-default-idx needs a URL"; return 1; }
                _tdd_py_default="$_TDD_OPTVAL"; shift "$_TDD_CONSUMED" ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED" ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_vars_help
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ "$_tdd_crypto" = 0 ] && [ "$_tdd_secrets" = 0 ] && [ -z "$_tdd_py_extra" ] && [ -z "$_tdd_py_default" ]; then
        _tdd_error "nothing selected: --crypto, --secrets, --py-idx URL and/or --py-default-idx URL (see --help)"
        return 1
    fi
    _tdd_kept=""
    if [ "$_tdd_crypto" = 1 ] && [ -n "${_TDD_CRYPTO_KEY:-}" ] && [ "$_tdd_force" != 1 ]; then
        _tdd_kept="$_TDD_VARS_CRYPTO"
    fi
    if [ -n "$_tdd_vault" ] && [ "$_tdd_crypto" = 1 ] && [ "$_tdd_secrets" = 1 ]; then
        _tdd_error "--vault means different things to --crypto and --secrets; set them in two calls"
        return 1
    fi
    if [ "$_tdd_crypto" = 1 ] && [ -n "${_TDD_CRYPTO_KEY:-}" ] && [ "$_tdd_force" != 1 ]; then
        # Already there: no trip to 1Password (a signed-in `op` is not a given
        # in every shell); --force refetches.
        # The ok says it when the key was the only selection; otherwise say it here.
        if [ "$_tdd_secrets" = 1 ] || [ -n "$_tdd_py_extra" ] || [ -n "$_tdd_py_default" ]; then
            _tdd_info "$_TDD_VARS_CRYPTO is already set; not fetched (use --force to refetch)"
        fi
        _tdd_crypto=0
    fi
    if [ "$_tdd_crypto" = 1 ]; then
        _tdd_args=""
        [ -n "$_tdd_vault" ] && _tdd_args="$_tdd_args --vault=$_tdd_vault"
        [ -n "$_tdd_item" ] && _tdd_args="$_tdd_args --item=$_tdd_item"
        [ -n "$_tdd_field" ] && _tdd_args="$_tdd_args --field=$_tdd_field"
        _tdd_info "tdd system crypto-key$_tdd_args --as export"
        # shellcheck disable=SC2086
        _tdd_vars_apply crypto-key $(printf '%s' "$_tdd_args") || return 1
    fi
    if [ "$_tdd_secrets" = 1 ]; then
        _tdd_v="${_tdd_vault:-${ONE_PASSWORD_DEV_XP_VAULT:+1p:$ONE_PASSWORD_DEV_XP_VAULT}}"
        if [ -z "$_tdd_v" ]; then
            _tdd_error "--secrets needs --vault 1p:VAULT (or ONE_PASSWORD_DEV_XP_VAULT set)"
            return 1
        fi
        _tdd_info "tdd system secrets --set $_tdd_v --as export"
        _tdd_vars_apply secrets "--set=$_tdd_v" || return 1
    fi
    if [ -n "$_tdd_py_extra" ]; then
        for _tdd_v in $(printf '%s' "$_TDD_VARS_PY_EXTRA"); do
            export "$_tdd_v=$_tdd_py_extra"
            _tdd_set_names="$_tdd_set_names $_tdd_v"
        done
        export "$_TDD_VARS_PY_STRATEGY=$_TDD_VARS_PY_STRATEGY_VALUE"
        _tdd_set_names="$_tdd_set_names $_TDD_VARS_PY_STRATEGY"
    fi
    if [ -n "$_tdd_py_default" ]; then
        for _tdd_v in $(printf '%s' "$_TDD_VARS_PY_DEFAULT"); do
            export "$_tdd_v=$_tdd_py_default"
            _tdd_set_names="$_tdd_set_names $_tdd_v"
        done
    fi
    _tdd_names="$(printf '%s\n' $(printf '%s' "$_tdd_set_names") | grep -c .)"
    _tdd_json=""
    for _tdd_v in $(printf '%s' "$_tdd_set_names"); do _tdd_json="$_tdd_json${_tdd_json:+,}\"$_tdd_v\""; done
    if [ "$_tdd_names" = 0 ] && [ -n "$_tdd_kept" ]; then
        _tdd_ok "$_tdd_kept already set; nothing fetched" "\"set\":[],\"kept\":[\"$_tdd_kept\"]"
    else
        _tdd_ok "set $_tdd_names variable(s) in this shell: $(printf '%s' "$_tdd_set_names" | sed 's/^ *//; s/ *$//')${_tdd_kept:+ ($_tdd_kept already set, kept)}" "\"set\":[$_tdd_json],\"kept\":[${_tdd_kept:+\"$_tdd_kept\"}]"
    fi
}

_tdd_vars_unset() {
    _tdd_crypto=0
    _tdd_secrets=0
    _tdd_td=0
    _tdd_prefixes=""
    _tdd_py_extra=0
    _tdd_py_default=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --crypto) _tdd_crypto=1; shift ;;
            --secrets) _tdd_secrets=1; shift ;;
            --td) _tdd_td=1; shift ;;
            --vars | --vars=*)
                _tdd_optval "$@" || { _tdd_error "--vars needs a PREFIX"; return 1; }
                _tdd_prefixes="$_tdd_prefixes $_TDD_OPTVAL"; shift "$_TDD_CONSUMED" ;;
            --py-idx | --py-idx=*) _tdd_py_extra=1; shift ;;
            --py-default-idx | --py-default-idx=*) _tdd_py_default=1; shift ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED" ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_vars_help
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ "$_tdd_crypto" = 0 ] && [ "$_tdd_secrets" = 0 ] && [ "$_tdd_td" = 0 ] && [ -z "$_tdd_prefixes" ] && [ "$_tdd_py_extra" = 0 ] && [ "$_tdd_py_default" = 0 ]; then
        _tdd_error "nothing selected: --crypto, --secrets, --td, --vars PREFIX, --py-idx and/or --py-default-idx (see --help)"
        return 1
    fi
    _tdd_unset_names=""
    [ "$_tdd_crypto" = 1 ] && _tdd_unset_names="$_tdd_unset_names $_TDD_VARS_CRYPTO"
    if [ "$_tdd_secrets" = 1 ]; then
        if [ -z "${_TDD_SYSTEMS:-}" ]; then
            _tdd_warn "$_TDD_VARS_SYSTEMS is not set: no secrets are recorded in this shell, none removed"
        else
            for _tdd_p in $(printf '%s' "$_TDD_SYSTEMS"); do
                _tdd_unset_names="$_tdd_unset_names $(_tdd_vars_names "^${_tdd_p}__" | tr '\n' ' ')"
            done
            _tdd_unset_names="$_tdd_unset_names $_TDD_VARS_SYSTEMS"
        fi
    fi
    [ "$_tdd_td" = 1 ] && _tdd_unset_names="$_tdd_unset_names $(_tdd_vars_names '^TD_' | tr '\n' ' ')"
    for _tdd_p in $(printf '%s' "$_tdd_prefixes"); do
        _tdd_unset_names="$_tdd_unset_names $(_tdd_vars_names "^${_tdd_p}" | tr '\n' ' ')"
    done
    [ "$_tdd_py_extra" = 1 ] && _tdd_unset_names="$_tdd_unset_names $_TDD_VARS_PY_EXTRA $_TDD_VARS_PY_EXTRA_LEGACY $_TDD_VARS_PY_STRATEGY"
    [ "$_tdd_py_default" = 1 ] && _tdd_unset_names="$_tdd_unset_names $_TDD_VARS_PY_DEFAULT $_TDD_VARS_PY_DEFAULT_LEGACY"
    # Only what is actually set counts as unset; dedupe (--vars TD and --td overlap).
    # TDD_DIR is never unset: it is how `tdd` itself finds its dir in this shell,
    # and a prefix like --vars TD would otherwise take it out.
    _tdd_names=""
    for _tdd_v in $(printf '%s\n' $(printf '%s' "$_tdd_unset_names") | sort -u); do
        if [ "$_tdd_v" = "TDD_DIR" ]; then
            _tdd_info "TDD_DIR kept (tdd needs it; never unset)"
            continue
        fi
        if [ -n "$(eval "printf '%s' \"\${$_tdd_v+x}\"")" ]; then
            unset "$_tdd_v"
            _tdd_debug "unset $_tdd_v"
            _tdd_names="$_tdd_names $_tdd_v"
        fi
    done
    _tdd_json=""
    for _tdd_v in $(printf '%s' "$_tdd_names"); do _tdd_json="$_tdd_json${_tdd_json:+,}\"$_tdd_v\""; done
    if [ -z "$_tdd_names" ]; then
        _tdd_ok "nothing to unset" '"unset":[]'
    else
        _tdd_ok "unset $(printf '%s\n' $(printf '%s' "$_tdd_names") | grep -c .) variable(s): $(printf '%s' "$_tdd_names" | sed 's/^ *//')" "\"unset\":[$_tdd_json]"
    fi
}

# One `show` line: `NAME=value` when set, `- NAME` when not, indented under its
# group heading -- the `-` is the marker, a set variable gets spaces instead. Credentials -- the crypto key and any secret whose name says so
# (PASSWORD, SECRET, TOKEN, KEY, PASS, _PAT) -- are masked unless --reveal.
_tdd_vars_show_row() {
    if [ -z "$(eval "printf '%s' \"\${$1+x}\"")" ]; then
        _tdd_rows="$_tdd_rows  - $1
"
        _tdd_json="$_tdd_json${_tdd_json:+,}{\"name\":\"$1\",\"group\":\"$2\",\"set\":false}"
        return 0
    fi
    _tdd_val="$(eval "printf '%s' \"\$$1\"")"
    _tdd_shown="$_tdd_val"
    if [ "$_tdd_reveal" != 1 ]; then
        case "$2:$1" in
            *:"$_TDD_VARS_CRYPTO" | secrets:*PASSWORD* | secrets:*SECRET* | secrets:*TOKEN* | secrets:*KEY* | secrets:*PASS* | secrets:*_PAT | secrets:*_PAT_*)
                _tdd_shown="$(printf '%s' "$_tdd_val" | cut -c1-2)****" ;;
        esac
    fi
    _tdd_rows="$_tdd_rows    $1=$_tdd_shown
"
    _tdd_json="$_tdd_json${_tdd_json:+,}{\"name\":\"$1\",\"group\":\"$2\",\"set\":true,\"value\":\"$(_tdd_json_str "$_tdd_shown")\"}"
}

# A group: its heading, then one row per name, names sorted and deduplicated.
# $1 heading, $2 group id, the rest the names (a name may repeat).
_tdd_vars_show_group() {
    _tdd_rows="$_tdd_rows$1:
"
    _tdd_p="$1"
    _tdd_v="$2"
    shift 2
    if [ $# -eq 0 ]; then
        _tdd_rows="$_tdd_rows  (none)
"
        return 0
    fi
    for _tdd_n in $(printf '%s\n' "$@" | sort -u); do
        _tdd_vars_show_row "$_tdd_n" "$_tdd_v"
    done
}

_tdd_vars_show() {
    _tdd_reveal=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --reveal) _tdd_reveal=1; shift ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED" ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_vars_help
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_rows=""
    _tdd_json=""
    # TD: everything starting with TD (TD_, TDD_, TDX_, ...) that is set, plus
    # tdd's own private ones below.
    # shellcheck disable=SC2046
    # The crypto key is named even when unset (worth a `-` row: nothing works
    # without it); _TDD_SYSTEMS is bookkeeping, listed only while secrets are loaded.
    _tdd_vars_show_group TD td "$_TDD_VARS_CRYPTO" ${_TDD_SYSTEMS+"$_TDD_VARS_SYSTEMS"} $(_tdd_vars_names '^TD')
    # shellcheck disable=SC2046
    _tdd_vars_show_group PyPi pypi $(printf '%s' "$_TDD_VARS_PY_EXTRA $_TDD_VARS_PY_EXTRA_LEGACY $_TDD_VARS_PY_STRATEGY $_TDD_VARS_PY_DEFAULT $_TDD_VARS_PY_DEFAULT_LEGACY")
    _tdd_names=""
    for _tdd_p in $(printf '%s' "${_TDD_SYSTEMS:-}"); do
        _tdd_names="$_tdd_names $(_tdd_vars_names "^${_tdd_p}__" | tr '\n' ' ')"
    done
    # shellcheck disable=SC2046
    _tdd_vars_show_group Secrets secrets $(printf '%s' "$_tdd_names")
    _tdd_ok "${_tdd_rows%
}" "\"vars\":[$_tdd_json],\"revealed\":$([ "$_tdd_reveal" = 1 ] && echo true || echo false)"
}
