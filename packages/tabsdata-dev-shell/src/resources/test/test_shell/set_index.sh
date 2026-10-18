#
# Copyright 2026 Tabsdata Inc.
#
# `env set OPTION VALUE` in the POSIX half; prints its status, then
# UV_INDEX and UV_DEFAULT_INDEX, one per line.
#
#   set_index.sh COMMON_SH ENV_SH OPTION VALUE

common_sh=$1
env_sh=$2
option=$3
value=$4
set --
. "$common_sh"
. "$env_sh" 2>/dev/null
_tdd_cmd_reset

tddfn_env set "$option" "$value" >/dev/null 2>&1
printf '%s\n%s\n%s\n' "$?" "$UV_INDEX" "$UV_DEFAULT_INDEX"
