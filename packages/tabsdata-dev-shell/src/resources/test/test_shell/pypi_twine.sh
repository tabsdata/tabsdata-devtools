#
# Copyright 2026 Tabsdata Inc.
#
# `env set --pypi-twine`, then `env unset --pypi-twine`, in the POSIX half;
# after each prints `STATUS TWINE_USERNAME TWINE_PASSWORD`, `unset` for a
# variable that is not set.
#
#   pypi_twine.sh COMMON_SH ENV_SH

common_sh=$1
env_sh=$2
set --
. "$common_sh"
. "$env_sh" 2>/dev/null

for action in set unset; do
    _tdd_cmd_reset
    tddfn_env "$action" --pypi-twine >/dev/null 2>&1
    printf '%s %s %s\n' "$?" "${TWINE_USERNAME-unset}" "${TWINE_PASSWORD-unset}"
done
