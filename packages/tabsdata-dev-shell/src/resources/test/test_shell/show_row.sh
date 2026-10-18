#
# Copyright 2026 Tabsdata Inc.
#
# The `env show` row of one set variable, as the POSIX half prints it.
#
#   show_row.sh COMMON_SH ENV_SH NAME

common_sh=$1
env_sh=$2
name=$3
set --
. "$common_sh"
. "$env_sh" 2>/dev/null
_tdd_cmd_reset

_tdd_reveal=0
_tdd_rows=''
_tdd_json=''
_tdd_vars_show_row "$name" td
printf '%s' "$_tdd_rows"
