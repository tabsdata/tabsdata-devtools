#
# Copyright 2026 Tabsdata Inc.
#

if (-not $global:_TDD_COMMON_LOADED) { . $env:_TDD_COMMON_PS1 }

# Entering or leaving a toolset venv changes the current shell, which is exactly
# what an executable cannot do -- hence a shell command rather than a tdd-exe
# builtin. `_tdd-env` is a group with two words:
#
#     tdd _tdd-env activate --toolset <toolset>
#     tdd _tdd-env deactivate
#
# Activation sources the venv's own activate script rather than reimplementing
# it -- the same decision the POSIX half records, for the same reason: what
# `deactivate` then calls is the venv's own function, which is also why this
# leaves whatever venv is active, toolset or not. uv writes `activate.ps1`
# beside the `activate` the POSIX half sources, and it is careful about scope
# (`New-Variable -Scope global`, `function global:deactivate`), so dot-sourcing
# it from inside a function leaves exactly the session-level state it would
# leave at the prompt -- checked, not assumed.
#
# The one thing held back is the prompt: activate.ps1 installs a
# `global:prompt` of its own unless VIRTUAL_ENV_DISABLE_PROMPT is set, and
# tdd-source.ps1 already owns the prompt -- it keeps the session's original and
# wraps it, so a second wrapper is what the next re-source would silently drop.
# The POSIX half sets the same variable for the same reason.

# No `|` in the summary: it is the registry delimiter.
tdd_fn_register _tdd-env "activate --toolset <toolset>, or deactivate, a toolset venv in this shell"

# Built-in option defaults: what `tdd _tdd-env config` writes as its template,
# and what `--show` compares against.
function tdd_defaults__tdd-env {
    @('activate|--toolset|')
}

function tddfn__tdd-env {
    param([string[]]$Argv)
    _tdd_cmd_reset
    $sub = if ($Argv.Count -gt 0) { $Argv[0] } else { '' }
    $rest = @($Argv | Select-Object -Skip 1)
    # No status is returned and none is collected: every branch below ends in
    # _tdd_ok or _tdd_error, which is what sets $_TDD_RC for the dispatcher.
    # `break` because a PowerShell switch runs every clause that matches, not
    # only the first, unlike the POSIX `case` this mirrors.
    switch ($sub) {
        'config' {
            $global:_TDD_CMD = '_tdd-env-config'
            _tdd_config_action _tdd-env $rest
            break
        }
        { $_ -eq 'activate' -or $_ -eq 'deactivate' } {
            $global:_TDD_CMD = "_tdd-env-$sub"
            & "_tdd_env_$sub" $rest
            break
        }
        { $_ -eq '--help' -or $_ -eq '-h' } {
            _tdd_env_help
            break
        }
        '' {
            _tdd_error "a subcommand is required: activate or deactivate (see --help)"
            break
        }
        default { _tdd_error "unknown subcommand: $sub (see --help)" }
    }
}

# Single-quoted here-strings: the help pages quote shell words in backticks, and
# a backtick is PowerShell's escape character inside a double-quoted one.
function _tdd_env_help {
    _tdd_help_text @'
usage: tdd _tdd-env [-h] [-v] [--format {json,view}] SUBCOMMAND ...

enter or leave a toolset venv in this shell -- the envs the Python tools run in

positional arguments:
  SUBCOMMAND
    activate  put a toolset's bin/ first on PATH, in this shell
    deactivate  restore PATH
    config  this command's config file: --show, --default, --create [--force]

example: tdd _tdd-env activate --toolset systems
'@
}

function _tdd_env_help_activate {
    _tdd_help_text @'
usage: tdd _tdd-env activate --toolset TOOLSET

Put the toolset's bin/ first on PATH, in this shell, exactly as `tdd <tool>`
would arrange it -- which is what makes it useful while developing a tool: the
tool's entry point and its pinned binaries are there without `tdd` in front. It
sources the venv's own activate.ps1 rather than reimplementing activation.

options:
  --toolset TOOLSET  the toolset to enter (`tdd help` lists them)
'@
}

function _tdd_env_help_deactivate {
    _tdd_help_text @'
usage: tdd _tdd-env deactivate

Leave the venv active in this shell and restore PATH. What it calls is the
venv's own `deactivate`, so it leaves whatever is active, toolset or not, and
says so when nothing is.
'@
}

function _tdd_env_activate {
    param([string[]]$Argv)
    $ts = ''
    $i = 0
    while ($i -lt $Argv.Count) {
        $a = $Argv[$i]
        if ($a -eq '--toolset' -or $a -like '--toolset=*') {
            if (-not (_tdd_optval $Argv $i)) { _tdd_error "--toolset needs a value"; return }
            $ts = $global:_TDD_OPTVAL
        } elseif (-not (_tdd_common_opt $Argv $i)) {
            _tdd_error "unknown option: $a (see --help)"
            return
        }
        $i += $global:_TDD_CONSUMED
    }
    if ($global:_TDD_HELP) { _tdd_env_help_activate; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    if (-not $ts) {
        _tdd_error "--toolset is required; toolsets: $(_tdd_toolsets)"
        return
    }
    $venv = Join-Path (Join-Path $env:TDD_DIR 'tdd-venvs') $ts
    # _tdd_venv_bin answers bin/ or Scripts\ by what the venv actually has,
    # not by what this platform is, so the activate script is looked for where
    # this venv really keeps it.
    $bin = _tdd_venv_bin $venv
    if (-not (Test-Path -LiteralPath $bin -PathType Container)) {
        _tdd_error "no such toolset: $ts; toolsets: $(_tdd_toolsets)"
        return
    }
    # The script uv writes for this shell. Asked for by name rather than
    # assumed: a case-sensitive filesystem does not answer `Activate.ps1` for
    # the `activate.ps1` uv wrote.
    $script = $null
    foreach ($leaf in @('activate.ps1', 'Activate.ps1')) {
        $candidate = Join-Path $bin $leaf
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $script = $candidate; break }
    }
    if (-not $script) {
        _tdd_error "no such toolset: $ts; toolsets: $(_tdd_toolsets)"
        return
    }
    # Its own prompt stays quiet; tdd-source.ps1 owns the prompt. Restored
    # rather than left set, so a venv activated by hand afterwards still gets
    # the marker its own activate would have written.
    $had = $env:VIRTUAL_ENV_DISABLE_PROMPT
    $env:VIRTUAL_ENV_DISABLE_PROMPT = '1'
    try { . $script } finally { $env:VIRTUAL_ENV_DISABLE_PROMPT = $had }
    _tdd_ok "activated $ts ($venv)" ([ordered]@{ toolset = $ts; path = $venv })
}

function _tdd_env_deactivate {
    param([string[]]$Argv)
    $i = 0
    while ($i -lt $Argv.Count) {
        if (-not (_tdd_common_opt $Argv $i)) {
            _tdd_error "unknown option: $($Argv[$i]) (see --help)"
            return
        }
        $i += $global:_TDD_CONSUMED
    }
    if ($global:_TDD_HELP) { _tdd_env_help_deactivate; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    if (Get-Command -Name deactivate -CommandType Function -ErrorAction SilentlyContinue) {
        deactivate
        _tdd_ok "deactivated"
    } else {
        _tdd_error "no active venv"
    }
}

# Toolset names come from the catalog, not a glob of tdd-venvs/: that directory
# also holds the tdd and shells envs, which are not toolsets. The POSIX half
# reads the file with the tdd env's python because sh cannot parse JSON; this
# family has ConvertFrom-Json, and spending a subprocess here would put a
# dependency on a built tdd env into a message that exists to explain a failure.
function _tdd_toolsets {
    $catalog = Join-Path $env:TDD_DIR 'catalog.json'
    if (-not (Test-Path -LiteralPath $catalog -PathType Leaf)) { return '' }
    try {
        $doc = Get-Content -LiteralPath $catalog -Raw -ErrorAction Stop | ConvertFrom-Json
        return (@($doc.toolsets) -join ' ')
    } catch {
        return ''
    }
}
