#
# Copyright 2026 Tabsdata Inc.
#
# A --continue stage whose retried probe first says "not yet", then "waiting
# cannot change this": the retries stop at the second attempt.
#
#   retry_final.sh ENGINE LOG COUNTER
#
# `tdd _smoke` is the toolset's own `_smoke` program, $SMOKE_ENGINE.

tdd() {
    [ "$1" = _smoke ] || return 127
    shift
    "$SMOKE_ENGINE" "$@"
}

engine=$1
log=$2
counter=$3
set --
. "$engine"

probe() {
    echo x >>"$counter"
    [ "$(wc -l <"$counter")" -ge 2 ] && return "$COMMON_FINAL"
    return 1
}

STAGE_NAMES=(check cleanup)
common_init "$log" 0
common_stage --continue check "a check that fails for good on its second attempt"
common_run_retry 30 0 probe
common_stage cleanup "clean up"
common_run true
common_finish
