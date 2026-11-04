#
# Copyright 2026 Tabsdata Inc.
#
# A run whose --continue stage fails, and whose later stage, which needed what
# the failed one set up, is skipped.
#
#   stage_skip.sh ENGINE LOG
#
# `tdd _smoke` is the toolset's own `_smoke` program, $SMOKE_ENGINE.

tdd() {
    [ "$1" = _smoke ] || return 127
    shift
    "$SMOKE_ENGINE" "$@"
}

engine=$1
log=$2
set --
. "$engine"

STAGE_NAMES=(setup work check cleanup)
SET_UP=""
common_init "$log" 0
common_stage --continue setup "set something up"
common_run false && SET_UP=1
common_stage work "work that does not need it"
common_run true
common_stage --continue check "check what setup set up"
if [ -z "$SET_UP" ]; then
    common_stage_skip "setup did not complete"
else
    common_run true
fi
common_stage cleanup "clean up"
common_run true
common_finish
