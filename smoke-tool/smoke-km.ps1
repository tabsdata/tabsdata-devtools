#
# Copyright 2026 Tabsdata Inc.
#

# Tabsdata Kminus smoke test.
#
# The PowerShell 7 twin of smoke-km.sh: the same stages, names and options.
# Every name this run creates starts with sm_<NAME> (--name): the instance and
# the venv ARE sm_<NAME>; domains and xp instances/projects are sm_<NAME>__<what>.
# Arguments are read from $args: `pwsh -File` binds a `-`-led one to a param()
# block by name.

$ErrorActionPreference = 'Continue'
$HERE = $PSScriptRoot
# dot-sourced before the arguments are read, so --help is painted like a tdd command
. (Join-Path $HERE '_common.ps1')

# The same contract as the cluster flavours, minus the three that name a cluster
# a kminus run does not have: it brings its own.
$REQUIRED_OPTIONS = '--name --td-version'

function usage {
    @'
usage: smoke-km.ps1 --name NAME --td-version VERSION
                    [--uv-index URI] [--td-storage fs|aws|azure|gcs] [--llm-domain SYSTEM]
                    [--td-extras EXTRAS] [--venv-type uv|pyenv|conda] [--py-version VERSION]
                    [--port PORT] [--xp-suites LIST] [--expect-pods LIST] [--force] [--keep]
                    [--profile NAME] [--log FILE] [--tdd-dir DIR] [--verbose]

Tabsdata Kminus smoke test.

options:
  --name NAME         REQUIRED: the run's name, alphanumeric. Everything created is
                      sm_NAME -- the tdkserver instance and the managed venv -- or
                      sm_NAME__<what>: the domains and the xp instances/projects
  --td-version VERSION
                      REQUIRED: the tabsdata release to install, tabsdata[EXTRAS]==VERSION
  --td-storage STORAGE
                      where the instance keeps its storage: fs is tabsdata's
                      own, a folder of the instance; aws, azure or gcs is a
                      domain on that cloud's storage system (s3, azureblob or
                      gcs, which must be in the tdd store), created as
                      sm_NAME__<system> and handed to quickstart as the ROOT,
                      BUNDLES and IMAGES mounts under the domain's URI
                      (--config @stub, the credentials as env: references);
                      the domain is destroyed at the end unless --keep. The
                      clouds need tabsdata 2.3.0 or newer (default: fs)
  --td-extras EXTRAS
                      the extras to install (default: all). tabsdata is a
                      meta-package: without the right extras (server, cli,
                      conn-*, ...) the venv has no working tdkserver
  --venv-type TYPE    uv, pyenv or conda (default: uv; pyenv and conda are not
                      supported on Windows)
  --py-version VERSION
                      interpreter for the venv (default: 3.12.13)
  --port PORT         base port for the instance (default: 10000; one per
                      script -- km 10000, eks 11000, aks 12000, gke 13000 --
                      so two runs on one machine never fight over it)
  --uv-index URI      the Python package index, used by the tabsdata install
                      (uv --index, unsafe-best-match) and passed to tdkserver
                      quickstart --uv-index for the instance's pods
                      URI is a URL, or @dev for the development index
                      (https://d3mm0r95u5i3hf.cloudfront.net/simple/), @dev:NAME
                      for namespace NAME on it (.../NAME/, what tdd pypi push
                      --at NAME publishes), @local[::PORT][:NAME] for tdd
                      pypi serve here (http://localhost:PORT/NAME/, PORT
                      8000 and NAME simple unless given) or @prod for the
                      published one (https://pypi.tabsdata.com/simple/)
                      (default: none -- whatever uv is already configured with)
  --xp-suites LIST    comma-separated xp suite selectors to run, one stage each;
                      <type>/<name> for one definition, <type> for every
                      definition in that dir, ALL for every suite dir --
                      see `tdd xp list-suites`
                      (default: test,tableframe_api,dataquality,grok,
                      container-connectors,cdc,kafka,cloud-connectors)
  --llm-domain SYSTEM
                      create a domain on that system (sm_NAME__<system>; the system
                      must be in the tdd store), read its API key and hand it to
                      quickstart as --config <llm>-key=env:LLM__API_KEY (2.2.0 and
                      older: --<llm>-key), so the aiagent works; the domain
                      is destroyed at the end unless --keep (default: no LLM)
  --expect-pods LIST  comma-separated service names whose pods must be Running
                      and Ready after quickstart and after start, per
                      `tdkserver status` (default: srv-apiserver,srv-database)
  --force, -f         a venv or instance named sm_NAME already existing is an
                      error unless this is given: then the venv is recreated and
                      the previous instance stopped and removed first (default: fail)
  --keep              on success, leave the whole setup as it is at the end:
                      the instance running and logged in, the venv in place, the
                      storage and LLM domains, and -- passed on as `xp one-shot
                      --keep` -- every xp instance/project and its domains
                      (default: no -- the running instance is stopped and
                      trashed, and the venv deleted; a failed run always leaves
                      everything standing)
  --profile NAME      the tdk connection profile every `tdk` call and every xp
                      suite uses (tdk COMMAND --profile NAME), so this run's
                      login never replaces another session's on the same account
                      (default: sm_NAME)
  --log FILE          log file (default: <temp>/smoke-<instance>-<start time>.log;
                      <temp> is the system's temp folder)
  --tdd-dir DIR       the tdd dir to load (default: $env:TDD_DIR, else ~/.tdd)
  --verbose           show every command's output on the screen as it happens
                      (default: a rolling window of the last 10 log lines,
                      and a stage's commands collapse into `ok` when it passes)
  --help, -h          this help

The drivers added to the instance's fn and ag venvs (tdkserver venv update):
  pymysql==1.2.3  psycopg2-binary==2.9.12  oracledb==3.2.0
'@ | common_help $REQUIRED_OPTIONS
}

function fail_usage {
    param([string]$Text)
    [Console]::Error.WriteLine("smoke-km: $Text")
    exit 1
}

$NAME = ''                  # required; everything is sm_$NAME
$TD_STORAGE = 'fs'          # --td-storage: fs, or aws|azure|gcs for a domain on that cloud's storage
$LLM_SYSTEM = ''            # --llm-domain: none unless asked for
$EXPECT_PODS = 'srv-apiserver,srv-database'
$VENV_TYPE = 'uv'
$PYTHON = '3.12.13'
$TD_VERSION = ''            # required
$TD_EXTRAS = 'all'
$PORT = '10000'             # --port: the instance's base port, one per script
$UV_INDEX_URI = ''          # --uv-index as given, resolved below; never uv's own UV_INDEX
$SUITES = 'test,tableframe_api,dataquality,grok,container-connectors,cdc,kafka,cloud-connectors'
$FORCE = $false
$KEEP = $false
$LOG_OPT = ''
$PROFILE_NAME = ''          # --profile ($PROFILE is PowerShell's own); defaults to $BASE
$VERBOSE_OPT = 0
$TDD_DIR_OPT = if ($env:TDD_DIR) { $env:TDD_DIR } else { Join-Path $HOME '.tdd' }
$REQUIREMENTS = @('pymysql==1.2.3', 'psycopg2-binary==2.9.12', 'oracledb==3.2.0')

$valued = @{
    '--name' = 'NAME'; '--llm-domain' = 'LLM_SYSTEM'; '--expect-pods' = 'EXPECT_PODS'
    '--venv-type' = 'VENV_TYPE'; '--py-version' = 'PYTHON'; '--td-version' = 'TD_VERSION'
    '--td-storage' = 'TD_STORAGE'
    '--td-extras' = 'TD_EXTRAS'; '--port' = 'PORT'; '--uv-index' = 'UV_INDEX_URI'
    '--xp-suites' = 'SUITES'; '--log' = 'LOG_OPT'; '--profile' = 'PROFILE_NAME'
    '--tdd-dir' = 'TDD_DIR_OPT'
}
for ($i = 0; $i -lt $args.Count; $i++) {
    $a = $args[$i]
    if ($valued.ContainsKey($a)) {
        if ($i + 1 -ge $args.Count) { fail_usage "$a needs a value (see --help)" }
        Set-Variable -Name $valued[$a] -Value $args[$i + 1] -Scope Script
        $i++
    } elseif ($a -in '--force', '-f') {
        $FORCE = $true
    } elseif ($a -eq '--keep') {
        $KEEP = $true
    } elseif ($a -eq '--verbose') {
        $VERBOSE_OPT = 1
    } elseif ($a -in '-h', '--help') {
        usage
        exit 0
    } else {
        fail_usage "unknown option: $a (see --help)"
    }
}

# tdd is loaded as soon as the line is read: resolving --uv-index, the checks,
# the banner and every stage go through it (tdd _smoke).
$loader = Join-Path $TDD_DIR_OPT 'tdd-source.ps1'
if (-not (Test-Path -LiteralPath $loader)) {
    fail_usage "no tdd dir at $TDD_DIR_OPT (tdd-source.ps1 missing); install with cargo make install or pass --tdd-dir"
}
. $loader
$env:TDD_DIR = $TDD_DIR_OPT
$UV_INDEX_URI = common_resolve_uv_index $UV_INDEX_URI

if ($VENV_TYPE -notin 'uv', 'pyenv', 'conda') { fail_usage '--venv-type must be uv, pyenv or conda' }
# --td-storage names the cloud; the system behind it is the tdd store's.
$STORAGE_SYSTEM = switch ($TD_STORAGE) {
    'fs' { '' } 'aws' { 's3' } 'azure' { 'azureblob' } 'gcs' { 'gcs' }
    default { fail_usage '--td-storage must be fs, aws, azure or gcs' }
}
$missing = @()
foreach ($need in $REQUIRED_OPTIONS -split ' ') {
    if ($need -eq '--name' -and -not $NAME) { $missing += $need }
    if ($need -eq '--td-version' -and -not $TD_VERSION) { $missing += $need }
}
if ($missing) { fail_usage "missing required option(s): $($missing -join ' ') (see --help)" }
if ($NAME -notmatch '^[A-Za-z0-9]+$') { fail_usage '--name must be alphanumeric (it becomes part of domain names)' }
# The mounts are set through `quickstart --config @stub`, which came with 2.3.0 (see smoke-km.sh).
if ($STORAGE_SYSTEM -and $TD_VERSION -match '^(1\.|2\.0\.|2\.1\.|2\.2\.)') {
    fail_usage "--td-storage $TD_STORAGE needs tabsdata 2.3.0 or newer; $TD_VERSION keeps its storage in the instance (--td-storage fs)"
}

$BASE = "sm_$NAME"
if (-not $PROFILE_NAME) { $PROFILE_NAME = $BASE }   # the tdk connection is this run's own
$NAMES_PREFIX = $BASE
$INSTANCE = $BASE
$VENV = $BASE
$STAMP = Get-Date -Format 'yyyyMMdd-HHmmss'
$LLM_DOMAIN = if ($LLM_SYSTEM) { "${BASE}__${LLM_SYSTEM}" } else { '' }
$STORAGE_DOMAIN = if ($STORAGE_SYSTEM) { "${BASE}__${STORAGE_SYSTEM}" } else { '' }
$XP_PROJECTS = [Collections.Generic.List[string]]::new()
$SMOKE_DOMAINS = [Collections.Generic.List[string]]::new()
$LOGS_PROJECT = "${BASE}__logs"   # the worker-logs stage's own xp run, kept until its logs are read
$LOGS_SETUP = $false              # true once that run is set up: the cleanup removes its domains
$EXPECT_POD_LIST = @($EXPECT_PODS -split ',' | Where-Object { $_ })
$LOG = if ($LOG_OPT) { $LOG_OPT } else { Join-Path $COMMON_TMP "smoke-$INSTANCE-$STAMP.log" }
$WORK = Join-Path $COMMON_TMP "smoke-$INSTANCE-$STAMP.$([IO.Path]::GetRandomFileName().Substring(0, 4))"
New-Item -ItemType Directory -Force -Path $WORK | Out-Null
$SERVER = "localhost:$PORT"
$TABSDATA_SPEC = "tabsdata[$TD_EXTRAS]==$TD_VERSION"
$TDK_OPTS = @('-y', '--accept-terms', 'y')   # every tdkserver call accepts the terms
$INDEX_OPTS = if ($UV_INDEX_URI) { @('--index', $UV_INDEX_URI, '--index-strategy', 'unsafe-best-match') } else { @() }
$SUITE_LIST = [Collections.Generic.List[string]]::new([string[]]@($SUITES -split ',' | Where-Object { $_ }))
if ($SUITE_LIST.Count -eq 0) { fail_usage '--xp-suites needs at least one selector' }
$STAGE_NAMES = [Collections.Generic.List[string]]::new([string[]]@('unset-td', 'unset-pypi', 'set-crypto'))
# See the set-pypi stage below: only when there is an index to put back.
if ($UV_INDEX_URI) { $STAGE_NAMES.Add('set-pypi') }
foreach ($s in 'systems', 'pycache', 'clean-previous', 'create-venv', 'install') { $STAGE_NAMES.Add($s) }
if ($TD_VERSION -eq '2.0.2') { $STAGE_NAMES.Add('cdc-driver') }
if ($STORAGE_SYSTEM) { $STAGE_NAMES.Add('storage-domain') }
if ($LLM_SYSTEM) { $STAGE_NAMES.Add('llm-domain') }
foreach ($s in 'quickstart', 'pods-1', 'login-1', 'stop-1', 'venv-update', 'start', 'pods-2', 'login-2') { $STAGE_NAMES.Add($s) }
foreach ($suite in $SUITE_LIST) { $STAGE_NAMES.Add("xp-$($suite -replace '/', '_')") }
$STAGE_NAMES.Add('worker-logs')
$STAGE_NAMES.Add('cleanup')

$INSTANCE_DIR = Join-Path (Join-Path (Join-Path $HOME '.tabsdata') 'instances') $INSTANCE

# What this run would create must not already exist -- someone's setup could be
# behind those names. --force says they are ours to replace.
if (-not $FORCE) {
    $existing = @()
    foreach ($d in Get-ChildItem -Directory -Path (Join-Path $TDD_DIR_OPT 'managed-venvs') -ErrorAction SilentlyContinue) {
        $venvDir = Join-Path $d.FullName $VENV
        if (Test-Path $venvDir) { $existing += "venv:$venvDir" }
    }
    if (Test-Path $INSTANCE_DIR) { $existing += "instance:$INSTANCE_DIR" }
    if (common_instance_running $INSTANCE) { $existing += "running-instance:$INSTANCE" }
    if ($existing) {
        [Console]::Error.WriteLine("smoke-km: already exists: $($existing -join ' ')")
        fail_usage 'pass --force to stop/delete and recreate them, or pick another --name'
    }
}

common_init $LOG $VERBOSE_OPT

common_screen 'smoke-km: effective options'
common_screen "  --name              $NAME   -> instance and venv $BASE, domains and xp names ${BASE}__<what>"
common_screen "  --venv-type         $VENV_TYPE"
common_screen "  --py-version    $PYTHON"
common_screen "  --td-version        $TD_VERSION"
common_screen "  --td-extras   $TD_EXTRAS   -> installs $TABSDATA_SPEC"
common_screen "  --td-storage        $TD_STORAGE   -> $(if ($STORAGE_SYSTEM) { "domain $STORAGE_DOMAIN on $STORAGE_SYSTEM, the storage mounts under its URI" } else { "tabsdata's own, a folder of the instance" })"
common_screen "  --port              $PORT   -> server $SERVER"
common_screen "  --uv-index          $(common_display $(if ($UV_INDEX_URI) { $UV_INDEX_URI } else { '(none)' }))"
common_screen "  --xp-suites            $SUITES   -> xp projects ${BASE}__xp_<ts>_<suite>"
common_screen "  worker logs         test/test as $LOGS_PROJECT, read back from the pod runner once its pods are gone"
common_screen "  --llm-domain        $(if ($LLM_SYSTEM) { "$LLM_SYSTEM   -> domain $LLM_DOMAIN" } else { '(none)' })"
common_screen "  --expect-pods       $EXPECT_PODS"
common_screen "  --force             $(if ($FORCE) { 'yes (replace an existing venv/instance)' } else { 'no (an existing venv/instance is an error)' })"
common_screen "  --keep              $(if ($KEEP) { 'yes (also: xp one-shot --keep)' } else { 'no (domains, instance and venv deleted at the end)' })"
common_screen "  --profile           $PROFILE_NAME   -> tdk COMMAND --profile $PROFILE_NAME, xp --profile $PROFILE_NAME"
common_screen "  --log               $LOG"
common_screen "  --tdd-dir           $TDD_DIR_OPT"
common_screen "  --verbose           $(if ($VERBOSE_OPT) { 'yes' } else { "no (rolling window of $WINDOW log lines)" })"
common_screen "  drivers for fn/ag   $($REQUIREMENTS -join ' ')"
common_xp_expand_all


common_stage unset-td 'unset every TD_* variable (tdd env unset --td spares the crypto key)'
common_run tdd env unset --td

common_stage unset-pypi 'unset the Python package index variables'
common_run tdd env unset --py-idx --py-default-idx

common_stage set-crypto 'set _TDD_CRYPTO_KEY'
# 1Password is asked only when the key is unset; `unset --td` spared it. On
# Windows there is no 1Password: the key comes from the secrets file the Mac
# exported (`tdd _1p fetch --crypto --platform windows`), dot-sourced first.
common_run tdd env set --crypto

# `tdkserver quickstart --uv-index URL` does not reach the pods (see
# smoke-km.sh); kminus runs its pods as local processes, so they inherit this
# session's environment, and `--py-idx` is the pair tdkserver meant to set.
if ($UV_INDEX_URI) {
    common_stage set-pypi 'tdkserver workaround: UV_INDEX in this session for the pods to inherit'
    common_run tdd env set --py-idx $UV_INDEX_URI
    common_remark 'workaround: tdkserver quickstart --uv-index does not reach the pods (2.0.0, 2.0.1, 2.1.0); UV_INDEX and UV_INDEX_STRATEGY were set in this session instead, which the kminus pods inherit'
}

common_stage systems 'the dev and fs systems, then every system the suites need must be in the tdd store'
common_run tdd system create --type dev --sys dev --force
# fs needs an explicit absolute root: its default is target/backends/<name>
# against the current folder, which once landed inside a checkout.
common_run tdd system create --type fs --sys fs --sys-path (Join-Path (Join-Path $TDD_DIR_OPT 'data') 'fs-root') --force
foreach ($suite in $SUITE_LIST) {
    common_run tdd xp list-systems --suite $suite
}
# status checks the LLM credential is there without printing it
if ($LLM_SYSTEM) { common_run tdd system status --sys $LLM_SYSTEM }
# and the storage system's, the same way
if ($STORAGE_SYSTEM) { common_run tdd system status --sys $STORAGE_SYSTEM }

common_stage pycache 'purge tabsdata from the uv and pip caches'
# a republished wheel of the same version must not be served stale from the cache
common_run tdd pycache clean

common_stage clean-previous "stop and remove a previous $INSTANCE (--force; nothing exists otherwise)"
# The old instance's processes are waited out first: a km winding down would
# kill the new cluster through reused pid files. Scoped to THIS instance.
common_run common_instance_stop $INSTANCE $TDD_DIR_OPT @TDK_OPTS
if (Test-Path $INSTANCE_DIR) {
    common_run common_remove_folder $INSTANCE_DIR
}

common_stage create-venv "create and activate the managed venv $VENV ($VENV_TYPE, python $PYTHON)"
# Whatever this session was in has to go first: `tdd venv create` refuses under
# a venv tdd did not activate; --force leaves it, and succeeds when there was
# nothing to leave.
common_run tdd venv deactivate --force
$forceOpt = if ($FORCE) { @('--force') } else { @() }
common_run tdd venv create --name $VENV --type $VENV_TYPE --python $PYTHON @forceOpt

common_stage install "uv pip install $TABSDATA_SPEC into $VENV"
# the venv stays active in this session: later stages resolve programs inside it
common_run uv pip install @INDEX_OPTS $TABSDATA_SPEC
foreach ($program in 'tdkserver', 'tdk') {
    common_run common_venv_program $program
}

# tabsdata 2.0.2 ships no psycopg2 with its Postgres connector (see smoke-km.sh).
if ($TD_VERSION -eq '2.0.2') {
    common_stage cdc-driver "tabsdata 2.0.2 workaround: psycopg2-binary into $VENV for the Postgres CDC plugin"
    common_run uv pip install @INDEX_OPTS 'psycopg2-binary==2.9.11'
    common_remark "workaround: tabsdata 2.0.2 ships no psycopg2 with its Postgres connector; psycopg2-binary was installed into $VENV so the CDC plugin loads"
}

# kminus keeps the instance's storage in a folder of its own; a `quickstart
# --config @stub` points the ROOT, BUNDLES and IMAGES mounts at the domain and
# adds the cloud's credential keys as env: references, and object_store's
# request `timeout` under the cloud's prefix, for the image uploads over a
# laptop's uplink (see smoke-km.sh).
$STORAGE_TIMEOUT = '300s'
$STORAGE_OPTS = @()
if ($STORAGE_SYSTEM) {
    common_stage storage-domain "domain $STORAGE_DOMAIN on $STORAGE_SYSTEM, the instance's storage mounts for quickstart"
    common_run tdd domain create --sys $STORAGE_SYSTEM --domain $STORAGE_DOMAIN --force
    $SMOKE_DOMAINS.Add($STORAGE_DOMAIN)
    common_note "tdd domain info --domain $STORAGE_DOMAIN --format export --platform windows --prefix STORD | Invoke-Expression   (the credentials are not shown)"
    (tdd domain info --domain $STORAGE_DOMAIN --format export --platform windows --prefix STORD 2>$null) -join "`n" | Invoke-Expression
    common_run common_variable_set STORD__URI
    # the stub's option lines: the cloud's timeout key, then one per credential key
    switch ($TD_STORAGE) {
        'aws' {
            # the region and the keys are the s3 system's, as the cluster scripts read them
            common_note "tdd system info --sys $STORAGE_SYSTEM --format export --platform windows --prefix STORS | Invoke-Expression   (the keys are not shown)"
            (tdd system info --sys $STORAGE_SYSTEM --format export --platform windows --prefix STORS 2>$null) -join "`n" | Invoke-Expression
            common_run common_variable_set STORS__REGION
            $storageKeys = @("options.aws_timeout: $STORAGE_TIMEOUT", 'options.aws_region: env:STORS__REGION')
            # a system without keys leaves the pods to the AWS credentials this session has
            if ($env:STORS__ACCESS_KEY) {
                $storageKeys += 'options.aws_access_key_id: env:STORS__ACCESS_KEY'
                $storageKeys += 'options.aws_secret_access_key: env:STORS__SECRET_KEY'
            }
        }
        'azure' {
            common_run common_variable_set STORD__ACCOUNT_NAME
            common_run common_variable_set STORD__ACCOUNT_KEY
            $storageKeys = @("options.azure_timeout: $STORAGE_TIMEOUT")
            $storageKeys += 'options.azure_storage_account_name: env:STORD__ACCOUNT_NAME'
            $storageKeys += 'options.azure_storage_account_key: env:STORD__ACCOUNT_KEY'
        }
        'gcs' {
            # the gcs system holds the service-account key inline or as a path to
            # it; the mount wants the JSON, so a path is read here, into the variable
            common_run common_variable_set STORD__SERVICE_ACCOUNT_KEY
            if (-not "$env:STORD__SERVICE_ACCOUNT_KEY".TrimStart().StartsWith('{')) {
                $keyFile = "$env:STORD__SERVICE_ACCOUNT_KEY".Trim() -replace '^~', $HOME
                common_note "the service-account key is a path ($keyFile): its content is what tdkserver gets"
                common_run common_file_exists $keyFile
                $env:STORD__SERVICE_ACCOUNT_KEY = Get-Content -Raw -LiteralPath $keyFile
            }
            $storageKeys = @("options.google_timeout: $STORAGE_TIMEOUT")
            $storageKeys += 'options.google_service_account_key: env:STORD__SERVICE_ACCOUNT_KEY'
        }
    }
    $STORAGE_STUB = Join-Path $WORK 'storage.yaml'
    $storageUri = "$env:STORD__URI".TrimEnd('/')
    $stub = [Collections.Generic.List[string]]::new()
    $stub.Add('files:')
    $stub.Add('  apiserver.storage:')
    foreach ($mount in @('ROOT:data', 'BUNDLES:bundles', 'IMAGES:images')) {
        $id, $folder = $mount -split ':'
        $stub.Add("    storage.mounts[id=$id]:")
        $stub.Add("      uri: `"$storageUri/$folder/`"")
        foreach ($key in $storageKeys) { $stub.Add("      $key") }
    }
    [IO.File]::WriteAllText($STORAGE_STUB, (($stub -join "`n") + "`n"))
    common_note "quickstart --config @${STORAGE_STUB}: the mounts under $storageUri/, a $STORAGE_TIMEOUT request timeout, the credentials as env: references:"
    foreach ($line in $stub) { common_note "    $line" }
    $STORAGE_OPTS = @('--config', "@$STORAGE_STUB")
}

$LLM_KEY_OPTS = @()
if ($LLM_SYSTEM) {
    common_stage llm-domain "domain $LLM_DOMAIN on $LLM_SYSTEM, its API key for quickstart"
    # The key is set in THIS session's environment, never echoed; quickstart
    # reads it from that variable (`--config <llm>-key=env:LLM__API_KEY`), so it
    # is never on a command line. Releases up to 2.2.0 have no --config and take
    # the deprecated --<llm>-key, which the displayed command line masks.
    common_run tdd domain create --sys $LLM_SYSTEM --domain $LLM_DOMAIN --force
    $SMOKE_DOMAINS.Add($LLM_DOMAIN)
    common_note "tdd domain info --domain $LLM_DOMAIN --format export --platform windows --prefix LLM | Invoke-Expression   (the key is not shown)"
    (tdd domain info --domain $LLM_DOMAIN --format export --platform windows --prefix LLM 2>$null) -join "`n" | Invoke-Expression
    common_run common_variable_set LLM__API_KEY
    $LLM_KEY_OPTS = if ($TD_VERSION -match '^(1\.|2\.0\.|2\.1\.|2\.2\.0$)') {
        @("--$LLM_SYSTEM-key", $env:LLM__API_KEY)
    } else {
        @('--config', "$LLM_SYSTEM-key=env:LLM__API_KEY")
    }
}

$quickIndex = if ($UV_INDEX_URI) { @('--uv-index', $UV_INDEX_URI) } else { @() }
$storageSays = if ($STORAGE_DOMAIN) { "on $STORAGE_DOMAIN" } else { 'in the instance' }
$llmSays = if ($LLM_SYSTEM) { ", $LLM_SYSTEM key from $LLM_DOMAIN" } else { ', no LLM key' }
common_stage quickstart "tdkserver quickstart --instance $INSTANCE (kminus, storage $storageSays$llmSays)"
common_run tdd tdkserver quickstart --instance $INSTANCE --provider kminus --port $PORT @quickIndex @STORAGE_OPTS @LLM_KEY_OPTS @TDK_OPTS
common_run common_tdkserver_expect $INSTANCE running

# retried: the pods come up after quickstart/start return
common_stage pods-1 "every expected service pod is Running: $EXPECT_PODS"
common_run_retry 12 5 common_tdkserver_pods_running $INSTANCE @EXPECT_POD_LIST

# retried: the login IS the readiness probe -- start returns before the API answers
common_stage login-1 "tdk login as admin on $SERVER (profile $PROFILE_NAME)"
common_run_retry 30 5 tdd tdk login --profile $PROFILE_NAME --server $SERVER --user admin --password tabsdata

common_stage stop-1 'tdkserver stop'
common_run tdd tdkserver stop --instance $INSTANCE @TDK_OPTS
common_run common_tdkserver_expect $INSTANCE stopped

common_stage venv-update "update the instance's fn and ag venvs with the DB drivers"
# The drivers belong to the INSTANCE's fn/ag venvs, never to the client venv.
$requirementsFile = Join-Path $WORK 'requirements.txt'
Set-Content -LiteralPath $requirementsFile -Value $REQUIREMENTS
common_note "requirements: $($REQUIREMENTS -join ' ')"
# Both venvs in one call: every call rebuilds all three venvs and sends all
# three images to the IMAGES mount, minutes each over a laptop's uplink to a
# cloud domain (--td-storage), so two calls would pay that twice.
common_run tdd tdkserver venv update --instance $INSTANCE --name fn,ag --requirements $requirementsFile @TDK_OPTS

common_stage start 'tdkserver start'
common_run tdd tdkserver start --instance $INSTANCE @TDK_OPTS
common_run common_tdkserver_expect $INSTANCE running

common_stage pods-2 "every expected service pod is Running: $EXPECT_PODS"
common_run_retry 12 5 common_tdkserver_pods_running $INSTANCE @EXPECT_POD_LIST

common_stage login-2 "tdk login as admin on $SERVER (profile $PROFILE_NAME)"
common_run_retry 30 5 tdd tdk login --profile $PROFILE_NAME --server $SERVER --user admin --password tabsdata

# One --continue stage per suite: a suite failure is reported, not fatal.
# The project name is given so it carries sm_<NAME>__; --keep goes through.
$keepOpt = if ($KEEP) { @('--keep') } else { @() }
foreach ($suite in $SUITE_LIST) {
    $project = "${BASE}__xp_$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss'))_$($suite -replace '[^A-Za-z0-9]', '_')"
    $XP_PROJECTS.Add($project)
    common_stage --continue "xp-$($suite -replace '/', '_')" "xp one-shot $suite as $project (continue on error)"
    common_run tdd xp one-shot --suite $suite --suite-run $project --project $project --profile $PROFILE_NAME @keepOpt
}

# A worker's pod is deleted as soon as it finishes on kminus, so its log must
# come back from the pod runner's archive (see smoke-km.sh).
$XP_PROJECTS.Add($LOGS_PROJECT)
common_stage --continue worker-logs "run test/test as $LOGS_PROJECT, then read its workers' logs back from the pod runner (continue on error)"
common_run tdd xp one-shot --suite test/test --suite-run $LOGS_PROJECT --project $LOGS_PROJECT --profile $PROFILE_NAME --keep
if ($LASTEXITCODE -eq 0) {
    $LOGS_SETUP = $true
    common_run_retry 12 5 common_worker_logs_archived $PROFILE_NAME $LOGS_PROJECT pod-runner
}

if ($KEEP) {
    common_stage cleanup 'keeping the whole setup as it is (--keep)'
    common_note "logged in as admin on $SERVER; tdd xp one-shot --suite test/test --profile $PROFILE_NAME works as is"
    common_tabsdata_setup_info common_note
} else {
    common_stage cleanup "destroy the domains, stop and trash the instance $INSTANCE, delete the venv $VENV"
    # xp (no --keep) destroyed its own domains; what is left is ours
    if ($LLM_DOMAIN) { common_run tdd domain destroy --domain $LLM_DOMAIN --force }
    # the worker-logs run was kept to read its logs: its domains and suite run are ours too
    if ($LOGS_SETUP) {
        common_run tdd xp destroy-domains --suite-run $LOGS_PROJECT
        common_run tdd xp destroy-instance --suite-run $LOGS_PROJECT
    }
    # `tdkserver delete` cannot remove a kminus instance (see smoke-km.sh):
    # stop it ourselves, then trash the folder.
    common_run tdd tdkserver stop --instance $INSTANCE @TDK_OPTS
    common_run common_tdkserver_expect $INSTANCE stopped
    common_run tdd tdkserver trash --instance $INSTANCE @TDK_OPTS
    common_run common_instance_gone $INSTANCE
    # the storage domain outlives the instance that wrote into it; now it goes
    if ($STORAGE_DOMAIN) { common_run tdd domain destroy --domain $STORAGE_DOMAIN --force }
    common_run tdd venv deactivate
    common_run tdd venv delete --name $VENV
}
Remove-Item -LiteralPath $WORK -Recurse -Force -ErrorAction SilentlyContinue
common_finish
