#
# Copyright 2026 Tabsdata Inc.
#
# Load the loader's _tdd_argv_text alone -- found with PowerShell's parser,
# so nothing else of the loader runs -- and show how it passes three argument
# lists through: `COUNT|ARG|ARG...` per call.
#
#   pwsh -File argv_text.ps1 LOADER_PS1

# Arguments come from $args, never param(): -File reads an argument that
# starts with `-` (an option name) as a parameter name.
$Loader = $args[0]

$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Loader, [ref]$null, [ref]$null
)
$helper = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq '_tdd_argv_text'
}, $true)
if (-not $helper) {
    [Console]::Error.WriteLine("_tdd_argv_text is gone from $Loader")
    exit 1
}
. ([scriptblock]::Create($helper.Extent.Text))

function probe {
    $a = @(_tdd_argv_text $args)
    [Console]::Out.WriteLine("$($a.Count)|" + ($a -join '|'))
}

probe
probe x
probe --dirs a,b git 'two words' 1,2,3
