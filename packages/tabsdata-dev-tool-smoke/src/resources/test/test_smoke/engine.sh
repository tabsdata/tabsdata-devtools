#
# Copyright 2026 Tabsdata Inc.
#
# Load the smoke engine and call one of its functions with the rest of the
# arguments, untouched.
#
#   engine.sh ENGINE FUNCTION [ARG...]

# `tdd _smoke` is the toolset's own `_smoke` program, $SMOKE_ENGINE.
tdd() {
    [ "$1" = _smoke ] || return 127
    shift
    "$SMOKE_ENGINE" "$@"
}

engine=$1
shift
function=$1
shift
args=("$@")
set --
. "$engine"
"$function" "${args[@]}"
