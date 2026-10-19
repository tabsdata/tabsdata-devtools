#
# Copyright 2026 Tabsdata Inc.
#
# Dot-source an exported secrets file, as an operator on Windows does, and
# print what each named variable now holds, as one JSON object.
#
#   pwsh -File load_ps1.ps1 SECRETS_PS1 NAME...

# Arguments come from $args, never param(): -File reads an argument that
# starts with `-` (an option name) as a parameter name.
$File = $args[0]
$Names = $args[1..($args.Count - 1)]

. $File
$seen = [ordered]@{}
foreach ($name in $Names) {
    $seen[$name] = [Environment]::GetEnvironmentVariable($name)
}
[Console]::Out.WriteLine(($seen | ConvertTo-Json -Compress))
