#
# Copyright 2026 Tabsdata Inc.
#
# `env set OPTION VALUE` in the PowerShell half; prints its status, then
# UV_INDEX and UV_DEFAULT_INDEX, one per line.
#
#   pwsh -File set_index.ps1 COMMON_PS1 ENV_PS1 OPTION VALUE

# Arguments come from $args, never param(): -File reads an argument that
# starts with `-` (an option name, as here) as a parameter name.
$CommonPs1, $EnvPs1, $Option, $Value = $args

. $CommonPs1
function tdd_fn_register { param($Name, $Summary) }
. $EnvPs1
_tdd_cmd_reset

tddfn_env @('set', $Option, $Value) | Out-Null
[Console]::Out.WriteLine($global:_TDD_RC)
[Console]::Out.WriteLine($env:UV_INDEX)
[Console]::Out.WriteLine($env:UV_DEFAULT_INDEX)
