#
# Copyright 2026 Tabsdata Inc.
#
# The shared `config --show` for a made-up command, `demo`, whose file sets
# `type = "uv"`: a stub tdd-exe stands in for the TOML parser.
#
#   config_show.sh COMMON_SH

common_sh=$1
set --
# what the loaders export: common.sh finds help.awk beside it through it
_TDD_COMMON_SH=$common_sh
. "$common_sh"
_tdd_cmd_reset

tdd-exe() {
    printf '%s' '{"options":{"":{"type":"uv"}}}'
}

tdd_defaults_demo() {
    printf '%s\n' '-|--type|pyenv' 'create|--python|3.12'
}

_tdd_config_show demo
