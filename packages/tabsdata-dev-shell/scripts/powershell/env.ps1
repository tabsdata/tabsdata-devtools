#
# Copyright 2026 Tabsdata Inc.
#

if (-not $global:_TDD_COMMON_LOADED) { . $env:_TDD_COMMON_PS1 }

# Setting and unsetting variables in the caller's session is the one thing a
# Python tool cannot do, so this one command owns every variable tdd manages:
#
#     crypto     _TDD_CRYPTO_KEY            from 1Password, via `tdd _1p fetch --crypto`,
#                                          or verbatim from --value
#     secrets    <PREFIX>__<KEY>..., _TDD_SYSTEMS   via `tdd _1p fetch --secrets`; the latter lists
#                                                  the prefixes, which is how unset knows what to remove
#     pypi-twine TWINE_USERNAME, TWINE_PASSWORD    the PyPI upload credentials, via `tdd _1p fetch
#                                                  --pypi-twine` (DevSecrets' PYPI_TWINE_USERNAME/_PASSWORD)
#     td         TD_*                              (unset only)
#     vars       <PREFIX>*                         (unset only)
#     py-idx     UV_INDEX, PIP_EXTRA_INDEX_URL     the extra Python package index, with UV_INDEX_STRATEGY=
#                                                  unsafe-best-match so uv considers it (+ legacy UV_EXTRA_INDEX_URL on unset)
#     py-default-idx  UV_DEFAULT_INDEX, PIP_INDEX_URL  the default index (+ legacy UV_INDEX_URL on unset)
#
# `set` exports, `unset` removes, `show` lists them all (`-` marks unset) in
# three sorted groups: TD (everything starting with TD that is set, the two
# above always), PyPi (the index variables and twine's credentials), Secrets.
#
# The twin of env.sh; edit both. PowerShell forces three mechanisms to differ,
# and only three: a variable is set through the Env: provider rather than
# `export` (_tdd_vars_put, because the names arrive in a variable and `$env:X`
# can only spell a name written into the source); the `export NAME=VALUE` lines
# `tdd-exe _1p fetch` prints are parsed rather than eval'd
# (_tdd_vars_parse_exports); and the environment is read back as name/value
# pairs rather than as text (_tdd_vars_names).

tdd_fn_register env "set, unset or show this shell's crypto key, 1Password secrets, TD_ and Python index variables"

$global:_TDD_VARS_CRYPTO = '_TDD_CRYPTO_KEY'
# Where --crypto and --secrets read from unless --vault says otherwise, as
# provider refs. Literals, not $ONE_PASSWORD_*: a vault is a choice made on the
# command line, and a variable in the environment silently changing which vault
# a key comes from is exactly the kind of surprise these commands are meant to
# remove. The minimum key length is crypto.MIN_SECRET_LEN, checked by a test.
$global:_TDD_VAULT_CRYPTO = '1p:Employee'
$global:_TDD_VAULT_SECRETS = '1p:dev_xp'
$global:_TDD_CRYPTO_MIN = 12
$global:_TDD_VARS_SYSTEMS = '_TDD_SYSTEMS'
# What --pypi-twine sets: the names twine reads, so `twine upload` needs
# nothing else. They come from the crypto key's vault and item, under the
# fields PYPI_TWINE_USERNAME/_PASSWORD (`_1p fetch` owns that mapping).
$global:_TDD_VARS_PYPI_TWINE = @('TWINE_USERNAME', 'TWINE_PASSWORD')
$global:_TDD_VARS_PY_EXTRA = @('UV_INDEX', 'PIP_EXTRA_INDEX_URL')
$global:_TDD_VARS_PY_EXTRA_LEGACY = @('UV_EXTRA_INDEX_URL')
# An extra index only matters if uv may pick a package from it over the
# default one; the default strategy never does.
$global:_TDD_VARS_PY_STRATEGY = 'UV_INDEX_STRATEGY'
$global:_TDD_VARS_PY_STRATEGY_VALUE = 'unsafe-best-match'
$global:_TDD_VARS_PY_DEFAULT = @('UV_DEFAULT_INDEX', 'PIP_INDEX_URL')
$global:_TDD_VARS_PY_DEFAULT_LEGACY = @('UV_INDEX_URL')
# $global: and not a plain assignment: the loader dot-sources this file from
# inside a function, so anything not global would go out of scope with it --
# and `tdd_defaults_env` below is read much later, by `config`.

# Built-in option defaults: what `tdd env config` writes as its template,
# and what `--show` compares against.
function tdd_defaults_env {
    @(
        "set|--vault|crypto, pypi-twine: $($global:_TDD_VAULT_CRYPTO); secrets: $($global:_TDD_VAULT_SECRETS)",
        'set|--item|DevSecrets', 'set|--field|TD_BACKENDS_CRYPTO_KEY', 'set|--value|', 'set|--force|false',
        'show|--group|all', 'show|--reveal|false'
    )
}

function tddfn_env {
    param([string[]]$Argv)
    _tdd_cmd_reset
    $sub = if ($Argv -and $Argv.Count -gt 0) { $Argv[0] } else { '' }
    $rest = @($Argv | Select-Object -Skip 1)
    # No `unset` of the temporaries at the end, as the POSIX half needs: a
    # PowerShell function's variables are its own and die with the call, so
    # nothing here can leak into the session. Only $env: and $global: outlive it.
    switch ($sub) {
        'config' {
            $global:_TDD_CMD = 'env-config'
            _tdd_config_action env $rest
        }
        'tdd-source' {
            $global:_TDD_CMD = 'env-tdd-source'
            _tdd_vars_tdd_source $rest
        }
        { $_ -in @('set', 'unset', 'show') } {
            $global:_TDD_CMD = "env-$sub"
            & "_tdd_vars_$sub" $rest
        }
        { $_ -in @('--help', '-h') } { _tdd_vars_help }
        '' { _tdd_error 'a subcommand is required: set, unset or show (see --help)' }
        default { _tdd_error "unknown subcommand: $sub (see --help)" }
    }
}

# ---------------------------------------------------------------- help

function _tdd_vars_help {
    _tdd_help_text @'
usage: tdd env [-h] [-v] [--format {json,view}] SUBCOMMAND ...

set, unset or show the variables tdd manages in this shell: the descriptor crypto key, the
1Password secrets, tabsdata's TD_ settings and the Python index variables

positional arguments:
  SUBCOMMAND
    set  export the selected variables, in this shell
    unset  remove the selected variables
    show  every variable these commands handle, set or not
    tdd-source  load $TDD_DIR/tdd-source.ps1 again, in this shell
    config  this command's config file: --show, --default, --create [--force]

example: tdd env set --crypto --secrets && tdd env show
'@
}

function _tdd_vars_help_set {
    _tdd_help_text @'
usage: tdd env set (--crypto | --secrets | --pypi-twine | --py-idx URL | --py-default-idx URL)...
                   [--vault 1p:VAULT] [--item ITEM] [--field FIELD] [--value VALUE] [--force]

Export the selected variables in THIS shell; several selections combine in one call. The
crypto key, the secrets and the PyPI upload credentials come from 1Password, through one
`tdd _1p fetch` whose export lines are read here, so nothing is written to disk. The vault
defaults are literals: no variable of the environment decides which vault a key comes from.

options:
  --crypto  _TDD_CRYPTO_KEY, the key that encrypts the system and domain descriptors; read only when the variable is not already set, unless --force (or --value, which reads nothing)
  --secrets  every <PREFIX>__<KEY> secret of a shared vault, plus _TDD_SYSTEMS, the prefix list that `unset --secrets` reads back
  --pypi-twine  the PyPI upload credentials, for twine: the fields PYPI_TWINE_USERNAME and PYPI_TWINE_PASSWORD of item DevSecrets (the crypto key's item and vault) exported as TWINE_USERNAME and TWINE_PASSWORD, the names `twine upload` reads. Fetched every time, set or not
  --py-idx URL  the extra Python package index: UV_INDEX and PIP_EXTRA_INDEX_URL, plus UV_INDEX_STRATEGY=unsafe-best-match so uv considers it. URL is a URL, or @dev for the development index (https://d3mm0r95u5i3hf.cloudfront.net/simple/) or @prod for the published one (https://pypi.tabsdata.com/simple/) -- quote a marker, since a bare @dev is PowerShell's splatting syntax
  --py-default-idx URL  the default Python package index: UV_DEFAULT_INDEX and PIP_INDEX_URL. Takes '@dev' and '@prod' too
  --vault 1p:VAULT  the vault to read from, as a provider ref (1p is the only provider today). Defaults: --crypto and --pypi-twine 1p:Employee, --secrets 1p:dev_xp
  --item ITEM  --crypto: the item in the vault (default: DevSecrets)
  --field FIELD  --crypto: the field of that item (default: TD_BACKENDS_CRYPTO_KEY)
  --value VALUE  --crypto: this value IS the key (at least 12 characters); nothing is read from 1Password and the variable is replaced whether or not it is set. Not with --vault, --item or --field
  --force, -f  --crypto: fetch from 1Password even if _TDD_CRYPTO_KEY is already set
'@
}

function _tdd_vars_help_unset {
    _tdd_help_text @'
usage: tdd env unset (--crypto | --secrets | --pypi-twine | --td | --vars PREFIX | --py-idx | --py-default-idx)...

Remove the selected variables from THIS shell; several selections combine in one call.

options:
  --crypto  _TDD_CRYPTO_KEY
  --secrets  every secret _TDD_SYSTEMS names, and the list itself
  --pypi-twine  TWINE_USERNAME and TWINE_PASSWORD
  --td  every variable starting with TD_ -- tabsdata's own. tdd's _TDD_SYSTEMS and _TDD_CRYPTO_KEY are not among them; --secrets and --crypto remove those
  --vars PREFIX  every variable starting with PREFIX (repeatable). TDD_DIR, the tdd dir itself, is never unset
  --py-idx  UV_INDEX and PIP_EXTRA_INDEX_URL, and the legacy UV_EXTRA_INDEX_URL with them
  --py-default-idx  UV_DEFAULT_INDEX and PIP_INDEX_URL, and the legacy UV_INDEX_URL with them
'@
}

function _tdd_vars_help_tdd_source {
    _tdd_help_text @'
usage: tdd env tdd-source

Load $TDD_DIR/tdd-source.ps1 again, in this shell. That file is generated by tdd-install, so a
reinstall does not reach a shell that sourced the old one -- every other shell file is linked
to the checkout and needs nothing. Use it after `cargo make dev` to get the new `tdd` function
without opening a new terminal.
'@
}

function _tdd_vars_help_show {
    _tdd_help_text @'
usage: tdd env show [--group {all,td,pypi,secrets}] [--reveal]

Every variable these commands handle, NAME=value when set and -NAME when not, in three sorted
groups: TD (every variable starting with TD, plus _TDD_CRYPTO_KEY, and _TDD_SYSTEMS while it
is set), PyPi (the index variables and TWINE_USERNAME/TWINE_PASSWORD) and Secrets. A value
whose name says PASSWORD, SECRET, TOKEN, KEY, PASS, _PAT, _PEM or PEM_ is masked in every
group -- a certificate is both a credential and unreadable in a listing.

options:
  --group {all,td,pypi,secrets}  print one group instead of all three (default: all)
  --reveal  print the masked values instead of masking them
'@
}

# ---------------------------------------------------------------- variables

# One variable of the session, by a name held in another variable. `$env:X`
# names X in the source text and nothing else, so every read and write here
# goes through the Env: provider instead -- the same process environment, and
# the same thing `export`/`unset` reach in sh. Set-Item keeps an empty value as
# `export X=` does, and Remove-Item is what removes: the .NET call that looks
# like the pair of them, SetEnvironmentVariable($name, $null), is handed
# PowerShell's conversion of $null to an empty string and leaves the variable
# standing where sh would have dropped it.
function _tdd_vars_get {
    param([string]$Name)
    return [Environment]::GetEnvironmentVariable($Name)
}

function _tdd_vars_isset {
    param([string]$Name)
    return (Test-Path -LiteralPath "Env:$Name")
}

function _tdd_vars_put {
    param([string]$Name, [string]$Value)
    Set-Item -LiteralPath "Env:$Name" -Value $Value
}

function _tdd_vars_drop {
    param([string]$Name)
    Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
}

# `sort -u` over names, in byte order. Sort-Object sorts by the current
# culture, which ignores punctuation and files _TDD_SYSTEMS among the TD_ ones;
# the POSIX half's `sort` is the C locale's, and it also folds nothing, so two
# names differing only in case stay two names. A listing of the environment
# should read the same on every machine and in every locale, which is the one
# ordering that does.
function _tdd_vars_sort {
    param([string[]]$Names)
    $sorted = [string[]]@($Names)
    [Array]::Sort($sorted, [System.StringComparer]::Ordinal)
    $out = [System.Collections.Generic.List[string]]::new()
    foreach ($n in $sorted) {
        if ($out.Count -eq 0 -or $out[$out.Count - 1] -cne $n) { $out.Add($n) }
    }
    return @($out)
}

# Names of the exported variables matching a regex, sorted. The POSIX half has
# to read `env`'s output and keep only assignment-shaped lines -- a value
# holding a newline must not be mistaken for a variable; PowerShell hands the
# environment back as name/value pairs, so there is nothing to mis-split. The
# identifier filter stays: Windows keeps entries like `ProgramFiles(x86)` that
# no sh could ever export, and a prefix must not sweep them up.
function _tdd_vars_names {
    param([string]$Pattern)
    return (_tdd_vars_sort @(Get-ChildItem -Path Env: |
            Where-Object { $_.Name -cmatch '^[A-Za-z_][A-Za-z0-9_]*$' -and $_.Name -cmatch $Pattern } |
            ForEach-Object { $_.Name }))
}

# The words of a whitespace-separated variable, the way `for x in $VAR` reads it.
function _tdd_vars_words {
    param([string]$Text)
    if (-not $Text) { return @() }
    return @($Text -split '\s+' | Where-Object { $_ -ne '' })
}

# One layer of shell quoting off a value, or $null when a quote is still open --
# which is how the caller knows the value runs on to the next line.
#
# `tdd _1p fetch` renders its values with Python's
# shlex.quote, so a value is either bare or wrapped in single quotes with
# '"'"' standing in for an embedded quote; this reverses exactly that, and the
# double-quote and backslash cases besides, so the reading is the shell's and
# not a guess about the writer.
function _tdd_vars_unquote {
    param([string]$Text)
    $out = [System.Text.StringBuilder]::new()
    $i = 0
    while ($i -lt $Text.Length) {
        $c = $Text[$i]
        if ($c -eq "'") {
            $j = $Text.IndexOf("'", $i + 1)
            if ($j -lt 0) { return $null }
            [void]$out.Append($Text.Substring($i + 1, $j - $i - 1))
            $i = $j + 1
            continue
        }
        if ($c -eq '"') {
            $i++
            while ($true) {
                if ($i -ge $Text.Length) { return $null }
                $d = $Text[$i]
                if ($d -eq '"') { $i++; break }
                if ($d -eq '\' -and $i + 1 -lt $Text.Length -and $Text[$i + 1] -in @('"', '\', '$', '`')) {
                    [void]$out.Append($Text[$i + 1])
                    $i += 2
                    continue
                }
                [void]$out.Append($d)
                $i++
            }
            continue
        }
        if ($c -eq '\') {
            if ($i + 1 -ge $Text.Length) { return $null }
            [void]$out.Append($Text[$i + 1])
            $i += 2
            continue
        }
        [void]$out.Append($c)
        $i++
    }
    return $out.ToString()
}

# `export NAME=VALUE` lines into this session's variables; appends every name
# it set to $Names.
#
# The POSIX half evals the lines, which is the shortest correct thing there.
# Here it would be neither: `export` is not a PowerShell command and `=` is not
# an assignment, so the lines have to be read rather than run -- and running
# them would mean handing text fetched from a shared 1Password vault to the
# PowerShell parser, where a value carrying `;` or `$(...)` would execute. A
# parser reads a secret as data, which is the only thing a secret ever is.
#
# A value may span lines (a PEM is a secret like any other), and shlex.quote
# writes it as one long single-quoted string; when the quoting is still open at
# the end of a line the next line belongs to the same value.
function _tdd_vars_parse_exports {
    param([string[]]$Lines, [System.Collections.Generic.List[string]]$Names)
    $name = ''
    $pending = $null
    foreach ($line in $Lines) {
        if ($null -ne $pending) {
            $pending = "$pending`n$line"
            $value = _tdd_vars_unquote $pending
            if ($null -eq $value) { continue }
            _tdd_vars_put $name $value
            $Names.Add($name)
            $pending = $null
            continue
        }
        if ($line -match '^export ([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $name = $Matches[1]
            $raw = $Matches[2]
            $value = _tdd_vars_unquote $raw
            if ($null -eq $value) { $pending = $raw; continue }
            _tdd_vars_put $name $value
            $Names.Add($name)
        }
    }
}

# Run `tdd-exe _1p fetch ARGS` and apply the export lines it prints -- the one
# way a value a Python tool read reaches this session; appends the names it set
# to $Names. Reports and leaves $_TDD_RC at 1
# on failure -- the status never travels back as a value, because this function
# has a caller that emits.
function _tdd_vars_apply {
    param([string[]]$FetchArgs, [System.Collections.Generic.List[string]]$Names)
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $out = & { tdd-exe _1p fetch @FetchArgs 2>$errFile }
        if ($global:_TDD_RC -ne 0) {
            $details = Get-Content -LiteralPath $errFile -Raw
            $last = @(@($details -split "`r?`n") | Where-Object { $_ -ne '' -and $_ -notmatch '^details:' })
            $summary = if ($last.Count -gt 0) { $last[-1] } else { '' }
            _tdd_error "tdd _1p fetch failed: $summary" $details
            return
        }
    } finally {
        Remove-Item -LiteralPath $errFile -ErrorAction SilentlyContinue
    }
    $lines = @($out | ForEach-Object { [string]$_ })
    if ($lines.Count -eq 0 -or ($lines -join '') -eq '') {
        _tdd_error "tdd _1p fetch returned nothing to export"
        return
    }
    _tdd_vars_parse_exports $lines $Names
}

# ---------------------------------------------------------------- set

function _tdd_vars_set {
    param([string[]]$Argv)
    $crypto = $false
    $secrets = $false
    $pypiTwine = $false
    $pyExtra = ''
    $pyDefault = ''
    $vault = ''
    $item = ''
    $field = ''
    $value = ''
    $force = $false
    $setNames = [System.Collections.Generic.List[string]]::new()
    for ($i = 0; $i -lt $Argv.Count; ) {
        switch -Regex ($Argv[$i]) {
            '^--crypto$' { $crypto = $true; $i++; continue }
            '^--secrets$' { $secrets = $true; $i++; continue }
            '^--pypi-twine$' { $pypiTwine = $true; $i++; continue }
            '^(--force|-f)$' { $force = $true; $i++; continue }
            '^--vault(=.*)?$' {
                if (-not (_tdd_optval $Argv $i)) { _tdd_error '--vault needs a value'; return }
                $vault = $global:_TDD_OPTVAL; $i += $global:_TDD_CONSUMED; continue
            }
            '^--item(=.*)?$' {
                if (-not (_tdd_optval $Argv $i)) { _tdd_error '--item needs a value'; return }
                $item = $global:_TDD_OPTVAL; $i += $global:_TDD_CONSUMED; continue
            }
            '^--field(=.*)?$' {
                if (-not (_tdd_optval $Argv $i)) { _tdd_error '--field needs a value'; return }
                $field = $global:_TDD_OPTVAL; $i += $global:_TDD_CONSUMED; continue
            }
            '^--value(=.*)?$' {
                if (-not (_tdd_optval $Argv $i)) { _tdd_error '--value needs a value'; return }
                $value = $global:_TDD_OPTVAL; $i += $global:_TDD_CONSUMED; continue
            }
            '^--py-idx(=.*)?$' {
                if (-not (_tdd_optval $Argv $i)) { _tdd_error '--py-idx needs a URL'; return }
                if (-not (_tdd_resolve_index $global:_TDD_OPTVAL)) {
                    _tdd_error "unknown --py-idx marker: $($global:_TDD_OPTVAL) (@dev, @prod, or a URL)"
                    return
                }
                # An empty value almost always means an unquoted marker: `@dev`
                # written bare is PowerShell's splatting syntax, so it expands
                # an undefined variable and arrives as nothing at all. Saying
                # so beats "nothing selected", which names the wrong problem.
                if (-not $global:_TDD_INDEX_RESOLVED) {
                    _tdd_error "--py-idx needs a URL (a bare @dev is PowerShell splatting and arrives empty -- quote it: --py-idx '@dev')"
                    return
                }
                $pyExtra = $global:_TDD_INDEX_RESOLVED; $i += $global:_TDD_CONSUMED; continue
            }
            '^--py-default-idx(=.*)?$' {
                if (-not (_tdd_optval $Argv $i)) { _tdd_error '--py-default-idx needs a URL'; return }
                if (-not (_tdd_resolve_index $global:_TDD_OPTVAL)) {
                    _tdd_error "unknown --py-default-idx marker: $($global:_TDD_OPTVAL) (@dev, @prod, or a URL)"
                    return
                }
                # An empty value almost always means an unquoted marker: `@dev`
                # written bare is PowerShell's splatting syntax, so it expands
                # an undefined variable and arrives as nothing at all. Saying
                # so beats "nothing selected", which names the wrong problem.
                if (-not $global:_TDD_INDEX_RESOLVED) {
                    _tdd_error "--py-default-idx needs a URL (a bare @dev is PowerShell splatting and arrives empty -- quote it: --py-default-idx '@dev')"
                    return
                }
                $pyDefault = $global:_TDD_INDEX_RESOLVED; $i += $global:_TDD_CONSUMED; continue
            }
            default {
                if (-not (_tdd_common_opt $Argv $i)) {
                    _tdd_error "unknown option: $($Argv[$i]) (see --help)"
                    return
                }
                $i += $global:_TDD_CONSUMED
            }
        }
    }
    if ($global:_TDD_HELP) { _tdd_vars_help_set; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    if ($value -and -not $crypto) {
        # Before "nothing selected": --value says what to set, not that anything is.
        _tdd_error '--value is the crypto key itself; pass --crypto to say so'
        return
    }
    if (-not $crypto -and -not $secrets -and -not $pypiTwine -and -not $pyExtra -and -not $pyDefault) {
        _tdd_error 'nothing selected: --crypto, --secrets, --pypi-twine, --py-idx URL and/or --py-default-idx URL (see --help)'
        return
    }
    if ($vault) {
        # One form for both selections: a provider ref, which is what
        # `_1p fetch` takes for each. 1p is the only provider.
        if ($vault -notlike '1p:?*') {
            _tdd_error "--vault takes a vault as a provider ref, 1p:NAME (got: $vault)"
            return
        }
    }
    if ($value) {
        if ($vault -or $item -or $field) {
            _tdd_error '--value is the key itself; --vault, --item and --field say where to read one instead'
            return
        }
        # The value never reaches an event or the failure log; only its length.
        if ($value.Length -lt $global:_TDD_CRYPTO_MIN) {
            _tdd_error "--value must be at least $($global:_TDD_CRYPTO_MIN) characters, got $($value.Length)"
            return
        }
    }
    $kept = ''
    if ($crypto -and $value) {
        # Given, not fetched: no trip to 1Password, so nothing to keep or force.
        _tdd_vars_put $global:_TDD_VARS_CRYPTO $value
        $setNames.Add($global:_TDD_VARS_CRYPTO)
        $crypto = $false
    }
    if ($crypto -and (_tdd_vars_get $global:_TDD_VARS_CRYPTO) -and -not $force) {
        # Already there: no trip to 1Password (a signed-in `op` is not a given
        # in every shell); --force refetches.
        $kept = $global:_TDD_VARS_CRYPTO
        # The ok says it when the key was the only selection; otherwise say it here.
        if ($secrets -or $pypiTwine -or $pyExtra -or $pyDefault) {
            _tdd_info "$($global:_TDD_VARS_CRYPTO) is already set; not fetched (use --force to refetch)"
        }
        $crypto = $false
    }
    # Every 1Password selection is one fetch: one child, one trip through `op` sign-in.
    $fetchArgs = @()
    if ($crypto) {
        $v = if ($vault) { $vault } else { $global:_TDD_VAULT_CRYPTO }
        $fetchArgs += "--crypto=$v"
        if ($item) { $fetchArgs += "--item=$item" }
        if ($field) { $fetchArgs += "--field=$field" }
    }
    if ($secrets) {
        $v = if ($vault) { $vault } else { $global:_TDD_VAULT_SECRETS }
        $fetchArgs += "--secrets=$v"
    }
    if ($pypiTwine) {
        $v = if ($vault) { $vault } else { $global:_TDD_VAULT_CRYPTO }
        $fetchArgs += "--pypi-twine=$v"
    }
    if ($fetchArgs.Count -gt 0) {
        _tdd_info "tdd _1p fetch $($fetchArgs -join ' ')"
        _tdd_vars_apply $fetchArgs $setNames
        if (_tdd_failed) { return }
    }
    if ($pyExtra) {
        foreach ($v in $global:_TDD_VARS_PY_EXTRA) {
            _tdd_vars_put $v $pyExtra
            $setNames.Add($v)
        }
        _tdd_vars_put $global:_TDD_VARS_PY_STRATEGY $global:_TDD_VARS_PY_STRATEGY_VALUE
        $setNames.Add($global:_TDD_VARS_PY_STRATEGY)
    }
    if ($pyDefault) {
        foreach ($v in $global:_TDD_VARS_PY_DEFAULT) {
            _tdd_vars_put $v $pyDefault
            $setNames.Add($v)
        }
    }
    # Built by assignment and not by an `if` expression: a one-element array
    # coming out of a statement block is unrolled to the element, and "kept"
    # would then be a string where the POSIX half writes a list of one.
    $keptList = @()
    if ($kept) { $keptList = @($kept) }
    if ($setNames.Count -eq 0 -and $kept) {
        _tdd_ok "$kept already set; nothing fetched" ([ordered]@{ set = @(); kept = $keptList })
    } else {
        $tail = if ($kept) { " ($kept already set, kept)" } else { '' }
        _tdd_ok "set $($setNames.Count) variable(s) in this shell: $($setNames -join ' ')$tail" ([ordered]@{
                set  = @($setNames)
                kept = $keptList
            })
    }
}

# ---------------------------------------------------------------- unset

function _tdd_vars_unset {
    param([string[]]$Argv)
    $crypto = $false
    $secrets = $false
    $pypiTwine = $false
    $td = $false
    $prefixes = @()
    $pyExtra = $false
    $pyDefault = $false
    for ($i = 0; $i -lt $Argv.Count; ) {
        switch -Regex ($Argv[$i]) {
            '^--crypto$' { $crypto = $true; $i++; continue }
            '^--secrets$' { $secrets = $true; $i++; continue }
            '^--pypi-twine$' { $pypiTwine = $true; $i++; continue }
            '^--td$' { $td = $true; $i++; continue }
            '^--vars(=.*)?$' {
                if (-not (_tdd_optval $Argv $i)) { _tdd_error '--vars needs a PREFIX'; return }
                $prefixes += $global:_TDD_OPTVAL; $i += $global:_TDD_CONSUMED; continue
            }
            '^--py-idx(=.*)?$' { $pyExtra = $true; $i++; continue }
            '^--py-default-idx(=.*)?$' { $pyDefault = $true; $i++; continue }
            default {
                if (-not (_tdd_common_opt $Argv $i)) {
                    _tdd_error "unknown option: $($Argv[$i]) (see --help)"
                    return
                }
                $i += $global:_TDD_CONSUMED
            }
        }
    }
    if ($global:_TDD_HELP) { _tdd_vars_help_unset; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    if (-not $crypto -and -not $secrets -and -not $pypiTwine -and -not $td -and $prefixes.Count -eq 0 -and -not $pyExtra -and -not $pyDefault) {
        _tdd_error 'nothing selected: --crypto, --secrets, --pypi-twine, --td, --vars PREFIX, --py-idx and/or --py-default-idx (see --help)'
        return
    }
    $wanted = [System.Collections.Generic.List[string]]::new()
    if ($crypto) { $wanted.Add($global:_TDD_VARS_CRYPTO) }
    if ($secrets) {
        if (-not (_tdd_vars_get $global:_TDD_VARS_SYSTEMS)) {
            _tdd_warn "$($global:_TDD_VARS_SYSTEMS) is not set: no secrets are recorded in this shell, none removed"
        } else {
            foreach ($p in (_tdd_vars_words (_tdd_vars_get $global:_TDD_VARS_SYSTEMS))) {
                foreach ($n in (_tdd_vars_names "^${p}__")) { $wanted.Add($n) }
            }
            $wanted.Add($global:_TDD_VARS_SYSTEMS)
        }
    }
    if ($pypiTwine) { foreach ($n in $global:_TDD_VARS_PYPI_TWINE) { $wanted.Add($n) } }
    if ($td) { foreach ($n in (_tdd_vars_names '^TD_')) { $wanted.Add($n) } }
    foreach ($p in $prefixes) {
        foreach ($n in (_tdd_vars_names "^${p}")) { $wanted.Add($n) }
    }
    if ($pyExtra) {
        foreach ($n in ($global:_TDD_VARS_PY_EXTRA + $global:_TDD_VARS_PY_EXTRA_LEGACY + @($global:_TDD_VARS_PY_STRATEGY))) { $wanted.Add($n) }
    }
    if ($pyDefault) {
        foreach ($n in ($global:_TDD_VARS_PY_DEFAULT + $global:_TDD_VARS_PY_DEFAULT_LEGACY)) { $wanted.Add($n) }
    }
    # Only what is actually set counts as unset; dedupe (--vars TD and --td overlap).
    # TDD_DIR is never unset: it is how `tdd` itself finds its dir in this shell,
    # and a prefix like --vars TD would otherwise take it out.
    $done = [System.Collections.Generic.List[string]]::new()
    foreach ($v in (_tdd_vars_sort $wanted)) {
        if ($v -ceq 'TDD_DIR') {
            _tdd_info 'TDD_DIR kept (tdd needs it; never unset)'
            continue
        }
        if (_tdd_vars_isset $v) {
            _tdd_vars_drop $v
            _tdd_debug "unset $v"
            $done.Add($v)
        }
    }
    if ($done.Count -eq 0) {
        _tdd_ok 'nothing to unset' ([ordered]@{ unset = @() })
    } else {
        _tdd_ok "unset $($done.Count) variable(s): $($done -join ' ')" ([ordered]@{ unset = @($done) })
    }
}

# ---------------------------------------------------------------- tdd-source

# `tdd env tdd-source`: load $TDD_DIR/tdd-source.ps1 again, in this shell.
#
# The file is generated by tdd-install, so unlike every other shell file -- which
# an editable install links straight to the checkout -- a reinstall leaves the
# copy this shell loaded behind. Re-sourcing is what picks the new one up, and
# the whole reason it belongs to `env`: it changes this shell and nothing else
# can. It redefines the very function that is running, which PowerShell allows
# the same way a shell does: the call in flight finishes on the body it started
# with.
#
# The file is the PowerShell loader, not the POSIX one: a `tdd-source.sh` read
# by pwsh is not a shell script, it is a syntax error.
function _tdd_vars_tdd_source {
    param([string[]]$Argv)
    for ($i = 0; $i -lt $Argv.Count; ) {
        if (-not (_tdd_common_opt $Argv $i)) {
            _tdd_error "unknown option: $($Argv[$i]) (see --help)"
            return
        }
        $i += $global:_TDD_CONSUMED
    }
    if ($global:_TDD_HELP) { _tdd_vars_help_tdd_source; return }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    $src = Join-Path $env:TDD_DIR 'tdd-source.ps1'
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) {
        _tdd_error "no $src to source; build the tdd dir first (tdd-install)"
        return
    }
    # The loader's own greeting is for a first source, not for this one: two
    # announcements of one thing, and in --format json a line that is not JSON.
    $env:_TDD_RESOURCING = '1'
    try {
        . $src
    } catch {
        _tdd_error "could not source $src" "$_"
        return
    } finally {
        _tdd_vars_drop '_TDD_RESOURCING'
    }
    $versionFile = Join-Path $env:TDD_DIR 'VERSION'
    $version = '?'
    if (Test-Path -LiteralPath $versionFile) { $version = (Get-Content -LiteralPath $versionFile -Raw).Trim() }
    _tdd_ok "re-sourced $src ($version)" ([ordered]@{ file = $src })
}

# ---------------------------------------------------------------- show

# Is this group asked for? `all` is every one of them.
function _tdd_vars_wanted {
    param([string]$Group, [string]$Which)
    return ($Group -eq 'all' -or $Group -eq $Which)
}

# One `show` line: `NAME=value` when set, `- NAME` when not, indented under its
# group heading -- the `-` is the marker, a set variable gets spaces instead.
# Credentials -- the crypto key and any secret whose name says so (PASSWORD,
# SECRET, TOKEN, KEY, PASS, _PAT) -- are masked unless --reveal.
function _tdd_vars_show_row {
    param(
        [string]$Name, [string]$Group, [bool]$Reveal,
        [System.Collections.Generic.List[string]]$Rows,
        [System.Collections.Generic.List[object]]$Vars
    )
    if (-not (_tdd_vars_isset $Name)) {
        $Rows.Add("  - $Name")
        $Vars.Add([ordered]@{ name = $Name; group = $Group; set = $false })
        return
    }
    # Trailing newlines off, as the POSIX half gets for free from `$(...)`: a
    # PEM ends in one, and a row that ends in a blank line is a row that has
    # broken the listing.
    $val = (_tdd_vars_get $Name).TrimEnd("`n")
    $shown = $val
    if (-not $Reveal) {
        # By name, in every group: TD_BACKENDS_CRYPTO_KEY is as much a secret in
        # the TD group as any <SYSTEM>__PASSWORD is among the secrets, and a
        # masked non-secret costs nothing -- --reveal prints the value.
        $secretish = @('*PASSWORD*', '*SECRET*', '*TOKEN*', '*KEY*', '*PASS*', '*_PAT', '*_PAT_*', '*_PEM*', '*PEM_*')
        $hit = ($Name -ceq $global:_TDD_VARS_CRYPTO)
        foreach ($pattern in $secretish) { if ($Name -clike $pattern) { $hit = $true } }
        # Two characters of the whole value, not of every line of it. The POSIX
        # half masked with `cut -c1-2`, which is line-oriented and handed back
        # the first two characters of each line of a multi-line secret -- four
        # readable lines of a certificate in what is meant to be a mask. Writing
        # this half is what found it; both do the same thing now, and a test
        # runs the masking in both rather than grepping for it.
        if ($hit) { $shown = $val.Substring(0, [Math]::Min(2, $val.Length)) + '****' }
    }
    $Rows.Add("    $Name=$shown")
    $Vars.Add([ordered]@{ name = $Name; group = $Group; set = $true; value = $shown })
}

# A group: its heading, then one row per name, names sorted and deduplicated.
function _tdd_vars_show_group {
    param(
        [string]$Heading, [string]$Group, [string[]]$Names, [bool]$Reveal,
        [System.Collections.Generic.List[string]]$Rows,
        [System.Collections.Generic.List[object]]$Vars
    )
    $Rows.Add("${Heading}:")
    if ($Names.Count -eq 0) {
        $Rows.Add('  (none)')
        return
    }
    foreach ($n in (_tdd_vars_sort $Names)) {
        _tdd_vars_show_row $n $Group $Reveal $Rows $Vars
    }
}

function _tdd_vars_show {
    param([string[]]$Argv)
    $reveal = $false
    $group = 'all'
    for ($i = 0; $i -lt $Argv.Count; ) {
        switch -Regex ($Argv[$i]) {
            '^--reveal$' { $reveal = $true; $i++; continue }
            '^--group(=.*)?$' {
                if (-not (_tdd_optval $Argv $i)) { _tdd_error '--group needs a value'; return }
                $group = $global:_TDD_OPTVAL; $i += $global:_TDD_CONSUMED; continue
            }
            default {
                if (-not (_tdd_common_opt $Argv $i)) {
                    _tdd_error "unknown option: $($Argv[$i]) (see --help)"
                    return
                }
                $i += $global:_TDD_CONSUMED
            }
        }
    }
    if ($global:_TDD_HELP) { _tdd_vars_help_show; return }
    if ($group -cnotin @('all', 'td', 'pypi', 'secrets')) {
        _tdd_error "--group must be all, td, pypi or secrets, got $group"
        return
    }
    _tdd_cmd_check
    if (_tdd_failed) { return }
    $rows = [System.Collections.Generic.List[string]]::new()
    $vars = [System.Collections.Generic.List[object]]::new()
    # TD: everything starting with TD (TD_, TDD_, TDX_, ...) that is set, plus
    # tdd's own private ones below.
    # The crypto key is named even when unset (worth a `-` row: nothing works
    # without it); _TDD_SYSTEMS is bookkeeping, listed only while secrets are loaded.
    if (_tdd_vars_wanted $group td) {
        $names = @($global:_TDD_VARS_CRYPTO)
        if (_tdd_vars_isset $global:_TDD_VARS_SYSTEMS) { $names += $global:_TDD_VARS_SYSTEMS }
        $names += _tdd_vars_names '^TD'
        _tdd_vars_show_group TD td $names $reveal $rows $vars
    }
    if (_tdd_vars_wanted $group pypi) {
        $names = $global:_TDD_VARS_PY_EXTRA + $global:_TDD_VARS_PY_EXTRA_LEGACY +
            @($global:_TDD_VARS_PY_STRATEGY) + $global:_TDD_VARS_PY_DEFAULT + $global:_TDD_VARS_PY_DEFAULT_LEGACY +
            $global:_TDD_VARS_PYPI_TWINE
        _tdd_vars_show_group PyPi pypi $names $reveal $rows $vars
    }
    if (_tdd_vars_wanted $group secrets) {
        $names = @()
        foreach ($p in (_tdd_vars_words (_tdd_vars_get $global:_TDD_VARS_SYSTEMS))) {
            $names += _tdd_vars_names "^${p}__"
        }
        _tdd_vars_show_group Secrets secrets $names $reveal $rows $vars
    }
    _tdd_ok ($rows -join "`n") ([ordered]@{ vars = @($vars); group = $group; revealed = $reveal })
}
