#
# Copyright 2026 Tabsdata Inc.
#

# _common.ps1 -- the plumbing every PowerShell smoke script shares, the twin of
# _common.sh: the same functions under the same names, the same screen and the
# same log. Dot-source it before parsing options, then call `common_init`.
#
# What is an algorithm rather than stage keeping is `tdd _smoke`, written once
# for both families (see _common.sh): this file keeps the stages, the screen and
# the log, and asks `_smoke` for the rest. Ported so far: what smoke-km needs.
# The cluster scripts' port-forward, k8s report and placeholder fills come with
# their own port.
#
# PowerShell differs from bash in three ways that shape this file:
#   - there is no `exec >>LOG`: a stage command's output is redirected to the
#     log where it runs (`*>>`), and a line for the log is appended to it;
#   - a function's success-stream output IS its return value, so a stage
#     command's status travels in $LASTEXITCODE, which the tdd functions and
#     every helper here set, never as output;
#   - `tdd` passes no pipeline input on to tdd-exe (forwarding it would take
#     the console away from every interactive command), so `_smoke`, which
#     reads stdin for some answers, is called through `common_smoke`;
#   - a bare `--` given to a native program is dropped, so it is quoted: '--'.
#
# PowerShell 7.

Set-StrictMode -Off

# The system's temp folder, as Python's tempfile finds it.
$script:COMMON_TMP = [IO.Path]::GetTempPath().TrimEnd([IO.Path]::DirectorySeparatorChar)
$script:COMMON_SCRIPT = [IO.Path]::GetFileNameWithoutExtension($MyInvocation.PSCommandPath)

$script:WINDOW = if ($env:WINDOW) { [int]$env:WINDOW } else { 10 }
# The exit a probe for common_run_retry gives when waiting cannot change its
# answer: the retries stop there instead of spending the rest of the wait.
$script:COMMON_FINAL = 97

# `tdd _smoke ARGS...` with this function's pipeline input as its stdin.
function common_smoke {
    $venv = Join-Path (Join-Path $env:TDD_DIR 'tdd-venvs') 'tdd'
    $exe = _tdd_venv_exe $venv 'tdd-exe'
    if ($MyInvocation.ExpectingInput) {
        $input | & $exe _smoke @args
    } else {
        & $exe _smoke @args
    }
}

function _common_exe {
    _tdd_venv_exe (Join-Path (Join-Path $env:TDD_DIR 'tdd-venvs') 'tdd') 'tdd-exe'
}

function common_init {
    param([string]$Log, [int]$Verbose = 0)
    $script:LOG = $Log
    $script:VERBOSE = $Verbose
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Log) | Out-Null
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $script:TTY = -not [Console]::IsOutputRedirected
    $e = [char]27
    if ($script:TTY -and -not $env:NO_COLOR) {
        $script:BLUE = "$e[38;5;33m"; $script:GREEN = "$e[32m"; $script:RED = "$e[31m"
        $script:YELLOW = "$e[33m"; $script:DIM = "$e[2m"; $script:RESET = "$e[0m"
    } else {
        $script:BLUE = ''; $script:GREEN = ''; $script:RED = ''
        $script:YELLOW = ''; $script:DIM = ''; $script:RESET = ''
    }
    # Lines under the stage header can be collapsed (cursor arithmetic) only on
    # a terminal that is not streaming command output.
    $script:COLLAPSE = $script:TTY -and $Verbose -eq 0
    $script:STAGE_STATUS = @{}
    $script:STAGE_SECONDS = @{}
    $script:STAGE_I = -1
    $script:STAGE_T0 = Get-Date
    $script:STAGE_LINES = 0
    $script:STAGE_CMDS = [Collections.Generic.List[string]]::new()
    $script:STAGE_CMD_STATUS = [Collections.Generic.List[string]]::new()
    $script:STAGE_CONTINUE = $false
    $script:CURRENT = ''
    $script:CONTINUED = 0
    $script:WINDOW_PROC = $null
    $script:CMD_LOG_FROM = 0
    $script:RUN_T0 = Get-Date
    Add-Content -Path $Log -Value '' -NoNewline
}

# Seconds as 1h 2m 3s / 2m 3s / 3s.
function common_duration {
    param([int]$Seconds)
    if ($Seconds -ge 3600) { return '{0}h {1}m {2}s' -f [int][math]::Floor($Seconds / 3600), [int][math]::Floor($Seconds % 3600 / 60), ($Seconds % 60) }
    if ($Seconds -ge 60) { return '{0}m {1}s' -f [int][math]::Floor($Seconds / 60), ($Seconds % 60) }
    return "${Seconds}s"
}

function _common_plain {
    param([string]$Text)
    $Text -replace "$([char]27)\[[0-9;]*m", ''
}

# A line for the screen, and plain (no colour) into the log too, so the log
# reads like the screen.
function common_screen {
    param([string]$Text = '')
    [Console]::Out.WriteLine($Text)
    Add-Content -Path $script:LOG -Value (_common_plain $Text)
}

# A line for the log alone: what a stage command says about itself.
function common_log {
    param([string]$Text = '')
    Add-Content -Path $script:LOG -Value $Text
}

# The console's width, re-read where it matters so a resize mid-run is honoured.
function common_width {
    try { $w = [Console]::WindowWidth } catch { $w = 0 }
    if ($w -gt 0) { return $w }
    return 120
}

# Plain text cut to the console width: a line under a stage must not wrap,
# the collapse counts lines.
function common_fit {
    param([string]$Text)
    $width = (common_width) - 6
    if ($Text.Length -gt $width) { return $Text.Substring(0, $width) }
    return $Text
}

# A line under the current stage header, counted for the collapse.
function common_note {
    param([string]$Text)
    common_screen "    $(common_fit $Text)"
    $script:STAGE_LINES += 1
}

# A yellow line that STAYS on the screen: it closes the running stage as ok
# first and prints outside any stage.
function common_remark {
    param([string]$Text)
    common_stage_ok
    common_screen "    $($script:YELLOW)$Text$($script:RESET)"
}

# ---------------------------------------------------------------- window
# The last WINDOW lines the RUNNING COMMAND wrote (`tdd _smoke window`), drawn
# on the console by a process of its own, ended by a stop file.
function common_window_start {
    if (-not $script:COLLAPSE) { return }
    $from = (Get-Item -LiteralPath $script:LOG).Length
    $script:WINDOW_STOP = "$($script:LOG).window-stop"
    Remove-Item -LiteralPath $script:WINDOW_STOP -ErrorAction SilentlyContinue
    $arguments = @(
        '_smoke', 'window', '--log', $script:LOG, '--from', $from, '--lines', $script:WINDOW,
        '--stop', $script:WINDOW_STOP, '--parent', $PID
    )
    if ($script:DIM) { $arguments += '--dim' }
    # stdout carries only its closing answer; stderr, where it draws, is the
    # console it shares
    $script:WINDOW_PROC = Start-Process -FilePath (_common_exe) -ArgumentList $arguments `
        -NoNewWindow -PassThru -RedirectStandardOutput "$($script:LOG).window-out"
}

function common_window_stop {
    if (-not $script:WINDOW_PROC) { return }
    Set-Content -LiteralPath $script:WINDOW_STOP -Value ''
    $script:WINDOW_PROC.WaitForExit()
    Remove-Item -LiteralPath $script:WINDOW_STOP, "$($script:LOG).window-out" -ErrorAction SilentlyContinue
    $script:WINDOW_PROC = $null
    [Console]::Out.Write("$([char]27)[J")
}

# ---------------------------------------------------------------- masking
# A command line as text with every credential masked (`tdd _smoke display`).
function common_display {
    (common_smoke display '--' @args) -join "`n"
}

# ---------------------------------------------------------------- stages
function common_elapsed {
    [int][math]::Floor(((Get-Date) - $script:STAGE_T0).TotalSeconds)
}

# Erase the lines printed under the current header (terminal, non-verbose).
function common_collapse {
    if ($script:COLLAPSE -and $script:STAGE_LINES -gt 0) {
        [Console]::Out.Write("$([char]27)[$($script:STAGE_LINES)A$([char]27)[J")
    }
    $script:STAGE_LINES = 0
}

# The stage's commands, each with its outcome.
function common_recap {
    for ($i = 0; $i -lt $script:STAGE_CMDS.Count; $i++) {
        $mark = switch ($script:STAGE_CMD_STATUS[$i]) {
            'ok' { "$($script:GREEN)✓$($script:RESET)" }
            'failed' { "$($script:RED)✗$($script:RESET)" }
            default { "$($script:YELLOW)·$($script:RESET)" }
        }
        common_screen "    $mark $(common_fit $script:STAGE_CMDS[$i])"
    }
}

# Close the running stage as ok: its command lines collapse into one line.
function common_stage_ok {
    if ($script:STAGE_I -lt 0) { return }
    if ($script:STAGE_STATUS.ContainsKey($script:STAGE_I)) { return }
    $script:STAGE_STATUS[$script:STAGE_I] = 'ok'
    $script:STAGE_SECONDS[$script:STAGE_I] = common_elapsed
    common_collapse
    common_screen "    $($script:GREEN)ok$($script:RESET) ($($script:STAGE_SECONDS[$script:STAGE_I])s)"
}

# Close the running stage as skipped, saying why: what it checks was never set
# up, because an earlier stage failed -- and that failure is already counted.
function common_stage_skip {
    param([string]$Why)
    if ($script:STAGE_I -lt 0) { return }
    if ($script:STAGE_STATUS.ContainsKey($script:STAGE_I)) { return }
    $script:STAGE_STATUS[$script:STAGE_I] = 'skipped'
    $script:STAGE_SECONDS[$script:STAGE_I] = common_elapsed
    common_collapse
    common_screen "    $($script:YELLOW)skipped$($script:RESET) -- $Why"
}

# common_stage [--continue] NAME "what it does"
function common_stage {
    common_stage_ok
    $rest = @($args)
    $script:STAGE_CONTINUE = $false
    if ($rest[0] -eq '--continue') {
        $script:STAGE_CONTINUE = $true
        $rest = @($rest | Select-Object -Skip 1)
    }
    $script:STAGE_I += 1
    $script:CURRENT = $rest[0]
    $script:STAGE_T0 = Get-Date
    $script:STAGE_LINES = 0
    $script:STAGE_CMDS.Clear()
    $script:STAGE_CMD_STATUS.Clear()
    common_screen ''
    common_screen "$($script:BLUE)==> [$($script:STAGE_I + 1)] $($rest[0]) -- $($rest[1])$($script:RESET)   $($script:DIM)$(Get-Date -Format HH:mm:ss)$($script:RESET)"
}

# A stage failed: expand its commands with their outcomes, close it in red,
# then stop -- or, for a --continue stage, record it and carry on.
function common_stage_failed {
    param([string]$Why, [int]$Rc = 1)
    common_window_stop
    $script:STAGE_SECONDS[$script:STAGE_I] = common_elapsed
    common_collapse
    common_recap
    $seconds = $script:STAGE_SECONDS[$script:STAGE_I]
    if ($script:STAGE_CONTINUE) {
        $script:STAGE_STATUS[$script:STAGE_I] = 'continued'
        $script:CONTINUED += 1
        common_screen "    $($script:RED)error$($script:RESET) (${seconds}s) -- $Why"
        common_pointers "log $($script:LOG)"
        common_screen "    $($script:YELLOW)continuing: this stage does not stop the run$($script:RESET)"
        return
    }
    $script:STAGE_STATUS[$script:STAGE_I] = 'failed'
    common_screen "    $($script:RED)error$($script:RESET) (${seconds}s) -- $Why"
    common_pointers
    if (Get-Command common_on_stage_failed -ErrorAction SilentlyContinue) { common_on_stage_failed }
    common_report
    common_screen "$($script:RED)$($script:COMMON_SCRIPT): FAILED at stage $($script:CURRENT)   (log: $($script:LOG))$($script:RESET)"
    exit $Rc
}

# Where to look, printed under a failed command while the run goes on: the log
# files the command itself named (`tdd _smoke pointers`), plus any EXTRA
# "label path" given.
function common_pointers {
    $found = @(common_smoke pointers --log $script:LOG --from $script:CMD_LOG_FROM 2>$null)
    $found += @($args)
    $found = @($found | Where-Object { $_ })
    if (-not $found) { return }
    common_screen "    $($script:YELLOW)look at:$($script:RESET)"
    foreach ($line in $found) {
        # the label may be two words; the path has none
        $cut = $line.LastIndexOf(' ')
        common_screen "      $($script:DIM)$($line.Substring(0, $cut))$($script:RESET)  $($line.Substring($cut + 1))"
    }
}

# Run CMD... in THIS session -- tdd venv/env change it -- its output into the
# log. The status: $LASTEXITCODE, or 1 for a command that failed without one.
function _common_invoke {
    param([object[]]$Command)
    $global:LASTEXITCODE = 0
    $name = $Command[0]
    $rest = @($Command | Select-Object -Skip 1)
    try {
        if ($script:VERBOSE) {
            & $name @rest *>&1 | Tee-Object -FilePath $script:LOG -Append | ForEach-Object { [Console]::Out.WriteLine("$_") }
        } else {
            & $name @rest *>> $script:LOG
        }
        $ok = $?
    } catch {
        common_log "$_"
        return 1
    }
    if ($LASTEXITCODE) { return $LASTEXITCODE }
    if (-not $ok) { return 1 }
    return 0
}

# Run CMD in THIS session. Its status is the stage's: a failure fails it.
function common_run {
    common_run_shown (common_display @args) @args
}

# common_run_shown TEXT CMD... -- common_run, but the stage records and echoes
# TEXT in place of CMD.
function common_run_shown {
    $shown = $args[0]
    $command = @($args | Select-Object -Skip 1)
    $script:STAGE_CMDS.Add($shown)
    $script:STAGE_CMD_STATUS.Add('running')
    common_note "$($script:DIM)`$$($script:RESET) $shown"
    common_log "`$ $shown"
    $script:CMD_LOG_FROM = (Get-Item -LiteralPath $script:LOG).Length
    common_window_start
    $rc = _common_invoke $command
    common_window_stop
    if ($rc -ne 0) {
        $script:STAGE_CMD_STATUS[$script:STAGE_CMD_STATUS.Count - 1] = 'failed'
        common_stage_failed "$shown exited $rc" $rc
        $global:LASTEXITCODE = 1
        return
    }
    $script:STAGE_CMD_STATUS[$script:STAGE_CMD_STATUS.Count - 1] = 'ok'
    $global:LASTEXITCODE = 0
}

# common_run_retry N PAUSE CMD... -- for a probe of something that comes up on
# its own time (a server after start): the command is the readiness check.
function common_run_retry {
    $attempts = [int]$args[0]
    $pause = [int]$args[1]
    $command = @($args | Select-Object -Skip 2)
    $shown = common_display @command
    $script:STAGE_CMDS.Add($shown)
    $script:STAGE_CMD_STATUS.Add('running')
    common_note "$($script:DIM)`$$($script:RESET) $shown   $($script:DIM)(up to $attempts attempts, ${pause}s apart)$($script:RESET)"
    common_log "`$ $shown   (up to $attempts attempts, ${pause}s apart)"
    $script:CMD_LOG_FROM = (Get-Item -LiteralPath $script:LOG).Length
    common_window_start
    for ($attempt = 1; ; $attempt++) {
        $rc = _common_invoke $command
        if ($rc -eq 0) {
            common_window_stop
            $script:STAGE_CMD_STATUS[$script:STAGE_CMD_STATUS.Count - 1] = 'ok'
            if ($attempt -gt 1) { common_note "succeeded on attempt $attempt" }
            $global:LASTEXITCODE = 0
            return
        }
        if ($rc -eq $script:COMMON_FINAL) {
            $script:STAGE_CMD_STATUS[$script:STAGE_CMD_STATUS.Count - 1] = 'failed'
            common_stage_failed "$shown failed on attempt $attempt/$attempts, and waiting cannot change it" 1
            $global:LASTEXITCODE = 1
            return
        }
        if ($attempt -ge $attempts) {
            $script:STAGE_CMD_STATUS[$script:STAGE_CMD_STATUS.Count - 1] = 'failed'
            common_stage_failed "$shown failed $attempts times (last exit $rc)" $rc
            $global:LASTEXITCODE = 1
            return
        }
        common_log "attempt $attempt/$attempts failed (exit $rc); retrying in ${pause}s"
        Start-Sleep -Seconds $pause
    }
}

# A stage command's verdict: $LASTEXITCODE, 0 when TRUE.
function common_status {
    param([bool]$Ok)
    $global:LASTEXITCODE = if ($Ok) { 0 } else { 1 }
}

# Stage commands for what a cmdlet does: `common_run` hands a command its
# arguments as values, and a cmdlet reads `-Recurse` given that way as one.
function common_remove_folder {
    param([string]$Folder)
    Remove-Item -LiteralPath $Folder -Recurse -Force -ErrorAction SilentlyContinue
    common_status (-not (Test-Path -LiteralPath $Folder))
}

# common_file_exists PATH -- PATH is a file (the sh side's `test -r`).
function common_file_exists {
    param([string]$Path)
    common_status (Test-Path -LiteralPath $Path -PathType Leaf)
}

# common_variable_set NAME -- NAME holds a value in this session's environment;
# the value itself is never shown.
function common_variable_set {
    param([string]$Name)
    $set = [bool][Environment]::GetEnvironmentVariable($Name)
    Write-Output "${Name}: $(if ($set) { 'set' } else { 'not set' })"
    common_status $set
}

# common_venv_program NAME -- NAME is a program of the active venv, beside its
# python: uv only WARNS about a nonexistent extra.
function common_venv_program {
    param([string]$Name)
    $python = (Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    $suffix = if ($IsWindows) { '.exe' } else { '' }
    $program = if ($python) { Join-Path (Split-Path -Parent $python) "$Name$suffix" } else { '' }
    Write-Output "program ${Name}: $(if ($program) { $program } else { '(no python on PATH)' })"
    common_status ([bool]$program -and (Test-Path -LiteralPath $program))
}

# ---------------------------------------------------------------- tabsdata instances
# A local instance's processes, found BY NAME (`tdd _smoke`).
function common_instance_pids {
    param([string]$Instance)
    @((common_smoke instance-pids --instance $Instance) -split '\s+' | Where-Object { $_ })
}

function common_instance_running {
    param([string]$Instance)
    (common_instance_pids $Instance).Count -gt 0
}

# common_instance_stop NAME TDD_DIR [TDKSERVER_OPTS...] -- end the km
# processes of an instance a previous run left running, and WAIT until every
# one is gone. Meant for `common_run`.
function common_instance_stop {
    $instance, $tddDir, $options = $args
    common_smoke instance-stop --instance $instance --tdd-dir $tddDir '--' @options
}

# common_instance_gone NAME -- no km process of the instance left and no
# instance folder. Meant for `common_run`.
function common_instance_gone {
    param([string]$Instance)
    common_smoke instance-gone --instance $Instance
}

# common_tdkserver_pods_running NAME SERVICE... -- every SERVICE has a
# Running, Ready pod in `tdd tdkserver status`. Meant for `common_run_retry`.
function common_tdkserver_pods_running {
    $instance, $services = $args
    $out = (tdd tdkserver status --instance $instance --accept-terms y 2>&1 | Out-String)
    if ($LASTEXITCODE) {
        Write-Output $out
        Write-Output 'tdkserver status failed'
        common_status $false
        return
    }
    $verdict = ($out | common_smoke pods-ready --instance $instance @services) -join ''
    common_status ($verdict -eq 'ready')
}

function common_worker_logs_live {
    param([string]$Kubeconfig, [string]$Context, [string]$Namespace, [string]$ProfileName, [string]$Project, [string]$Dir)
    $listing = (tdd tdk worker list --profile $ProfileName --proj $Project --format json | Out-String)
    if ($LASTEXITCODE) {
        Write-Output 'tdk worker list failed'
        common_status $false
        return
    }
    $ids = @($listing | common_smoke finished-workers | Where-Object { $_ })
    if ($ids.Count -eq 0) {
        Write-Output "no finished worker in $Project yet"
        common_status $false
        return
    }
    $pods = (kubectl --kubeconfig $Kubeconfig --context $Context --namespace $Namespace `
            get pods --selector tabsdata.com/worker-id --output json | Out-String)
    if ($LASTEXITCODE) {
        Write-Output 'kubectl get pods failed'
        common_status $false
        return
    }
    $ended = @($pods | common_smoke live-workers --workers ($ids -join ' ') | Where-Object { $_ })
    if ($ended.Count -eq 0) {
        Write-Output "no finished worker of $Project has an ended pod left to read"
        common_status $false
        return
    }
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    Remove-Item -Path (Join-Path $Dir '*.live') -ErrorAction SilentlyContinue
    foreach ($id in $ended) {
        $log = (tdd tdk worker logs --profile $ProfileName --worker $id | Out-String)
        if ($LASTEXITCODE) {
            Write-Output "tdk worker logs --worker $id failed"
            common_status $false
            return
        }
        Set-Content -Path (Join-Path $Dir "$id.live") -Value $log -NoNewline
    }
    $pods = (kubectl --kubeconfig $Kubeconfig --context $Context --namespace $Namespace `
            get pods --selector tabsdata.com/worker-id --output json | Out-String)
    if ($LASTEXITCODE) {
        Write-Output 'kubectl get pods failed'
        common_status $false
        return
    }
    $kept = @($pods | common_smoke live-workers --workers ($ended -join ' ') | Where-Object { $_ })
    foreach ($id in $ended) {
        $file = Join-Path $Dir "$id.live"
        if ($kept -notcontains $id) {
            Write-Output "worker ${id}: its pod went during the read, which may have come from the archive"
            Remove-Item -Path $file -ErrorAction SilentlyContinue
            continue
        }
        $verdict = (Get-Content -Raw -Path $file | common_smoke live-log --worker $id) -join ''
        if ($verdict -ne 'ready') {
            common_status $false
            return
        }
        Write-Output "worker ${id}: live log in $file"
    }
    if (-not (Get-ChildItem -Path (Join-Path $Dir '*.live') -ErrorAction SilentlyContinue)) {
        Write-Output 'no live log kept'
        common_status $false
        return
    }
    common_status $true
}
function common_worker_logs_archived {
    param([string]$ProfileName, [string]$Project, [string]$Archive, [string]$Dir = '')
    if ($Dir) {
        $ids = @(Get-ChildItem -Path (Join-Path $Dir '*.live') -ErrorAction SilentlyContinue |
                ForEach-Object { $_.BaseName })
    } else {
        $listing = (tdd tdk worker list --profile $ProfileName --proj $Project --format json | Out-String)
        if ($LASTEXITCODE) {
            Write-Output 'tdk worker list failed'
            common_status $false
            return
        }
        $ids = @($listing | common_smoke finished-workers | Where-Object { $_ })
    }
    if ($ids.Count -eq 0) {
        Write-Output "no finished worker in $Project yet"
        common_status $false
        return
    }
    foreach ($id in $ids) {
        $log = (tdd tdk worker logs --profile $ProfileName --worker $id | Out-String)
        if ($LASTEXITCODE) {
            Write-Output "tdk worker logs --worker $id failed"
            common_status $false
            return
        }
        if ($Dir) {
            Set-Content -Path (Join-Path $Dir "$id.archived") -Value $log -NoNewline
            $live = Join-Path $Dir "$id.live"
            $verdict = ($log | common_smoke archived-logs --worker $id --archive $Archive --live $live) -join ''
            if ($verdict -eq 'failed') {
                $global:LASTEXITCODE = $script:COMMON_FINAL
                return
            }
        } else {
            $verdict = ($log | common_smoke archived-logs --worker $id --archive $Archive) -join ''
        }
        if ($verdict -ne 'ready') {
            common_status $false
            return
        }
    }
    common_status $true
}

# common_worker_pods_gone KUBECONFIG CONTEXT NAMESPACE PROFILE PROJECT -- no pod of
# PROJECT's finished workers is left. Read while its pod is there, a worker's
# log is the live one, and an archive that writes the live log's own headers
# (CloudWatch) could not be told from it. Meant for `common_run_retry`: the pods
# go when their Job's time to live runs out.
function common_worker_pods_gone {
    param([string]$Kubeconfig, [string]$Context, [string]$Namespace, [string]$ProfileName, [string]$Project)
    $listing = (tdd tdk worker list --profile $ProfileName --proj $Project --format json | Out-String)
    if ($LASTEXITCODE) {
        Write-Output 'tdk worker list failed'
        common_status $false
        return
    }
    $ids = @($listing | common_smoke finished-workers | Where-Object { $_ })
    if ($ids.Count -eq 0) {
        Write-Output "no finished worker in $Project yet"
        common_status $false
        return
    }
    $pods = (kubectl --kubeconfig $Kubeconfig --context $Context --namespace $Namespace `
            get pods --selector tabsdata.com/worker-id --output json | Out-String)
    if ($LASTEXITCODE) {
        Write-Output 'kubectl get pods failed'
        common_status $false
        return
    }
    $verdict = ($pods | common_smoke worker-pods-gone --workers ($ids -join ' ')) -join ''
    common_status ($verdict -eq 'ready')
}

# common_tdkserver_expect NAME running|stopped -- `tdd tdkserver status`
# asserting the state a stage just produced (`tdd _smoke instance-state`).
# Meant for `common_run`.
function common_tdkserver_expect {
    param([string]$Instance, [string]$Expect)
    $out = (tdd tdkserver status --instance $Instance --accept-terms y 2>&1 | Out-String)
    $rc = $LASTEXITCODE
    Write-Output $out
    if ($rc) {
        Write-Output "tdkserver status exited $rc"
        common_status $false
        return
    }
    $found = ($out | common_smoke instance-state --instance $Instance) -join ''
    if ($found -ne $Expect) {
        Write-Output "instance $Instance is $found, expected $Expect"
        common_status $false
        return
    }
    Write-Output "instance $Instance is $Expect, as expected"
    common_status $true
}

# ---------------------------------------------------------------- help, index
# common_help REQUIRED -- paint a help page read from the pipeline the way
# every tdd command paints one (`tdd _smoke paint-help`). --help is read while
# the options are, before the script loads tdd, so it is loaded here from the
# tdd dir known so far; without one the page is printed as it is.
function common_help {
    param([string]$Required = '')
    $page = ($input | Out-String).TrimEnd("`r", "`n")
    if (-not (Get-Command tdd -ErrorAction SilentlyContinue) -and $script:TDD_DIR_OPT -and
        (Test-Path (Join-Path $script:TDD_DIR_OPT 'tdd-source.ps1'))) {
        . (Join-Path $script:TDD_DIR_OPT 'tdd-source.ps1') *> $null
    }
    if (-not (Get-Command tdd -ErrorAction SilentlyContinue)) { return $page }
    $flags = @('--required', $Required)
    # PowerShell holds the stdout of what it runs: the decision is made here
    if (-not [Console]::IsOutputRedirected -and -not $env:NO_COLOR) { $flags += '--tty' }
    ($page | common_smoke paint-help @flags) -join "`n"
}

# common_resolve_uv_index VALUE -- the URL VALUE stands for (`tdd _smoke
# uv-index`); an unknown `@marker` is refused, exiting the script.
function common_resolve_uv_index {
    param([string]$Value)
    $url = (common_smoke uv-index --value $Value) -join ''
    if ($Value -and -not $url) {
        [Console]::Error.WriteLine("$($script:COMMON_SCRIPT): unknown --uv-index marker: $Value (@dev, @dev:NAME, @local[::PORT][:NAME], @prod, or a URL)")
        exit 1
    }
    $url
}

# common_xp_expand_all -- `--xp-suites ALL` becomes the suite dirs `tdd xp
# list-suites` reports, in SUITE_LIST and STAGE_NAMES (see _common.sh).
function common_xp_expand_all {
    if ($script:SUITE_LIST.Count -ne 1) { return }
    $all = $script:SUITE_LIST[0]
    if ($all.ToUpper() -ne 'ALL') { return }
    $dirs = @((tdd xp list-suites --format json | common_smoke event-field --field dirs) | Where-Object { $_ })
    if (-not $dirs) {
        common_screen "$($script:RED)$($script:COMMON_SCRIPT): --xp-suites ${all}: tdd xp list-suites named no suite dir$($script:RESET)"
        exit 1
    }
    $script:SUITE_LIST = [Collections.Generic.List[string]]::new([string[]]$dirs)
    $names = [Collections.Generic.List[string]]::new()
    foreach ($name in $script:STAGE_NAMES) {
        if ($name -eq "xp-$all") {
            foreach ($dir in $dirs) { $names.Add("xp-$dir") }
        } else {
            $names.Add($name)
        }
    }
    $script:STAGE_NAMES = $names
    common_screen "  --xp-suites $all -> $($dirs -join ' ')"
}

# ---------------------------------------------------------------- report
# common_tabsdata_setup_info common_screen|common_note -- what the setup looks
# like right now: only what EXISTS (see _common.sh).
function common_tabsdata_setup_info {
    param([string]$Out = 'common_screen')
    $any = $false
    $running = 'not running'
    $instanceDir = Join-Path (Join-Path (Join-Path $HOME '.tabsdata') 'instances') $script:INSTANCE
    $venvDir = Join-Path (Join-Path (Join-Path $script:TDD_DIR_OPT 'managed-venvs') $script:VENV_TYPE) $script:VENV
    $venvRm = ''
    if (Test-Path $venvDir) {
        $any = $true
        $venvRm = "; tdd venv delete --name $($script:VENV)"
    }
    if (Test-Path $instanceDir) {
        $any = $true
        $pids = common_instance_pids $script:INSTANCE
        if ($pids.Count -gt 0) { $running = "running ($($pids.Count) processes), server http://$($script:SERVER)" }
        & $Out "instance   $($script:INSTANCE) -- $running; folder $instanceDir"
    }
    if (Test-Path $venvDir) { & $Out "venv       $($script:VENV) ($($script:VENV_TYPE)) at $venvDir" }
    $profileOpt = if ($script:PROFILE_NAME) { " --profile $($script:PROFILE_NAME)" } else { '' }
    if (Test-Path $instanceDir) {
        & $Out "use them   `$env:_TDD_VENV = '$($script:VENV)'; tdd tdk status$profileOpt; tdd tdkserver status --instance $($script:INSTANCE) --accept-terms y"
        & $Out "stop       `$env:_TDD_VENV = '$($script:VENV)'; tdd tdkserver stop --instance $($script:INSTANCE) -y --accept-terms y"
        & $Out "remove     `$env:_TDD_VENV = '$($script:VENV)'; tdd tdkserver delete --instance $($script:INSTANCE) --trash true -y --accept-terms y$venvRm"
    } elseif (Test-Path $venvDir) {
        & $Out "remove     tdd venv delete --name $($script:VENV)"
    }
    foreach ($d in @($script:SMOKE_DOMAINS)) {
        if (-not $d) { continue }
        $any = $true
        & $Out "domain     $d -- tdd domain destroy --domain $d --force"
    }
    foreach ($x in @($script:XP_PROJECTS)) {
        if (-not $x) { continue }
        $any = $true
        & $Out "xp         $x -- tdd xp destroy-project --project $x --force; tdd xp destroy-domains --suite-run $x --force; tdd xp destroy-instance --suite-run $x"
    }
    if (-not $any) { & $Out 'nothing    this run had built no instance, venv or domain yet' }
    if ($script:NAMES_PREFIX) {
        & $Out "all names  start with $($script:NAMES_PREFIX): tdd domain list, tdd xp list-instances, Get-ChildItem ~/.tabsdata/instances"
    }
}

# The default `common_on_stage_failed`: a failed run leaves everything
# standing; say what and how to reach it.
function common_on_stage_failed {
    if (-not $script:INSTANCE) { return }
    common_screen ''
    common_screen "$($script:COMMON_SCRIPT): left for you to look at"
    common_tabsdata_setup_info common_indented
}

function common_indented {
    param([string]$Text)
    common_screen "  $Text"
}

# Every stage, one line each, then the total run time.
function common_report {
    common_screen ''
    common_screen "$($script:COMMON_SCRIPT): stages"
    $i = 0
    foreach ($name in $script:STAGE_NAMES) {
        $status = $script:STAGE_STATUS[$i]
        $secs = $script:STAGE_SECONDS[$i]
        switch ($status) {
            'ok' { common_screen "  $($script:GREEN)✓$($script:RESET) $name$(if ($null -ne $secs) { " (${secs}s)" })" }
            'failed' { common_screen "  $($script:RED)✗$($script:RESET) $name (failed$(if ($null -ne $secs) { " after ${secs}s" }))" }
            'continued' { common_screen "  $($script:YELLOW)✗$($script:RESET) $name (failed after ${secs}s, continued)" }
            'skipped' { common_screen "  $($script:YELLOW)·$($script:RESET) $name (skipped)" }
            default { common_screen "  $($script:YELLOW)·$($script:RESET) $name (not done)" }
        }
        $i += 1
    }
    $total = [int][math]::Floor(((Get-Date) - $script:RUN_T0).TotalSeconds)
    common_screen "$($script:COMMON_SCRIPT): total $(common_duration $total), log $($script:LOG)"
}

# The end: close the last stage, report, verdict.
function common_finish {
    common_stage_ok
    common_report
    if ($script:CONTINUED -gt 0) {
        common_screen "$($script:YELLOW)$($script:COMMON_SCRIPT): COMPLETED, $($script:CONTINUED) stage(s) failed and were continued   (log: $($script:LOG))$($script:RESET)"
    } else {
        common_screen "$($script:GREEN)$($script:COMMON_SCRIPT): ALL STAGES OK   (log: $($script:LOG))$($script:RESET)"
    }
    exit 0
}
