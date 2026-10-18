#
# Copyright 2026 Tabsdata Inc.
#
# The `env show` row of one set variable, as the PowerShell half prints it.
#
#   pwsh -File show_row.ps1 COMMON_PS1 ENV_PS1 NAME

# Arguments come from $args, never param(): -File reads an argument that
# starts with `-` (an option name) as a parameter name.
$CommonPs1, $EnvPs1, $Name = $args

. $CommonPs1
function tdd_fn_register { param($Name, $Summary) }
. $EnvPs1
_tdd_cmd_reset

$rows = [System.Collections.Generic.List[string]]::new()
$vars = [System.Collections.Generic.List[object]]::new()
_tdd_vars_show_row $Name 'td' $false $rows $vars
[Console]::Out.WriteLine($rows[0])
