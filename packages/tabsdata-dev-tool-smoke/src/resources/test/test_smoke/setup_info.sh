#
# Copyright 2026 Tabsdata Inc.
#
# The failure report's `left for you to look at` for a run named
# sm_fixture_notarealrun, with the domains it says it created.
#
#   setup_info.sh ENGINE TDD_DIR LOG [DOMAINS]
#
# `tdd _smoke` is the toolset's own `_smoke` program, $SMOKE_ENGINE: the
# engine asks it for the instance's processes.

tdd() {
    [ "$1" = _smoke ] || return 127
    shift
    "$SMOKE_ENGINE" "$@"
}

engine=$1
tdd_dir=$2
log=$3
domains=${4:-}
set --
. "$engine"

TDD_DIR_OPT=$tdd_dir
SMOKE_DOMAINS=$domains
INSTANCE=sm_fixture_notarealrun
VENV=sm_fixture_notarealrun
VENV_TYPE=pyenv
SERVER=127.0.0.1:2457
NAMES_PREFIX=sm_fixture_notarealrun

common_init "$log" 0
common_tabsdata_setup_info common_indented
