#
# Copyright 2026 Tabsdata Inc.
#

if (-not $global:_TDD_COMMON_LOADED) { . $env:_TDD_COMMON_PS1 }

# Managed virtualenvs: created by pyenv, uv or conda, but all of them living
# under $TDD_DIR/managed-venvs/<type>/<name>, each with a <name>.json marker
# beside the type directories: the manager (type), the interpreter it runs
# (version and the base python it was built from), whether it is relocatable,
# when it was made. Every subcommand reads the marker to know which tool to
# drive, so the user never has to remember how a venv was made; `list` shows
# the rest. A marker from before the JSON (<name>.env, holding the type alone)
# is migrated on sight, the missing facts probed from the venv itself.
#
#     tdd venv create --name NAME [--type pyenv|uv|conda] [--python VERSION] [--relocatable]
#     tdd venv activate --name NAME
#     tdd venv deactivate [--force]
#     tdd venv delete (--name NAME | --all)
#     tdd venv list
#
# Activating and deactivating change this session, which is why the whole group
# is a shell command. The twin of venv.sh, behaviour for behaviour: the same
# options, the same events, the same JSON fields, so a consumer cannot tell
# which shell ran. Where this file differs it is because PowerShell left no
# choice, and the comment says so.
#
# A uv venv is built on a uv-managed interpreter only (--managed-python), never
# on whatever python happens to be on PATH, and is relocatable only when asked
# (--relocatable, uv's own flag; a pyenv or conda venv cannot be).
#
# Activation rules: the prompt shows (<type>/<python>/<name>), with /reloc
# appended for a relocatable venv; create ends in activation; activating while
# another managed venv is active switches to the new one; a venv that tdd did
# not activate (VIRTUAL_ENV, or a conda env other than base) blocks both --
# unless it lives under managed-venvs/<type>/<name> with its marker, in which
# case it is ours however it was entered and is adopted as the active one.
# deactivate leaves the managed venv; a venv tdd did not activate, or a stale
# record, is refused with a pointer to --force, which leaves it best effort
# from what the tool left in the environment (venv/uv, pyenv-virtualenv,
# conda) or drops the record. State lives in $env:_TDD_VENV (the name, and
# exported because the tdk/km/tdkserver launchers read it) and
# $global:_TDD_VENV_PROMPT (the prompt to restore).
#
# Status never travels as a return value here: a function's success-stream
# output IS its return value in PowerShell, and in --format json every event --
# info and debug included -- is written to that stream. So a function that can
# emit answers in $_TDD_RC (`_tdd_cmd_check; if (_tdd_failed) { return }`) and
# a function that returns data (a marker, a probe, a path) emits nothing at
# all. That split is why a few helpers are shaped differently from the sh half,
# each noted where it happens.

tdd_fn_register venv "create, activate, deactivate, delete or list managed venvs (pyenv, uv or conda)"

# Built-in option defaults: what `tdd venv config` writes as its template,
# and what `--show` compares against.
function tdd_defaults_venv {
    @('create|--type|pyenv', 'create|--python|3.12.13', 'create|--name|',
        'create|--force|false', 'create|--relocatable|false', 'deactivate|--force|false',
        'activate|--name|', 'delete|--name|', 'delete|--all|false')
}

function tddfn_venv {
    param([string[]]$Argv)
    if ($null -eq $Argv) { $Argv = @() }
    _tdd_cmd_reset
    $sub = if ($Argv.Count -gt 0) { $Argv[0] } else { '' }
    $rest = @($Argv | Select-Object -Skip 1)
    # -cin, not -in: sh's `case` matches exactly, and a group that answered to
    # `CREATE` in one shell and not in the other would be a difference a user
    # can feel. Same for every option and value compared below.
    if ($sub -ceq 'config') {
        $global:_TDD_CMD = 'venv-config'
        _tdd_config_action venv $rest
    } elseif ($sub -cin @('create', 'activate', 'deactivate', 'delete', 'list')) {
        $global:_TDD_CMD = "venv-$sub"
        & "_tdd_venv_$sub" $rest
    } elseif ($sub -cin @('--help', '-h')) {
        _tdd_venv_help
    } elseif ($sub -eq '') {
        _tdd_error "a subcommand is required: create, activate, deactivate, delete or list (see --help)"
    } else {
        _tdd_error "unknown subcommand: $sub (see --help)"
    }
    # A PowerShell function's own variables die with the call, so there is
    # nothing to unset here -- unlike a sourced sh function, whose temporaries
    # leak into the user's shell. Only what is deliberately global survives,
    # and _TDD_VENV_PREV is scratch: _TDD_VENV and _TDD_VENV_PROMPT are the
    # state, and they are meant to outlive the call.
    Remove-Variable -Name _TDD_VENV_PREV -Scope Global -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- the marker

function _tdd_venv_root {
    return (Join-Path $env:TDD_DIR 'managed-venvs')
}

# The marker of the managed venv NAME.
function _tdd_venv_marker {
    param([string]$Name)
    return (Join-Path (_tdd_venv_root) "$Name.json")
}

# Everything the marker of NAME records: Type, Python, PythonPath, Reloc (a
# bool) and Created; a fact the marker lacks is empty (a view shows it as ?).
# $null when there is no marker, or it is not JSON or names no manager.
#
# The sh half's _tdd_venv_read_marker sets variables and returns a status;
# here the two cannot be mixed, so the answer is the data and the caller
# reports the error it wants.
function _tdd_venv_read_marker {
    param([string]$Name)
    $file = _tdd_venv_marker $Name
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { return $null }
    try {
        $doc = Get-Content -LiteralPath $file -Raw -ErrorAction Stop | ConvertFrom-Json
    } catch {
        return $null
    }
    if (-not $doc -or -not $doc.manager) { return $null }
    return [pscustomobject]@{
        Type       = _tdd_venv_text $doc.manager
        Python     = _tdd_venv_text $doc.python
        PythonPath = _tdd_venv_text $doc.python_path
        Reloc      = ($doc.relocatable -eq $true)
        Created    = _tdd_venv_text $doc.created
    }
}

# A field of a marker as the file spells it. ConvertFrom-Json hands back an
# ISO 8601 string as a DateTime, and [string] would then print that in the
# host's culture -- `created` would leave this shell as 09/18/2026 15:09:26
# where the sh half emits 2026-09-18T15:09:26Z. (-DateKind would say so at the
# call, but it arrived in PowerShell 7.5 and this family targets 7.)
function _tdd_venv_text {
    param($Value)
    if ($null -eq $Value) { return '' }
    if ($Value -is [datetime]) { return $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    return [string]$Value
}

# The manager (type) of NAME from its marker, or ''.
function _tdd_venv_manager_of {
    param([string]$Name)
    if (-not $Name) { return '' }
    $marker = _tdd_venv_read_marker $Name
    if ($marker) { return $marker.Type }
    return ''
}

# What a venv says about itself: its interpreter's version and the base python
# it was built from (sys._base_executable, which pyvenv.cfg's `home` points at;
# a conda env carries its own, so that is the env's python), as Python and
# PythonPath; both empty when the venv's python does not run. $Dir the venv.
function _tdd_venv_probe {
    param([string]$Dir)
    $probe = [pscustomobject]@{ Python = ''; PythonPath = '' }
    $exe = _tdd_venv_exe $Dir 'python'
    if (-not $exe) { return $probe }
    $out = @(& $exe -c 'import sys; print(sys.version.split()[0]); print(sys._base_executable or sys.executable)' 2>$null)
    if ($LASTEXITCODE -ne 0 -or $out.Count -lt 2) { return $probe }
    $probe.Python = [string]$out[0]
    $probe.PythonPath = [string]$out[1]
    return $probe
}

# The version a venv's own interpreter reports, or '': what the prompt shows,
# asked at the moment it is shown rather than read from the marker.
function _tdd_venv_python_version {
    param([string]$Dir)
    $exe = _tdd_venv_exe $Dir 'python'
    if (-not $exe) { return '' }
    $out = (& $exe --version 2>&1 | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or -not $out) { return '' }
    return ([string]$out).Trim() -replace '^Python ', ''
}

# An empty fact is null in the marker, never "": jq's `def opt` of the sh half.
function _tdd_venv_opt {
    param([string]$Value)
    if ($Value) { return $Value }
    return $null
}

# Write the marker of a venv. PYTHON is the version the venv runs, REQUESTED
# what --python asked for; -Migrated stamps the time this marker replaced a
# pre-JSON one. Through a temporary file and one rename, so an interrupted
# write never leaves half a marker. Reports its own failure in $_TDD_RC.
function _tdd_venv_write_marker {
    param([string]$Name, [string]$Type, [string]$Python, [string]$PythonPath,
        [bool]$Reloc, [string]$Created, [string]$Requested,
        [string]$ManagerVersion = '', [switch]$Migrated)
    $file = _tdd_venv_marker $Name
    $tmp = Join-Path (_tdd_venv_root) ".$Name.json.$PID.tmp"
    $version = ''
    $versionFile = Join-Path $env:TDD_DIR 'VERSION'
    if (Test-Path -LiteralPath $versionFile -PathType Leaf) {
        $version = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    }
    # [ordered], so the fields come out in the order jq writes them on the
    # other half and the two files compare line for line.
    $doc = [ordered]@{
        schema           = 1
        name             = $Name
        manager          = $Type
        manager_version  = (_tdd_venv_opt $ManagerVersion)
        python           = (_tdd_venv_opt $Python)
        python_requested = (_tdd_venv_opt $Requested)
        python_path      = (_tdd_venv_opt $PythonPath)
        relocatable      = $Reloc
        created          = (_tdd_venv_opt $Created)
        tdd_version      = (_tdd_venv_opt $version)
    }
    if ($Migrated) { $doc['migrated'] = (_tdd_venv_now) }
    try {
        Set-Content -LiteralPath $tmp -Value ($doc | ConvertTo-Json -Depth 6) -Encoding utf8 -ErrorAction Stop
        Move-Item -LiteralPath $tmp -Destination $file -Force -ErrorAction Stop
    } catch {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        _tdd_error "cannot write $file" "$_"
    }
}

# Now, as the markers stamp it: UTC, to the second.
function _tdd_venv_now {
    return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

# The version of manager $Manager (pyenv, uv or conda) as `--version` says it:
# the second word of `uv 0.12.3 (...)`, `pyenv 2.8.4`, `conda 26.3.1`.
function _tdd_venv_manager_version {
    param([string]$Manager)
    try {
        $line = (& $Manager --version 2>$null | Select-Object -First 1)
    } catch {
        return ''
    }
    if (-not $line) { return '' }
    $words = ([string]$line).Trim() -split '\s+'
    if ($words.Count -ge 2) { return $words[1] }
    return ''
}

# The prompt marker of the active venv: (<type>/<python>/<name>), and /reloc
# inside the parenthesis when it is relocatable, so the prompt says what the
# venv can stand.
function _tdd_venv_mark_text {
    param([string]$Type, [string]$Python, [string]$Name, [bool]$Reloc)
    $shown = if ($Python) { $Python } else { '?' }
    $tail = if ($Reloc) { '/reloc' } else { '' }
    return "($Type/$shown/$Name$tail)"
}

# Two paths meaning the same place. The sh half compares strings; here they
# have to be normalised first, because a venv entered from Windows may spell
# its prefix with / where the tdd dir is spelled with \, and only a full path
# makes the two comparable. GetFullPath rather than Resolve-Path: the path may
# not exist, and this is also asked of PATH entries.
function _tdd_venv_samepath {
    param([string]$A, [string]$B)
    if (-not $A -or -not $B) { return $false }
    try {
        $A = [IO.Path]::GetFullPath($A)
        $B = [IO.Path]::GetFullPath($B)
    } catch {
        return $false
    }
    $sep = [IO.Path]::DirectorySeparatorChar
    return ($A.TrimEnd($sep) -eq $B.TrimEnd($sep))
}

# Markers from before the JSON: <name>.env holding the type alone. Each is
# replaced by a <name>.json on sight -- the type from the file, the interpreter
# probed from the venv, relocatable from what uv wrote in pyvenv.cfg, created
# from the old marker's mtime -- so the two formats never coexist and no reader
# has to know the old one. Every subcommand calls this before adopting, once
# past --help and with its options parsed (so an event here speaks the format
# asked for); `list` therefore writes to disk once, this once. Where the sh
# half tries both a BSD and a GNU `stat` and `date`, .NET has one answer.
function _tdd_venv_migrate {
    $root = _tdd_venv_root
    $old = @(Get-ChildItem -LiteralPath $root -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -eq '.env' } | Sort-Object Name)
    foreach ($file in $old) {
        $name = $file.BaseName
        $type = ''
        try { $type = (Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop).Trim() } catch { }
        if ($type -cnotin @('pyenv', 'uv', 'conda')) {
            _tdd_warn "$($file.FullName) names an unknown venv manager '$type'; left as it is"
            continue
        }
        $dir = Join-Path (Join-Path $root $type) $name
        $probe = _tdd_venv_probe $dir
        $reloc = $false
        $cfg = Join-Path $dir 'pyvenv.cfg'
        if (Test-Path -LiteralPath $cfg -PathType Leaf) {
            $reloc = [bool](Select-String -LiteralPath $cfg -Pattern '^relocatable = true' -Quiet)
        }
        $created = (Get-Item -LiteralPath $file.FullName).LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')
        _tdd_venv_write_marker -Name $name -Type $type -Python $probe.Python `
            -PythonPath $probe.PythonPath -Reloc $reloc -Created $created -Requested '' -Migrated
        if (_tdd_failed) { return }
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
        _tdd_debug "migrated the marker of $name ($type) to $(_tdd_venv_marker $name)"
    }
}

# ---------------------------------------------------------------- help

function _tdd_venv_help {
    _tdd_help_text @'
usage: tdd venv [-h] [-v] [--format {json,view}] SUBCOMMAND ...

managed virtualenvs (pyenv, uv or conda) under $TDD_DIR/managed-venvs, entered and left in the
calling shell

positional arguments:
  SUBCOMMAND
    create  make a venv and enter it
    activate  enter one, in this shell
    deactivate  leave the active managed venv
    delete  remove a venv, or every one of them
    list  every managed venv with its type, python, whether relocatable, path and base python
    config  this command's config file: --show, --default, --create [--force]

A <name>.json file beside them records the type, the python it runs and was built from,
whether it is relocatable and when it was made, so every subcommand -- and the tdk launchers
-- know which tool to use. The active one is named by _TDD_VENV; a managed venv found active
without that record (a shell from before a reinstall, bin/activate sourced by hand) is adopted
as the active one.

example: tdd venv create --name scratch --type uv --python 3.12.13 --relocatable
'@
}

function _tdd_venv_help_create {
    _tdd_help_text @'
usage: tdd venv create --name NAME [--type {pyenv,uv,conda}] [--python VERSION] [--relocatable] [--force]

Make a venv and enter it. Refuses while a venv tdd did not activate is active; switches from a
managed one. With --force an existing NAME is deleted first, even the active one.

options:
  --name NAME  the venv
  --type {pyenv,uv,conda}  the tool that creates it (default: pyenv). A pyenv venv is a plain `python -m venv` on a pyenv interpreter; a uv venv is built on a uv-managed interpreter only, never one found on PATH; conda gets its shell hook installed on the fly when the rc did not
  --python VERSION  the interpreter (default: 3.12.13, what a tdkserver instance builds its own environments with). pyenv needs it installed already (pyenv install VERSION); uv and conda fetch it
  --relocatable  make the venv relocatable: it keeps working after being moved or copied (uv venvs only; the prompt ends in /reloc). Without it the venv is bound to its path, whatever UV_VENV_RELOCATABLE says
  --force, -f  delete NAME first if it exists, leaving it if it is the active one
'@
}

function _tdd_venv_help_activate {
    _tdd_help_text @'
usage: tdd venv activate --name NAME

Enter it, in this shell: the prompt shows (<type>/PYTHON/NAME) in green -- (<type>/PYTHON/NAME/reloc)
for a relocatable venv -- and _TDD_VENV=NAME is exported, which `tdd tdk`, `tdd tdkserver` and
`tdd km` read. Switches if another managed venv is active; refuses if a venv tdd did not
activate is -- deactivate that one first.

options:
  --name NAME  the venv
'@
}

function _tdd_venv_help_deactivate {
    _tdd_help_text @'
usage: tdd venv deactivate [--force]

Leave the active managed venv and restore the prompt. A venv tdd did not activate, or a stale
record (recorded, nothing active), is an error that says so.

options:
  --force, -f  leave it anyway, best effort -- venv and uv through their own deactivate, pyenv-virtualenv through `pyenv deactivate`, conda through `conda deactivate` -- or drop the stale record
'@
}

function _tdd_venv_help_delete {
    _tdd_help_text @'
usage: tdd venv delete (--name NAME | --all)

Remove a venv and its marker. Refuses while it is active: the shell would be left standing in
a deleted venv.

options:
  --name NAME  the venv
  --all  every managed venv instead of one, and none of them may be active
'@
}

function _tdd_venv_help_list {
    _tdd_help_text @'
usage: tdd venv list

Every managed venv, one line each: name, type, the python version it runs, `reloc` when it is
relocatable (`-` when not), its path, and the base python it was built from -- all from its
<name>.json marker. The only subcommand that changes neither the shell nor a venv.
'@
}

# ---------------------------------------------------------------- this session

# The venv active in this session right now, managed or not, as a path; '' if
# none. conda's base does not count: after `conda init` it is active in every
# shell, and treating it as a venv would lock conda users out.
function _tdd_venv_current {
    if ($env:VIRTUAL_ENV) { return $env:VIRTUAL_ENV }
    $default = if ($env:CONDA_DEFAULT_ENV) { $env:CONDA_DEFAULT_ENV } else { 'base' }
    if ($env:CONDA_PREFIX -and $default -cne 'base') { return $env:CONDA_PREFIX }
    return ''
}

# Whether a venv's activation left its `deactivate` FUNCTION behind. The type
# matters: pyenv-virtualenv installs a `deactivate` program on PATH that only
# prints "must be sourced" when run.
function _tdd_venv_has_deactivate_fn {
    return ($null -ne (Get-Command -Name deactivate -CommandType Function -ErrorAction SilentlyContinue))
}

# The activation script of a venv. uv writes bin/activate.ps1 and `python -m
# venv` writes bin/Activate.ps1; the two spellings are one file only on a
# case-insensitive filesystem, so both are asked for -- and the directory is
# bin/ or Scripts\ depending on the machine the venv was built on, which is
# what _tdd_venv_bin answers.
function _tdd_venv_activate_script {
    param([string]$Dir)
    $bin = _tdd_venv_bin $Dir
    foreach ($leaf in @('activate.ps1', 'Activate.ps1')) {
        $candidate = Join-Path $bin $leaf
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

# Directory of the managed venv recorded in $env:_TDD_VENV, or '' when its
# marker is gone -- which no real venv's path can equal, so a comparison
# against it fails the way the sh half's does.
function _tdd_venv_active_dir {
    $manager = _tdd_venv_manager_of $env:_TDD_VENV
    if (-not $manager) { return '' }
    return (Join-Path (Join-Path (_tdd_venv_root) $manager) $env:_TDD_VENV)
}

# The prompt to restore for a venv entered behind tdd's back: the one the tool
# replaced, which a venv's Activate.ps1 keeps in _old_virtual_prompt and
# conda's hook in CondaPromptBackup. This is the counterpart of the sh half
# cutting "(name) " and $CONDA_PROMPT_MODIFIER back out of $PS1 -- it cannot be
# done by string surgery here, because a PowerShell prompt is a function.
# Nothing saved: the prompt as it stands, which at worst keeps the tool's mark.
function _tdd_venv_prompt_beneath {
    foreach ($saved in @('_old_virtual_prompt', 'CondaPromptBackup')) {
        $fn = Get-Command -Name $saved -CommandType Function -ErrorAction SilentlyContinue
        if ($fn) { return $fn.ScriptBlock }
    }
    return (Get-Command -Name prompt -CommandType Function -ErrorAction SilentlyContinue).ScriptBlock
}

# A managed venv active without its record -- a shell that entered it before a
# reinstall renamed the record, `bin/activate` sourced by hand, a script -- is
# still ours: its path is <root>/<type>/<name> and <name>.json says <type>.
# Adopt it as the recorded one, so create/activate switch from it and
# deactivate leaves it as managed instead of refusing it as foreign. Every
# subcommand calls this first, once past --help and after _tdd_venv_migrate, so
# the marker it reads is JSON.
function _tdd_venv_adopt {
    if ($env:_TDD_VENV) { return }
    $current = _tdd_venv_current
    if (-not $current) { return }
    $name = Split-Path -Leaf $current
    $type = Split-Path -Leaf (Split-Path -Parent $current)
    if (-not $name -or -not $type) { return }
    if (-not (_tdd_venv_samepath $current (Join-Path (Join-Path (_tdd_venv_root) $type) $name))) { return }
    if ((_tdd_venv_manager_of $name) -cne $type) { return }
    # A session that already wrapped the prompt once kept what it wrapped;
    # anything else is the tool's own saved prompt, or the prompt as it is.
    if (-not $global:_TDD_VENV_PROMPT) { $global:_TDD_VENV_PROMPT = _tdd_venv_prompt_beneath }
    $env:_TDD_VENV = $name
    _tdd_debug "adopted $name ($type): active in this shell without a record"
}

# Leave the recorded managed venv: the tool's own deactivate, then the prompt
# and the record. Shared by deactivate and by activate when switching.
function _tdd_venv_leave {
    if ((_tdd_venv_manager_of $env:_TDD_VENV) -ceq 'conda') {
        $env:CONDA_CHANGEPS1 = 'false'
        try { conda deactivate *> $null } catch { }
        $env:CONDA_CHANGEPS1 = $null
    } elseif (_tdd_venv_has_deactivate_fn) {
        deactivate | Out-Null
    }
    # Restored, not edited back: the prompt is a function, so what was wrapped
    # is put back as it was rather than a substring cut out of it.
    if ($global:_TDD_VENV_PROMPT) {
        Set-Item -Path function:global:prompt -Value $global:_TDD_VENV_PROMPT
    }
    Remove-Variable -Name _TDD_VENV_PROMPT, _TDD_VENV_MARK -Scope Global -ErrorAction SilentlyContinue
    $env:_TDD_VENV = $null
}

# Refuse when a venv tdd did not activate is in the way: on its own, or on top
# of the recorded managed one. Shared by activate and create, which both must
# fail before changing anything.
function _tdd_venv_foreign_check {
    $current = _tdd_venv_current
    if ($env:_TDD_VENV) {
        if ($current -and -not (_tdd_venv_samepath $current (_tdd_venv_active_dir))) {
            _tdd_error "a venv tdd did not activate is on top of managed venv $($env:_TDD_VENV) ($current); leave it first -- its own tool's deactivate, or ``tdd venv deactivate --force``"
        }
    } elseif ($current) {
        _tdd_error "a venv tdd did not activate is active ($current); leave it first -- its own tool's deactivate, or ``tdd venv deactivate --force``"
    }
}

# Enter $Name/$Type/$Dir ($Reloc says whether it is relocatable): leave the
# recorded managed venv if any, dot-source the tool's activation with its
# prompt marker silenced, write ours, record the state. Foreign check already
# done. The venv left behind goes into $_TDD_VENV_PREV rather than coming back
# as a value, because this function emits events -- and in --format json an
# event is written to the very stream a value would travel on.
function _tdd_venv_enter {
    param([string]$Name, [string]$Type, [string]$Dir, [bool]$Reloc)
    $global:_TDD_VENV_PREV = ''
    if ($env:_TDD_VENV) {
        $global:_TDD_VENV_PREV = $env:_TDD_VENV
        _tdd_venv_leave
        _tdd_debug "deactivated $($global:_TDD_VENV_PREV)"
    }
    # The prompt as it stands before any tool touches it -- what deactivation
    # will put back.
    $before = (Get-Command -Name prompt -CommandType Function -ErrorAction SilentlyContinue).ScriptBlock
    # The tools would each stamp their own marker on the prompt; keep them
    # quiet and write one consistent (<type>/<python>/<name>) ourselves.
    if ($Type -ceq 'conda') {
        $env:CONDA_CHANGEPS1 = 'false'
        $out = ''
        try { $out = (& conda activate $Dir 2>&1 | Out-String) } catch { $out = "$_" }
        if (-not (_tdd_venv_samepath (_tdd_venv_current) $Dir)) {
            # `conda activate` is the shell hook's function, not the program;
            # install the hook on the fly when the user's profile did not.
            # PowerShell has no `eval`: the hook is PowerShell source, so it is
            # collected with Out-String and run by Invoke-Expression, whose own
            # output is discarded the way the sh half discards `eval`'s: this
            # function must leave nothing on the success stream. Unlike the sh
            # half it runs in this very session -- there is no subshell to
            # swallow it -- so no third `conda activate` is needed.
            try { (& conda shell.powershell hook 2>$null | Out-String) | Invoke-Expression | Out-Null } catch { }
            try { $out = (& conda activate $Dir 2>&1 | Out-String) } catch { $out = "$_" }
        }
        $env:CONDA_CHANGEPS1 = $null
        # conda reports failure by leaving the prefix unentered rather than by
        # a status this shell can read from a function call.
        if (-not (_tdd_venv_samepath (_tdd_venv_current) $Dir)) {
            _tdd_error "conda could not activate $Dir" $out
            return
        }
    } else {
        $script = _tdd_venv_activate_script $Dir
        if (-not $script) {
            _tdd_error "could not source $(Join-Path (_tdd_venv_bin $Dir) 'activate.ps1')"
            return
        }
        $env:VIRTUAL_ENV_DISABLE_PROMPT = '1'
        try {
            . $script
        } catch {
            $env:VIRTUAL_ENV_DISABLE_PROMPT = $null
            _tdd_error "could not source $script" "$_"
            return
        }
        $env:VIRTUAL_ENV_DISABLE_PROMPT = $null
    }
    # The active managed venv, in green, with the interpreter it runs (asked of
    # the venv's own python rather than read from the marker: it is what runs
    # now) and /reloc when it is relocatable -- placed after the red `* `
    # tdd-source.ps1 put first, so that stays first; ahead of everything when
    # the prompt does not start with it.
    $global:_TDD_VENV_PROMPT = $before
    $global:_TDD_VENV_MARK = (_tdd_ps1_wrap green (_tdd_venv_mark_text $Type (_tdd_venv_python_version $Dir) $Name $Reloc)) + ' '
    function global:prompt {
        $body = if ($global:_TDD_VENV_PROMPT) { "$(& $global:_TDD_VENV_PROMPT)" } else { '' }
        $star = $global:_TDD_PROMPT_MARK
        if ($star -and $body.StartsWith($star)) {
            return $star + $global:_TDD_VENV_MARK + $body.Substring($star.Length)
        }
        return $global:_TDD_VENV_MARK + $body
    }
    $env:_TDD_VENV = $Name
}

# What is active and how it got there, for deactivate: Kind (conda | pyenv | uv
# | venv, '' when nothing is active) and Current, the prefix. Best effort:
# conda leaves CONDA_PREFIX, pyenv-virtualenv PYENV_VIRTUAL_ENV, and a venv's
# pyvenv.cfg says whether uv made it or which interpreter did.
function _tdd_venv_detect {
    $current = _tdd_venv_current
    $kind = ''
    if ($current) {
        $cfg = Join-Path $current 'pyvenv.cfg'
        if ($env:CONDA_PREFIX -and (_tdd_venv_samepath $current $env:CONDA_PREFIX)) {
            $kind = 'conda'
        } elseif ($env:PYENV_VIRTUAL_ENV -and (_tdd_venv_samepath $current $env:PYENV_VIRTUAL_ENV)) {
            $kind = 'pyenv'
        } elseif ((Test-Path -LiteralPath $cfg -PathType Leaf) -and
            (Select-String -LiteralPath $cfg -Pattern '^uv = ' -Quiet)) {
            $kind = 'uv'
        } elseif ((Test-Path -LiteralPath $cfg -PathType Leaf) -and
            (Select-String -LiteralPath $cfg -Pattern '^home = .*[\\/]\.pyenv[\\/]' -Quiet)) {
            $kind = 'pyenv'
        } else {
            $kind = 'venv'
        }
    }
    return [pscustomobject]@{ Kind = $kind; Current = $current }
}

# Leave a venv tdd did not activate, by the tool's own means when it left one
# behind, otherwise by undoing what activation does: the venv's bin off PATH,
# the variables gone. $false if something is still active afterwards. A pure
# predicate, like _tdd_optval: it says yes or no and emits nothing.
function _tdd_venv_leave_foreign {
    param([string]$Kind)
    if ($Kind -ceq 'conda') {
        try { conda deactivate *> $null } catch { }
        if (_tdd_venv_current) {
            try { (& conda shell.powershell hook 2>$null | Out-String) | Invoke-Expression | Out-Null } catch { }
            try { conda deactivate *> $null } catch { }
        }
    } elseif ($Kind -ceq 'pyenv') {
        # pyenv-virtualenv has no PowerShell integration, and `pyenv
        # sh-deactivate` prints sh this shell cannot run, so the plain command
        # is all there is to try; the PATH surgery below is the real way out.
        if ($env:PYENV_VIRTUAL_ENV -and (Get-Command -Name pyenv -ErrorAction SilentlyContinue)) {
            try { & pyenv deactivate *> $null } catch { }
        }
    }
    if ($env:VIRTUAL_ENV -and (_tdd_venv_has_deactivate_fn)) {
        try { deactivate | Out-Null } catch { }
    }
    if ($env:VIRTUAL_ENV) {
        # No deactivate function: activation was done by hand, undo it by hand.
        # PATH is separated by ; or : depending on the platform, never the
        # literal ':' the sh half can count on.
        $bin = _tdd_venv_bin $env:VIRTUAL_ENV
        $sep = [IO.Path]::PathSeparator
        $env:PATH = (($env:PATH.Split($sep) | Where-Object { -not (_tdd_venv_samepath $_ $bin) }) -join $sep)
        $env:VIRTUAL_ENV = $null
        $env:VIRTUAL_ENV_PROMPT = $null
        # No `hash -r`: PowerShell resolves an external command on every call.
    }
    return (-not (_tdd_venv_current))
}

# Remove the managed venv $Name of $Type: conda forgets the prefix first (the
# delete covers a partial env), then the directory and the marker go. Shared by
# delete, delete --all and create --force. Reports failure in $_TDD_RC.
function _tdd_venv_remove {
    param([string]$Name, [string]$Type)
    $dir = Join-Path (Join-Path (_tdd_venv_root) $Type) $Name
    if ($Type -ceq 'conda' -and (Test-Path -LiteralPath $dir -PathType Container)) {
        try { & conda env remove -y -q --prefix $dir *> $null } catch { }
    }
    Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $dir) {
        _tdd_error "could not remove $dir"
        return
    }
    Remove-Item -LiteralPath (_tdd_venv_marker $Name) -Force -ErrorAction SilentlyContinue
    _tdd_debug "removed $Name ($Type)"
}

# ---------------------------------------------------------------- subcommands

function _tdd_venv_create {
    param([string[]]$Argv)
    if ($null -eq $Argv) { $Argv = @() }
    $name = ''
    $type = 'pyenv'
    # One interpreter across every venv tdd makes, whichever tool makes it --
    # otherwise `--type uv` and `--type pyenv` hand you different Pythons from
    # the same command. 3.12.13 is what a tdkserver instance builds its own
    # environments with, so a venv made here matches what the product runs.
    $python = '3.12.13'
    $force = $false
    # Bound to its path unless asked otherwise: a venv that keeps working
    # after a move is uv's --relocatable, and the default is to not want it.
    $reloc = $false
    $i = 0
    while ($i -lt $Argv.Count) {
        $arg = $Argv[$i]
        if ($arg -cmatch '^--name(=.*)?$') {
            if (-not (_tdd_optval $Argv $i)) { _tdd_error '--name needs a value'; return }
            $name = $global:_TDD_OPTVAL
            $i += $global:_TDD_CONSUMED
        } elseif ($arg -cin @('--force', '-f')) {
            $force = $true
            $i++
        } elseif ($arg -ceq '--relocatable') {
            $reloc = $true
            $i++
        } elseif ($arg -cmatch '^--type(=.*)?$') {
            if (-not (_tdd_optval $Argv $i)) { _tdd_error '--type needs a value'; return }
            $type = $global:_TDD_OPTVAL
            $i += $global:_TDD_CONSUMED
        } elseif ($arg -cmatch '^--python(=.*)?$') {
            if (-not (_tdd_optval $Argv $i)) { _tdd_error '--python needs a value'; return }
            $python = $global:_TDD_OPTVAL
            $i += $global:_TDD_CONSUMED
        } else {
            if (-not (_tdd_common_opt $Argv $i)) { _tdd_error "unknown option: $arg (see --help)"; return }
            $i += $global:_TDD_CONSUMED
        }
    }
    if ($global:_TDD_HELP) { _tdd_venv_help_create; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    _tdd_venv_migrate
    if (_tdd_failed) { return }
    _tdd_venv_adopt
    if (-not $name) {
        _tdd_error '--name is required'
        return
    }
    if ($name -cmatch '[^A-Za-z0-9._-]' -or $name.StartsWith('.')) {
        _tdd_error "invalid name: $name (letters, digits, . _ - only; no leading dot)"
        return
    }
    if ($type -cnotin @('pyenv', 'uv', 'conda')) {
        _tdd_error "unknown --type: $type (pyenv, uv or conda)"
        return
    }
    # Only uv builds a venv that survives a move; `python -m venv` and conda
    # both bake the path in, so asking is a mistake worth stopping on rather
    # than a flag to shrug off.
    if ($reloc -and $type -cne 'uv') {
        _tdd_error "--relocatable needs --type uv: a $type venv is bound to its path"
        return
    }
    $relocs = if ($reloc) { ', relocatable' } else { '' }  # for the messages
    $recreated = $false
    if (Test-Path -LiteralPath (_tdd_venv_marker $name)) {
        $previous = _tdd_venv_manager_of $name
        if (-not $force) {
            _tdd_error "a managed venv named $name already exists (type $previous); --force recreates it"
            return
        }
        # --force: leave it if it is the active one, then remove it under its
        # OLD type -- the new one may differ -- so nothing stale survives.
        _tdd_info "recreate $name (was $previous)"
        if ($env:_TDD_VENV -ceq $name) {
            _tdd_venv_leave
            _tdd_debug "deactivated $name"
        }
        _tdd_venv_remove $name $previous
        if (_tdd_failed) { return }
        $recreated = $true
    }
    # Get-Command with no -CommandType, like `command -v`: after its hook conda
    # is a function in this session, not a program on PATH.
    if (-not (Get-Command -Name $type -ErrorAction SilentlyContinue)) {
        _tdd_error "$type is not on PATH"
        return
    }
    $dir = Join-Path (Join-Path (_tdd_venv_root) $type) $name
    # Creation ends in activation, so anything that would block activating
    # blocks creating -- before a directory exists.
    _tdd_venv_foreign_check
    if (_tdd_failed) { return }
    try {
        New-Item -ItemType Directory -Path (Join-Path (_tdd_venv_root) $type) -Force -ErrorAction Stop | Out-Null
    } catch {
        _tdd_error "cannot create $(_tdd_venv_root)" "$_"
        return
    }

    _tdd_info "create $name ($type$relocs)"
    _tdd_debug "python: $(if ($python) { $python } else { 'default' })"
    $out = ''
    $rc = 0
    switch ($type) {
        'uv' {
            # --managed-python: uv's own interpreters only, fetched when
            # missing -- never the homebrew, pyenv or system python that
            # happens to be on PATH under the same version. The relocatable
            # flag is passed only when asked, and UV_VENV_RELOCATABLE is kept
            # out of it: the marker records what this venv is, so the
            # environment must not decide it behind the flag's back. PowerShell
            # has no `env -u`, so the variable is saved, cleared for the call
            # and put back -- and the arguments are an array, which is how this
            # shell passes an optional argument through intact.
            $uvArgs = @('venv', '--managed-python')
            if ($reloc) { $uvArgs += '--relocatable' }
            if ($python) { $uvArgs += @('--python', $python) }
            $uvArgs += $dir
            $saved = $env:UV_VENV_RELOCATABLE
            $env:UV_VENV_RELOCATABLE = $null
            try {
                $out = (& uv @uvArgs 2>&1 | Out-String)
                $rc = $LASTEXITCODE
            } finally {
                if ($null -ne $saved) { $env:UV_VENV_RELOCATABLE = $saved }
            }
        }
        'pyenv' {
            # A plain venv built from a pyenv-managed interpreter: pyenv's own
            # virtualenv plugin cannot place an env outside its versions dir.
            if ($python) { $prefix = (& pyenv prefix $python 2>&1 | Out-String) }
            else { $prefix = (& pyenv prefix 2>&1 | Out-String) }
            $rc = $LASTEXITCODE
            $prefix = $prefix.Trim()
            if ($rc -ne 0) {
                $asked = if ($python) { $python } else { 'current' }
                $install = if ($python) { $python } else { 'VERSION' }
                _tdd_error "pyenv has no $asked version; run: pyenv install $install" $prefix
                return
            }
            # bin/python3 under a Unix pyenv; python.exe at the root of the
            # prefix under pyenv-win, which keeps no bin/ at all.
            $interp = _tdd_venv_exe $prefix 'python3'
            if (-not $interp) { $interp = _tdd_venv_exe $prefix 'python' }
            if (-not $interp) {
                foreach ($leaf in @('python.exe', 'python3', 'python')) {
                    $candidate = Join-Path $prefix $leaf
                    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $interp = $candidate; break }
                }
            }
            if (-not $interp) {
                _tdd_error "no python under pyenv prefix $prefix"
                return
            }
            $out = (& $interp -m venv $dir 2>&1 | Out-String)
            $rc = $LASTEXITCODE
        }
        'conda' {
            $spec = if ($python) { "python=$python" } else { 'python' }
            $out = (& conda create -y -q --prefix $dir $spec 2>&1 | Out-String)
            $rc = $LASTEXITCODE
        }
    }
    if ($rc -ne 0) {
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
        _tdd_error "$type failed to create $name" $out
        return
    }
    # The marker: what the venv turned out to be, asked of its own python --
    # the version it runs and the base interpreter it was built from -- beside
    # what was asked for and who made it.
    $probe = _tdd_venv_probe $dir
    $created = _tdd_venv_now
    _tdd_venv_write_marker -Name $name -Type $type -Python $probe.Python -PythonPath $probe.PythonPath `
        -Reloc $reloc -Created $created -Requested $python -ManagerVersion (_tdd_venv_manager_version $type)
    if (_tdd_failed) {
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
        return
    }
    $shown = if ($probe.Python) { $probe.Python } else { '?' }
    _tdd_debug "create $name ($type): done; python $shown from $(if ($probe.PythonPath) { $probe.PythonPath } else { '?' })"
    _tdd_venv_enter $name $type $dir $reloc
    if (_tdd_failed) { return }
    $prev = $global:_TDD_VENV_PREV
    $fields = [ordered]@{
        name             = $name
        type             = $type
        path             = $dir
        python           = $probe.Python
        python_requested = $python
        python_path      = $probe.PythonPath
        relocatable      = $reloc
        created          = $created
        activated        = $true
        recreated        = $recreated
    }
    if ($prev) { $fields['deactivated'] = $prev }
    _tdd_ok "$(if ($recreated) { 're' })created and activated $name ($type, python $shown$relocs) at $dir$(if ($prev) { " (left $prev)" })" $fields
}

function _tdd_venv_activate {
    param([string[]]$Argv)
    if ($null -eq $Argv) { $Argv = @() }
    # The sh half shares this loop with delete through _tdd_venv_parse_name; it
    # is written out here because a helper that reports an error cannot also
    # hand back the name it parsed -- in --format json the error line and the
    # name would travel on the same stream.
    $name = ''
    $i = 0
    while ($i -lt $Argv.Count) {
        $arg = $Argv[$i]
        if ($arg -cmatch '^--name(=.*)?$') {
            if (-not (_tdd_optval $Argv $i)) { _tdd_error '--name needs a value'; return }
            $name = $global:_TDD_OPTVAL
            $i += $global:_TDD_CONSUMED
        } else {
            if (-not (_tdd_common_opt $Argv $i)) { _tdd_error "unknown option: $arg (see --help)"; return }
            $i += $global:_TDD_CONSUMED
        }
    }
    if ($global:_TDD_HELP) { _tdd_venv_help_activate; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    _tdd_venv_migrate
    if (_tdd_failed) { return }
    _tdd_venv_adopt
    if (-not $name) {
        _tdd_error '--name is required'
        return
    }
    $marker = _tdd_venv_read_marker $name
    if (-not $marker) {
        _tdd_error "no managed venv named $name (see tdd venv list)"
        return
    }
    $dir = Join-Path (Join-Path (_tdd_venv_root) $marker.Type) $name
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        _tdd_error "$name ($($marker.Type)) has lost its directory $dir; delete and recreate it"
        return
    }
    _tdd_venv_foreign_check
    if (_tdd_failed) { return }
    if ($env:_TDD_VENV -ceq $name) {
        _tdd_ok "$name ($($marker.Type)) is already active" ([ordered]@{
                name = $name; type = $marker.Type; path = $dir
                relocatable = $marker.Reloc; already_active = $true
            })
        return
    }
    _tdd_venv_enter $name $marker.Type $dir $marker.Reloc
    if (_tdd_failed) { return }
    $prev = $global:_TDD_VENV_PREV
    $fields = [ordered]@{ name = $name; type = $marker.Type; path = $dir; relocatable = $marker.Reloc }
    if ($prev) { $fields['deactivated'] = $prev }
    _tdd_ok "activated $name ($($marker.Type)$(if ($marker.Reloc) { ', relocatable' })) at $dir$(if ($prev) { " (left $prev)" })" $fields
}

function _tdd_venv_deactivate {
    param([string[]]$Argv)
    if ($null -eq $Argv) { $Argv = @() }
    $force = $false
    $i = 0
    while ($i -lt $Argv.Count) {
        $arg = $Argv[$i]
        if ($arg -cin @('--force', '-f')) {
            $force = $true
            $i++
        } else {
            if (-not (_tdd_common_opt $Argv $i)) { _tdd_error "unknown option: $arg (see --help)"; return }
            $i += $global:_TDD_CONSUMED
        }
    }
    if ($global:_TDD_HELP) { _tdd_venv_help_deactivate; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    _tdd_venv_migrate
    if (_tdd_failed) { return }
    _tdd_venv_adopt
    $state = _tdd_venv_detect
    $current = $state.Current
    if ($env:_TDD_VENV -and $current -and (_tdd_venv_samepath $current (_tdd_venv_active_dir))) {
        # The recorded (or just adopted) managed venv, active: the ordinary case.
        $name = $env:_TDD_VENV
        $type = _tdd_venv_manager_of $name
        _tdd_venv_leave
        _tdd_ok "deactivated $name" ([ordered]@{ name = $name; type = $type; managed = $true })
        return
    }
    if ($env:_TDD_VENV -and -not $current) {
        # A stale record: the venv was left behind tdd's back (its own
        # deactivate, a deleted directory). Only --force drops it -- the state
        # is not what the record says, and the user should know before it is
        # rewritten.
        if (-not $force) {
            _tdd_error "$($env:_TDD_VENV) is recorded as the active managed venv but no venv is active: a stale record; tdd venv deactivate --force drops it"
            return
        }
        $name = $env:_TDD_VENV
        $type = _tdd_venv_manager_of $name
        _tdd_venv_leave
        _tdd_ok "dropped the stale record of $name (no venv was active)" ([ordered]@{
                name = $name; type = $type; managed = $true; stale = $true
            })
        return
    }
    if (-not $current) {
        # --force asks to be out of any venv, and out is where we are: an ok,
        # so a script can put it in front of whatever needs a clean shell
        # without having to swallow a failure that means "already fine".
        if ($force) {
            _tdd_ok 'no venv was active' ([ordered]@{ managed = $false; already = $true })
            return
        }
        _tdd_error 'no venv is active'
        return
    }
    # Something tdd did not activate -- possibly on top of the managed one,
    # whose record then stays for the next deactivate. Left only with --force:
    # tdd did not set it up, so it does not tear it down unasked.
    # conda names a prefix-activated env by its full path; the last component
    # is what the prompt shows.
    $name = Split-Path -Leaf $current
    if ($state.Kind -ceq 'conda' -and $env:CONDA_DEFAULT_ENV -and $env:CONDA_DEFAULT_ENV -notmatch '[\\/]') {
        $name = $env:CONDA_DEFAULT_ENV
    }
    if (-not $force) {
        _tdd_error "$name ($($state.Kind), $current) is active but tdd did not activate it$(if ($env:_TDD_VENV) { " -- on top of the managed venv $($env:_TDD_VENV)" }); tdd venv deactivate --force leaves it anyway"
        return
    }
    _tdd_info "deactivate $name ($($state.Kind), not managed by tdd)"
    if (-not (_tdd_venv_leave_foreign $state.Kind)) {
        _tdd_error "could not deactivate $current ($($state.Kind)); it is still active" @"
kind: $($state.Kind)
VIRTUAL_ENV=$($env:VIRTUAL_ENV)
CONDA_PREFIX=$($env:CONDA_PREFIX)
PYENV_VIRTUAL_ENV=$($env:PYENV_VIRTUAL_ENV)
"@
        return
    }
    _tdd_ok "deactivated $name ($($state.Kind), not managed by tdd)$(if ($env:_TDD_VENV) { "; managed venv $($env:_TDD_VENV) is still recorded, deactivate again to leave it" })" ([ordered]@{
            name = $name; type = $state.Kind; path = $current; managed = $false
        })
}

function _tdd_venv_delete {
    param([string[]]$Argv)
    if ($null -eq $Argv) { $Argv = @() }
    $name = ''
    $all = $false
    $i = 0
    while ($i -lt $Argv.Count) {
        $arg = $Argv[$i]
        if ($arg -ceq '--all') {
            $all = $true
            $i++
        } elseif ($arg -cmatch '^--name(=.*)?$') {
            if (-not (_tdd_optval $Argv $i)) { _tdd_error '--name needs a value'; return }
            $name = $global:_TDD_OPTVAL
            $i += $global:_TDD_CONSUMED
        } else {
            if (-not (_tdd_common_opt $Argv $i)) { _tdd_error "unknown option: $arg (see --help)"; return }
            $i += $global:_TDD_CONSUMED
        }
    }
    if ($global:_TDD_HELP) { _tdd_venv_help_delete; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    _tdd_venv_migrate
    if (_tdd_failed) { return }
    _tdd_venv_adopt
    if ($all) {
        if ($name) {
            _tdd_error '--all and --name are exclusive'
            return
        }
        # None may be active: the same rule as for one, and it keeps this from
        # pulling the venv the shell stands in out from under it.
        if ($env:_TDD_VENV) {
            _tdd_error "$($env:_TDD_VENV) is active; run tdd venv deactivate first"
            return
        }
        $rows = [System.Collections.Generic.List[string]]::new()
        $deleted = [System.Collections.Generic.List[object]]::new()
        foreach ($file in (_tdd_venv_markers)) {
            $one = $file.BaseName
            $type = _tdd_venv_manager_of $one
            _tdd_info "delete $one ($type)"
            _tdd_venv_remove $one $type
            if (_tdd_failed) { return }
            $rows.Add("$one ($type)")
            $deleted.Add([ordered]@{ name = $one; type = $type })
        }
        if ($rows.Count -eq 0) {
            _tdd_ok 'no managed venvs to delete' ([ordered]@{ deleted = @() })
        } else {
            _tdd_ok "deleted $($rows -join ', ')" ([ordered]@{ deleted = @($deleted) })
        }
        return
    }
    if (-not $name) {
        _tdd_error '--name NAME or --all is required'
        return
    }
    $marker = _tdd_venv_read_marker $name
    if (-not $marker) {
        _tdd_error "no managed venv named $name (see tdd venv list)"
        return
    }
    if ($env:_TDD_VENV -ceq $name) {
        _tdd_error "$name is active; run tdd venv deactivate first"
        return
    }
    _tdd_info "delete $name ($($marker.Type))"
    _tdd_venv_remove $name $marker.Type
    if (_tdd_failed) { return }
    _tdd_ok "deleted $name ($($marker.Type))" ([ordered]@{ name = $name; type = $marker.Type })
}

# Every marker file, sorted. The sh half needs `find` rather than a glob
# because an unmatched glob is an error in zsh; here the only care is that a
# missing directory is not one either, and that `.env` (the pre-JSON marker)
# never answers to `*.json` under a filesystem with 8.3 names.
function _tdd_venv_markers {
    return @(Get-ChildItem -LiteralPath (_tdd_venv_root) -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -eq '.json' } | Sort-Object Name)
}

function _tdd_venv_list {
    param([string[]]$Argv)
    if ($null -eq $Argv) { $Argv = @() }
    $i = 0
    while ($i -lt $Argv.Count) {
        if (-not (_tdd_common_opt $Argv $i)) { _tdd_error "unknown option: $($Argv[$i]) (see --help)"; return }
        $i += $global:_TDD_CONSUMED
    }
    if ($global:_TDD_HELP) { _tdd_venv_help_list; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    _tdd_venv_migrate
    if (_tdd_failed) { return }
    _tdd_venv_adopt
    $rows = [System.Collections.Generic.List[string]]::new()
    $venvs = [System.Collections.Generic.List[object]]::new()
    foreach ($file in (_tdd_venv_markers)) {
        $name = $file.BaseName
        $marker = _tdd_venv_read_marker $name
        if (-not $marker) { continue }
        $dir = Join-Path (Join-Path (_tdd_venv_root) $marker.Type) $name
        $active = ($env:_TDD_VENV -ceq $name)
        $exists = Test-Path -LiteralPath $dir -PathType Container
        $mark = ''
        if ($active) { $mark = '  (active)' }
        if (-not $exists) { $mark = "$mark  (missing directory)" }
        # name, type, the python it runs, reloc or -, its path, the base
        # python it was built from: everything the marker knows, one line.
        $rows.Add(("{0} {1} {2} {3} {4}  {5}{6}" -f
            $name.PadRight(24), $marker.Type.PadRight(6),
            $(if ($marker.Python) { $marker.Python } else { '?' }).PadRight(9),
            $(if ($marker.Reloc) { 'reloc' } else { '-' }).PadRight(6),
            $dir, $(if ($marker.PythonPath) { $marker.PythonPath } else { '?' }), $mark))
        $venvs.Add([ordered]@{
                name        = $name
                type        = $marker.Type
                python      = $marker.Python
                python_path = $marker.PythonPath
                relocatable = $marker.Reloc
                created     = $marker.Created
                path        = $dir
                active      = $active
                exists      = $exists
            })
    }
    if ($rows.Count -eq 0) {
        _tdd_ok 'no managed venvs (create one: tdd venv create --name NAME)' ([ordered]@{ venvs = @() })
    } else {
        _tdd_ok ($rows -join "`n") ([ordered]@{ venvs = @($venvs) })
    }
}
