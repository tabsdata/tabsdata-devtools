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

Worker logs: the run gives the apiserver the Google service account
td-<namespace>-apiserver and the log view tabsdata-<namespace> (each reused if
it exists, an IAM binding added only if missing), runs test/test, reads its
workers' logs while their pods are there, and checks the copies Cloud Logging
returns once the pods are gone match them line for line. It needs gcloud
with an account that can make what is missing (roles/logging.configWriter for the
view, roles/iam.serviceAccountAdmin for the service account and its Workload
Identity binding, project IAM admin for the view grant) and the cluster's
Workload Identity. If that setup fails, the run says why and skips the check.
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
LOGS_PROJECT="${BASE}__logs"   # the worker-logs stage's own xp run, kept until its logs are read
LOGS_SETUP=""            # 1 once that run is set up: the cleanup removes its domains
WORKER_LOGS=""           # 1 once worker-logs-setup has the service account and view: init annotates with them
WORKER_LOGS_WHY=""       # why worker-logs-setup stopped, for the remark that says so
EXPECT_POD_LIST="$(printf '%s' "$EXPECT_PODS" | tr ',' ' ')"
LOG="${LOG:-$COMMON_TMP/smoke-$INSTANCE-$STAMP.log}"
LOGS_DIR="${LOG%.log}-worker-logs"   # the live and archived copies the worker-logs check compares
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
# The apiserver reads a removed pod's log from Cloud Logging as a Google service
# account of its own, through a view of its namespace alone, as the dguide's GKE
# worker logs page makes them by hand. What this run adds it removes; what it
# finds is reused and left.
GKE_GSA="$(tdd _smoke gke-service-account --namespace "$NAMESPACE" 2>/dev/null)"
GKE_GSA_EMAIL=""
GKE_VIEW="tabsdata-$NAMESPACE"
GKE_VIEW_PATH=""
GKE_CONDITION=""         # the view grant's IAM condition: this view only
GKE_VIEW_CREATED=""      # 1 for each thing this run made: only those does the cleanup undo
GKE_GSA_CREATED=""
GKE_GRANT_ADDED=""
GKE_WI_ADDED=""
SUITE_LIST=()
for suite in $(printf '%s' "$SUITES" | tr ',' ' '); do SUITE_LIST[${#SUITE_LIST[@]}]="$suite"; done
if [ "${#SUITE_LIST[@]}" -eq 0 ]; then
    echo "smoke-gke: --xp-suites needs at least one selector" >&2
    exit 1
fi
STAGE_NAMES=(unset-td unset-pypi set-crypto cluster systems pycache clean-previous create-venv install)
[ "$TD_VERSION" = "2.0.2" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="cdc-driver"
for stage in domains namespace worker-logs-setup init configure create start-1 pods-1 forward-1 login-1; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
for stage in stop-1 venv-update start-2 pods-2 forward-2 login-2; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
for suite in "${SUITE_LIST[@]}"; do STAGE_NAMES[${#STAGE_NAMES[@]}]="xp-$(printf '%s' "$suite" | tr '/' '_')"; done
STAGE_NAMES[${#STAGE_NAMES[@]}]="worker-logs"
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
    gke_left common_indented
    common_k8s_report "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE"
}

# What worker-logs-setup made, each with the command that undoes it -- for a
# failed or --keep run, which leaves them.
gke_left() {
    local emit="$1" scope="--bucket $GKE_BUCKET --location $GKE_BUCKET_LOCATION --project $GKE_PROJECT"
    [ -z "$GKE_GRANT_ADDED" ] ||
        "$emit" "iam grant  roles/logging.viewAccessor on $GKE_VIEW -- gcloud projects remove-iam-policy-binding $GKE_PROJECT --member serviceAccount:$GKE_GSA_EMAIL --role roles/logging.viewAccessor --condition='expression=$GKE_CONDITION,title=$GKE_VIEW-only'"
    if [ -n "$GKE_GSA_CREATED" ]; then
        "$emit" "gsa        $GKE_GSA_EMAIL -- gcloud iam service-accounts delete $GKE_GSA_EMAIL --project $GKE_PROJECT"
    elif [ -n "$GKE_WI_ADDED" ]; then
        "$emit" "iam grant  roles/iam.workloadIdentityUser on $GKE_GSA_EMAIL -- gcloud iam service-accounts remove-iam-policy-binding $GKE_GSA_EMAIL --project $GKE_PROJECT --role roles/iam.workloadIdentityUser --member 'serviceAccount:$GKE_PROJECT.svc.id.goog[$NAMESPACE/aut-apiserver]'"
    fi
    [ -z "$GKE_VIEW_CREATED" ] ||
        "$emit" "log view   $GKE_VIEW -- gcloud logging views delete $GKE_VIEW $scope"
}

# The steps of worker-logs-setup, each a stage command: a failure records why
# for the remark, since the stage's own lines are gone once it closes.
gke_why() {
    WORKER_LOGS_WHY="$1"
    echo "$1"
    return 1
}

# gke_retry CMD... -- IAM takes a moment to see a service account just made,
# and a project policy written by someone else meanwhile refuses ours once.
gke_retry() {
    local attempt=1
    until "$@"; do
        [ "$attempt" -lt 6 ] || return 1
        echo "attempt $attempt/6 failed; retrying in 5s"
        attempt=$((attempt + 1))
        sleep 5
    done
}

gke_provider() {
    [ "$PROVIDER" = gke ] ||
        gke_why "--provider $PROVIDER: only the gke provider's tabsdata.yaml has worker_logs" || return 1
    [ -n "$GKE_GSA" ] || gke_why "no service account id for namespace $NAMESPACE" || return 1
}

gke_gcloud_identity() {
    local account
    command -v gcloud >/dev/null 2>&1 || gke_why "no gcloud on the PATH" || return 1
    account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')" ||
        gke_why "gcloud auth list failed" || return 1
    [ -n "$account" ] || gke_why "gcloud has no active account: gcloud auth login" || return 1
    echo "gcloud account: $account"
}

gke_cluster() {
    local found
    found="$("${KUBECTL[@]}" config view --minify --output json | tdd _smoke gke-cluster)" ||
        gke_why "no GKE project, location and cluster in context $CONTEXT" || return 1
    read -r GKE_PROJECT GKE_LOCATION GKE_CLUSTER <<<"$found"
    GKE_GSA_EMAIL="$GKE_GSA@$GKE_PROJECT.iam.gserviceaccount.com"
    echo "cluster $GKE_CLUSTER in $GKE_LOCATION, project $GKE_PROJECT"
}

gke_workload_identity() {
    local pool
    pool="$(gcloud container clusters describe "$GKE_CLUSTER" --location "$GKE_LOCATION" --project "$GKE_PROJECT" \
        --format='value(workloadIdentityConfig.workloadPool)')" ||
        gke_why "gcloud container clusters describe $GKE_CLUSTER failed" || return 1
    [ "$pool" = "$GKE_PROJECT.svc.id.goog" ] ||
        gke_why "cluster $GKE_CLUSTER has no Workload Identity pool; once per cluster: gcloud container clusters update $GKE_CLUSTER --location $GKE_LOCATION --project $GKE_PROJECT --workload-pool=$GKE_PROJECT.svc.id.goog, and GKE_METADATA on its node pools" ||
        return 1
    echo "workload pool: $pool"
}

# The view goes in the bucket the logs land in: a sink of the dguide's that
# routes Tabsdata pods to a bucket of their own, else _Default, wherever it is.
gke_log_bucket() {
    local found
    gcloud logging sinks list --project "$GKE_PROJECT" --format json >"$WORK/sinks.json" &&
        gcloud logging buckets list --project "$GKE_PROJECT" --format json >"$WORK/buckets.json" ||
        gke_why "gcloud logging sinks list / buckets list failed in $GKE_PROJECT" || return 1
    found="$(tdd _smoke gke-log-bucket --sinks "$WORK/sinks.json" --buckets "$WORK/buckets.json")" ||
        gke_why "the log buckets of $GKE_PROJECT could not be read" || return 1
    read -r GKE_BUCKET GKE_BUCKET_LOCATION <<<"$found"
    GKE_VIEW_PATH="projects/$GKE_PROJECT/locations/$GKE_BUCKET_LOCATION/buckets/$GKE_BUCKET/views/$GKE_VIEW"
    GKE_CONDITION="resource.name == \"$GKE_VIEW_PATH\""
    echo "the logs land in bucket $GKE_BUCKET ($GKE_BUCKET_LOCATION): view $GKE_VIEW_PATH"
}

gke_view() {
    local filter current scope=(--bucket "$GKE_BUCKET" --location "$GKE_BUCKET_LOCATION" --project "$GKE_PROJECT")
    filter="resource.type=\"k8s_container\" AND resource.labels.namespace_name=\"$NAMESPACE\""
    if current="$(gcloud logging views describe "$GKE_VIEW" "${scope[@]}" --format='value(filter)' 2>/dev/null)"; then
        if [ "$current" = "$filter" ]; then
            echo "view $GKE_VIEW exists with this namespace's filter: reused"
            return 0
        fi
        echo "view $GKE_VIEW exists with another filter ($current): reused, its filter set"
        gcloud logging views update "$GKE_VIEW" "${scope[@]}" --log-filter="$filter" ||
            gke_why "gcloud logging views update $GKE_VIEW failed" || return 1
        return 0
    fi
    gcloud logging views create "$GKE_VIEW" "${scope[@]}" --log-filter="$filter" \
        --description="tdd smoke $BASE: the container logs of namespace $NAMESPACE" ||
        gke_why "gcloud logging views create $GKE_VIEW failed: the account may lack roles/logging.configWriter" || return 1
    GKE_VIEW_CREATED=1
}

gke_service_account() {
    if gcloud iam service-accounts describe "$GKE_GSA_EMAIL" --project "$GKE_PROJECT" >/dev/null 2>&1; then
        echo "service account $GKE_GSA_EMAIL exists: reused"
        return 0
    fi
    gcloud iam service-accounts create "$GKE_GSA" --project "$GKE_PROJECT" \
        --display-name="tdd smoke $BASE apiserver ($NAMESPACE)" ||
        gke_why "gcloud iam service-accounts create $GKE_GSA failed: the account may lack roles/iam.serviceAccountAdmin" ||
        return 1
    GKE_GSA_CREATED=1
}

# Each binding is read first and written only when it is missing, so a setup an
# admin made once is reused by an account that can only read IAM. A service
# account this run just made has none, so its policies are not read.
gke_view_grant() {
    local member="serviceAccount:$GKE_GSA_EMAIL" state
    if [ -z "$GKE_GSA_CREATED" ]; then
        state="$(gcloud projects get-iam-policy "$GKE_PROJECT" --format json |
            tdd _smoke gke-has-binding --role roles/logging.viewAccessor --member "$member" --expression "$GKE_CONDITION")" ||
            gke_why "gcloud projects get-iam-policy $GKE_PROJECT failed" || return 1
        if [ "$state" = present ]; then
            echo "$GKE_GSA_EMAIL already has roles/logging.viewAccessor on $GKE_VIEW"
            return 0
        fi
    fi
    gke_retry gcloud projects add-iam-policy-binding "$GKE_PROJECT" --member "$member" \
        --role roles/logging.viewAccessor --condition="expression=$GKE_CONDITION,title=$GKE_VIEW-only" \
        --quiet >/dev/null ||
        gke_why "gcloud projects add-iam-policy-binding $GKE_PROJECT failed: the account may not change the project's IAM policy" ||
        return 1
    GKE_GRANT_ADDED=1
}

gke_workload_binding() {
    local member="serviceAccount:$GKE_PROJECT.svc.id.goog[$NAMESPACE/aut-apiserver]" state
    if [ -z "$GKE_GSA_CREATED" ]; then
        state="$(gcloud iam service-accounts get-iam-policy "$GKE_GSA_EMAIL" --project "$GKE_PROJECT" --format json |
            tdd _smoke gke-has-binding --role roles/iam.workloadIdentityUser --member "$member")" ||
            gke_why "gcloud iam service-accounts get-iam-policy $GKE_GSA_EMAIL failed" || return 1
        if [ "$state" = present ]; then
            echo "$NAMESPACE/aut-apiserver already acts as $GKE_GSA_EMAIL"
            return 0
        fi
    fi
    gke_retry gcloud iam service-accounts add-iam-policy-binding "$GKE_GSA_EMAIL" --project "$GKE_PROJECT" \
        --role roles/iam.workloadIdentityUser --member "$member" --quiet >/dev/null ||
        gke_why "gcloud iam service-accounts add-iam-policy-binding $GKE_GSA_EMAIL failed: the account may lack roles/iam.serviceAccountAdmin" ||
        return 1
    GKE_WI_ADDED=1
}

# The apiserver names the view it reads once it runs as a Google service
# account; without one it has no Cloud Logging reader at all.
gke_apiserver_reads_view() {
    local out
    out="$("${KUBECTL[@]}" --namespace "$NAMESPACE" logs deployment/srv-apiserver --all-containers=true)" || return 1
    if printf '%s\n' "$out" | grep -F "Cloud Logging view '$GKE_VIEW_PATH'"; then
        return 0
    fi
    echo "the apiserver names no Cloud Logging view '$GKE_VIEW_PATH'; what it says of one:"
    printf '%s\n' "$out" | grep -F "Cloud Logging" || echo "  nothing: it does not run as $GKE_GSA_EMAIL"
    return 1
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
common_screen "  worker logs         service account $GKE_GSA and view $GKE_VIEW, then test/test as $LOGS_PROJECT, read live, then back from Cloud Logging once its pods are gone, and compared"
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

common_stage --continue worker-logs-setup "the apiserver's service account $GKE_GSA and log view $GKE_VIEW, to read worker logs from Cloud Logging (continue on error)"
common_run_shown "--provider $PROVIDER has worker_logs" gke_provider &&
    common_run_shown "gcloud auth list" gke_gcloud_identity &&
    common_run_shown "kubectl config view --minify: the GKE project, location and cluster" gke_cluster &&
    common_run_shown "gcloud container clusters describe: the Workload Identity pool" gke_workload_identity &&
    common_run_shown "gcloud logging sinks list; gcloud logging buckets list: where the logs land" gke_log_bucket &&
    common_run_shown "gcloud logging views describe (or create) $GKE_VIEW" gke_view &&
    common_run_shown "gcloud iam service-accounts describe (or create) $GKE_GSA" gke_service_account &&
    common_run_shown "gcloud projects get-iam-policy (add-iam-policy-binding if missing): roles/logging.viewAccessor on $GKE_VIEW" gke_view_grant &&
    common_run_shown "gcloud iam service-accounts get-iam-policy (add-iam-policy-binding if missing): roles/iam.workloadIdentityUser for $NAMESPACE/aut-apiserver" gke_workload_binding &&
    WORKER_LOGS=1
[ -n "$WORKER_LOGS" ] || common_remark "worker logs not checked: ${WORKER_LOGS_WHY:-the setup failed} (see the log)"

common_stage init "tdkserver init --provider $PROVIDER --instance $INSTANCE (the editable config folder${WORKER_LOGS:+, with the apiserver service account})"
# bucket and location stay empty for _Default in global, as the dguide says
INIT_CONFIG=()
if [ -n "$WORKER_LOGS" ]; then
    INIT_CONFIG=(--config "tabsdata:pods.service.apiserver.service_account.annotations.\"iam.gke.io/gcp-service-account\"=$GKE_GSA_EMAIL")
    [ "$GKE_BUCKET" = _Default ] || INIT_CONFIG+=(--config "tabsdata:pods.service.apiserver.worker_logs.bucket=$GKE_BUCKET")
    [ "$GKE_BUCKET_LOCATION" = global ] || INIT_CONFIG+=(--config "tabsdata:pods.service.apiserver.worker_logs.location=$GKE_BUCKET_LOCATION")
fi
common_run tdd tdkserver init --provider "$PROVIDER" --instance "$INSTANCE" --kubeconfig "$RUN_KUBECONFIG" "${TDK_OPTS[@]}" "${INIT_CONFIG[@]}"
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

common_stage --continue worker-logs "run test/test as $LOGS_PROJECT, read its workers' live logs, then their copies from Cloud Logging once their pods are gone, line for line (continue on error)"
if [ -z "$WORKER_LOGS" ]; then
    common_stage_skip "worker-logs-setup did not complete"
else
    XP_PROJECTS="$XP_PROJECTS $LOGS_PROJECT"
    common_kubeportforward_ensure &&
        common_run_retry 6 10 gke_apiserver_reads_view &&
        common_run tdd xp one-shot --suite test/test --suite-run "$LOGS_PROJECT" --project "$LOGS_PROJECT" --profile "$PROFILE" --keep &&
        LOGS_SETUP=1 &&
        common_run_retry 5 3 common_worker_logs_live "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE" "$PROFILE" "$LOGS_PROJECT" "$LOGS_DIR" &&
        common_run_retry 30 10 common_worker_pods_gone "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE" "$PROFILE" "$LOGS_PROJECT" &&
        common_run_retry 36 10 common_worker_logs_archived "$PROFILE" "$LOGS_PROJECT" cloud-logging "$LOGS_DIR"
fi

if [ -n "$KEEP" ]; then
    common_stage cleanup "keeping the whole setup as it is (--keep; the port-forward is stopped)"
    common_kubeportforward_stop
    common_note "re-establish: kubectl --context $CONTEXT --namespace $NAMESPACE port-forward service/net-apiserver $FORWARD_PORT:$PORT &"
    common_note "then: export _TDD_VENV=$VENV; tdd tdk login --profile $PROFILE --server $SERVER --user admin --password ***"
    common_note "your kubeconfig was not touched; the run's copy is $RUN_KUBECONFIG ($CONTEXT, namespace $NAMESPACE)"
    common_tabsdata_setup_info common_note
    gke_left common_note
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
    # the worker-logs run was kept to read its logs: its domains and suite run are ours too
    if [ -n "$LOGS_SETUP" ]; then
        common_run tdd xp destroy-domains --suite-run "$LOGS_PROJECT"
        common_run tdd xp destroy-instance --suite-run "$LOGS_PROJECT"
    fi
    common_run tdd tdkserver delete --instance "$INSTANCE" --trash true "${TDK_OPTS[@]}"
    common_run "${KUBECTL[@]}" delete namespace "$NAMESPACE" --wait=true --timeout=300s
    # only what worker-logs-setup made; what it found stays. The entries
    # themselves expire with the bucket: Cloud Logging deletes no single one.
    if [ -n "$GKE_GRANT_ADDED" ]; then
        common_run gcloud projects remove-iam-policy-binding "$GKE_PROJECT" --member "serviceAccount:$GKE_GSA_EMAIL" \
            --role roles/logging.viewAccessor --condition="expression=$GKE_CONDITION,title=$GKE_VIEW-only" --quiet
    fi
    if [ -n "$GKE_GSA_CREATED" ]; then
        common_run gcloud iam service-accounts delete "$GKE_GSA_EMAIL" --project "$GKE_PROJECT" --quiet
    elif [ -n "$GKE_WI_ADDED" ]; then
        common_run gcloud iam service-accounts remove-iam-policy-binding "$GKE_GSA_EMAIL" --project "$GKE_PROJECT" \
            --role roles/iam.workloadIdentityUser --member "serviceAccount:$GKE_PROJECT.svc.id.goog[$NAMESPACE/aut-apiserver]" --quiet
    fi
    if [ -n "$GKE_VIEW_CREATED" ]; then
        common_run gcloud logging views delete "$GKE_VIEW" --bucket "$GKE_BUCKET" --location "$GKE_BUCKET_LOCATION" \
            --project "$GKE_PROJECT" --quiet
    fi
    common_run tdd venv deactivate
    common_run tdd venv delete --name "$VENV"
fi
rm -rf "$WORK"
common_finish
