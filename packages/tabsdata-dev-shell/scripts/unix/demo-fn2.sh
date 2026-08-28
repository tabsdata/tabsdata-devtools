#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# A demo shell command. It prints its name, then something fetched through two
# external binaries -- which is the part it really demonstrates: the
# bin-reqs.txt beside this file declares them, `tdd --reqs` reports them, and
# tdd-fn refuses to run the command if one is missing from PATH. Registered
# --demo, so it stays out of `tdd help` unless asked for. It is also the
# smallest possible command that follows docs/command-cli-guidelines.md.

tdd_fn_register --demo demo-fn2 "demo shell command: prints its name, then the OS and the date"

tddfn_demo-fn2() {
    _tdd_cmd_reset
    while [ $# -gt 0 ]; do
        _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
        shift "$_TDD_CONSUMED"
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_help_text <<'HELP'
usage: tdd demo-fn2 [-h] [-v] [--format {json,view}]

Demo shell command: prints its name, then the OS and the date.
HELP
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_debug "about to print"
    _tdd_ok "demo-fn2: $(uname -s) $(date +%Y-%m-%d)" \
        "\"os\":\"$(_tdd_json_str "$(uname -s)")\",\"date\":\"$(date +%Y-%m-%d)\""
}
