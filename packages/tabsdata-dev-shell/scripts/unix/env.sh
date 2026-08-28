#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Setting variables in the caller's shell is the one thing a Python tool cannot
# do, so these two wrap `tdd system secrets` and `tdd system crypto-key`: run
# them with --as export, eval the lines here, report what was set.
#
#     tdd env set-crypto  [--vault V] [--item I] [--field F]   -> TD_BACKENDS_CRYPTO_KEY
#     tdd env set-secrets [--set 1p:VAULT]                      -> every <PREFIX>__<KEY>
#
# `set-secrets` defaults --set to 1p:$ONE_PASSWORD_DEV_XP_VAULT when that is set.

tdd_fn_register env "set-crypto or set-secrets: fetch from 1Password and export into this shell"

# Built-in option defaults, for `tdd defaults --command env`.
tdd_defaults_env() {
    printf '%s\n' "set-crypto|--vault|\${ONE_PASSWORD_EMPLOYEE_VAULT:-Employee}" \
        "set-crypto|--item|DevSecrets" "set-crypto|--field|TD_BACKENDS_CRYPTO_KEY" \
        "set-secrets|--set|1p:\${ONE_PASSWORD_DEV_XP_VAULT}"
}

tddfn_env() {
    _tdd_cmd_reset
    case "${1:-}" in
        set-crypto | set-secrets)
            _tdd_sub="$1"
            shift
            _TDD_CMD="env-$_tdd_sub"
            "_tdd_envset_${_tdd_sub#set-}" "$@"
            _tdd_rc=$?
            ;;
        --help | -h)
            _tdd_envset_help
            _tdd_rc=0
            ;;
        "")
            _tdd_error "a subcommand is required: set-crypto or set-secrets (see --help)"
            _tdd_rc=1
            ;;
        *)
            _tdd_error "unknown subcommand: $1 (see --help)"
            _tdd_rc=1
            ;;
    esac
    unset _tdd_sub _tdd_args _tdd_lines _tdd_err _tdd_names _tdd_n _tdd_set _tdd_json
    return "$_tdd_rc"
}

_tdd_envset_help() {
    _tdd_help_text <<'HELP'
usage: tdd env set-crypto [--vault VAULT] [--item ITEM] [--field FIELD]
       tdd env set-secrets [--set PROVIDER:REF]

Fetch secrets from 1Password and export them into THIS shell. Both run the
Python command with --as export and eval its output here; nothing is written
to disk. The `op` CLI must be installed and signed in.

commands:
  set-crypto    TD_BACKENDS_CRYPTO_KEY, the key that encrypts the system and
                domain descriptors, read from op://VAULT/ITEM/FIELD. Same as
                `tdd system crypto-key`
  set-secrets   every <PREFIX>__<KEY> item of a shared vault, plus
                TD_BACKENDS_SYSTEMS. Same as `tdd system secrets`

options:
  --vault VAULT        1Password vault (default: $ONE_PASSWORD_EMPLOYEE_VAULT,
                       else Employee)
  --item ITEM          item in the vault (default: DevSecrets)
  --field FIELD        field of the item (default: TD_BACKENDS_CRYPTO_KEY)
  --set PROVIDER:REF   the vault to read, as 1p:VAULT (default:
                       1p:$ONE_PASSWORD_DEV_XP_VAULT, when that is set)

example: tdd env set-crypto && tdd system list
HELP
}

# Run `tdd system <verb> <args> --as export`, eval the export lines here, and
# report the names set. The child's stdout is exactly the export lines (its
# progress goes to stderr); a a non-zero status carries the child's error.
_tdd_envset_apply() {
    _tdd_err="$(mktemp)"
    # shellcheck disable=SC2086
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
    _tdd_names="$(printf '%s\n' "$_tdd_lines" | sed -n 's/^export \([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p')"
    _tdd_n="$(printf '%s\n' "$_tdd_names" | grep -c .)"
    _tdd_json=""
    for _tdd_v in $(printf '%s\n' "$_tdd_names"); do _tdd_json="$_tdd_json${_tdd_json:+,}\"$_tdd_v\""; done
    unset _tdd_v
    _tdd_ok "set $_tdd_n variable(s) in this shell: $(printf '%s\n' "$_tdd_names" | tr '\n' ' ' | sed 's/ $//')" "\"names\":[$_tdd_json]"
}

_tdd_envset_crypto() {
    _tdd_args=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --vault | --vault=* | --item | --item=* | --field | --field=*)
                _tdd_optval "$@" || { _tdd_error "$1 needs a value"; return 1; }
                _tdd_args="$_tdd_args ${1%%=*}=$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_envset_help
        return 0
    fi
    _tdd_cmd_check || return 1
    # shellcheck disable=SC2086
    _tdd_envset_apply crypto-key $(printf '%s' "$_tdd_args")
}

_tdd_envset_secrets() {
    _tdd_set="${ONE_PASSWORD_DEV_XP_VAULT:+1p:$ONE_PASSWORD_DEV_XP_VAULT}"
    while [ $# -gt 0 ]; do
        case "$1" in
            --set | --set=*)
                _tdd_optval "$@" || { _tdd_error "--set needs a value"; return 1; }
                _tdd_set="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_envset_help
        return 0
    fi
    _tdd_cmd_check || return 1
    if [ -z "$_tdd_set" ]; then
        _tdd_error "--set PROVIDER:REF is required (or set ONE_PASSWORD_DEV_XP_VAULT)"
        return 1
    fi
    _tdd_envset_apply secrets "--set=$_tdd_set"
}
