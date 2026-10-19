#
# Copyright 2026 Tabsdata Inc.
#
# Load the loader's _tdd_warn_old_powershell alone -- found with PowerShell's
# parser -- and call it as each version would see itself: 7.4, then 5.1
# ($PSVersionTable is read-only, so the version is passed in).
#
#   pwsh -File old_powershell.ps1 LOADER_PS1

# Arguments come from $args, never param(): -File reads an argument that
# starts with `-` (an option name) as a parameter name.
$Loader = $args[0]

$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Loader, [ref]$null, [ref]$null
)
$warn = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq '_tdd_warn_old_powershell'
}, $true)
if (-not $warn) {
    [Console]::Error.WriteLine("_tdd_warn_old_powershell is gone from $Loader")
    exit 1
}
. ([scriptblock]::Create($warn.Extent.Text))

foreach ($version in '7.4.6', '5.1.19041') {
    [Console]::Error.WriteLine("== $version")
    _tdd_warn_old_powershell -Version $version
}
