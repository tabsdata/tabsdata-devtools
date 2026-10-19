#
# Copyright 2026 Tabsdata Inc.
#
# Evaluate exported lines in this session, as `... | Invoke-Expression` does,
# and print what each named variable now holds, as one JSON object.
#
#   pwsh -File eval_lines.ps1 LINES_FILE NAME...

# Arguments come from $args, never param(): -File reads an argument that
# starts with `-` (an option name) as a parameter name.
$File = $args[0]
$Names = $args[1..($args.Count - 1)]

Get-Content -LiteralPath $File -Raw | Invoke-Expression
$seen = [ordered]@{}
foreach ($name in $Names) {
    $seen[$name] = [Environment]::GetEnvironmentVariable($name)
}
[Console]::Out.WriteLine(($seen | ConvertTo-Json -Compress))
