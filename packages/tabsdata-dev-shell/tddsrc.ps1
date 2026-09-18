#
# Copyright 2026 Tabsdata Inc.
#

# tddsrc.ps1 -- defines the `tdd` function for PowerShell.
#
#     . ~/.tdd/tdd-source.ps1
#
# Installed to <TDD_DIR>/tdd-source.ps1 by `tdd-install`, with the dir baked in
# so that several tdd dirs can each carry a loader pointing at themselves. The
# twin of tddsrc.sh; edit both.
#
# Why a dot-sourced function at all: `tdd-exe` is a real executable and
# therefore can never change the calling session. Commands that must -- entering
# or leaving a toolset venv -- live as functions instead. `tdd` is the single
# front door over both.
#
# PowerShell 7, on macOS, Linux and Windows alike: a family is the shell the
# user is in, not the operating system they are on. Everything that differs
# between platforms -- where a venv keeps its executables, what the interpreter
# is called, which character separates PATH entries -- goes through the helpers
# at the top of this file and nowhere else.

# Locate ourselves rather than trusting a baked path: the whole point of the
# relocatable envs is that this tree can be moved, copied or unzipped anywhere,
# and a hardcoded TDD_DIR would defeat that on the first move. The baked value
# is only a fallback for a host that exposes no script path.
$_tdd_self = $PSCommandPath
if ($_tdd_self -and (Test-Path -LiteralPath $_tdd_self)) {
    $env:TDD_DIR = (Split-Path -Parent (Resolve-Path -LiteralPath $_tdd_self))
} elseif (-not $env:TDD_DIR) {
    $env:TDD_DIR = '__TDD_DIR__'
}
Remove-Variable -Name _tdd_self -ErrorAction SilentlyContinue

# Which shell family's requirements `tdd --reqs` should check: this one. The
# POSIX half needs jq and awk, and this one needs neither, so the answer
# depends on who is asking.
$env:_TDD_SHELL_FAMILY = 'powershell'

# ---------------------------------------------------------------- platform

# A venv keeps its executables in bin/ on Unix and Scripts\ on Windows, and
# names the interpreter python or python.exe. Asked of the venv rather than of
# the platform, so a tdd dir built under WSL and opened from Windows -- or the
# reverse -- still finds what is actually there.
function _tdd_venv_bin {
    param([string]$Venv)
    foreach ($leaf in @('bin', 'Scripts')) {
        $candidate = Join-Path $Venv $leaf
        if (Test-Path -LiteralPath $candidate -PathType Container) { return $candidate }
    }
    return (Join-Path $Venv 'bin')
}

# The full path of a program inside a venv, with or without .exe, or $null.
function _tdd_venv_exe {
    param([string]$Venv, [string]$Name)
    $bin = _tdd_venv_bin $Venv
    foreach ($suffix in @('', '.exe')) {
        $candidate = Join-Path $bin "$Name$suffix"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function _tdd_shells_python {
    return (_tdd_venv_exe (Join-Path (Join-Path $env:TDD_DIR 'tdd-venvs') 'shells') 'python')
}

# Where the command files of this family live, or $null. Asked of the shell
# env's own Python, so the answer follows a moved or reinstalled tdd dir rather
# than a path written down here.
function _tdd_scripts_dir {
    $python = _tdd_shells_python
    if (-not $python) { return $null }
    $scripts = & $python -c 'from tabsdata_dev.shell import scripts_dir, POWERSHELL; print(scripts_dir(POWERSHELL))' 2>$null
    if (-not $scripts -or -not (Test-Path -LiteralPath $scripts -PathType Container)) { return $null }
    return $scripts
}

# EVERYTHING BELOW IS DOT-SOURCED AT THIS FILE'S TOP LEVEL, AND HAS TO BE.
# PowerShell dot-sources into the *current* scope, so a `. $file` inside a
# function defines that file's functions in the function -- and they are gone
# the moment it returns. (Only a file that says `function global:` survives,
# which is why a venv's own activate.ps1 can be sourced from anywhere and this
# cannot.) The POSIX half is free to load inside `_tdd_locate_common`; here the
# load is this file's own business, and the file is what the user dot-sources.
$_tdd_scripts = _tdd_scripts_dir
if (-not $_tdd_scripts) {
    [Console]::Error.WriteLine("tdd: no shell env at $(Join-Path $env:TDD_DIR 'tdd-venvs/shells'); run tdd-install")
} else {
    $env:_TDD_COMMON_PS1 = Join-Path $_tdd_scripts 'common.ps1'
    $global:_TDD_COMMON_DIR = $env:TDD_DIR
    # Re-sourcing must reload everything -- that is how a session picks up a
    # reinstall. common.ps1 guards against being loaded twice within one load
    # (each command file dot-sources it by name); this file owns the load, so
    # it lifts the guard first.
    $global:_TDD_COMMON_LOADED = $false
    . $env:_TDD_COMMON_PS1
}

# tdd-exe lives in its own venv inside the tdd dir, so nothing needs to be
# installed globally and no venv has to be active for `tdd` to work. Wrapping
# it as a function keeps that env's other binaries off PATH.
function tdd-exe {
    $venv = Join-Path (Join-Path $env:TDD_DIR 'tdd-venvs') 'tdd'
    $exe = _tdd_venv_exe $venv 'tdd-exe'
    if (-not $exe) {
        $global:_TDD_CMD = 'tdd'
        _tdd_error "no tdd-exe env at $venv; run tdd-install"
        return
    }
    # The envs are relocatable but their interpreter is not inside the tree:
    # bin/python points at the uv-managed Python by absolute path. If that is
    # gone -- a tdd dir unzipped on another machine, or a removed uv Python --
    # tdd-exe cannot even start, so no Python-side check could ever report it.
    if (-not (_tdd_venv_exe $venv 'python')) {
        $global:_TDD_CMD = 'tdd'
        _tdd_error "the interpreter for $venv is unreachable: this tdd dir was built for a different machine or its uv Python was removed; rebuild here with tdd-install, or restore it with: uv python install"
        return
    }
    & $exe @args
    $global:_TDD_RC = $LASTEXITCODE
}

# Registry of loaded commands, one object per command: Name, Summary, Reqs.
# Reqs is the content of the bin-reqs.txt beside the file that registered the
# command -- the loader fills $_TDD_FN_REQS before dot-sourcing each file.
$global:TDD_FN_COMMANDS = [System.Collections.Generic.List[object]]::new()
$global:_TDD_FN_REQS = @()

# Spelled exactly as the POSIX half spells it -- `tdd_fn_register venv "..."` --
# so one regex in the generator reads both families and can hold them to the
# same commands and the same summaries.
function tdd_fn_register {
    param([string]$Name, [string]$Summary)
    $global:TDD_FN_COMMANDS.Add([pscustomobject]@{
            Name    = $Name
            Summary = $Summary
            Reqs    = @($global:_TDD_FN_REQS)
        })
}

# ---------------------------------------------------------------- loading

# The binaries a command file's commands declare: what the family's shared
# helpers need (nothing, here -- this family builds its own JSON and lays out
# its own help, so there is no common.bin-reqs.txt, which is the whole
# difference between the two families' requirements) plus the file's own
# <file>.bin-reqs.txt. Checked when a command runs, never at load: loading must
# stay cheap and must never fail.
function _tdd_file_reqs {
    param([string]$Scripts, [string]$Stem)
    $common = @()
    $commonFile = Join-Path $Scripts 'common.bin-reqs.txt'
    if (Test-Path -LiteralPath $commonFile) { $common = _tdd_read_reqs $commonFile }
    $own = @()
    $ownFile = Join-Path $Scripts "$Stem.bin-reqs.txt"
    if (Test-Path -LiteralPath $ownFile) { $own = _tdd_read_reqs $ownFile }
    return @($common) + @($own | Where-Object { $_ -notin $common })
}

# The bare names in a bin-reqs.txt.
function _tdd_read_reqs {
    param([string]$Path)
    return @(Get-Content -LiteralPath $Path |
        ForEach-Object { ($_ -split '#', 2)[0].Trim() } |
        Where-Object { $_ -ne '' })
}

function _tdd_fn_get {
    param([string]$Name)
    return ($global:TDD_FN_COMMANDS | Where-Object { $_.Name -eq $Name } | Select-Object -First 1)
}

function _tdd_fn_has {
    param([string]$Name)
    return ($null -ne (_tdd_fn_get $Name))
}

# Refuse to run a command whose declared binaries are not all on PATH. Failing
# up front with the whole list beats failing halfway through with a bare
# "command not found" -- and it is what makes the declaration honest.
function _tdd_fn_check_reqs {
    param([string]$Name, [string[]]$Argv)
    # Help never depends on what the machine has installed.
    foreach ($a in $Argv) { if ($a -in @('--help', '-h')) { return $true } }
    $entry = _tdd_fn_get $Name
    $missing = @()
    foreach ($binary in $entry.Reqs) {
        $found = Get-Command -Name $binary -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $found) { $missing += "  $binary  not found"; continue }
        # A pyenv shim stands in for every program any pyenv version ever had;
        # only `pyenv which` says whether the CURRENT one provides it.
        if ($found.Source -match '[\\/]shims[\\/]') {
            $isPyenv = $false
            try { $isPyenv = (Select-String -LiteralPath $found.Source -Pattern 'pyenv' -Quiet) } catch { }
            if ($isPyenv -and (Get-Command pyenv -ErrorAction SilentlyContinue)) {
                $real = (& pyenv which $binary 2>$null)
                if (-not $real -or $real -eq $found.Source -or $real -match '[\\/]shims[\\/]') {
                    $missing += "  $binary  pyenv shim at $($found.Source) is not wired (pyenv which $binary finds no program)"
                }
            }
        }
    }
    if ($missing.Count -gt 0) {
        _tdd_cmd_reset
        $global:_TDD_CMD = $Name
        $n = $missing.Count
        $plural = if ($n -eq 1) { 'y that is' } else { 'ies that are' }
        $them = if ($n -eq 1) { 'it' } else { 'them' }
        _tdd_error ("$Name needs $n required binar$plural not on PATH:`n" + ($missing -join "`n") +
            "`ninstall $them; ``tdd --reqs $Name`` lists every requirement")
        return $false
    }
    return $true
}

# ---------------------------------------------------------------- help

# Commands from both halves, merged and sorted alphabetically, as one ok event.
# view: the usage plus a listing, shell commands marked with * because they
# behave differently -- they can change this session. json: a "commands" array.
function _tdd_help {
    $global:_TDD_CMD = 'tdd'
    $rows = _tdd_help_rows
    if ($global:_TDD_FORMAT -eq 'json') {
        _tdd_ok "$($rows.Count) commands" ([ordered]@{
                tdd_dir  = $env:TDD_DIR
                options  = @('--dir', '--format', '--verbose', '--help', '--version', '--reqs')
                commands = @($rows | ForEach-Object {
                        [ordered]@{ name = $_.Name; shell = $_.Shell; summary = $_.Summary; kind = $_.Kind }
                    })
            })
        return
    }
    # Laid out and painted by `_tdd_help_text`, the engine every command's help
    # goes through -- which is what keeps the front door from looking like a
    # different program. It supplies the three options every command shares,
    # puts `options:` after the commands the way argparse does, wraps a long
    # summary to the terminal, and paints a heading bold and a term cyan.
    $listing = ($rows | ForEach-Object {
            $lead = if ($_.Shell) { '  * ' } else { '    ' }
            "$lead$($_.Name)  $($_.Summary)"
        }) -join "`n"
    _tdd_help_text @"
usage: tdd [--help] [--verbose] [--format {json,view}] [--dir TDD_PATH] [--version]
           [--reqs [TOOL]]
           SUBCOMMAND ...
       tdd --help full

the front door: run one of the tools, or one of the shell commands that change this session

positional arguments:
  SUBCOMMAND
$listing
  (a * marks a command that runs in this session, so that it can change it)

options:
  --dir TDD_PATH  the tdd dir to use (default: `$TDD_DIR, else ~/.tdd)
  --version, -V  the version stamped into that dir
  --reqs [TOOL]  report the external binaries every tool needs; exit 1 if one is missing
  --help full  this listing, and then the help of every command after it
  (--dir, --format and --verbose come before the command word)

TDD_DIR=$($env:TDD_DIR)
"@
}

# `tdd --help full`: this help, then every command's, in one pass -- what a
# reader wants when they are hunting for a command whose name they cannot
# remember, and what a reviewer wants when checking that the pages agree.
#
# A launcher is skipped, and says so. `tdd tdk -h` is not tdd's help to print: a
# launcher owns no options, so every argument, -h included, goes to the real
# program -- which needs a managed venv and answers for itself.
function _tdd_help_full {
    _tdd_help
    $launchers = @()
    $catalog = Join-Path $env:TDD_DIR 'catalog.json'
    if (Test-Path -LiteralPath $catalog) {
        $tools = (Get-Content -LiteralPath $catalog -Raw | ConvertFrom-Json).tools
        $launchers = @($tools.PSObject.Properties | Where-Object { $_.Value.launcher } | ForEach-Object { $_.Name })
    }
    $skipped = @()
    foreach ($row in (_tdd_help_rows)) {
        if ($row.Name -in $launchers) { $skipped += $row.Name; continue }
        # A separator in every format: a help page is what argparse prints, not
        # an event, so `--format json --help` has always been plain text and
        # there is no JSON here to keep clean.
        [Console]::Out.WriteLine("`n`n========== tdd $($row.Name) ==========`n")
        tdd $row.Name --help
    }
    if ($skipped.Count -gt 0) {
        [Console]::Out.WriteLine("`n`n(no tdd help for $($skipped -join ' '): a launcher hands every argument, -h included, to the program it runs)")
    }
}

# Rows as objects with Name, Shell, Summary, Kind, sorted case-insensitively.
function _tdd_help_rows {
    $rows = [System.Collections.Generic.List[object]]::new()
    foreach ($entry in $global:TDD_FN_COMMANDS) {
        $rows.Add([pscustomobject]@{
                Name = $entry.Name; Shell = $true; Summary = $entry.Summary; Kind = 'shell'
            })
    }
    $porcelain = & { tdd-exe --porcelain 2>$null }
    foreach ($line in @($porcelain)) {
        if (-not $line) { continue }
        $parts = $line -split '\|', 3
        if ($parts.Count -lt 3) { continue }
        $rows.Add([pscustomobject]@{
                Name = $parts[0]; Shell = $false; Summary = $parts[2]; Kind = $parts[1]
            })
    }
    return @($rows | Sort-Object { $_.Name.ToLowerInvariant() })
}

function _tdd_fn_help {
    $global:_TDD_CMD = 'tdd-fn'
    $rows = @(_tdd_help_rows | Where-Object { $_.Shell })
    if ($global:_TDD_FORMAT -eq 'json') {
        _tdd_ok "$($rows.Count) shell commands" ([ordered]@{
                commands = @($rows | ForEach-Object {
                        [ordered]@{ name = $_.Name; shell = $_.Shell; summary = $_.Summary; kind = $_.Kind }
                    })
            })
        return
    }
    $listing = ($rows | ForEach-Object { '  ' + $_.Name.PadRight(14) + ' ' + $_.Summary }) -join "`n"
    _tdd_ok "shell commands (run in this session):`n$listing"
}

# Merge the command's configured default options into the argument list, then
# say what it resolved to. The file is <tdd_dir>/<command>.toml ([options], and
# [options.<action>] for one action); the merge itself -- typed options win, the
# action's table wins over the command's -- is tdd-exe's job, so it is one
# testable piece of Python; this side only rebuilds the argument list and says
# what it resolved to. Sets $_TDD_RESOLVED and $_TDD_DEFAULTS_SRC. Returns
# 'applied', 'none' or 'invalid' (already reported).
function _tdd_apply_defaults {
    param([string[]]$Argv)
    $file = Join-Path $env:TDD_DIR "$($Argv[0]).toml"
    # No file, no work: the common case is not worth a subprocess.
    if (-not (Test-Path -LiteralPath $file)) { return 'none' }
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $out = & { tdd-exe --defaults @Argv 2>$errFile }
        if ($global:_TDD_RC -ne 0) {
            _tdd_cmd_reset
            $global:_TDD_CMD = $Argv[0]
            _tdd_error "invalid default options for $($Argv[0]) in $file" (Get-Content -LiteralPath $errFile -Raw)
            return 'invalid'
        }
    } finally {
        Remove-Item -LiteralPath $errFile -ErrorAction SilentlyContinue
    }
    $lines = @($out)
    if ($lines.Count -eq 0) { return 'none' }
    $global:_TDD_DEFAULTS_SRC = ($lines[0] -replace '^# ', '')
    $global:_TDD_RESOLVED = @($lines | Select-Object -Skip 1)
    return 'applied'
}

# ---------------------------------------------------------------- dispatch

# The shell half of the pair: the same role as tdd-exe, for loaded functions.
function tdd-fn {
    if ($args.Count -eq 0) {
        _tdd_cmd_reset
        _tdd_fn_help
        return
    }
    $argv = @($args | ForEach-Object { [string]$_ })
    if ($argv[0] -in @('-h', '--help', 'help', 'list')) {
        _tdd_cmd_reset
        _tdd_scan_common $argv
        _tdd_fn_help
        return
    }
    if (_tdd_fn_has $argv[0]) {
        $name = $argv[0]
        $rest = @($argv | Select-Object -Skip 1)
        if (-not (_tdd_fn_check_reqs $name $rest)) { return }
        # For every event and the failure log: the command word, and the
        # command line as typed. A group refines $_TDD_CMD to its subcommand.
        $global:_TDD_CMD = $name
        $global:_TDD_ARGV = (@($name) + $rest) -join ' '
        & "tddfn_$name" $rest
        return
    }
    _tdd_cmd_reset
    $global:_TDD_CMD = 'tdd-fn'
    _tdd_error "unknown shell command: $($argv[0]) (see tdd-fn help)"
}

# --format/--verbose wherever they appear among the arguments, into the
# renderer state; for the listings, whose options are not positional.
function _tdd_scan_common {
    param([string[]]$Argv)
    $prev = ''
    foreach ($a in $Argv) {
        switch ($a) {
            '--format=json' { $global:_TDD_FORMAT = 'json' }
            '--format=view' { $global:_TDD_FORMAT = 'view' }
            '--verbose' { $global:_TDD_VERBOSE = $true }
            '-v' { $global:_TDD_VERBOSE = $true }
            default {
                if ($a -in @('json', 'view') -and $prev -eq '--format') { $global:_TDD_FORMAT = $a }
            }
        }
        $prev = $a
    }
}

# The front door. Routes to tdd-fn when the command is a loaded one, and to
# tdd-exe otherwise, so a caller never has to know which half owns a command.
function tdd {
    _tdd_cmd_reset
    $global:_TDD_CMD = 'tdd'
    $dirArgs = @()
    # _TDD_TOOL is tdd-exe's word to the tool it execs, never meant for a
    # session: one set here would make every tool believe it is another.
    if ($null -ne $env:_TDD_TOOL) {
        _tdd_warn "_TDD_TOOL was set in this session ($($env:_TDD_TOOL)); it is tdd's private variable and is ignored"
        $env:_TDD_TOOL = $null
    }
    $argv = @($args | ForEach-Object { [string]$_ })
    # Leading options are tdd's own; --format/--verbose also travel on to the
    # command that runs, appended after its word, so `tdd --format json venv
    # list` and `tdd venv list --format json` are the same request.
    $pass = @()
    $i = 0
    while ($i -lt $argv.Count) {
        $a = $argv[$i]
        if ($a -eq '--dir') {
            $env:TDD_DIR = $argv[$i + 1]
            $dirArgs = @("--dir=$($argv[$i + 1])")
            $i += 2
        } elseif ($a -like '--dir=*') {
            $env:TDD_DIR = $a.Substring(6)
            $dirArgs = @($a)
            $i += 1
        } elseif ($a -eq '--format' -or $a -like '--format=*' -or $a -eq '--verbose' -or $a -eq '-v') {
            if (-not (_tdd_common_opt $argv $i)) { break }
            $pass = @("--format=$($global:_TDD_FORMAT)")
            if ($global:_TDD_VERBOSE) { $pass += '--verbose' }
            $i += $global:_TDD_CONSUMED
        } else { break }
    }
    $argv = @($argv | Select-Object -Skip $i)
    # A --dir pointing somewhere else changes where the tools and the catalog
    # come from, but not the helpers: they are already in this session and read
    # $TDD_DIR at call time, so they follow it on their own. Reloading them
    # from the other dir is what the POSIX half does and what this one cannot
    # -- a dot-source inside a function stays inside it -- and it would buy
    # only the other dir's *version* of the same helpers. What it cannot give
    # is that dir's command files, so say so rather than half-do it.
    if ($global:_TDD_COMMON_DIR -ne $env:TDD_DIR) {
        _tdd_warn "the commands loaded here came from $($global:_TDD_COMMON_DIR); to use the ones in $($env:TDD_DIR), dot-source $(Join-Path $env:TDD_DIR 'tdd-source.ps1')"
    }
    if ($global:_TDD_BAD_FORMAT) {
        _tdd_error "--format must be json or view, got $($global:_TDD_BAD_FORMAT)"
        return
    }

    if ($argv.Count -eq 0) { _tdd_help; return }

    if ($argv[0] -in @('-h', '--help', 'help')) {
        _tdd_scan_common $argv
        $topic = if ($argv.Count -gt 1) { $argv[1] } else { '' }
        switch ($topic) {
            '' { _tdd_help }
            'full' { _tdd_help_full }
            default { _tdd_error "unknown help topic: $topic (the only one is 'full')" }
        }
        return
    }
    if ($argv[0] -in @('-V', '--version', '--reqs')) {
        tdd-exe @dirArgs @pass @argv
        return
    }

    switch (_tdd_apply_defaults $argv) {
        'invalid' { return }
        'applied' {
            # The resolved lines are the arguments after the command word, so
            # put the word back in front.
            $word = $argv[0]
            $argv = @($word) + @($global:_TDD_RESOLVED)
            # Say what will run, as an info event of the command about to run,
            # in the format it will use.
            _tdd_cmd_reset
            $global:_TDD_CMD = $word
            if ($argv.Count -gt 1 -and $argv[1] -notlike '-*') { $global:_TDD_CMD = "$word-$($argv[1])" }
            $prev = ''
            foreach ($a in $argv) {
                if ($a -eq '--format=json' -or ($a -eq 'json' -and $prev -eq '--format')) {
                    $global:_TDD_FORMAT = 'json'
                }
                $prev = $a
            }
            _tdd_info "resolved: tdd $(_tdd_mask_argv ($argv -join ' '))" ([ordered]@{ defaults = $global:_TDD_DEFAULTS_SRC })
            Remove-Variable -Name _TDD_RESOLVED, _TDD_DEFAULTS_SRC -Scope Global -ErrorAction SilentlyContinue
        }
    }

    if (_tdd_fn_has $argv[0]) {
        tdd-fn @argv @pass
    } else {
        tdd-exe @dirArgs @argv @pass
    }
}

# ---------------------------------------------------------------- prompt

# A red `* ` in front of the prompt, so a session that has tdd loaded says so.
# PowerShell's prompt is a function, not a string, so the mark is applied by
# wrapping it: the original is kept and called, and a re-source restores it
# first rather than wrapping the wrapper -- which is how a reinstall is picked
# up without the mark stacking.
if ($global:_TDD_PROMPT_ORIGINAL) {
    Set-Item -Path function:global:prompt -Value $global:_TDD_PROMPT_ORIGINAL
}
$global:_TDD_PROMPT_ORIGINAL = (Get-Command prompt -CommandType Function -ErrorAction SilentlyContinue).ScriptBlock
if (-not $global:_TDD_PROMPT_ORIGINAL) {
    $global:_TDD_PROMPT_ORIGINAL = { "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) " }
}
$global:_TDD_PROMPT_MARK = (_tdd_ps1_wrap red '*') + ' '
function global:prompt {
    $global:_TDD_PROMPT_MARK + (& $global:_TDD_PROMPT_ORIGINAL)
}

# The command files, at top level for the reason given above. A command file
# defines `tddfn_<name>` and calls `tdd_fn_register`, and both have to land in
# the session the user is typing into.
if ($_tdd_scripts) {
    foreach ($_tdd_file in (Get-ChildItem -LiteralPath $_tdd_scripts -Filter '*.ps1' | Sort-Object Name)) {
        if ($_tdd_file.Name -eq 'common.ps1') { continue }
        $global:_TDD_FN_REQS = _tdd_file_reqs $_tdd_scripts $_tdd_file.BaseName
        . $_tdd_file.FullName
    }
    $global:_TDD_FN_REQS = @()
}
Remove-Variable -Name _tdd_scripts, _tdd_file -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- hello

# Interactive sessions only: a script that dot-sources this wants the function,
# not a greeting on its stdout.
if ([Environment]::UserInteractive -and -not [Console]::IsOutputRedirected) {
    $_tdd_version = ''
    $_tdd_version_file = Join-Path $env:TDD_DIR 'VERSION'
    if (Test-Path -LiteralPath $_tdd_version_file) {
        $_tdd_version = (Get-Content -LiteralPath $_tdd_version_file -Raw).Trim()
    }
    [Console]::Out.WriteLine("`ntdd $_tdd_version installed at $($env:TDD_DIR) -- tdd -h for help`n")
    Remove-Variable -Name _tdd_version, _tdd_version_file -ErrorAction SilentlyContinue
}
