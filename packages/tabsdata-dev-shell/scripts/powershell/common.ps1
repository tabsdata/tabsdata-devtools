#
# Copyright 2026 Tabsdata Inc.
#

# common.ps1 -- what every PowerShell command dot-sources: the parts of
# docs/command-cli-guidelines.md that are the same for all of them. The twin of
# common.sh; edit both.
#
#   the common options      --help/-h, --verbose/-v, --format json|view
#   the help layout         argparse's, from a declaration (_tdd_help_text)
#   the event model         command + event (ok, error, warn, info, debug)
#                           + message [+ fields], one line each
#   the two renderings      json: one JSON object per line on stdout
#                           view: ok on stdout, the rest on stderr
#   the colours             ok green, error red, warn yellow, debug white,
#                           info plain -- both formats, only on a terminal
#   the failure log         <temp>/tdd-<command>-<stamp>-<pid>.log
#
# JSON is ConvertTo-Json's, and the layout engine is written out here, so this
# family needs no external binary at all: where the POSIX half declares `jq`
# and `awk` in common.bin-reqs.txt, there is no common.bin-reqs.txt beside this
# file. That is the only difference between the two halves' requirements.
#
# tdd-source.ps1 dot-sources this before any command file and exports its path
# as $env:_TDD_COMMON_PS1; a command file dot-sources it by that name so it is
# explicit about what it depends on. The guard makes that a no-op.
#
# PowerShell 7, on macOS, Linux and Windows alike. State that must outlive a
# function call is $global:, because a function's own assignments are local to
# it however the file was loaded.
#
# Status does NOT travel as a return value. In PowerShell everything a function
# writes to the success stream is its return value, so `return 1` beside an ok
# message would put a stray 1 in the caller's output -- and a caller assigning
# the result would swallow the message with it. Instead every command and every
# helper that can fail sets $_TDD_RC, and the dispatcher copies it to
# $LASTEXITCODE on the way out; the ok message is the one thing on the success
# stream, so `$x = tdd venv list` captures exactly what `$(tdd venv list)`
# captures in sh. A helper that emits nothing at all -- a pure predicate like
# _tdd_optval -- may still answer with $true/$false.

if ($global:_TDD_COMMON_LOADED) { return }
$global:_TDD_COMMON_LOADED = $true

# ---------------------------------------------------------------- options

# Start of every command: default format, not verbose, no help yet. $_TDD_CMD
# is set by the dispatcher to the command word; a group refines it to the
# subcommand (venv -> venv-create) so every event and the log say which.
function _tdd_cmd_reset {
    $global:_TDD_FORMAT = 'view'
    $global:_TDD_VERBOSE = $false
    $global:_TDD_HELP = $false
    $global:_TDD_CONSUMED = 0
    $global:_TDD_BAD_FORMAT = ''
    $global:_TDD_RC = 0
}

# Consume a common option at $Argv[$Index] (and the one after). Sets
# $_TDD_CONSUMED to how many arguments it took; returns $false when the
# argument is not a common option.
function _tdd_common_opt {
    param([string[]]$Argv, [int]$Index = 0)
    $arg = $Argv[$Index]
    switch -Regex ($arg) {
        '^(--help|-h)$' { $global:_TDD_HELP = $true; $global:_TDD_CONSUMED = 1; return $true }
        '^(--verbose|-v)$' { $global:_TDD_VERBOSE = $true; $global:_TDD_CONSUMED = 1; return $true }
        '^--format(=.*)?$' {
            if (-not (_tdd_optval $Argv $Index)) { $global:_TDD_OPTVAL = '' }
            if ($global:_TDD_OPTVAL -in @('json', 'view')) {
                $global:_TDD_FORMAT = $global:_TDD_OPTVAL
            } else {
                $global:_TDD_BAD_FORMAT = if ($global:_TDD_OPTVAL) { $global:_TDD_OPTVAL } else { '<missing>' }
            }
            return $true
        }
    }
    return $false
}

# Value of an option written `--opt value` or `--opt=value` at $Index, into
# $_TDD_OPTVAL; $_TDD_CONSUMED says how many arguments it took. Returns $false
# when the value is missing.
function _tdd_optval {
    param([string[]]$Argv, [int]$Index = 0)
    $arg = $Argv[$Index]
    if ($arg -match '^[^=]+=(.*)$') {
        $global:_TDD_OPTVAL = $Matches[1]
        $global:_TDD_CONSUMED = 1
        return $true
    }
    if ($Index + 1 -ge $Argv.Count) {
        $global:_TDD_OPTVAL = ''
        $global:_TDD_CONSUMED = 1
        return $false
    }
    $global:_TDD_OPTVAL = $Argv[$Index + 1]
    $global:_TDD_CONSUMED = 2
    return $true
}

# After parsing: the one common-option error that cannot be reported inline.
# The call site's shape is `_tdd_cmd_check; if (_tdd_failed) { return }`.
function _tdd_cmd_check {
    if ($global:_TDD_BAD_FORMAT) {
        _tdd_error "--format must be json or view, got $($global:_TDD_BAD_FORMAT)"
    }
}

# Whether the command has already failed. The one place $_TDD_RC is read, so a
# call site never has to know it is a number.
function _tdd_failed {
    return ($global:_TDD_RC -ne 0)
}

# ---------------------------------------------------------------- prompt

# TEXT coloured for the prompt. PowerShell's prompt is a function returning a
# string rather than a PS1 with escape-wrapping rules, so this is plain ANSI --
# there is no bash `\[ \]` or zsh `%{ %}` to emit, because there is nothing
# counting characters the way a POSIX shell's line editor does. Plain text
# under NO_COLOR. $Colour is red or green.
function _tdd_ps1_wrap {
    param([string]$Colour, [string]$Text)
    if ($env:NO_COLOR) { return $Text }
    $code = switch ($Colour) { 'red' { 31 } 'green' { 32 } default { 0 } }
    return "$([char]27)[${code}m$Text$([char]27)[0m"
}

# ---------------------------------------------------------------- help

# Render a command's --help in the layout argparse gives the Python tools --
# usage, description, `commands:`/`options:` tables with the help text at
# column 24 and wrapped to the terminal, epilog -- from a short declaration, so
# both halves of tdd read the same. The declaration is the POSIX half's, to the
# letter (see common.sh); what awk does there is done here in PowerShell, which
# is why this family needs no awk.
function _tdd_help_text {
    param([string]$Declaration)

    $width = if ($env:COLUMNS) { [int]$env:COLUMNS } else { 80 }
    $W = $width - 2
    if ($W -lt 40) { $W = 40 }
    $HC = 24

    # The colours the Python half paints (common.core.render.colorize_help): a
    # heading bold, a term -- what stands before a description -- cyan, and
    # nothing when stdout is not a terminal or NO_COLOR is set. Painted onto
    # finished lines, so no column moves.
    $bold = ''; $termcol = ''; $off = ''
    if ((-not [Console]::IsOutputRedirected) -and (-not $env:NO_COLOR)) {
        $esc = [char]27
        $bold = "$esc[1m"; $termcol = "$esc[36m"; $off = "$esc[0m"
    }

    function _paintline([string]$l) {
        if (-not $bold) { return $l }
        if ($l -match '^[a-z][a-z0-9 /_-]*:$') { return "$bold$l$off" }
        if ($l -match '^(usage|examples?):( |$)') {
            $m = $l.IndexOf(':') + 1
            return $bold + $l.Substring(0, $m) + $off + $l.Substring($m)
        }
        $m = [regex]::Match($l, '^  \* [^ ]')
        if (-not $m.Success) { $m = [regex]::Match($l, '^ {1,6}[^ ]') }
        if ($m.Success) {
            $start = $m.Index + $m.Length - 1
            $stop = $start
            while ($stop -lt $l.Length - 1 -and $l.Substring($stop + 1, [Math]::Min(2, $l.Length - $stop - 1)) -ne '  ') { $stop++ }
            if ($stop -lt $l.Length - 1) {
                return $l.Substring(0, $start) + $termcol + $l.Substring($start, $stop - $start + 1) + $off + $l.Substring($stop + 1)
            }
        }
        return $l
    }

    function _paint([string]$s) {
        if (-not $bold) { return $s }
        return (($s -split "`n" | ForEach-Object { _paintline $_ }) -join "`n")
    }

    function _wrap([string]$text, [string]$first, [string]$rest, [int]$w) {
        $words = $text -split ' +' | Where-Object { $_ -ne '' }
        $line = ''; $out = @(); $ind = $first
        foreach ($word in $words) {
            if ($line -eq '') { $line = $word }
            elseif ($ind.Length + $line.Length + 1 + $word.Length -le $w) { $line = "$line $word" }
            else { $out += "$ind$line"; $line = $word; $ind = $rest }
        }
        $out += "$ind$line"
        return ($out -join "`n")
    }

    # An entry: the term in a column $n wide, its help wrapped at $HC. `$Pre`
    # replaces the plain indent for an entry carrying a marker; it has to be
    # exactly $n wide so the names stay in one column whether or not they are
    # marked -- the marker sits in the margin, not in the name.
    function _indented([int]$n, [string]$term, [string]$help, [string]$pre = '') {
        if ($pre -eq '') { $pre = ' ' * $n }
        if ($help -eq '') { return (_paint "$pre$term") }
        if ($term.Length -le $HC - $n - 2) {
            $pad = $term.PadRight($HC - $n)
            return (_paint (_wrap $help "$pre$pad" (' ' * $HC) $W))
        }
        return "$pre$term`n" + (_wrap $help (' ' * $HC) (' ' * $HC) $W)
    }

    $common = @(
        (_indented 2 '--help, -h' 'show this help message and exit'),
        (_indented 2 '--verbose, -v' 'show debug events too'),
        (_indented 2 '--format {json,view}' 'json is JSON Lines, one event per line (default: view)')
    )

    $lines = $Declaration -split "`n"
    if ($lines.Count -gt 0 -and $lines[-1] -eq '') { $lines = $lines[0..($lines.Count - 2)] }
    $out = [System.Collections.Generic.List[string]]::new()

    # Everything up to the first blank line is the usage, verbatim.
    $i = 0
    while ($i -lt $lines.Count -and $lines[$i] -ne '') { $out.Add((_paint $lines[$i])); $i++ }

    # Blocks: a section with its entries, a preformatted block, a paragraph.
    $blocks = [System.Collections.Generic.List[object]]::new()
    $cur = $null; $gap = $true; $hasopts = $false; $lastsec = -1; $para = ''; $paragap = $true
    function _flushpara {
        if ($script:_tdd_para -ne '') {
            $blocks.Add(@{ type = 'para'; text = $script:_tdd_para; gap = $script:_tdd_paragap })
            $script:_tdd_para = ''
        }
    }
    # `para`/`paragap` live in the script scope so the local helper can clear
    # them; everything else is plain local state in this loop.
    $script:_tdd_para = ''; $script:_tdd_paragap = $true

    for (; $i -lt $lines.Count; $i++) {
        $l = $lines[$i]
        if ($l -eq '') { _flushpara; $gap = $true; continue }
        if ($l -match '^[a-z][a-z0-9 -]*:$') {
            _flushpara
            $cur = @{ type = 'sec'; text = $l; entries = [System.Collections.Generic.List[object]]::new() }
            $blocks.Add($cur); $lastsec = $blocks.Count - 1
            if ($l -eq 'options:') { $hasopts = $true }
            $gap = $false; continue
        }
        if ($null -ne $cur -and $l -match '^ ') {
            if ($l -match '^  [^ ]' -or $l -match '^    [^ ]') {
                # `  * name` is a four-column entry whose first two columns
                # hold the marker: same name column as `    name`.
                $mark = if ($l -match '^  \* [^ ]') { '  * ' } else { '' }
                $deep = ($mark -ne '' -or $l -match '^    [^ ]')
                $t = if ($deep) { $l.Substring(4) } else { $l.Substring(2) }
                $m = [regex]::Match($t, '  +')
                if ($m.Success) {
                    $term = $t.Substring(0, $m.Index)
                    $help = $t.Substring($m.Index + $m.Length)
                } else { $term = $t; $help = '' }
                $cur.entries.Add(@{ term = $term; help = $help; deep = $deep; mark = $mark })
            } elseif ($cur.entries.Count -gt 0) {
                $last = $cur.entries[$cur.entries.Count - 1]
                $stripped = $l -replace '^ +', ''
                $last.help = if ($last.help -eq '') { $stripped } else { "$($last.help) $stripped" }
            }
            $gap = $false; continue
        }
        $cur = $null
        if ($l -match '^    ') {
            _flushpara
            if ($blocks.Count -gt 0 -and $blocks[$blocks.Count - 1].type -eq 'pre') {
                $blocks[$blocks.Count - 1].text += $(if ($gap) { "`n`n" } else { "`n" }) + $l
            } else {
                $blocks.Add(@{ type = 'pre'; text = $l; gap = $gap })
            }
            $gap = $false; continue
        }
        $l = ($l -replace '^ +', '') -replace ' +$', ''
        if ($script:_tdd_para -eq '') { $script:_tdd_paragap = $gap }
        $script:_tdd_para = if ($script:_tdd_para -eq '') { $l } else { "$($script:_tdd_para) $l" }
        $gap = $false
    }
    _flushpara

    # `options:` is created where argparse puts it -- after the last section,
    # or after the description when there is none -- so no command repeats the
    # three options every command shares.
    $optafter = if ($hasopts) { -2 } elseif ($lastsec -ge 0) { $lastsec } elseif ($blocks.Count -gt 0) { 0 } else { -1 }
    if ($optafter -eq -1) {
        $out.Add(''); $out.Add((_paint 'options:')); $common | ForEach-Object { $out.Add($_) }
    }
    for ($b = 0; $b -lt $blocks.Count; $b++) {
        $block = $blocks[$b]
        if ($block.type -eq 'sec') {
            $out.Add(''); $out.Add((_paint $block.text))
            if ($block.text -eq 'options:') { $common | ForEach-Object { $out.Add($_) } }
            foreach ($e in $block.entries) {
                if ($e.deep) { $out.Add((_indented 4 $e.term $e.help $e.mark)) }
                else { $out.Add((_indented 2 $e.term $e.help)) }
            }
        } else {
            if ($block.gap) { $out.Add('') }
            if ($block.type -eq 'para') { $out.Add((_wrap $block.text '' '' $W)) }
            else { $out.Add((_paint $block.text)) }
        }
        if ($b -eq $optafter) {
            $out.Add(''); $out.Add((_paint 'options:')); $common | ForEach-Object { $out.Add($_) }
        }
    }
    # Printed, never returned as data: a help page is what argparse prints, and
    # [Console] keeps it out of the pipeline the way the POSIX half keeps it
    # out of a $(...) capture.
    [Console]::Out.WriteLine(($out -join "`n"))
}

# ---------------------------------------------------------------- rendering

# A string as JSON text, without the surrounding quotes -- for callers that
# assemble a message by hand. ConvertTo-Json quotes and escapes it.
function _tdd_json_str {
    param([string]$Value)
    $json = $Value | ConvertTo-Json -Compress
    return $json.Substring(1, $json.Length - 2)
}

# ANSI colour for an event kind, or nothing. $Tty is whether the target stream
# is a terminal -- decided by the caller, because which stream an event goes to
# depends on the format. NO_COLOR wins.
function _tdd_color {
    param([string]$Kind, [bool]$Tty)
    if ($env:NO_COLOR -or -not $Tty) { return '' }
    $esc = [char]27
    switch ($Kind) {
        'ok' { "$esc[32m" }
        'error' { "$esc[31m" }
        'warn' { "$esc[33m" }
        'debug' { "$esc[37m" }
        # Not event kinds: paints for a command that colours rows inside its
        # ok message (`config --show`: green = built-in default, blue = what
        # the file sets, white = the built-in named beside it). The Python half
        # paints with the same six codes (render.PAINTS). Blue is a 256-colour
        # entry, not palette 34/94: themes remap the 16 palette colours but
        # leave the cube alone, so 38;5;33 is the same azure everywhere.
        'green' { "$esc[32m" }
        'white' { "$esc[37m" }
        'blue' { "$esc[38;5;33m" }
        'yellow' { "$esc[33m" }
        'red' { "$esc[31m" }
        'magenta' { "$esc[35m" }
        default { '' }
    }
}

function _tdd_color_end {
    param([string]$Kind, [bool]$Tty)
    if ($env:NO_COLOR -or -not $Tty) { return '' }
    if ($Kind -in @('ok', 'error', 'warn', 'debug', 'green', 'white', 'blue', 'yellow', 'red', 'magenta')) {
        return "$([char]27)[0m"
    }
    return ''
}

# One event. $Kind, $Message, $Fields (a hashtable, may be empty). json: a line
# on stdout for every kind. view: ok on stdout, the rest on stderr. Both
# coloured by kind when that stream is a terminal.
#
# The ok of a view goes through Write-Output rather than [Console], so
# `$x = tdd venv list` captures the result the way `$(tdd venv list)` does in
# sh; everything else is written to the real stderr, which keeps PowerShell's
# error records -- and their stack traces -- out of a command's output.
function _tdd_emit {
    param([string]$Kind, [string]$Message, [System.Collections.IDictionary]$Fields)
    $tty1 = -not [Console]::IsOutputRedirected
    $tty2 = -not [Console]::IsErrorRedirected
    if ($global:_TDD_FORMAT -eq 'json') {
        $obj = [ordered]@{ command = $global:_TDD_CMD; event = $Kind; message = $Message }
        if ($Fields) { foreach ($k in $Fields.Keys) { $obj[$k] = $Fields[$k] } }
        $line = $obj | ConvertTo-Json -Compress -Depth 12
        Write-Output ((_tdd_color $Kind $tty1) + $line + (_tdd_color_end $Kind $tty1))
    } elseif ($Kind -eq 'ok') {
        # A message that paints itself -- a help listing -- sets
        # $_TDD_PRECOLORED, so one colour over the whole of it does not undo
        # its own. The Python half does the same by looking for an escape.
        if ($global:_TDD_PRECOLORED) { Write-Output $Message }
        else { Write-Output ((_tdd_color ok $tty1) + $Message + (_tdd_color_end ok $tty1)) }
    } else {
        [Console]::Error.WriteLine((_tdd_color $Kind $tty2) + $Message + (_tdd_color_end $Kind $tty2))
    }
}

# The outcome; exactly one, last. Leaves $_TDD_RC at 0.
function _tdd_ok {
    param([string]$Message, [System.Collections.IDictionary]$Fields)
    _tdd_emit ok $Message $Fields
    $global:_TDD_RC = 0
}

# Something worth knowing while working; always shown.
function _tdd_info {
    param([string]$Message, [System.Collections.IDictionary]$Fields)
    _tdd_emit info $Message $Fields
}

function _tdd_warn {
    param([string]$Message, [System.Collections.IDictionary]$Fields)
    _tdd_emit warn $Message $Fields
}

# Detail for --verbose only.
function _tdd_debug {
    param([string]$Message, [System.Collections.IDictionary]$Fields)
    if (-not $global:_TDD_VERBOSE) { return }
    _tdd_emit debug $Message $Fields
}

# A command line for the eyes and for the log, with the value of any option
# that carries a secret replaced: `tdd env set --crypto --value KEY` must not
# write the key into a world-readable log or echo it back. Both spellings,
# `--opt value` and `--opt=value`.
function _tdd_mask_argv {
    param([string]$Line)
    return ($Line -replace '(--(value|password|secret|token|key))([= ])[^ ]*', '$1$3****')
}

# Where the failure log goes. /tmp when there is one, so the path is the one
# docs/command-cli-guidelines.md names and the two halves agree; the platform's
# own temp directory otherwise, which is what Windows has.
function _tdd_temp_dir {
    if (Test-Path -LiteralPath '/tmp' -PathType Container) { return '/tmp' }
    return [System.IO.Path]::GetTempPath().TrimEnd([System.IO.Path]::DirectorySeparatorChar)
}

# The failure; exactly one, last, then return 1. Writes the log the guidelines
# require -- what the terminal did not show -- and points at it: view prints
# `details: <path>` after the message, json carries it as "log".
function _tdd_error {
    param([string]$Message, [string]$Details = '')
    $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
    $cmd = if ($global:_TDD_CMD) { $global:_TDD_CMD } else { 'shell' }
    $logf = Join-Path (_tdd_temp_dir) "tdd-$cmd-$stamp-$PID.log"
    $argv = if ($global:_TDD_ARGV) { $global:_TDD_ARGV } else { $cmd }
    $body = @(
        "command: tdd $(_tdd_mask_argv $argv)",
        "cwd:     $((Get-Location).Path)",
        "TDD_DIR: $($env:TDD_DIR)",
        "version: $(if (Test-Path -LiteralPath (Join-Path $env:TDD_DIR 'VERSION')) { (Get-Content -LiteralPath (Join-Path $env:TDD_DIR 'VERSION') -Raw).Trim() })",
        "time:    $(Get-Date)",
        "error:   $Message"
    )
    if ($Details) { $body += @('', 'details:', $Details) }
    try { Set-Content -LiteralPath $logf -Value ($body -join "`n") -Encoding utf8 } catch { }
    _tdd_emit error $Message @{ log = $logf }
    if ($global:_TDD_FORMAT -ne 'json') {
        $tty2 = -not [Console]::IsErrorRedirected
        [Console]::Error.WriteLine((_tdd_color error $tty2) + "details: $logf" + (_tdd_color_end error $tty2))
    }
    $global:_TDD_RC = 1
}

# ---------------------------------------------------------------- config
# `tdd <command> config [--show | --default | --create [--force]]`, the same
# action every Python tool gets from common.core.config -- here for the
# PowerShell half. The template is rendered from the command's own
# tdd_defaults_<name> declarations (`sub|--option|value` lines), so it cannot
# drift from the options; what the file sets now comes back from `tdd-exe
# --defaults-doc`, which has the TOML parser this side lacks.

# The document `--create` writes and `--default` prints: the [options] tables
# and nothing else, plus whatever the file already sets. No option is listed at
# its built-in value -- that would put today's defaults in the reader's copy,
# where a later change to one would never reach them; `config --show` is what
# lists them. Whatever tables the file keeps of its own are carried across,
# which is what makes `--create --force` a rewrite of the template rather than
# a loss of the reader's file. The twin of common.core.config.render_doc and of
# _tdd_config_template in common.sh -- edit all three.
function _tdd_config_template {
    param([string]$Command, [switch]$Current)
    $file = Join-Path $env:TDD_DIR "$Command.toml"
    $doc = $null
    if ($Current) {
        $raw = tdd-exe --dir $env:TDD_DIR --defaults-doc $Command 2>$null
        if ($raw) { $doc = $raw | ConvertFrom-Json }
    }
    $out = [System.Collections.Generic.List[string]]::new()
    $out.Add('#')
    $out.Add('# Copyright 2026 Tabsdata Inc.')
    $out.Add('#')
    $out.Add('')
    $out.Add('# Each subcommand may have an [options.<SUBCOMMAND>] table setting user')
    $out.Add('# defaults: key is the option, value is its value, strings in double quotes.')
    $out.Add('')
    $out.Add('[options]')
    foreach ($row in @('-|--format|view', '-|--verbose|false')) {
        $line = _tdd_config_line $doc $row
        if ($line) { $out.Add($line) }
    }
    $last = '-'
    foreach ($row in (_tdd_defaults_of $Command | Sort-Object { ($_ -split '\|')[0] })) {
        $parts = $row -split '\|'
        if (-not $parts[1]) { continue }
        if ($parts[0] -ne $last) {
            if ($parts[0] -notin @('-', '')) { $out.Add(''); $out.Add("[options.$($parts[0])]") }
            $last = $parts[0]
        }
        $line = _tdd_config_line $doc $row
        if ($line) { $out.Add($line) }
    }
    # What the command (or the reader) keeps of its own: every table that is
    # not an [options] one, verbatim -- comments and all.
    if ($Current -and (Test-Path -LiteralPath $file)) {
        $keep = $false
        $kept = foreach ($line in (Get-Content -LiteralPath $file)) {
            if ($line -match '^\[') { $keep = ($line -notmatch '^\[options[\].]') }
            if ($keep) { $line }
        }
        if ($kept) { $out.Add(''); $kept | ForEach-Object { $out.Add($_) } }
    }
    return (($out -join "`n") + "`n")
}

# The `sub|--option|value` declarations of a command, or nothing.
function _tdd_defaults_of {
    param([string]$Command)
    $fn = "tdd_defaults_$Command"
    if (Get-Command -Name $fn -CommandType Function -ErrorAction SilentlyContinue) {
        return @(& $fn)
    }
    return @()
}

# One line of the template: `key = value` when the file sets it, nothing at all
# otherwise -- the built-in default is not written down.
function _tdd_config_line {
    param($Doc, [string]$Row)
    $parts = $Row -split '\|'
    $key = _tdd_config_key $parts[1]
    $set = _tdd_config_set $Doc $parts[0] $key
    if ($null -eq $set) { return '' }
    return "$key = $(_tdd_config_toml $set)"
}

# What <command>.toml sets for an option now, or $null.
function _tdd_config_set {
    param($Doc, [string]$Sub, [string]$Key)
    if (-not $Doc) { return $null }
    $table = if ($Sub -in @('-', '')) { '' } else { $Sub }
    $options = $Doc.options
    if (-not $options) { return $null }
    $inner = $options.PSObject.Properties[$table]
    if (-not $inner -or -not $inner.Value) { return $null }
    $prop = $inner.Value.PSObject.Properties[$Key]
    if (-not $prop) { return $null }
    $value = $prop.Value
    if ($value -is [bool]) { return $(if ($value) { 'true' } else { 'false' }) }
    return [string]$value
}

# `--type` -> `type`: a TOML key is the option's dest, as on the Python side.
function _tdd_config_key {
    param([string]$Option)
    return ($Option -replace '^--', '') -replace '-', '_'
}

# A built-in default as a TOML value: true/false and numbers bare, the rest
# quoted; an empty declaration means "no default", shown as an empty string.
function _tdd_config_toml {
    param([string]$Value)
    if ($Value -in @('true', 'false')) { return $Value }
    if ($Value -ne '' -and $Value -match '^[0-9]+$') { return $Value }
    return '"' + $Value + '"'
}

function _tdd_config_action {
    param([string]$Command, [string[]]$Argv)
    $what = 'show'
    $force = $false
    for ($i = 0; $i -lt $Argv.Count; ) {
        switch ($Argv[$i]) {
            '--show' { $what = 'show'; $i++; continue }
            '--default' { $what = 'default'; $i++; continue }
            '--create' { $what = 'create'; $i++; continue }
            '--force' { $force = $true; $i++; continue }
            '-f' { $force = $true; $i++; continue }
            default {
                if (-not (_tdd_common_opt $Argv $i)) {
                    _tdd_error "unknown option: $($Argv[$i]) (see --help)"
                    return
                }
                $i += $global:_TDD_CONSUMED
            }
        }
    }
    if ($global:_TDD_HELP) { _tdd_config_help $Command; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    $file = Join-Path $env:TDD_DIR "$Command.toml"
    switch ($what) {
        'default' {
            _tdd_ok (_tdd_config_template $Command).TrimEnd("`n") ([ordered]@{ config = $file; action = 'default' })
            return
        }
        'create' {
            if ((Test-Path -LiteralPath $file) -and -not $force) {
                _tdd_error "$file already exists; --force overwrites it"
                return
            }
            # Write and replace: an interrupted write leaves the previous file,
            # never half a config.
            $tmp = Join-Path $env:TDD_DIR ".$Command.toml.$PID.tmp"
            try {
                if (-not (Test-Path -LiteralPath $env:TDD_DIR)) {
                    New-Item -ItemType Directory -Path $env:TDD_DIR -Force | Out-Null
                }
                $body = if (Test-Path -LiteralPath $file) {
                    _tdd_config_template $Command -Current
                } else {
                    _tdd_config_template $Command
                }
                Set-Content -LiteralPath $tmp -Value $body -NoNewline -Encoding utf8
                Move-Item -LiteralPath $tmp -Destination $file -Force
            } catch {
                Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
                _tdd_error "cannot write $file" "$_"
                return
            }
            _tdd_ok "wrote $file" ([ordered]@{ config = $file; action = 'create' })
            return
        }
        default { _tdd_config_show $Command }
    }
}

# What the options resolve to now: a value at its built-in default in green, a
# value the file sets in blue with that built-in named in white beside it. The
# twin of common.core.config.show -- edit both. The file is read by tdd-exe,
# which has the TOML parser this side lacks.
function _tdd_config_show {
    param([string]$Command)
    $file = Join-Path $env:TDD_DIR "$Command.toml"
    $doc = $null
    $raw = tdd-exe --dir $env:TDD_DIR --defaults-doc $Command 2>$null
    if ($raw) { $doc = $raw | ConvertFrom-Json }
    $tty = -not [Console]::IsOutputRedirected
    $green = _tdd_color green $tty
    $blue = _tdd_color blue $tty
    $white = _tdd_color white $tty
    $off = _tdd_color_end green $tty   # every paint ends the same
    $rows = [System.Collections.Generic.List[string]]::new()
    $suffix = if (Test-Path -LiteralPath $file) { '' } else { '  (no file yet)' }
    $rows.Add("$green$file$suffix$off")
    $changed = [ordered]@{}
    $last = $null
    $all = @('-|--format|view', '-|--verbose|false') + (_tdd_defaults_of $Command)
    foreach ($row in ($all | Sort-Object { ($_ -split '\|')[0] })) {
        $parts = $row -split '\|'
        if (-not $parts[1]) { continue }
        if ($parts[0] -ne $last) {
            $header = if ($parts[0] -in @('-', '')) { '[options]' } else { "[options.$($parts[0])]" }
            $rows.Add('')
            $rows.Add("$green$header$off")
            $last = $parts[0]
        }
        $key = _tdd_config_key $parts[1]
        $set = _tdd_config_set $doc $parts[0] $key
        if ($null -ne $set) {
            # The built-in is named even when the file sets exactly that: the
            # paint says who is responsible for the value, and the parenthesis
            # what it would be without the line.
            $rows.Add("  $blue$key = $(_tdd_config_toml $set)$off   $white(built in default: $(_tdd_config_toml $parts[2]))$off")
            $changed[$key] = $set
        } else {
            $rows.Add("  $green$key = $(_tdd_config_toml $parts[2])$off")
        }
    }
    $global:_TDD_PRECOLORED = $true
    _tdd_ok ($rows -join "`n") @{ config = $file; action = 'show'; changed = $changed }
    $global:_TDD_PRECOLORED = $false
}

function _tdd_config_help {
    param([string]$Command)
    _tdd_help_text @"
usage: tdd $Command config [--show | --default | --create [--force]]

The config file of ``tdd $Command``: `$TDD_DIR/$Command.toml. Its [options] table holds what
this command's options default to ([options.ACTION] for one action); typed
options always win. Whatever else the command keeps lives in the same file.

options:
  --show       what the options resolve to now; what this file sets is
               highlighted, with the built-in default beside it (default)
  --default    print the default config, the document --create would write
  --create     write the default config; refuses when the file exists
  --force, -f  --create: overwrite an existing file

example: tdd $Command config --create && tdd $Command config --show
"@
}
