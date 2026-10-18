#
# Copyright 2026 Tabsdata Inc.
#
# Load the smoke engine and call one of its functions with the rest of the
# arguments, untouched.
#
#   engine.sh ENGINE FUNCTION [ARG...]

engine=$1
shift
function=$1
shift
args=("$@")
set --
. "$engine"
"$function" "${args[@]}"
