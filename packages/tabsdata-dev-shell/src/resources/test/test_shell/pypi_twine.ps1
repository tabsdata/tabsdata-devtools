#
# Copyright 2026 Tabsdata Inc.
#
# `env set --pypi-twine`, then `env unset --pypi-twine`, in the PowerShell
# half; after each prints `STATUS TWINE_USERNAME TWINE_PASSWORD`, `unset` for a
# variable that is not set.
#
#   pwsh -File pypi_twine.ps1 COMMON_PS1 ENV_PS1

# Arguments come from $args, never param(): -File reads an argument that
# starts with `-` (an option name) as a parameter name.
$CommonPs1, $EnvPs1 = $args

. $CommonPs1
function tdd_fn_register { param($Name, $Summary) }
. $EnvPs1

function Show([string]$Variable) {
    $value = [Environment]::GetEnvironmentVariable($Variable)
    if ($null -eq $value) { 'unset' } else { $value }
}

foreach ($action in 'set', 'unset') {
    _tdd_cmd_reset
    tddfn_env @($action, '--pypi-twine') | Out-Null
    $user = Show 'TWINE_USERNAME'
    $pass = Show 'TWINE_PASSWORD'
    [Console]::Out.WriteLine("$($global:_TDD_RC) $user $pass")
}
