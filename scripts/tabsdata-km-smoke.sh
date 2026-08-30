#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#

# tabsdata-km-smoke.sh -- a fresh tabsdata (kubernetes flavour) install exercised
# end to end with the tdd tools:
#
#    1  unset the TD_* variables (the crypto key is spared)   tdd env unset --td
#    2  unset the Python index variables         tdd env unset --py-idxx --py-default-idx
#    3  set the descriptor crypto key            tdd env set --crypto
#    4  create `dev` and `fs`, check every system the suites (and --llm) need
#       exists -- UPFRONT: a run missing one must fail here, not after the
#       cache purge, the venv and the install    tdd system create, tdd xp list-systems
#    5  purge tabsdata from the uv and pip caches   tdd pycache clean
#    6  stop the instance if a previous run still runs it, delete ~/.tabsdata
#    7  create a managed venv                    tdd venv create --name V --type T --python P --force
#    8  install tabsdata[EXTRAS] in it           uv pip install (extras default: all)
#   8b  (--llm) create the LLM domain and read its API key   tdd domain create, tdd domain info --as export
#    9  tdkserver quickstart (the LLM key when --llm)   tdd tdkserver quickstart --instance I --provider kminus [--<llm>-key K]
#   9b  every expected service pod is Running    tdd tdkserver status (retried)
#   10  log in                                   tdd tdk login (retried until the server answers)
#   11  stop the instance                        tdd tdkserver stop
#   12  update the instance's fn and ag venvs with the DB drivers below   tdd tdkserver venv update
#   13  start the instance                       tdd tdkserver start
#  13b  every expected service pod is Running    tdd tdkserver status (retried)
#   14  log in
#   15  one stage per suite in --suites (default: test tableframe_api dataquality grok
#       container-connectors cloud-connectors), continue on error   tdd xp one-shot --suite S --project P [--keep]
#   16  destroy the domains this run created, delete the RUNNING instance
#       (tdkserver delete needs its cluster up to tear the workloads down; the
#       folder is trashed) and the venv -- unless --keep, which leaves everything
#       running for a look and is passed on to xp so its setups stay too
#
# Every name this run creates starts with sm_<NAME> (--name): the instance and
# the venv ARE sm_<NAME>; domains and xp instances/projects are sm_<NAME>__<what>.
# What a run left behind is one `ls`/`list` away.
#
# Output model, masking, stages, report, what a failure leaves standing, the
# tdkserver state assertion after every quickstart/start/stop: scripts/_common.sh. The script runs in
# bash, not sourced: `tdd venv`/`tdd env` change THIS process's environment, and
# the venv it creates stays active for every later stage.

set -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

usage() {
    cat <<'HELP'
usage: tabsdata-km-smoke.sh --name NAME --tabsdata-version VERSION [--tabsdata-extras EXTRAS]
                   [--venv-type pyenv|uv|conda] [--python-version VERSION] [--port PORT]
                   [--uv-index URI] [--suites LIST] [--llm anthropic|openai]
                   [--expect-pods LIST] [--keep] [--stop-after STAGE] [--log FILE]
                   [--tdd-dir DIR] [--verbose]

A fresh tabsdata install exercised end to end with the tdd tools: unset the
TD_/PyPI variables, purge tabsdata from the uv/pip caches, stop a previous
instance and delete ~/.tabsdata, set the crypto key, create a venv and
install tabsdata[EXTRAS], tdkserver quickstart, login, stop, update the fn/ag
venvs with the DB drivers, start, login, xp one-shot for every suite in --suites
(a suite failure is reported but does not stop the run), then delete the running
instance and the venv -- or, with --keep, leave everything running.

options:
  --name NAME         REQUIRED: the run's name, alphanumeric. Everything created is
                      sm_NAME -- the tdkserver instance and the managed venv -- or
                      sm_NAME__<what>: the domains and the xp instances/projects
  --tabsdata-version VERSION
                      REQUIRED: the tabsdata release to install, tabsdata[EXTRAS]==VERSION
  --tabsdata-extras EXTRAS
                      the extras to install (default: all). tabsdata is a
                      meta-package: without the right extras (server, cli,
                      conn-*, ...) the venv has no working tdkserver
  --venv-type TYPE    pyenv, uv or conda (default: pyenv)
  --python-version VERSION
                      interpreter for the venv (default: 3.12.13)
  --port PORT         base port for the instance (default: 10000)
  --uv-index URI      Python package index (default: none): used by the tabsdata install
                      (uv --index, unsafe-best-match) and passed to tdkserver
                      quickstart --uv-index for the instance's pods
  --suites LIST       comma-separated xp suite selectors to run, one stage each;
                      <type>/<name> for one definition, <type> for every
                      definition in that dir -- see `tdd xp list-suites`
                      (default: test,tableframe_api,dataquality,grok,
                      container-connectors,cloud-connectors)
  --llm anthropic|openai
                      create a domain on that system (sm_NAME__llm_<llm>; the system
                      must be in the tdd store), read its API key and hand it to
                      quickstart as --<llm>-key, so the aiagent works; the domain
                      is destroyed at the end unless --keep (default: no LLM)
  --expect-pods LIST  comma-separated service names whose pods must be Running
                      and Ready after quickstart and after start, per
                      `tdkserver status` (default: srv-apiserver,srv-database)
  --keep              on success, leave the whole setup as it is at the end:
                      the instance running and logged in, the venv in place, the
                      LLM domain, and -- passed on as `xp one-shot --keep` -- every
                      xp instance/project and its domains
                      (default: no -- the running instance is deleted, tdkserver
                      delete tearing it down and trashing its folder, and the venv
                      deleted; a failed run always leaves everything standing)
  --stop-after STAGE  stop (exit 0, everything left standing) after the named
                      stage: unset-td unset-pypi set-crypto systems pycache
                      delete-tabsdata create-venv install [llm-domain] quickstart
                      pods-1 login-1 stop-1 venv-update start pods-2 login-2 xp-<suite> (one per --suites entry,
                      / replaced by _) cleanup
  --log FILE          log file (default: /tmp/smoke-<instance>-<start time>.log)
  --tdd-dir DIR       the tdd dir to source (default: $TDD_DIR, else ~/.tdd)
  --verbose           show every command's output on the screen as it happens
                      (default: a rolling window of the last 10 log lines,
                      and a stage's commands collapse into `ok` when it passes)
  -h, --help          this help

The drivers added to the instance's fn and ag venvs (tdkserver venv update):
  mysql-connector-python==9.6.0  psycopg2-binary==2.9.12  oracledb==3.2.0
HELP
}

NAME=""                  # required; everything is sm_$NAME
LLM=""                   # anthropic | openai | empty
EXPECT_PODS="srv-apiserver,srv-database"
VENV_TYPE="pyenv"
PYTHON="3.12.13"
TABSDATA_VERSION=""     # required
TABSDATA_EXTRAS="all"
PORT="10000"
UV_INDEX_URI=""
SUITES="test,tableframe_api,dataquality,grok,container-connectors,cloud-connectors"
KEEP=""                  # 1 with --keep; empty otherwise (so ${KEEP:+--keep} works)
STOP_AFTER=""
LOG=""
VERBOSE=0
TDD_DIR_OPT="${TDD_DIR:-$HOME/.tdd}"
REQUIREMENTS="mysql-connector-python==9.6.0
psycopg2-binary==2.9.12
oracledb==3.2.0"

while [ $# -gt 0 ]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        --llm) LLM="$2"; shift 2 ;;
        --expect-pods) EXPECT_PODS="$2"; shift 2 ;;
        --venv-type) VENV_TYPE="$2"; shift 2 ;;
        --python-version) PYTHON="$2"; shift 2 ;;
        --tabsdata-version) TABSDATA_VERSION="$2"; shift 2 ;;
        --tabsdata-extras) TABSDATA_EXTRAS="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --uv-index) UV_INDEX_URI="$2"; shift 2 ;;
        --suites) SUITES="$2"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --stop-after) STOP_AFTER="$2"; shift 2 ;;
        --log) LOG="$2"; shift 2 ;;
        --tdd-dir) TDD_DIR_OPT="$2"; shift 2 ;;
        --verbose) VERBOSE=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) echo "tabsdata-km-smoke: unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
done
case "$VENV_TYPE" in pyenv | uv | conda) ;; *) echo "tabsdata-km-smoke: --venv-type must be pyenv, uv or conda" >&2; exit 1 ;; esac
case "$LLM" in "" | anthropic | openai) ;; *) echo "tabsdata-km-smoke: --llm must be anthropic or openai" >&2; exit 1 ;; esac
case "$NAME" in *[!A-Za-z0-9]*) echo "tabsdata-km-smoke: --name must be alphanumeric (it becomes part of domain names)" >&2; exit 1 ;; "") echo "tabsdata-km-smoke: --name NAME is required (everything created is sm_NAME)" >&2; exit 1 ;; esac
if [ -z "$TABSDATA_VERSION" ]; then
    echo "tabsdata-km-smoke: --tabsdata-version VERSION is required (the tabsdata release to install)" >&2
    exit 1
fi
# sm_NAME is the instance and the venv; sm_NAME__<what> everything else (`_` is
# what domain names allow, `__` keeps the run's name readable in them).
BASE="sm_$NAME"
NAMES_PREFIX="$BASE"     # what common_tabsdata_setup_info tells the reader to look for
INSTANCE="$BASE"
VENV="$BASE"
STAMP="$(date +%Y%m%d-%H%M%S)"
LLM_DOMAIN="${LLM:+${BASE}__llm_${LLM}}"
XP_PROJECTS=""           # the xp instance/project names this run creates, for --keep and failures
SMOKE_DOMAINS="$LLM_DOMAIN"   # domains this run creates outside xp (common_tabsdata_setup_info lists them)
EXPECT_POD_LIST="$(printf '%s' "$EXPECT_PODS" | tr ',' ' ')"
LOG="${LOG:-/tmp/smoke-$INSTANCE-$STAMP.log}"
WORK="$(mktemp -d "/tmp/smoke-$INSTANCE-$STAMP.XXXX")"
SERVER="localhost:$PORT"
TABSDATA_SPEC="tabsdata[$TABSDATA_EXTRAS]==$TABSDATA_VERSION"
TDK_OPTS=(-y --accept-terms y)       # after `rm -rf ~/.tabsdata` every tdkserver call must accept the terms again
SUITE_LIST=()
for suite in $(printf '%s' "$SUITES" | tr ',' ' '); do SUITE_LIST[${#SUITE_LIST[@]}]="$suite"; done
if [ "${#SUITE_LIST[@]}" -eq 0 ]; then
    echo "tabsdata-km-smoke: --suites needs at least one selector" >&2
    exit 1
fi
STAGE_NAMES=(unset-td unset-pypi set-crypto systems pycache delete-tabsdata create-venv install)
[ -n "$LLM" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="llm-domain"
for stage in quickstart pods-1 login-1 stop-1 venv-update start pods-2 login-2; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
for suite in "${SUITE_LIST[@]}"; do STAGE_NAMES[${#STAGE_NAMES[@]}]="xp-$(printf '%s' "$suite" | tr '/' '_')"; done
STAGE_NAMES[${#STAGE_NAMES[@]}]="cleanup"

# shellcheck disable=SC1091
. "$HERE/_common.sh"
common_init "$LOG" "$VERBOSE"

# On a failed stage, _common.sh's common_on_stage_failed describes the instance and
# the venv left standing (INSTANCE, SERVER, VENV, VENV_TYPE, TDD_DIR_OPT).

# The effective options, every one, so the screen and the log say exactly what ran.
common_screen "tabsdata-km-smoke: effective options"
common_screen "  --name              $NAME   -> instance and venv $BASE, domains and xp names ${BASE}__<what>"
common_screen "  --venv-type         $VENV_TYPE"
common_screen "  --python-version    $PYTHON"
common_screen "  --tabsdata-version  $TABSDATA_VERSION"
common_screen "  --tabsdata-extras   $TABSDATA_EXTRAS   -> installs $TABSDATA_SPEC"
common_screen "  --port              $PORT   -> server $SERVER"
common_screen "  --uv-index          $(common_display "${UV_INDEX_URI:-(none)}")"
common_screen "  --suites            $SUITES   -> xp projects ${BASE}__xp_<ts>_<suite>"
common_screen "  --llm               ${LLM:-(none)}${LLM:+   -> domain $LLM_DOMAIN}"
common_screen "  --expect-pods       $EXPECT_PODS"
common_screen "  --keep              $([ -n "$KEEP" ] && echo "yes (also: xp one-shot --keep)" || echo "no (domains, instance and venv deleted at the end)")"
common_screen "  --stop-after        ${STOP_AFTER:-(run everything)}"
common_screen "  --log               $LOG"
common_screen "  --tdd-dir           $TDD_DIR_OPT"
common_screen "  --verbose           $([ "$VERBOSE" = 1 ] && echo yes || echo "no (rolling window of $WINDOW log lines)")"
common_screen "  drivers for fn/ag   $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
if [ ! -r "$TDD_DIR_OPT/tdd-source.sh" ]; then
    common_screen "${RED}tabsdata-km-smoke: no tdd dir at $TDD_DIR_OPT (tdd-source.sh missing); install with cargo make install or pass --tdd-dir${RESET}"
    exit 1
fi
# shellcheck disable=SC1090
. "$TDD_DIR_OPT/tdd-source.sh"

# A venv already active in this shell (conda, a manual activate) would make
# `tdd venv create` refuse; leave it first. Not a stage: there may be none.
tdd venv deactivate >/dev/null 2>&1 || true

common_stage unset-td "unset every TD_* variable (tdd env unset --td spares the crypto key)"
common_run tdd env unset --td
common_checkpoint unset-td

common_stage unset-pypi "unset the Python package index variables"
common_run tdd env unset --py-idxx --py-default-idx
common_checkpoint unset-pypi

common_stage set-crypto "set _TDD_CRYPTO_KEY"
# 1Password is asked only when the key is not set: `tdd env set --crypto`
# skips it otherwise, and `unset --td` above left it alone.
common_run tdd env set --crypto
common_checkpoint set-crypto

common_stage systems "the dev and fs systems, then every system the suites need must be in the tdd store"
# Every suite provisions on `dev`, which a fresh tdd dir lacks (--force also
# replaces a descriptor an older key left unreadable). The other systems are
# the user's store: check them now, by name and type, rather than find out
# lane by lane after quickstart has spent its minutes.
common_run tdd system create --type dev --sys dev --force
# fs is local plumbing like dev (grok, localfile and friends stage files on it).
# The root must be explicit and absolute: the backend's default is
# target/backends/<name> resolved against the CWD, which once landed inside a
# checkout. Destroy leaves the root dir itself in place.
common_run tdd system create --type fs --sys fs --sys-path "$TDD_DIR_OPT/data/fs-root" --force
for suite in "${SUITE_LIST[@]}"; do
    common_run tdd xp list-systems --suite "$suite"
done
# The LLM system is a credential-only descriptor; status says whether it is
# there and carries its key, without printing the key.
[ -z "$LLM" ] || common_run tdd system status --sys "$LLM"
common_checkpoint systems

common_stage pycache "purge tabsdata from the uv and pip caches"
# A republished wheel of the same version, or one from --uv-index, must not be
# served from a stale cache entry into the venv created below.
common_run tdd pycache clean
common_checkpoint pycache

common_stage delete-tabsdata "stop a previous $INSTANCE if still running, delete ~/.tabsdata"
# Both from _common.sh: the instance's km processes are found by name and
# waited out before the delete (a km winding down would otherwise SIGKILL the
# new cluster through reused pid files), and the rm is retried.
common_run common_instance_stop "$INSTANCE" "$TDD_DIR_OPT" "${TDK_OPTS[@]}"
common_run common_tabsdata_home_delete
common_checkpoint delete-tabsdata

common_stage create-venv "create and activate the managed venv $VENV ($VENV_TYPE, python $PYTHON)"
common_run tdd venv create --name "$VENV" --type "$VENV_TYPE" --python "$PYTHON" --force
common_checkpoint create-venv

common_stage install "uv pip install $TABSDATA_SPEC into $VENV"
# The venv is active in this shell from here on: uv installs into it, and the
# programs the later stages run resolve inside it.
# shellcheck disable=SC2086
common_run uv pip install ${UV_INDEX_URI:+--index "$UV_INDEX_URI" --index-strategy unsafe-best-match} "$TABSDATA_SPEC"
# uv only WARNS about an extra the package does not have, and the venv would
# then hold an empty shell; the programs the later stages run must be there.
for program in tdkserver tdk; do
    common_run test -x "$(dirname "$(command -v python)")/$program"
done
common_checkpoint install

if [ -n "$LLM" ]; then
    common_stage llm-domain "domain $LLM_DOMAIN on $LLM, its API key for quickstart"
    # A domain on a service system is the credential itself, prefixed with the
    # run's name so it is found and destroyed with the rest. The key is read
    # through `info --as export` and eval'd into THIS shell (never echoed):
    # `--<llm>-key` is masked when quickstart's command line is displayed.
    common_run tdd domain create --sys "$LLM" --domain "$LLM_DOMAIN" --force
    common_note "eval \$(tdd domain info --domain $LLM_DOMAIN --as export --prefix LLM)   (the key is not shown)"
    eval "$(tdd domain info --domain "$LLM_DOMAIN" --as export --prefix LLM 2>/dev/null)"
    common_run test -n "${LLM__API_KEY:+set}"
    common_checkpoint llm-domain
fi

common_stage quickstart "tdkserver quickstart --instance $INSTANCE (kminus${LLM:+, $LLM key from $LLM_DOMAIN}${LLM:-, no LLM key})"
# shellcheck disable=SC2086
common_run tdd tdkserver quickstart --instance "$INSTANCE" --provider kminus --port "$PORT" ${UV_INDEX_URI:+--uv-index "$UV_INDEX_URI"} ${LLM:+--$LLM-key "$LLM__API_KEY"} "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running
common_checkpoint quickstart

# The pods come up after quickstart/start return; the check is retried until
# every expected service has a Running, Ready pod (or gives up).
common_stage pods-1 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 12 5 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST
common_checkpoint pods-1

# `tdkserver start` returns before the API server accepts connections (and a
# quickstart may too on a slow machine): the login is retried, it IS the
# readiness probe.
common_stage login-1 "tdk login as admin on $SERVER"
common_run_retry 30 5 tdd tdk login --server "$SERVER" --user admin --password tabsdata
common_checkpoint login-1

common_stage stop-1 "tdkserver stop"
common_run tdd tdkserver stop --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" stopped
common_checkpoint stop-1

common_stage venv-update "update the instance's fn and ag venvs with the DB drivers"
# The drivers belong to the INSTANCE (its fn and ag venvs), not to the client
# venv: that is what `tdkserver venv update` is for.
printf '%s\n' "$REQUIREMENTS" > "$WORK/requirements.txt"
common_note "requirements: $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
for name in fn ag; do
    common_run tdd tdkserver venv update --instance "$INSTANCE" --name "$name" --requirements "$WORK/requirements.txt" "${TDK_OPTS[@]}"
done
common_checkpoint venv-update

common_stage start "tdkserver start"
common_run tdd tdkserver start --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running
common_checkpoint start

common_stage pods-2 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 12 5 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST
common_checkpoint pods-2

common_stage login-2 "tdk login as admin on $SERVER"
common_run_retry 30 5 tdd tdk login --server "$SERVER" --user admin --password tabsdata
common_checkpoint login-2

# A suite can fail on connectivity or a missing system without saying anything
# about the install: each is its own stage, reported, not fatal.
# The xp instance/project name is given, so it carries the prefix and is known
# for the summary; --keep goes through, so xp keeps its setup exactly when the
# script keeps its own.
for suite in "${SUITE_LIST[@]}"; do
    project="${BASE}__xp_$(date -u +%Y%m%dT%H%M%S)_$(printf '%s' "$suite" | tr -c 'A-Za-z0-9\n' '_')"
    XP_PROJECTS="$XP_PROJECTS $project"
    common_stage --continue "xp-$(printf '%s' "$suite" | tr '/' '_')" "xp one-shot $suite as $project (continue on error)"
    # shellcheck disable=SC2086
    common_run tdd xp one-shot --suite "$suite" --project "$project" ${KEEP:+--keep}
    common_checkpoint "xp-$(printf '%s' "$suite" | tr '/' '_')"
done

if [ -n "$KEEP" ]; then
    common_stage cleanup "keeping the whole setup as it is (--keep)"
    common_note "logged in as admin on $SERVER; tdd xp one-shot --suite test/test works as is"
    common_tabsdata_setup_info common_note
else
    common_stage cleanup "destroy the domains, delete the running instance $INSTANCE and the venv $VENV"
    # xp destroyed its own domains and pointers (no --keep); what is left is ours.
    [ -z "$LLM_DOMAIN" ] || common_run tdd domain destroy --domain "$LLM_DOMAIN" --force
    # Deleted while RUNNING: `tdkserver delete` lists and removes the workloads
    # through the instance's kube API, so a stopped cluster makes it abort with
    # `client error (Connect)` -- seen when a stop preceded it here.
    common_run tdd tdkserver delete --instance "$INSTANCE" --trash true "${TDK_OPTS[@]}"
    common_run common_instance_gone "$INSTANCE"
    common_run tdd venv deactivate
    common_run tdd venv delete --name "$VENV"
fi
rm -rf "$WORK"
common_finish
