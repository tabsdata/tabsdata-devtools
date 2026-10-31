#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#

# Tabsdata Kminus smoke test.
#
# Every name this run creates starts with sm_<NAME> (--name): the instance and
# the venv ARE sm_<NAME>; domains and xp instances/projects are sm_<NAME>__<what>.

set -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# sourced before the arguments are read, so --help is painted like a tdd command
# shellcheck disable=SC1091
. "$HERE/_common.sh"

# The same contract as the cluster flavours, minus the three that name a cluster
# a kminus run does not have: it brings its own. A default for what is left is
# either a confusing failure or a quiet install from the wrong index.
REQUIRED_OPTIONS="--name --td-version"

usage() {
    cat <<'HELP' | common_help "$REQUIRED_OPTIONS"
usage: smoke-km.sh --name NAME --td-version VERSION
                   [--uv-index URI] [--llm-domain SYSTEM] [--td-extras EXTRAS]
                   [--venv-type uv|pyenv|conda] [--py-version VERSION] [--port PORT]
                   [--xp-suites LIST] [--expect-pods LIST] [--force] [--keep]
                   [--profile NAME] [--log FILE] [--tdd-dir DIR] [--verbose]

Tabsdata Kminus smoke test.

options:
  --name NAME         REQUIRED: the run's name, alphanumeric. Everything created is
                      sm_NAME -- the tdkserver instance and the managed venv -- or
                      sm_NAME__<what>: the domains and the xp instances/projects
  --td-version VERSION
                      REQUIRED: the tabsdata release to install, tabsdata[EXTRAS]==VERSION
  --td-extras EXTRAS
                      the extras to install (default: all). tabsdata is a
                      meta-package: without the right extras (server, cli,
                      conn-*, ...) the venv has no working tdkserver
  --venv-type TYPE    uv, pyenv or conda (default: uv)
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
                      LLM domain, and -- passed on as `xp one-shot --keep` -- every
                      xp instance/project and its domains
                      (default: no -- the running instance is deleted, tdkserver
                      delete tearing it down and trashing its folder, and the venv
                      deleted; a failed run always leaves everything standing)
  --profile NAME      the tdk connection profile every `tdk` call and every xp
                      suite uses (tdk COMMAND --profile NAME), so this run's
                      login never replaces another shell's on the same account
                      (default: sm_NAME)
  --log FILE          log file (default: <temp>/smoke-<instance>-<start time>.log;
                      <temp> is $TMPDIR, else /tmp)
  --tdd-dir DIR       the tdd dir to source (default: $TDD_DIR, else ~/.tdd)
  --verbose           show every command's output on the screen as it happens
                      (default: a rolling window of the last 10 log lines,
                      and a stage's commands collapse into `ok` when it passes)
  --help, -h          this help

The drivers added to the instance's fn and ag venvs (tdkserver venv update):
  mysql-connector-python==9.6.0  psycopg2-binary==2.9.12  oracledb==3.2.0
HELP
}

NAME=""                  # required; everything is sm_$NAME
LLM_SYSTEM=""            # --llm-domain: none unless asked for
EXPECT_PODS="srv-apiserver,srv-database"
VENV_TYPE="uv"
PYTHON="3.12.13"
TD_VERSION=""     # required
TD_EXTRAS="all"
PORT="10000"             # --port: the instance's base port. One per script
                         # (km 10000, eks 11000, aks 12000, gke 13000): the ports a run holds on
                         # this machine are the one thing two runs can collide on.
UV_INDEX_URI=""
SUITES="test,tableframe_api,dataquality,grok,container-connectors,cdc,kafka,cloud-connectors"
FORCE=""                 # 1 with --force; empty otherwise
KEEP=""                  # 1 with --keep; empty otherwise (so ${KEEP:+--keep} works)
LOG=""
PROFILE=""               # --profile: defaults to $BASE once --name is known
VERBOSE=0
TDD_DIR_OPT="${TDD_DIR:-$HOME/.tdd}"
REQUIREMENTS="mysql-connector-python==9.6.0
psycopg2-binary==2.9.12
oracledb==3.2.0"

while [ $# -gt 0 ]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        --llm-domain) LLM_SYSTEM="$2"; shift 2 ;;
        --expect-pods) EXPECT_PODS="$2"; shift 2 ;;
        --venv-type) VENV_TYPE="$2"; shift 2 ;;
        --py-version) PYTHON="$2"; shift 2 ;;
        --td-version) TD_VERSION="$2"; shift 2 ;;
        --td-extras) TD_EXTRAS="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --uv-index) UV_INDEX_URI="$2"; shift 2 ;;
        --xp-suites) SUITES="$2"; shift 2 ;;
        --force | -f) FORCE=1; shift ;;
        --keep) KEEP=1; shift ;;
        --log) LOG="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --tdd-dir) TDD_DIR_OPT="$2"; shift 2 ;;
        --verbose) VERBOSE=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) echo "smoke-km: unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
done
# tdd is loaded as soon as the line is read: resolving --uv-index, the checks,
# the banner and every stage go through it (tdd _smoke).
if [ ! -r "$TDD_DIR_OPT/tdd-source.sh" ]; then
    echo "smoke-km: no tdd dir at $TDD_DIR_OPT (tdd-source.sh missing); install with cargo make install or pass --tdd-dir" >&2
    exit 1
fi
# shellcheck disable=SC1090
. "$TDD_DIR_OPT/tdd-source.sh"
UV_INDEX_URI="$(common_resolve_uv_index "$UV_INDEX_URI")" || exit 1

case "$VENV_TYPE" in uv | pyenv | conda) ;; *) echo "smoke-km: --venv-type must be uv, pyenv or conda" >&2; exit 1 ;; esac
missing=""
for _need in $REQUIRED_OPTIONS; do
    case "$_need" in
        --name) [ -n "$NAME" ] || missing="$missing $_need" ;;
        --td-version) [ -n "$TD_VERSION" ] || missing="$missing $_need" ;;
    esac
done
if [ -n "$missing" ]; then
    echo "smoke-km: missing required option(s):$missing (see --help)" >&2
    exit 1
fi
case "$NAME" in *[!A-Za-z0-9]*) echo "smoke-km: --name must be alphanumeric (it becomes part of domain names)" >&2; exit 1 ;; esac
BASE="sm_$NAME"
PROFILE="${PROFILE:-$BASE}"   # the tdk connection is this run's own, like every name it makes
NAMES_PREFIX="$BASE"     # what the failure summary tells the reader to look for
INSTANCE="$BASE"
VENV="$BASE"
STAMP="$(date +%Y%m%d-%H%M%S)"
LLM_DOMAIN="${LLM_SYSTEM:+${BASE}__${LLM_SYSTEM}}"
XP_PROJECTS=""           # the xp instance/project names this run creates, for --keep and failures
SMOKE_DOMAINS=""         # domains this run creates outside xp, appended as each one is (common_tabsdata_setup_info lists them)
EXPECT_POD_LIST="$(printf '%s' "$EXPECT_PODS" | tr ',' ' ')"
LOG="${LOG:-$COMMON_TMP/smoke-$INSTANCE-$STAMP.log}"
WORK="$(mktemp -d "$COMMON_TMP/smoke-$INSTANCE-$STAMP.XXXX")"
SERVER="localhost:$PORT"
TABSDATA_SPEC="tabsdata[$TD_EXTRAS]==$TD_VERSION"
TDK_OPTS=(-y --accept-terms y)       # after `rm -rf ~/.tabsdata` every tdkserver call must accept the terms again
SUITE_LIST=()
for suite in $(printf '%s' "$SUITES" | tr ',' ' '); do SUITE_LIST[${#SUITE_LIST[@]}]="$suite"; done
if [ "${#SUITE_LIST[@]}" -eq 0 ]; then
    echo "smoke-km: --xp-suites needs at least one selector" >&2
    exit 1
fi
STAGE_NAMES=(unset-td unset-pypi set-crypto)
# See the set-pypi stage below: only when there is an index to put back.
[ -n "$UV_INDEX_URI" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="set-pypi"
for stage in systems pycache clean-previous create-venv install; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
[ "$TD_VERSION" = "2.0.2" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="cdc-driver"
[ -n "$LLM_SYSTEM" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="llm-domain"
for stage in quickstart pods-1 login-1 stop-1 venv-update start pods-2 login-2; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
for suite in "${SUITE_LIST[@]}"; do STAGE_NAMES[${#STAGE_NAMES[@]}]="xp-$(printf '%s' "$suite" | tr '/' '_')"; done
STAGE_NAMES[${#STAGE_NAMES[@]}]="cleanup"

# shellcheck disable=SC1091
. "$HERE/_common.sh"

# What this run would create must not already exist -- someone's setup could be
# behind those names. --force says they are ours to replace.
if [ -z "$FORCE" ]; then
    EXISTING=""
    for d in "$TDD_DIR_OPT"/managed-venvs/*/"$VENV"; do
        [ -e "$d" ] && EXISTING="$EXISTING venv:$d"
    done
    [ -e "$HOME/.tabsdata/instances/$INSTANCE" ] && EXISTING="$EXISTING instance:$HOME/.tabsdata/instances/$INSTANCE"
    common_instance_running "$INSTANCE" && EXISTING="$EXISTING running-instance:$INSTANCE"
    if [ -n "$EXISTING" ]; then
        echo "smoke-km: already exists:$EXISTING" >&2
        echo "smoke-km: pass --force to stop/delete and recreate them, or pick another --name" >&2
        exit 1
    fi
fi

common_init "$LOG" "$VERBOSE"

common_screen "smoke-km: effective options"
common_screen "  --name              $NAME   -> instance and venv $BASE, domains and xp names ${BASE}__<what>"
common_screen "  --venv-type         $VENV_TYPE"
common_screen "  --py-version    $PYTHON"
common_screen "  --td-version        $TD_VERSION"
common_screen "  --td-extras   $TD_EXTRAS   -> installs $TABSDATA_SPEC"
common_screen "  --port              $PORT   -> server $SERVER"
common_screen "  --uv-index          $(common_display "${UV_INDEX_URI:-(none)}")"
common_screen "  --xp-suites            $SUITES   -> xp projects ${BASE}__xp_<ts>_<suite>"
common_screen "  --llm-domain        ${LLM_SYSTEM:-(none)}${LLM_SYSTEM:+   -> domain $LLM_DOMAIN}"
common_screen "  --expect-pods       $EXPECT_PODS"
common_screen "  --force             $([ -n "$FORCE" ] && echo "yes (replace an existing venv/instance)" || echo "no (an existing venv/instance is an error)")"
common_screen "  --keep              $([ -n "$KEEP" ] && echo "yes (also: xp one-shot --keep)" || echo "no (domains, instance and venv deleted at the end)")"
common_screen "  --profile           $PROFILE   -> tdk COMMAND --profile $PROFILE, xp --profile $PROFILE"
common_screen "  --log               $LOG"
common_screen "  --tdd-dir           $TDD_DIR_OPT"
common_screen "  --verbose           $([ "$VERBOSE" = 1 ] && echo yes || echo "no (rolling window of $WINDOW log lines)")"
common_screen "  drivers for fn/ag   $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
common_xp_expand_all


common_stage unset-td "unset every TD_* variable (tdd env unset --td spares the crypto key)"
common_run tdd env unset --td

common_stage unset-pypi "unset the Python package index variables"
common_run tdd env unset --py-idx --py-default-idx


common_stage set-crypto "set _TDD_CRYPTO_KEY"
# 1Password is asked only when the key is unset; `unset --td` spared it
common_run tdd env set --crypto

# `tdkserver quickstart --uv-index URL` takes the URL, says "Set UV_INDEX to
# URL ... in tabsdata.yaml", and writes it there under pods.global.envs -- and
# then the pods get nothing: the pymanager pod prints `UV_INDEX = <unset>` and
# resolves against PyPI alone, so a version that exists only on that index
# cannot be installed and quickstart dies in `ins-pymanager` with "no version
# of tabsdata[all]==X". Seen on 2.0.0, 2.0.1 and 2.1.0; UV_INDEX_STRATEGY
# beside it does arrive, so it is that one placeholder, not the mechanism.
# kminus runs its pods as local processes, so they inherit this environment:
# setting the pair here is what reaches them, and `--py-idx` is the same pair
# tdkserver meant to set. Until tdkserver hands its own --uv-index to the pods,
# put it back for that version -- and say so, since it is not tdkserver's own.
if [ -n "$UV_INDEX_URI" ]; then
    common_stage set-pypi "tdkserver workaround: UV_INDEX in this shell for the pods to inherit"
    common_run tdd env set --py-idx "$UV_INDEX_URI"
    common_remark "workaround: tdkserver quickstart --uv-index does not reach the pods (2.0.0, 2.0.1, 2.1.0); UV_INDEX and UV_INDEX_STRATEGY were set in this shell instead, which the kminus pods inherit"
fi

common_stage systems "the dev and fs systems, then every system the suites need must be in the tdd store"
# Checked UPFRONT: a store missing a system its suites need must fail the run
# here, before anything is built. dev and fs are free and local, so created.
common_run tdd system create --type dev --sys dev --force
# fs needs an explicit absolute root: its default is target/backends/<name>
# against the CWD, which once landed inside a checkout.
common_run tdd system create --type fs --sys fs --sys-path "$TDD_DIR_OPT/data/fs-root" --force
for suite in "${SUITE_LIST[@]}"; do
    common_run tdd xp list-systems --suite "$suite"
done
# status checks the LLM credential is there without printing it
[ -z "$LLM_SYSTEM" ] || common_run tdd system status --sys "$LLM_SYSTEM"

common_stage pycache "purge tabsdata from the uv and pip caches"
# a republished wheel of the same version must not be served stale from the cache
common_run tdd pycache clean

common_stage clean-previous "stop and remove a previous $INSTANCE (--force; nothing exists otherwise)"
# The old instance's processes are waited out first: a km winding down would
# SIGKILL the new cluster through reused pid files. Scoped to THIS instance --
# other instances under ~/.tabsdata are not this run's to touch.
common_run common_instance_stop "$INSTANCE" "$TDD_DIR_OPT" "${TDK_OPTS[@]}"
if [ -e "$HOME/.tabsdata/instances/$INSTANCE" ]; then
    common_run rm -rf "$HOME/.tabsdata/instances/$INSTANCE"
fi

common_stage create-venv "create and activate the managed venv $VENV ($VENV_TYPE, python $PYTHON)"
# shellcheck disable=SC2086
# Whatever this shell was in has to go first: `tdd venv create` refuses under a
# venv tdd did not activate. Plain `deactivate` will not leave one of those,
# which is why this used to be a silent `|| true` that let the create fail
# anyway; --force leaves it, and succeeds when there was nothing to leave.
common_run tdd venv deactivate --force
common_run tdd venv create --name "$VENV" --type "$VENV_TYPE" --python "$PYTHON" ${FORCE:+--force}

common_stage install "uv pip install $TABSDATA_SPEC into $VENV"
# the venv stays active in this shell: later stages resolve programs inside it
# shellcheck disable=SC2086
common_run uv pip install ${UV_INDEX_URI:+--index "$UV_INDEX_URI" --index-strategy unsafe-best-match} "$TABSDATA_SPEC"
# uv only WARNS about a nonexistent extra -- the programs must really be there
for program in tdkserver tdk; do
    common_run test -x "$(dirname "$(command -v python)")/$program"
done

# tabsdata 2.0.2 ships no psycopg2 with its Postgres connector (it sits in the
# `test` extra), yet the CDC plugin imports it when tdk loads the connectors, so
# every postgrescdc collection create fails. Until tabsdata ships it, put it in
# the client venv for that version -- and say so, since it is not tabsdata's own.
if [ "$TD_VERSION" = "2.0.2" ]; then
    common_stage cdc-driver "tabsdata 2.0.2 workaround: psycopg2-binary into $VENV for the Postgres CDC plugin"
    # shellcheck disable=SC2086
    common_run uv pip install ${UV_INDEX_URI:+--index "$UV_INDEX_URI" --index-strategy unsafe-best-match} psycopg2-binary==2.9.11
    common_remark "workaround: tabsdata 2.0.2 ships no psycopg2 with its Postgres connector; psycopg2-binary was installed into $VENV so the CDC plugin loads"
fi

if [ -n "$LLM_SYSTEM" ]; then
    common_stage llm-domain "domain $LLM_DOMAIN on $LLM_SYSTEM, its API key for quickstart"
    # The key is eval'd (exported) into THIS shell, never echoed; quickstart
    # reads it from that variable (`--config <llm>-key=env:LLM__API_KEY`), so it
    # is never on a command line. Releases up to 2.2.0 have no --config and take
    # the deprecated --<llm>-key, which the displayed command line masks.
    common_run tdd domain create --sys "$LLM_SYSTEM" --domain "$LLM_DOMAIN" --force
    SMOKE_DOMAINS="$SMOKE_DOMAINS $LLM_DOMAIN"
    common_note "eval \$(tdd domain info --domain $LLM_DOMAIN --format export --prefix LLM)   (the key is not shown)"
    eval "$(tdd domain info --domain "$LLM_DOMAIN" --format export --prefix LLM 2>/dev/null)"
    common_run test -n "${LLM__API_KEY:+set}"
    case "$TD_VERSION" in
        1.* | 2.0.* | 2.1.* | 2.2.0) LLM_KEY_OPTS=("--$LLM_SYSTEM-key" "$LLM__API_KEY") ;;
        *) LLM_KEY_OPTS=(--config "$LLM_SYSTEM-key=env:LLM__API_KEY") ;;
    esac
fi

common_stage quickstart "tdkserver quickstart --instance $INSTANCE (kminus${LLM_SYSTEM:+, $LLM_SYSTEM key from $LLM_DOMAIN}${LLM_SYSTEM:-, no LLM key})"
# shellcheck disable=SC2086
common_run tdd tdkserver quickstart --instance "$INSTANCE" --provider kminus --port "$PORT" ${UV_INDEX_URI:+--uv-index "$UV_INDEX_URI"} ${LLM_KEY_OPTS[@]+"${LLM_KEY_OPTS[@]}"} "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running

# retried: the pods come up after quickstart/start return
common_stage pods-1 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 12 5 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST

# retried: the login IS the readiness probe -- start returns before the API answers
common_stage login-1 "tdk login as admin on $SERVER (profile $PROFILE)"
common_run_retry 30 5 tdd tdk login --profile "$PROFILE" --server "$SERVER" --user admin --password tabsdata

common_stage stop-1 "tdkserver stop"
common_run tdd tdkserver stop --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" stopped

common_stage venv-update "update the instance's fn and ag venvs with the DB drivers"
# The drivers belong to the INSTANCE's fn/ag venvs, never to the client venv.
printf '%s\n' "$REQUIREMENTS" > "$WORK/requirements.txt"
common_note "requirements: $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
for name in fn ag; do
    common_run tdd tdkserver venv update --instance "$INSTANCE" --name "$name" --requirements "$WORK/requirements.txt" "${TDK_OPTS[@]}"
done

common_stage start "tdkserver start"
common_run tdd tdkserver start --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running

common_stage pods-2 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 12 5 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST

common_stage login-2 "tdk login as admin on $SERVER (profile $PROFILE)"
common_run_retry 30 5 tdd tdk login --profile "$PROFILE" --server "$SERVER" --user admin --password tabsdata

# One --continue stage per suite: a suite failure is reported, not fatal.
# The project name is given so it carries sm_<NAME>__; --keep goes through.
for suite in "${SUITE_LIST[@]}"; do
    project="${BASE}__xp_$(date -u +%Y%m%dT%H%M%S)_$(printf '%s' "$suite" | tr -c 'A-Za-z0-9\n' '_')"
    XP_PROJECTS="$XP_PROJECTS $project"
    common_stage --continue "xp-$(printf '%s' "$suite" | tr '/' '_')" "xp one-shot $suite as $project (continue on error)"
    # shellcheck disable=SC2086
    common_run tdd xp one-shot --suite "$suite" --suite-run "$project" --project "$project" --profile "$PROFILE" ${KEEP:+--keep}
done

if [ -n "$KEEP" ]; then
    common_stage cleanup "keeping the whole setup as it is (--keep)"
    common_note "logged in as admin on $SERVER; tdd xp one-shot --suite test/test --profile $PROFILE works as is"
    common_tabsdata_setup_info common_note
else
    common_stage cleanup "destroy the domains, stop and trash the instance $INSTANCE, delete the venv $VENV"
    # xp (no --keep) destroyed its own domains; what is left is ours
    [ -z "$LLM_DOMAIN" ] || common_run tdd domain destroy --domain "$LLM_DOMAIN" --force
    # `tdkserver delete` cannot remove a kminus instance: it stops the kminus
    # cluster first and then tries to delete the workload remnants THROUGH the
    # API it just stopped (`client error (Connect)`, running or not). `trash`
    # is the kminus removal: stop it ourselves, then trash the folder.
    common_run tdd tdkserver stop --instance "$INSTANCE" "${TDK_OPTS[@]}"
    common_run common_tdkserver_expect "$INSTANCE" stopped
    common_run tdd tdkserver trash --instance "$INSTANCE" "${TDK_OPTS[@]}"
    common_run common_instance_gone "$INSTANCE"
    common_run tdd venv deactivate
    common_run tdd venv delete --name "$VENV"
fi
rm -rf "$WORK"
common_finish
