#
# Copyright 2026 Tabsdata Inc.
#
# Parse every file named with PowerShell's own parser; on the first error,
# print `FILE : ERROR` and exit 1.
#
#   pwsh -File parse.ps1 FILE...

foreach ($file in $args) {
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $file, [ref]$null, [ref]$errors
    ) | Out-Null
    if ($errors) {
        [Console]::Out.WriteLine("$file : $($errors[0])")
        exit 1
    }
}
