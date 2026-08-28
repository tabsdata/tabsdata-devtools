#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Purging the uv and pip caches for a set of packages -- by name prefix, so a
# rebuilt local wheel (same version, new contents) or a republished index
# package cannot be served stale -- or wholesale with --all.
#
#     tdd pycache clean [--package-prefixes tabsdata[,other...]] [--all]
#
# A shell command only because it belongs beside venv and vars in this shell's
# toolbox; it changes nothing in the shell itself.

tdd_fn_register pycache "clean the uv and pip caches, by package prefix (default tabsdata) or all of it"

# Built-in option defaults, for `tdd defaults --command pycache`.
tdd_defaults_pycache() {
    printf '%s\n' "clean|--package-prefixes|tabsdata" "clean|--all|false"
}

tddfn_pycache() {
    _tdd_cmd_reset
    case "${1:-}" in
        clean)
            shift
            _TDD_CMD="pycache-clean"
            _tdd_pycache_clean "$@"
            _tdd_rc=$?
            ;;
        --help | -h)
            _tdd_pycache_help
            _tdd_rc=0
            ;;
        "")
            _tdd_error "a subcommand is required: clean (see --help)"
            _tdd_rc=1
            ;;
        *)
            _tdd_error "unknown subcommand: $1 (see --help)"
            _tdd_rc=1
            ;;
    esac
    unset _tdd_prefixes _tdd_all _tdd_p _tdd_names _tdd_out _tdd_pip _tdd_cache _tdd_purged _tdd_json _tdd_pipout
    return "$_tdd_rc"
}

_tdd_pycache_help() {
    cat <<'HELP'
usage: tdd pycache clean [--package-prefixes PREFIX[,PREFIX...]] [--all]

Remove packages from the uv cache and the pip cache.

  --package-prefixes PREFIXES
                      comma-separated name prefixes; every cached package whose
                      name starts with one is purged. Default: tabsdata
  --all               purge both caches entirely instead

common options: --help/-h, --verbose/-v, --format json|view (default view)

example: tdd pycache clean --package-prefixes tabsdata,td-
HELP
}

# Which pip to drive: a pip on PATH, else python3 -m pip, else none.
_tdd_pip_cmd() {
    if command -v pip >/dev/null 2>&1 && pip --version >/dev/null 2>&1; then
        printf 'pip'
    elif command -v python3 >/dev/null 2>&1 && python3 -m pip --version >/dev/null 2>&1; then
        printf 'python3 -m pip'
    fi
}

_tdd_pycache_clean() {
    _tdd_prefixes="tabsdata"
    _tdd_all=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --package-prefixes | --package-prefixes=*)
                _tdd_optval "$@" || { _tdd_error "--package-prefixes needs a value"; return 1; }
                _tdd_prefixes="$_TDD_OPTVAL"
                shift "$_TDD_CONSUMED"
                ;;
            --all)
                _tdd_all=1
                shift
                ;;
            *)
                _tdd_common_opt "$@" || { _tdd_error "unknown option: $1 (see --help)"; return 1; }
                shift "$_TDD_CONSUMED"
                ;;
        esac
    done
    if [ "$_TDD_HELP" = 1 ]; then
        _tdd_pycache_help
        return 0
    fi
    _tdd_cmd_check || return 1
    _tdd_pip="$(_tdd_pip_cmd)"
    [ -n "$_tdd_pip" ] || _tdd_warn "no pip found; only the uv cache will be cleaned"

    if [ "$_tdd_all" = 1 ]; then
        _tdd_info "uv cache clean"
        _tdd_out="$(uv cache clean 2>&1)" || { _tdd_error "uv cache clean failed" "$_tdd_out"; return 1; }
        _tdd_debug "uv cache clean: done"
        if [ -n "$_tdd_pip" ]; then
            _tdd_info "pip cache purge"
            # shellcheck disable=SC2086
            _tdd_pipout="$($_tdd_pip cache purge 2>&1)" || _tdd_warn "pip cache purge: $_tdd_pipout"
            _tdd_debug "pip cache purge: done"
        fi
        _tdd_ok "purged the whole uv cache$([ -n "$_tdd_pip" ] && echo ' and the whole pip cache')" '"scope":"all","uv":true,"pip":'"$([ -n "$_tdd_pip" ] && echo true || echo false)"
        return 0
    fi

    # uv cache clean wants exact package names, so derive them from what the
    # cache holds: every entry whose name starts with a prefix, normalized the
    # way uv does (lower-case, - for _, version and suffix stripped).
    _tdd_cache="$(uv cache dir 2>/dev/null)"
    _tdd_names=""
    for _tdd_p in $(printf '%s' "$_tdd_prefixes" | tr ',' ' '); do
        _tdd_names="$_tdd_names $(find "$_tdd_cache" -maxdepth 5 -iname "$_tdd_p*" 2>/dev/null \
            | awk -F/ '{print $NF}' \
            | sed -E 's/\.dist-info$//; s/\.(rkyv|msgpack|http|rev|whl|tar\.gz|zip)$//; s/-[0-9].*$//' \
            | tr '_' '-' | tr 'A-Z' 'a-z')"
    done
    _tdd_names="$(printf '%s\n' $_tdd_names | sort -u | tr '\n' ' ')"
    _tdd_names="${_tdd_names% }"
    _tdd_purged=0
    if [ -n "$_tdd_names" ]; then
        _tdd_info "uv cache clean ($(printf '%s\n' $_tdd_names | wc -l | tr -d ' ') packages)"
        # shellcheck disable=SC2086
        _tdd_out="$(uv cache clean $_tdd_names 2>&1)" || { _tdd_error "uv cache clean failed" "$_tdd_out"; return 1; }
        _tdd_debug "uv: $_tdd_names"
        _tdd_debug "uv cache clean: done"
        _tdd_purged="$(printf '%s\n' $_tdd_names | wc -l | tr -d ' ')"
    else
        _tdd_debug "uv: nothing cached under $_tdd_prefixes"
    fi
    if [ -n "$_tdd_pip" ]; then
        # pip matches wheel file names, where - became _; try both spellings.
        for _tdd_p in $(printf '%s' "$_tdd_prefixes" | tr ',' ' '); do
            _tdd_info "pip cache remove $_tdd_p*"
            # shellcheck disable=SC2086
            _tdd_pipout="$($_tdd_pip cache remove "$_tdd_p*" 2>&1; $_tdd_pip cache remove "$(printf '%s' "$_tdd_p" | tr '-' '_')*" 2>&1)"
            _tdd_debug "pip: $(printf '%s' "$_tdd_pipout" | tr '\n' ' ')"
            _tdd_debug "pip cache remove $_tdd_p*: done"
        done
    fi
    _tdd_json='"scope":"prefixes","prefixes":['
    for _tdd_p in $(printf '%s' "$_tdd_prefixes" | tr ',' ' '); do _tdd_json="$_tdd_json\"$(_tdd_json_str "$_tdd_p")\","; done
    _tdd_json="${_tdd_json%,}],\"uv_packages\":["
    for _tdd_p in $_tdd_names; do _tdd_json="$_tdd_json\"$_tdd_p\","; done
    _tdd_json="${_tdd_json%,}],\"pip\":$([ -n "$_tdd_pip" ] && echo true || echo false)"
    _tdd_ok "uv: purged $_tdd_purged cached packages under $_tdd_prefixes$([ -n "$_tdd_pip" ] && echo '; pip: purged matching wheels' || echo '; pip: not found, skipped')" "$_tdd_json"
}
