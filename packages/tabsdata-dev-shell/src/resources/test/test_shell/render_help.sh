#
# Copyright 2026 Tabsdata Inc.
#
# Lay out the help declaration on stdin as common.sh does.
#
#   render_help.sh COMMON_SH < DECLARATION

common_sh=$1
set --
# what the loaders export: common.sh finds help.awk beside it through it
_TDD_COMMON_SH=$common_sh
. "$common_sh"
_tdd_help_text
