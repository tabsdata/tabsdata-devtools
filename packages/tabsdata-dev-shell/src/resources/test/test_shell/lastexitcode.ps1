#
# Copyright 2026 Tabsdata Inc.
#
# Load the loader's three public entry points (tdd-exe, tdd-fn, tdd) alone --
# found with PowerShell's parser, so nothing else of the loader runs -- over
# stub bodies that set $_TDD_RC to their first argument, and show what each
# call passed through and what $LASTEXITCODE said after it: `COUNT|ARG|...`
# then `rc=N`. An argument that arrives as an array shows as [a,b].
#
#   pwsh -File lastexitcode.ps1 LOADER_PS1

# Arguments come from $args, never param(): -File reads an argument that
# starts with `-` (an option name) as a parameter name.
$Loader = $args[0]
$EntryPoints = 'tdd-exe', 'tdd-fn', 'tdd'

$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $Loader, [ref]$null, [ref]$null
)
foreach ($name in $EntryPoints) {
    $wrapper = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if (-not $wrapper) {
        [Console]::Error.WriteLine("$name is gone from $Loader")
        exit 1
    }
    . ([scriptblock]::Create($wrapper.Extent.Text))
}

function Stub {
    $global:_TDD_RC = [int]$args[0]
    $shown = $args | ForEach-Object {
        if ($_ -is [array]) { '[' + ($_ -join ',') + ']' } else { $_ }
    }
    [Console]::Out.WriteLine("$($args.Count)|" + ($shown -join '|'))
}
foreach ($body in '_tdd_body_tdd_exe', '_tdd_body_tdd_fn', '_tdd_body_tdd') {
    Set-Item -Path "function:$body" -Value ${function:Stub}
}

foreach ($entry in $EntryPoints) {
    & $entry 3 x
    [Console]::Out.WriteLine("rc=$LASTEXITCODE")
    & $entry 0 --dirs a,b
    [Console]::Out.WriteLine("rc=$LASTEXITCODE")
}
