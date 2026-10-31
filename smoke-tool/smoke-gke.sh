#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#

# Tabsdata GKE smoke test.
#
# The EKS flavour (smoke-eks.sh) against a Google Kubernetes Engine
# cluster: storage is a GCS bucket prefix instead of S3, and the database is
# whatever --db-domain names -- gcppostgres, the Cloud SQL instance in the same
# project as the cluster, which is what a GKE run should be exercising. The five
# postgres types record one info block, so --db-domain awspostgres (or
# azpostgres) reads the same keys and is a flag rather than an edit.
#
# Every name this run creates starts with sm_<NAME> (--name): the instance and
# the venv ARE sm_<NAME>; domains and xp instances/projects are sm_<NAME>__<what>;
# the k8s namespace is --kube-namespace. The kminus flavour is smoke-km.sh.

set -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# sourced before the arguments are read, so --help is painted like a tdd command
# shellcheck disable=SC1091
. "$HERE/_common.sh"

# Nothing here is guessed. A cluster run reaches a named cluster in a named
# namespace and installs from a named index, and the wrong default for any of
# them is a confusing failure -- or a quiet success somewhere nobody meant to
# touch. These are the options common_help paints red.
REQUIRED_OPTIONS="--name --kube-config --kube-context --td-version"

usage() {
    cat <<'HELP' | common_help "$REQUIRED_OPTIONS"
usage: smoke-gke.sh --name NAME --kube-config FILE --kube-context NAME --td-version VERSION
                   [--kube-namespace NAME] [--kube-port-forward PORT] [--uv-index URI]
                   [--db-domain SYSTEM] [--storage-domain SYSTEM] [--llm-domain SYSTEM]
                   [--provider NAME] [--td-extras EXTRAS] [--td-fn-memory SIZE]
                   [--td-fn-disk SIZE] [--venv-type uv|pyenv|conda] [--py-version VERSION]
                   [--xp-suites LIST] [--expect-pods LIST] [--force] [--keep]
                   [--profile NAME] [--log FILE] [--tdd-dir DIR] [--verbose]

Tabsdata GKE smoke test: a tdkserver instance on a Google Kubernetes Engine
cluster, its storage a prefix of the `gcs` system's bucket and its database a
domain of --db-domain, exercised with xp suites.

Get a kubeconfig for the cluster first:
  gcloud container clusters get-credentials CLUSTER --region REGION --project PROJECT
which needs gke-gcloud-auth-plugin on PATH (gcloud components install gke-gcloud-auth-plugin).

options:
  --name NAME         REQUIRED: the run's name, alphanumeric. Everything created
                      is sm_NAME -- the tdkserver instance and the managed venv --
                      or sm_NAME__<what> (domains, xp instances/projects)
  --kube-config FILE  REQUIRED: the kubeconfig holding the cluster. It is never
                      modified: the run copies it and works on the copy
  --kube-context NAME
                      REQUIRED: the context in that file to run against. The file
                      chooses nothing on its own -- one kubeconfig holds every
                      cluster a developer has, and the context picks among them
  --kube-namespace NAME
                      the namespace to create and run in, RFC 1123 (lowercase,
                      digits, hyphens). Default: sm-<name>, lowercased
  --kube-port-forward PORT
                      the local port `kubectl port-forward` listens on for the
                      apiserver -- where tdk logs in. Only this side moves: the
                      apiserver's own port in the cluster stays 2457
                      (default: 13000; one per script -- km 10000, eks 11000,
                      aks 12000, gke 13000 -- so two runs on one machine
                      never fight over it)
  --td-version VERSION
                      REQUIRED: the tabsdata release to install, tabsdata[EXTRAS]==VERSION
  --td-extras EXTRAS
                      the extras to install (default: all)
  --td-fn-memory SIZE
                      memory of each function pod, written into tabsdata.yaml as
                      pods.function.resources.memory (default: 8Gi; the template
                      asks for 16Gi)
  --td-fn-disk SIZE   disk of each function pod, the same way (default: 32Gi;
                      the template asks for 64Gi)
  --venv-type TYPE    uv, pyenv or conda (default: uv)
  --py-version VERSION
                      interpreter for the venv (default: 3.12.13 -- the exact
                      version the instance builds its own environments with)
  --provider NAME     the tdkserver init provider for this cluster (default: gke).
                      It is an option because the provider name is tdkserver's to
                      define: if `init` refuses it, name the one it accepts here
  --db-domain SYSTEM  the system the instance's database is created on (default:
                      gcppostgres). Every domain this run creates is named
                      sm_NAME__<system>, and --force recreates it. Any of the
                      five postgres types: they share one info block
                      (default: gcppostgres -- the Cloud SQL instance beside the
                      cluster; awspostgres or azpostgres to cross clouds)
  --uv-index URI      the Python package index, used by the tabsdata install and
                      written into tabsdata.yaml (UV_INDEX) for the pods
                      URI is a URL, or @dev for the development index
                      (https://d3mm0r95u5i3hf.cloudfront.net/simple/), @dev:NAME
                      for namespace NAME on it (.../NAME/, what tdd pypi push
                      --at NAME publishes) or @prod for the published
                      one (https://pypi.tabsdata.com/simple/); not @local,
                      since the pods would read localhost as themselves
                      (default: none -- whatever uv is already configured with)
  --xp-suites LIST    comma-separated xp suite selectors, one stage each;
                      ALL for every suite dir
                      (default: test,tableframe_api,dataquality,grok/s3_examples,
                      grok/s3_world_csv,cloud-connectors -- cloud-connectors covers
                      cloud-connectors/gcs; container-connectors and the fs-backed
                      grok suites stay out: docker systems and local paths are
                      unreachable from function pods running in GKE)
  --storage-domain SYSTEM
                      the system the instance's storage comes from (default:
                      gcs). The config filling knows this cloud's option
                      keys; another cloud's storage leaves placeholders the run
                      then refuses
  --llm-domain SYSTEM
                      create a domain on that system too, read its API key and
                      write it into aiagent.yaml (default: no LLM)
  --expect-pods LIST  service names whose pods must be Running and Ready after
                      every start, per `tdkserver status` (default: srv-apiserver)
  --force, -f         a venv, instance or namespace of this name already existing
                      is an error unless this is given: then they are removed and
                      recreated (default: fail)
  --keep              on success, leave everything as it is: instance running,
                      namespace, domains, venv, xp setups (xp one-shot --keep);
                      the port-forward is still stopped -- the closing report
                      prints the command to re-establish it
                      (default: no -- domains destroyed, instance deleted,
                      namespace deleted, venv deleted; a failed run always
                      leaves everything standing)
  --profile NAME      the tdk connection profile every `tdk` call and every xp
                      suite uses (tdk COMMAND --profile NAME), so this run's
                      login never replaces another shell's on the same account
                      (default: sm_NAME)
  --log FILE          log file (default: <temp>/smoke-sm_NAME-<start time>.log;
                      <temp> is $TMPDIR, else /tmp)
  --tdd-dir DIR       the tdd dir to source (default: $TDD_DIR, else ~/.tdd)
  --verbose           show every command's output as it happens (default: a
                      rolling window of the running command's last lines)
  --help, -h          this help

The drivers added to the instance's fn and ag venvs (tdkserver venv update):
  mysql-connector-python==9.6.0  psycopg2-binary==2.9.12  oracledb==3.2.0
HELP
}

NAME=""                  # required; everything is sm_$NAME
STORAGE_SYSTEM="gcs"   # --storage-domain: the system the instance's storage comes from
LLM_SYSTEM=""            # --llm-domain: none unless asked for
EXPECT_PODS="srv-apiserver"
VENV_TYPE="uv"
PYTHON="3.12.13"
TD_VERSION=""            # required
TD_EXTRAS="all"
FN_MEMORY="8Gi"          # --td-fn-memory: each function pod's memory; the template says 16Gi
FN_DISK="32Gi"           # --td-fn-disk: each function pod's disk; the template says 64Gi
KUBECONFIG_OPT=""        # required
CONTEXT=""               # required
NAMESPACE=""             # required
PROVIDER="gke"           # tdkserver's name for this kind of cluster
DB_SYSTEM="gcppostgres"  # Cloud SQL, beside the cluster; --db-domain crosses clouds
PORT="2457"              # the apiserver's port in the cluster: tdkserver create --port, the forward's far side
FORWARD_PORT="13000"     # --kube-port-forward: the local port the forward listens on; where tdk logs in.
                         # One per script (km 10000, eks 11000, aks 12000, gke 13000): the local end is the
                         # one thing two runs on a laptop can collide on, and they do run side by side.
UV_INDEX_URI=""
# grok only through its s3 sub-suites: the fs-backed ones stage files on a local
# path the GKE function pods cannot see. S3 itself they reach over the internet.
SUITES="test,tableframe_api,dataquality,grok/s3_examples,grok/s3_world_csv,cloud-connectors"
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
        --storage-domain) STORAGE_SYSTEM="$2"; shift 2 ;;
        --llm-domain) LLM_SYSTEM="$2"; shift 2 ;;
        --expect-pods) EXPECT_PODS="$2"; shift 2 ;;
        --venv-type) VENV_TYPE="$2"; shift 2 ;;
        --py-version) PYTHON="$2"; shift 2 ;;
        --td-version) TD_VERSION="$2"; shift 2 ;;
        --td-extras) TD_EXTRAS="$2"; shift 2 ;;
        --td-fn-memory) FN_MEMORY="$2"; shift 2 ;;
        --td-fn-disk) FN_DISK="$2"; shift 2 ;;
        --kube-config) KUBECONFIG_OPT="$2"; shift 2 ;;
        --kube-context) CONTEXT="$2"; shift 2 ;;
        --kube-namespace) NAMESPACE="$2"; shift 2 ;;
        --kube-port-forward) FORWARD_PORT="$2"; shift 2 ;;
        --provider) PROVIDER="$2"; shift 2 ;;
        --db-domain) DB_SYSTEM="$2"; shift 2 ;;
        --uv-index) UV_INDEX_URI="$2"; shift 2 ;;
        --xp-suites) SUITES="$2"; shift 2 ;;
        --force | -f) FORCE=1; shift ;;
        --keep) KEEP=1; shift ;;
        --log) LOG="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --tdd-dir) TDD_DIR_OPT="$2"; shift 2 ;;
        --verbose) VERBOSE=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) echo "smoke-gke: unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
done
# tdd is loaded as soon as the line is read: resolving --uv-index, the checks,
# the banner and every stage go through it (tdd _smoke).
if [ ! -r "$TDD_DIR_OPT/tdd-source.sh" ]; then
    echo "smoke-gke: no tdd dir at $TDD_DIR_OPT (tdd-source.sh missing); install with cargo make install or pass --tdd-dir" >&2
    exit 1
fi
# shellcheck disable=SC1090
. "$TDD_DIR_OPT/tdd-source.sh"
UV_INDEX_URI="$(common_resolve_uv_index "$UV_INDEX_URI" --no-local)" || exit 1

case "$VENV_TYPE" in uv | pyenv | conda) ;; *) echo "smoke-gke: --venv-type must be uv, pyenv or conda" >&2; exit 1 ;; esac
missing=""
for _need in $REQUIRED_OPTIONS; do
    case "$_need" in
        --name) [ -n "$NAME" ] || missing="$missing $_need" ;;
        --kube-config) [ -n "$KUBECONFIG_OPT" ] || missing="$missing $_need" ;;
        --kube-context) [ -n "$CONTEXT" ] || missing="$missing $_need" ;;
        --td-version) [ -n "$TD_VERSION" ] || missing="$missing $_need" ;;
    esac
done
if [ -n "$missing" ]; then
    echo "smoke-gke: missing required option(s):$missing (see --help)" >&2
    exit 1
fi
case "$NAME" in *[!A-Za-z0-9]*) echo "smoke-gke: --name must be alphanumeric (it becomes part of domain and xp names)" >&2; exit 1 ;; esac
case "$NAMESPACE" in *[!a-z0-9-]* | -* | *-) echo "smoke-gke: --kube-namespace must be RFC 1123: lowercase letters, digits and inner hyphens" >&2; exit 1 ;; esac
case "$FORWARD_PORT" in '' | *[!0-9]*) echo "smoke-gke: --kube-port-forward must be a port number, 1-65535" >&2; exit 1 ;; esac
if [ "$FORWARD_PORT" -lt 1 ] || [ "$FORWARD_PORT" -gt 65535 ]; then echo "smoke-gke: --kube-port-forward must be a port number, 1-65535" >&2; exit 1; fi
QUANTITY='^[0-9]+(\.[0-9]+)?([EPTGMK]i?|m)?$'   # a Kubernetes quantity: 8Gi, 512Mi, 1.5G
[[ "$FN_MEMORY" =~ $QUANTITY ]] || { echo "smoke-gke: --td-fn-memory must be a Kubernetes quantity such as 8Gi or 512Mi" >&2; exit 1; }
[[ "$FN_DISK" =~ $QUANTITY ]] || { echo "smoke-gke: --td-fn-disk must be a Kubernetes quantity such as 32Gi" >&2; exit 1; }
if [ ! -r "$KUBECONFIG_OPT" ]; then
    echo "smoke-gke: no kubeconfig at $KUBECONFIG_OPT (pass --kube-config)" >&2
    echo "smoke-gke: get one with: gcloud container clusters get-credentials CLUSTER --region REGION --project PROJECT" >&2
    exit 1
fi
# --kube-config picks the FILE; the context is what picks the cluster, and one
# kubeconfig holds every cluster a developer has. Both are given, so there is
# nothing to infer here -- only to check, before anything is built.
KUBE_NAMES="$(kubectl --kubeconfig "$KUBECONFIG_OPT" config view -o jsonpath='{range .contexts[*]}{.name}{"\n"}{end}' 2>/dev/null)"
if ! printf '%s\n' "$KUBE_NAMES" | grep -qxF -- "$CONTEXT"; then
    echo "smoke-gke: no context '$CONTEXT' in $KUBECONFIG_OPT; it has:" >&2
    printf '%s\n' "$KUBE_NAMES" | sed 's/^/  /' >&2
    exit 1
fi
# not required: the run's own name makes a good namespace, and RFC 1123 only
# needs it lowercased
NAMESPACE="${NAMESPACE:-sm-$(printf '%s' "$NAME" | tr 'A-Z' 'a-z')}"
BASE="sm_$NAME"
PROFILE="${PROFILE:-$BASE}"   # the tdk connection is this run's own, like every name it makes
NAMES_PREFIX="$BASE"     # what the failure summary tells the reader to look for
INSTANCE="$BASE"
VENV="$BASE"
STAMP="$(date +%Y%m%d-%H%M%S)"
DB_DOMAIN="${BASE}__${DB_SYSTEM}"
STORAGE_DOMAIN="${BASE}__${STORAGE_SYSTEM}"
LLM_DOMAIN="${LLM_SYSTEM:+${BASE}__${LLM_SYSTEM}}"
XP_PROJECTS=""           # the xp instance/project names this run creates, for --keep and failures
SMOKE_DOMAINS=""         # domains this run creates, appended as each one is (common_tabsdata_setup_info lists them)
EXPECT_POD_LIST="$(printf '%s' "$EXPECT_PODS" | tr ',' ' ')"
LOG="${LOG:-$COMMON_TMP/smoke-$INSTANCE-$STAMP.log}"
WORK="$(mktemp -d "$COMMON_TMP/smoke-$INSTANCE-$STAMP.XXXX")"
SERVER="http://127.0.0.1:$FORWARD_PORT"
TABSDATA_SPEC="tabsdata[$TD_EXTRAS]==$TD_VERSION"
TDK_OPTS=(-y --accept-terms y)
CONFIGS="$HOME/.tabsdata/instances/$INSTANCE/init/input/configs"
# tdkserver resolves the cluster and the namespace from the kubeconfig's CURRENT
# context, and `venv update`, `config` and `delete` take no --context to say
# otherwise. Rather than move the developer's current context out from under
# whatever else they have running, the run works on a COPY of the file with its
# own current context and namespace, and points tdkserver at that. What they
# passed in is only ever read.
RUN_KUBECONFIG="$WORK/kubeconfig"
cp "$KUBECONFIG_OPT" "$RUN_KUBECONFIG"
kubectl --kubeconfig "$RUN_KUBECONFIG" config use-context "$CONTEXT" >/dev/null
export KUBECONFIG="$RUN_KUBECONFIG"
KUBECTL=(kubectl --kubeconfig "$RUN_KUBECONFIG" --context "$CONTEXT")
SUITE_LIST=()
for suite in $(printf '%s' "$SUITES" | tr ',' ' '); do SUITE_LIST[${#SUITE_LIST[@]}]="$suite"; done
if [ "${#SUITE_LIST[@]}" -eq 0 ]; then
    echo "smoke-gke: --xp-suites needs at least one selector" >&2
    exit 1
fi
STAGE_NAMES=(unset-td unset-pypi set-crypto cluster systems pycache clean-previous create-venv install)
[ "$TD_VERSION" = "2.0.2" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="cdc-driver"
for stage in domains namespace init configure create start-1 pods-1 forward-1 login-1 stop-1 venv-update start-2 pods-2 forward-2 login-2; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
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
    "${KUBECTL[@]}" get namespace "$NAMESPACE" >/dev/null 2>&1 && EXISTING="$EXISTING namespace:$NAMESPACE"
    if [ -n "$EXISTING" ]; then
        echo "smoke-gke: already exists:$EXISTING" >&2
        echo "smoke-gke: pass --force to delete and recreate them, or pick another --name" >&2
        exit 1
    fi
fi

common_init "$LOG" "$VERBOSE"
trap common_kubeportforward_stop EXIT      # the forward never outlives the script

# the generic failure block plus the GKE pieces
common_on_stage_failed() {
    common_screen ""
    common_screen "$(basename "$0"): left for you to look at"
    common_tabsdata_setup_info common_indented
    # only when the namespace is really there: a run that died before creating it
    # -- or against a cluster that stopped answering -- would otherwise be handed
    # a delete and a port-forward for something that does not exist
    if common_k8s_namespace_exists "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE"; then
        common_indented "namespace  $NAMESPACE on $CONTEXT -- kubectl --context $CONTEXT delete namespace $NAMESPACE"
        common_indented "reach it   kubectl --context $CONTEXT --namespace $NAMESPACE port-forward service/net-apiserver $FORWARD_PORT:$PORT &   then: _TDD_VENV=$VENV tdd tdk login --profile $PROFILE --server $SERVER"
        # the cluster's own account of the failure, collected while the namespace is
        # still there: `Init job 'ins-dbmanager' failed` names the job, and the
        # reason is in the pod it left behind
        common_indented "cluster    the failed pods' logs and the namespace's events are in the log"
    fi
    common_k8s_report "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE"
}

common_screen "smoke-gke: effective options"
common_screen "  --name              $NAME   -> instance and venv $BASE, namespace $NAMESPACE, domains ${BASE}__<what>"
common_screen "  --venv-type         $VENV_TYPE"
common_screen "  --py-version    $PYTHON"
common_screen "  --td-version        $TD_VERSION"
common_screen "  --td-extras   $TD_EXTRAS   -> installs $TABSDATA_SPEC"
common_screen "  --td-fn-memory      $FN_MEMORY   -> tabsdata.yaml pods.function.resources.memory"
common_screen "  --td-fn-disk        $FN_DISK   -> tabsdata.yaml pods.function.resources.disk"
common_screen "  --kube-config       $KUBECONFIG_OPT   (read only; the run works on a copy)"
common_screen "  --kube-context      $CONTEXT"
common_screen "  --kube-namespace    $NAMESPACE"
common_screen "  --kube-port-forward $FORWARD_PORT   -> server $SERVER; the apiserver itself listens on $PORT"
common_screen "  --provider          $PROVIDER   -> tdkserver init --provider $PROVIDER"
common_screen "  --db-domain         $DB_SYSTEM   -> domain $DB_DOMAIN"
common_screen "  storage             gcs   -> domain $STORAGE_DOMAIN (a prefix of the gcs system's bucket)"
common_screen "  --uv-index          $(common_display "${UV_INDEX_URI:-(none)}")"
common_screen "  --xp-suites            $SUITES   -> xp projects ${BASE}__xp_<ts>_<suite>"
common_screen "  --storage-domain    $STORAGE_SYSTEM   -> domain $STORAGE_DOMAIN"
common_screen "  --llm-domain        ${LLM_SYSTEM:-(none)}${LLM_SYSTEM:+   -> domain $LLM_DOMAIN}"
common_screen "  --expect-pods       $EXPECT_PODS"
common_screen "  --force             $([ -n "$FORCE" ] && echo "yes (replace an existing venv/instance/namespace)" || echo "no (an existing one is an error)")"
common_screen "  --keep              $([ -n "$KEEP" ] && echo "yes (also: xp one-shot --keep)" || echo "no (domains, instance, namespace and venv deleted at the end)")"
common_screen "  --profile           $PROFILE   -> tdk COMMAND --profile $PROFILE, xp --profile $PROFILE"
common_screen "  --log               $LOG"
common_screen "  --tdd-dir           $TDD_DIR_OPT"
common_screen "  --verbose           $([ "$VERBOSE" = 1 ] && echo yes || echo "no (rolling window of $WINDOW log lines)")"
common_screen "  server              $SERVER through kubectl port-forward service/net-apiserver $FORWARD_PORT:$PORT"
common_screen "  drivers for fn/ag   $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
common_xp_expand_all

common_stage unset-td "unset every TD_* variable (tdd env unset --td spares the crypto key)"
common_run tdd env unset --td

common_stage unset-pypi "unset the Python package index variables"
common_run tdd env unset --py-idx --py-default-idx

common_stage set-crypto "set _TDD_CRYPTO_KEY"
common_run tdd env set --crypto

common_stage cluster "make $CONTEXT current and check it reaches the cluster (GKE needs gke-gcloud-auth-plugin)"
# In front of everything that costs time: without the auth plugin, or pointed at
# another cloud's context, kubectl fails deep inside a later stage with a message
# about credentials rather than about which cluster it was talking to. Pinning
# here is also what carries --context to tdkserver, which resolves the cluster
# and the namespace from the current context itself, not from our flags.
common_note "the run's own kubeconfig is $RUN_KUBECONFIG, on context $CONTEXT"
common_run "${KUBECTL[@]}" version --output=yaml
common_run "${KUBECTL[@]}" get namespaces

common_stage systems "dev and fs, $DB_SYSTEM, gcs (and --llm) plus every system the suites need must be in the tdd store"
# checked UPFRONT: a run missing one must fail before anything is built
common_run tdd system create --type dev --sys dev --force
# fs needs an explicit absolute root: its default is target/backends/<name>
# against the CWD, which once landed inside a checkout.
common_run tdd system create --type fs --sys fs --sys-path "$TDD_DIR_OPT/data/fs-root" --force
for suite in "${SUITE_LIST[@]}"; do
    common_run tdd xp list-systems --suite "$suite"
done
common_run tdd system status --sys "$DB_SYSTEM"
common_run tdd system status --sys gcs
[ -z "$LLM_SYSTEM" ] || common_run tdd system status --sys "$LLM_SYSTEM"

common_stage pycache "purge tabsdata from the uv and pip caches"
common_run tdd pycache clean

common_stage clean-previous "remove what a previous $INSTANCE left (--force; nothing exists otherwise)"
# scoped to THIS run's names; the namespace delete waits -- a create over a
# Terminating namespace fails confusingly
if [ -d "$HOME/.tabsdata/instances/$INSTANCE" ]; then
    common_note "a previous instance folder exists; best-effort delete, then remove it"
    tdd tdkserver delete --instance "$INSTANCE" --trash true "${TDK_OPTS[@]}" || true
    common_run rm -rf "$HOME/.tabsdata/instances/$INSTANCE"
fi
if "${KUBECTL[@]}" get namespace "$NAMESPACE" >/dev/null 2>&1; then
    common_run "${KUBECTL[@]}" delete namespace "$NAMESPACE" --wait=true --timeout=180s
fi

common_stage create-venv "leave any active venv, then create and activate the managed venv $VENV ($VENV_TYPE, python $PYTHON)"
# Whatever this shell was in has to go first: `tdd venv create` refuses under a
# venv tdd did not activate, and the one a developer is most likely to be
# standing in -- their project's own -- is exactly that. --force is what leaves
# one tdd did not enter, and says "no venv was active" rather than failing when
# the shell is already clean.
common_run tdd venv deactivate --force
# shellcheck disable=SC2086
common_run tdd venv create --name "$VENV" --type "$VENV_TYPE" --python "$PYTHON" ${FORCE:+--force}

common_stage install "uv pip install $TABSDATA_SPEC into $VENV"
# shellcheck disable=SC2086
common_run uv pip install ${UV_INDEX_URI:+--index "$UV_INDEX_URI" --index-strategy unsafe-best-match} "$TABSDATA_SPEC"
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

common_stage domains "domains $DB_DOMAIN, $STORAGE_DOMAIN${LLM_SYSTEM:+, $LLM_DOMAIN} -- the instance's database, storage${LLM_SYSTEM:+ and LLM key}"
# Each domain is this run's slice of the shared system. Values are eval'd into
# THIS shell, never echoed; they fill the config files below.
common_run tdd domain create --sys "$DB_SYSTEM" --domain "$DB_DOMAIN" --force
SMOKE_DOMAINS="$SMOKE_DOMAINS $DB_DOMAIN"
common_note "eval \$(tdd domain info --domain $DB_DOMAIN --format export --prefix DB)   (values not shown)"
eval "$(tdd domain info --domain "$DB_DOMAIN" --format export --prefix DB 2>/dev/null)"
common_run test -n "${DB__EXTERNAL_HOST:+set}${DB__PORT:+set}${DB__DATABASE:+set}${DB__USER:+set}${DB__PASSWORD:+set}"
# A postgres domain names both networks its instance answers on, and the address
# that matters here is the pods', not this laptop's: the function pods reach a
# Cloud SQL instance over its private IP, which is what INTERNAL_HOST holds.
# Falling back to the external one covers an instance that has no private
# address (or a store that never recorded it) -- the same single endpoint that
# worked before the split.
DB_POD_HOST="${DB__INTERNAL_HOST:-$DB__EXTERNAL_HOST}"
if [ -n "${DB__INTERNAL_HOST:-}" ]; then
    common_note "database: the pods get $DB_SYSTEM's INTERNAL_HOST (its private-network address)"
else
    common_remark "$DB_SYSTEM records no INTERNAL_HOST; the pods get EXTERNAL_HOST ($DB__EXTERNAL_HOST) -- fine if that address routes from inside the cluster, and the reason to record the private one if it does not"
fi
common_run tdd domain create --sys "$STORAGE_SYSTEM" --domain "$STORAGE_DOMAIN" --force
SMOKE_DOMAINS="$SMOKE_DOMAINS $STORAGE_DOMAIN"
common_note "eval \$(tdd domain info --domain $STORAGE_DOMAIN --format export --prefix STORD)   (the service-account key is not shown)"
eval "$(tdd domain info --domain "$STORAGE_DOMAIN" --format export --prefix STORD 2>/dev/null)"
common_run test -n "${STORD__URI:+set}${STORD__BUCKET:+set}"
if [ -n "$LLM_SYSTEM" ]; then
    common_run tdd domain create --sys "$LLM_SYSTEM" --domain "$LLM_DOMAIN" --force
    SMOKE_DOMAINS="$SMOKE_DOMAINS $LLM_DOMAIN"
    common_note "eval \$(tdd domain info --domain $LLM_DOMAIN --format export --prefix LLM)   (the key is not shown)"
    eval "$(tdd domain info --domain "$LLM_DOMAIN" --format export --prefix LLM 2>/dev/null)"
    common_run test -n "${LLM__API_KEY:+set}"
fi

common_stage namespace "create the namespace $NAMESPACE and point the run's kubeconfig at it"
# tdkserver takes the namespace from the current context of the kubeconfig it is
# given, and this one is the run's own copy -- so nothing the developer's file
# says is touched, and nothing has to be put back afterwards.
common_run "${KUBECTL[@]}" create namespace "$NAMESPACE"
common_run "${KUBECTL[@]}" config set-context "$CONTEXT" --namespace "$NAMESPACE"

common_stage init "tdkserver init --provider $PROVIDER --instance $INSTANCE (the editable config folder)"
common_run tdd tdkserver init --provider "$PROVIDER" --instance "$INSTANCE" --kubeconfig "$RUN_KUBECONFIG" "${TDK_OPTS[@]}"
common_run test -d "$CONFIGS"

common_stage configure "fill the config files from the domains: database, storage, LLM key, uv index, function pod sizing"
# Named placeholders are shared across files; the storage file's ${{secret}}
# are positional. Values travel in the environment, never on a command line.
common_note "database: \${{literal:tdk_database_*}} and \${{secret:postgres_system_*}} from $DB_DOMAIN"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_host}}' "$DB_POD_HOST"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_port}}' "$DB__PORT"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_name}}' "$DB__DATABASE"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{secret:postgres_system_user}}' "$DB__USER"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{secret:postgres_system_password}}' "$DB__PASSWORD"
# Cloud SQL signs with a CA of its own, per instance, so there is no bundle to
# bake into an image: gke's template is the only one asking for the certificate
# inline (`secret:`), where eks/aks/fargate name a path tdkserver fills itself.
# The domain carries the PEM for exactly this reason. ssl_mode stays a `system:`
# placeholder -- tdkserver puts verify-ca there for every cloud provider, which
# is what the domain asks for anyway.
common_note "database TLS: $DB__SSLMODE with the instance's own CA, from $DB_DOMAIN"
common_fill_pem "$CONFIGS/dbmanager.database.yaml" -- '${{secret:tdk_database_ssl_root_cert_pem}}' "$DB__SERVER_CA_CERT_PEM"
common_note "storage: the ROOT/BUNDLES/IMAGES mounts under ${STORD__URI%/}/ with the gcs system's credentials"
common_run tdd _smoke fill-storage --file "$CONFIGS/apiserver.storage.yaml" --cloud gcp
if [ -n "$LLM_SYSTEM" ]; then
    common_note "aiagent: the $LLM_SYSTEM key from $LLM_DOMAIN"
    common_fill_placeholder "$CONFIGS/aiagent.yaml" -- "\${{secret:$LLM_SYSTEM-key?}}" "$LLM__API_KEY"
fi
if [ -n "$UV_INDEX_URI" ]; then
    common_note "tabsdata.yaml: UV_INDEX -> $(common_display "$UV_INDEX_URI")"
    common_run tdd _smoke set-uv-index --file "$CONFIGS/tabsdata.yaml" --uri "$UV_INDEX_URI"
fi
common_note "tabsdata.yaml: function pods memory $FN_MEMORY, disk $FN_DISK (pods.function.resources)"
common_run tdd _smoke set-fn-resources --file "$CONFIGS/tabsdata.yaml" --memory "$FN_MEMORY" --disk "$FN_DISK"
common_run tdd _smoke placeholders-left --dir "$CONFIGS"
common_run tdd tdkserver config check --instance "$INSTANCE" --init --accept-terms y

common_stage create "tdkserver create (upload the config), then delete the plaintext input folder"
common_run tdd tdkserver create --instance "$INSTANCE" --port "$PORT" "${TDK_OPTS[@]}"
# the input folder holds the secrets in plain text; create uploaded them --
# `config get --with-secrets` fetches them back
common_run rm -rf "$HOME/.tabsdata/instances/$INSTANCE/init"

common_stage start-1 "tdkserver start (the first start builds environments and runs the db setup)"
common_run tdd tdkserver start --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running

common_stage pods-1 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 30 10 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST

common_stage forward-1 "kubectl port-forward service/net-apiserver $FORWARD_PORT:$PORT (background)"
common_kubeportforward_start "$RUN_KUBECONFIG" "$NAMESPACE" net-apiserver "$FORWARD_PORT" "$PORT"

common_stage login-1 "tdk login as admin on $SERVER (profile $PROFILE)"
common_run_retry 30 5 tdd tdk login --profile "$PROFILE" --server "$SERVER" --user admin --password tabsdata

common_stage stop-1 "tdkserver stop (the port-forward dies with the pods)"
# rule: end the port-forward before tabsdata stops, restarts, or takes a tdkserver
# config or env change -- it holds the pods' connections and dies with them
common_kubeportforward_stop
common_run tdd tdkserver stop --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" stopped

common_stage venv-update "update the instance's fn and ag venvs with the DB drivers"
printf '%s\n' "$REQUIREMENTS" > "$WORK/requirements.txt"
common_note "requirements: $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
for name in fn ag; do
    common_run tdd tdkserver venv update --instance "$INSTANCE" --name "$name" --requirements "$WORK/requirements.txt" "${TDK_OPTS[@]}"
done

common_stage start-2 "tdkserver start"
common_run tdd tdkserver start --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running

common_stage pods-2 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 30 10 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST

common_stage forward-2 "kubectl port-forward service/net-apiserver $FORWARD_PORT:$PORT (re-established after start)"
common_kubeportforward_start "$RUN_KUBECONFIG" "$NAMESPACE" net-apiserver "$FORWARD_PORT" "$PORT"

common_stage login-2 "tdk login as admin on $SERVER (profile $PROFILE)"
common_run_retry 30 5 tdd tdk login --profile "$PROFILE" --server "$SERVER" --user admin --password tabsdata

for suite in "${SUITE_LIST[@]}"; do
    project="${BASE}__xp_$(date -u +%Y%m%dT%H%M%S)_$(printf '%s' "$suite" | tr -c 'A-Za-z0-9\n' '_')"
    XP_PROJECTS="$XP_PROJECTS $project"
    common_stage --continue "xp-$(printf '%s' "$suite" | tr '/' '_')" "xp one-shot $suite as $project (continue on error)"
    # the forward is one stream through the cluster's tunnel and can drop between
    # suites; a suite started over a dead one fails lane by lane as "not logged in"
    common_kubeportforward_ensure || continue
    # shellcheck disable=SC2086
    common_run tdd xp one-shot --suite "$suite" --suite-run "$project" --project "$project" --profile "$PROFILE" ${KEEP:+--keep}
done

if [ -n "$KEEP" ]; then
    common_stage cleanup "keeping the whole setup as it is (--keep; the port-forward is stopped)"
    common_kubeportforward_stop
    common_note "re-establish: kubectl --context $CONTEXT --namespace $NAMESPACE port-forward service/net-apiserver $FORWARD_PORT:$PORT &"
    common_note "then: export _TDD_VENV=$VENV; tdd tdk login --profile $PROFILE --server $SERVER --user admin --password ***"
    common_note "your kubeconfig was not touched; the run's copy is $RUN_KUBECONFIG ($CONTEXT, namespace $NAMESPACE)"
    common_tabsdata_setup_info common_note
else
    common_stage cleanup "destroy the domains, delete the instance, the namespace $NAMESPACE and the venv"
    common_kubeportforward_stop
    # xp (no --keep) destroyed its own domains; ours go youngest first -- the
    # database and the bucket prefix disappear with them
    [ -z "$LLM_DOMAIN" ] || common_run tdd domain destroy --domain "$LLM_DOMAIN" --force
    common_run tdd domain destroy --domain "$STORAGE_DOMAIN" --force
    common_run tdd domain destroy --domain "$DB_DOMAIN" --force
    # delete works here: the cluster is external, so it survives the workload
    # and configmap removal (unlike kminus, where delete stops the cluster first)
    common_run tdd tdkserver delete --instance "$INSTANCE" --trash true "${TDK_OPTS[@]}"
    common_run "${KUBECTL[@]}" delete namespace "$NAMESPACE" --wait=true --timeout=300s
    common_run tdd venv deactivate
    common_run tdd venv delete --name "$VENV"
fi
rm -rf "$WORK"
common_finish
