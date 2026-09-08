#
# Copyright 2026 Tabsdata Inc.
#

# shellcheck disable=SC1090
. "${_TDD_COMMON_SH:?tdd: common.sh not loaded; source tdd-source.sh}"

# Purging the uv and pip caches for a set of packages -- by name prefix, so a
# rebuilt local wheel (same version, new contents) or a republished index
# package cannot be served stale -- or wholesale with --all.
#
#     tdd pycache clean [--package-prefixes tabsdata[,other...]] [--all]
#
# A shell command only because it belongs beside venv and vars in this shell's
# toolbox; it changes nothing in the shell itself.

tdd_fn_register pycache "clean the uv and pip caches, by package prefix (default tabsdata) or all of it"

# Built-in option defaults: what `tdd pycache config` writes as its template,
# and what `--show` compares against.
tdd_defaults_pycache() {
    printf '%s\n' "clean|--package-prefixes|tabsdata" "clean|--all|false"
}

tddfn_pycache() {
    _tdd_cmd_reset
    case "${1:-}" in
        config)
            shift
            _TDD_CMD="pycache-config"
            _tdd_config_action pycache "$@"
            _tdd_rc=$?
            ;;
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
    unset _tdd_prefixes _tdd_all _tdd_before _tdd_found _tdd_swept _tdd_shards _tdd_shard _tdd_left _tdd_l _tdd_p _tdd_names _tdd_out _tdd_pip _tdd_cache _tdd_purged _tdd_json _tdd_pipout
    return "$_tdd_rc"
}

_tdd_pycache_help() {
    _tdd_help_text <<'HELP'
usage: tdd pycache [-h] [-v] [--format {json,view}] SUBCOMMAND ...

purge packages from the uv and pip caches, so a rebuilt wheel of the same version is never
served stale

positional arguments:
  SUBCOMMAND
    clean  purge the caches, by package name prefix or entirely
    config  this command's config file: --show, --default, --create [--force]

example: tdd pycache clean --package-prefixes tabsdata,td-
HELP
}

_tdd_pycache_help_clean() {
    _tdd_help_text <<'HELP'
usage: tdd pycache clean [--package-prefixes PREFIX[,PREFIX...]] [--all]

Remove packages from the uv cache and the pip cache. Package names come from the versioned
entries the caches hold, since `uv cache clean` wants exact names; editable and path builds
are keyed by source hash rather than by name, so uv skips them and they are swept by hand,
along with their unpacked archives. An entry inside a cached environment uv still references
is reported, not removed (`uv cache prune` takes those once unused, and --all takes
everything). pip is done by prefix too, in both the - and _ spellings, and no pip on PATH is
a warning and a uv-only clean.

options:
  --package-prefixes PREFIXES  comma-separated name prefixes; every cached package whose name starts with one is purged (default: tabsdata)
  --all  purge both caches entirely instead
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
        _tdd_pycache_help_clean
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
    # cache holds: every versioned distribution entry (name-<version>...: a
    # .dist-info, a wheel, an sdist, an index record) whose name starts with a
    # prefix, normalized the way uv does (lower-case, - for _, version and
    # suffix stripped). Requiring the version keeps a wheel's top-level import
    # package (tabsdata_dev/) from posing as a distribution called tabsdata-dev.
    _tdd_cache="$(uv cache dir 2>/dev/null)"
    _tdd_names=""
    _tdd_before=0
    for _tdd_p in $(printf '%s' "$_tdd_prefixes" | tr ',' ' '); do
        # Not what sits inside a cached environment (archive-v*/<id>/lib/...):
        # uv cache clean cannot address that by name, it is reported below.
        _tdd_found="$(find "$_tdd_cache" -iname "$_tdd_p*-[0-9]*" -not -path "*/lib/python*/*" 2>/dev/null)"
        [ -n "$_tdd_found" ] && _tdd_before=$((_tdd_before + $(printf '%s\n' "$_tdd_found" | wc -l)))
        _tdd_names="$_tdd_names $(printf '%s\n' "$_tdd_found" \
            | awk -F/ 'NF {print $NF}' \
            | sed -E 's/\.dist-info$//; s/\.(rkyv|msgpack|http|rev|whl|tar\.gz|zip)$//; s/-[0-9].*$//' \
            | tr '_' '-' | tr 'A-Z' 'a-z')"
    done
    # $(printf ...) rather than a bare $_tdd_names: zsh does not word-split an
    # unquoted parameter, so the whole list would travel as one argument (and
    # uv would reject it as one invalid package name).
    _tdd_names="$(printf '%s\n' $(printf '%s' "$_tdd_names") | sort -u | tr '\n' ' ')"
    _tdd_names="${_tdd_names% }"
    _tdd_purged=0
    _tdd_swept=0
    if [ -n "$_tdd_names" ]; then
        _tdd_purged="$(printf '%s\n' $(printf '%s' "$_tdd_names") | wc -l | tr -d ' ')"
        _tdd_info "uv cache clean ($_tdd_purged packages, $_tdd_before entries)"
        # shellcheck disable=SC2086
        _tdd_out="$(uv cache clean $(printf '%s' "$_tdd_names") 2>&1)" || { _tdd_error "uv cache clean failed" "$_tdd_out"; return 1; }
        _tdd_debug "uv: $_tdd_names"
        _tdd_debug "uv cache clean: $(printf '%s' "$_tdd_out" | tail -1)"
        # uv cache clean keys editable (and path) builds by the hash of their
        # source directory, not by name, so it leaves them -- and the unpacked
        # archive they point at -- behind, and `uv cache prune` calls them in
        # use. Those are exactly the entries a devtools developer wants gone,
        # so sweep them: the per-source shard under sdists-v*/<kind>/, and any
        # archive-v*/<id> whose top level is a matching .dist-info (an unpacked
        # wheel; an archive holding a whole environment is left alone).
        for _tdd_p in $(printf '%s' "$_tdd_prefixes" | tr ',' ' '); do
            _tdd_shards="$( { find "$_tdd_cache" -mindepth 4 -path "$_tdd_cache/sdists-v*/*" -iname "$_tdd_p*-[0-9]*" 2>/dev/null \
                    | sed "s|^$_tdd_cache/||" | cut -d/ -f1-3;
                find "$_tdd_cache" -mindepth 3 -maxdepth 3 -path "$_tdd_cache/archive-v*/*" -iname "$_tdd_p*-[0-9]*.dist-info" 2>/dev/null \
                    | sed "s|^$_tdd_cache/||" | cut -d/ -f1-2; } | sort -u)"
            [ -n "$_tdd_shards" ] || continue
            while IFS= read -r _tdd_shard; do
                [ -n "$_tdd_shard" ] || continue
                case "$_tdd_shard" in */*) ;; *) continue ;; esac
                rm -rf "$_tdd_cache/$_tdd_shard" && _tdd_swept=$((_tdd_swept + 1))
                _tdd_debug "swept $_tdd_shard"
            done <<EOF
$_tdd_shards
EOF
        done
        _tdd_debug "swept $_tdd_swept editable/path shards and archives uv cache clean skips"
    else
        _tdd_debug "uv: nothing cached under $_tdd_prefixes"
    fi
    # Say what is still there rather than claim a purge: entries inside cached
    # environments (archive-v*/<id>/lib/...) are uv's to prune once unused.
    _tdd_left=""
    for _tdd_p in $(printf '%s' "$_tdd_prefixes" | tr ',' ' '); do
        _tdd_left="$_tdd_left$(find "$_tdd_cache" -iname "$_tdd_p*-[0-9]*" 2>/dev/null | sed "s|^$_tdd_cache/||")
"
    done
    _tdd_left="$(printf '%s' "$_tdd_left" | sed '/^$/d')"
    if [ -n "$_tdd_left" ]; then
        _tdd_warn "$(printf '%s\n' "$_tdd_left" | wc -l | tr -d ' ') uv cache entries still match $_tdd_prefixes; they sit inside cached environments uv still references (uv cache prune removes them once unused, --all removes everything): $(printf '%s\n' "$_tdd_left" | head -3 | tr '\n' ' ')" \
            "\"left\":[$(printf '%s\n' "$_tdd_left" | while IFS= read -r _tdd_l; do printf '"%s",' "$(_tdd_json_str "$_tdd_l")"; done | sed 's/,$//')]"
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
    for _tdd_p in $(printf '%s' "$_tdd_names"); do _tdd_json="$_tdd_json\"$_tdd_p\","; done
    _tdd_json="${_tdd_json%,}],\"pip\":$([ -n "$_tdd_pip" ] && echo true || echo false)"
    _tdd_json="$_tdd_json,\"uv_entries\":$_tdd_before,\"uv_swept\":$_tdd_swept"
    if [ "$_tdd_purged" = 0 ]; then
        _tdd_ok "uv: nothing cached under $_tdd_prefixes$([ -n "$_tdd_pip" ] && echo '; pip: purged matching wheels' || echo '; pip: not found, skipped')" "$_tdd_json"
    else
        _tdd_ok "uv: purged $_tdd_purged packages ($_tdd_before entries) under $_tdd_prefixes$([ -n "$_tdd_pip" ] && echo '; pip: purged matching wheels' || echo '; pip: not found, skipped')" "$_tdd_json"
    fi
}
